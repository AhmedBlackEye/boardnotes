"""Job runner (D-3): runs the pipeline stages in order for one uploaded lecture and stores the results.

Stages are injected through `Stages` so tests can pass fakes. `default_stages()` points at the real
implementations (module paths from docs/decisions.md) but imports them only when a stage runs, so the
API starts even while some pipeline modules are still being built.
"""

import asyncio
import importlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

from app.config import Settings
from app.contracts.ai import LOW_CONFIDENCE, BoardBlock, SectionNotes, TranscriptSegment
from app.contracts.api import JobProgress
from app.contracts.enums import JobStage, LectureStatus, SectionStatus
from app.db import Conn, Pool, execute, fetch_all, fetch_one
from app.llm.client import LLM
from app.media import lecture_dir
from app.pipeline.interfaces import (
    AudioExtractor,
    BlockMerger,
    BoardReader,
    CitationValidator,
    FormulaRechecker,
    Keyframe,
    KeyframeSelector,
    NoteWriter,
    Probe,
    SectionPlanner,
    TermNormaliser,
    Transcriber,
    VideoCheckError,
)

log = logging.getLogger(__name__)

QUEUED = "Queued"  # jobs.detail of a job waiting for the worker (the schema has no separate state column)


@dataclass(frozen=True)
class Stages:
    probe_video: Probe
    extract_audio: AudioExtractor
    transcribe: Transcriber
    select_keyframes: KeyframeSelector
    read_board: BoardReader
    merge_blocks: BlockMerger
    plan_sections: SectionPlanner
    write_notes: NoteWriter
    validate_citations: CitationValidator
    recheck_formulas: FormulaRechecker
    normalise_terms: TermNormaliser


def _lazy(module: str, name: str) -> Any:
    """A stand-in that imports app.pipeline.<module>.<name> on first call (works for sync and async stages)."""

    def call(*args: Any, **kwargs: Any) -> Any:
        return getattr(importlib.import_module(f"app.pipeline.{module}"), name)(*args, **kwargs)

    return call


def default_stages() -> Stages:
    return Stages(
        probe_video=_lazy("video", "probe_video"),
        extract_audio=_lazy("video", "extract_audio"),
        transcribe=_lazy("transcribe", "transcribe"),
        select_keyframes=_lazy("keyframes", "select_keyframes"),
        read_board=_lazy("board", "read_board"),
        merge_blocks=_lazy("board", "merge_blocks"),
        plan_sections=_lazy("notes", "plan_sections"),
        write_notes=_lazy("notes", "write_notes"),
        validate_citations=_lazy("citations", "validate_citations"),
        recheck_formulas=_lazy("formulas", "recheck_formulas"),
        normalise_terms=_lazy("terms", "normalise_terms"),
    )


# ---------- Job table ----------
async def update_job(pool: Pool, lecture_id: str, stage: JobStage, progress: float, detail: str, **extra: Any) -> None:
    async with pool.connection() as conn:
        await execute(
            conn,
            """update jobs set stage = %(stage)s, progress = %(progress)s, detail = %(detail)s,
                 sections_ready = coalesce(%(sections_ready)s, sections_ready), error = %(error)s, updated_at = now()
               where lecture_id = %(lec)s""",
            {
                "lec": lecture_id,
                "stage": stage.value,
                "progress": progress,
                "detail": detail,
                "sections_ready": extra.get("sections_ready"),
                "error": extra.get("error"),
            },
        )


async def job_progress(conn: Conn, lecture_id: str) -> JobProgress | None:
    row = await fetch_one(conn, "select * from jobs where lecture_id = %(lec)s", {"lec": lecture_id})
    if row is None:
        return None
    return JobProgress(
        lecture_id=lecture_id,
        stage=row["stage"],
        progress=row["progress"],
        detail=row["detail"],
        sections_ready=row["sections_ready"],
        error=row["error"],
    )


async def enqueue(conn: Conn, lecture_id: str) -> None:
    await execute(
        conn,
        """insert into jobs (lecture_id, stage, progress, detail) values (%(lec)s, 'check_video', 0, %(q)s)
           on conflict (lecture_id) do update set stage = 'check_video', progress = 0, detail = %(q)s,
             sections_ready = 0, error = null, updated_at = now()""",
        {"lec": lecture_id, "q": QUEUED},
    )


async def claim_next_job(pool: Pool) -> str | None:
    """Take one queued job. SKIP LOCKED lets several workers poll without picking the same job."""
    async with pool.connection() as conn:
        row = await fetch_one(
            conn,
            """select j.lecture_id from jobs j join lectures l on l.id = j.lecture_id
               where l.status = 'processing' and j.detail = %(q)s and j.error is null
               order by j.updated_at limit 1 for update of j skip locked""",
            {"q": QUEUED},
        )
        if row is None:
            return None
        await execute(
            conn, "update jobs set detail = 'Starting', updated_at = now() where lecture_id = %(lec)s", {"lec": row["lecture_id"]}
        )
        return row["lecture_id"]


# ---------- Persisting results ----------
async def save_transcript(pool: Pool, lecture_id: str, segments: list[TranscriptSegment]) -> None:
    async with pool.connection() as conn:
        await execute(conn, "delete from transcript_segments where lecture_id = %(lec)s", {"lec": lecture_id})
        async with conn.cursor() as cur:
            await cur.executemany(
                "insert into transcript_segments (lecture_id, start_s, end_s, speaker, text) values (%s, %s, %s, %s, %s)",
                [(lecture_id, s.start_s, s.end_s, s.speaker, s.text) for s in segments],
            )


def nearest_keyframe(keyframes: list[Keyframe], time_s: float) -> Keyframe | None:
    return min(keyframes, key=lambda k: abs(k.time_s - time_s), default=None)


async def save_blocks(pool: Pool, lecture_id: str, blocks: list[BoardBlock], keyframes: list[Keyframe]) -> None:
    """Board blocks, each remembering the keyframe image its snapshot will be cropped from."""
    rows = []
    for b in blocks:
        frame = nearest_keyframe(keyframes, b.best_frame_s)
        rows.append(
            (
                b.id,
                lecture_id,
                b.type.value,
                b.text,
                b.latex,
                b.confidence,
                b.first_seen_s,
                b.best_frame_s,
                b.bbox,
                str(frame.path) if frame else None,
            )
        )
    async with pool.connection() as conn:
        await execute(conn, "delete from board_blocks where lecture_id = %(lec)s", {"lec": lecture_id})
        async with conn.cursor() as cur:
            await cur.executemany(
                """insert into board_blocks (id, lecture_id, type, text, latex, confidence, first_seen_s, best_frame_s, bbox, snapshot_path)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                rows,
            )


def section_status(notes: SectionNotes) -> SectionStatus:
    return SectionStatus.UNCERTAIN if any(b.confidence < LOW_CONFIDENCE for b in notes.bullets) else SectionStatus.DRAFT


async def save_notes(pool: Pool, lecture_id: str, notes: list[SectionNotes]) -> None:
    async with pool.connection() as conn:
        await execute(conn, "delete from sections where lecture_id = %(lec)s", {"lec": lecture_id})
        for order, section in enumerate(notes):
            row = await fetch_one(
                conn,
                """insert into sections (lecture_id, ord, heading, start_s, end_s, status, said_not_written)
                   values (%(lec)s, %(ord)s, %(heading)s, %(start)s, %(end)s, %(status)s, %(snw)s) returning id""",
                {
                    "lec": lecture_id,
                    "ord": order,
                    "heading": section.heading,
                    "start": section.start_s,
                    "end": section.end_s,
                    "status": section_status(section).value,
                    "snw": Jsonb([s.model_dump() for s in section.said_not_written]),
                },
            )
            assert row is not None
            async with conn.cursor() as cur:
                await cur.executemany(
                    """insert into bullets (section_id, ord, text, latex, confidence, board_block_ids, transcript_ranges)
                       values (%s, %s, %s, %s, %s, %s, %s)""",
                    [
                        (
                            row["id"],
                            i,
                            b.text,
                            b.latex,
                            b.confidence,
                            b.board_block_ids,
                            Jsonb([r.model_dump() for r in b.transcript_ranges]),
                        )
                        for i, b in enumerate(section.bullets)
                    ],
                )


async def set_lecture(pool: Pool, lecture_id: str, **fields: Any) -> None:
    allowed = {"status", "duration_s", "width", "height"}
    assert set(fields) <= allowed
    sets = ", ".join(f"{k} = %({k})s" for k in fields)
    async with pool.connection() as conn:
        await execute(conn, f"update lectures set {sets} where id = %(id)s", {**fields, "id": lecture_id})  # noqa: S608 - keys are whitelisted


# ---------- Running a job ----------
def glance_vocabulary(keyframes: list[Keyframe]) -> list[str]:
    """Distinct lines of board text from the keyframe glance, in order of first appearance."""
    lines = (" ".join(line.split()) for kf in keyframes for line in kf.lines)
    return list(dict.fromkeys(line for line in lines if line))


AfterNotes = Callable[[str], Awaitable[None]]


async def run_job(
    pool: Pool,
    lecture_id: str,
    *,
    stages: Stages,
    llm: LLM,
    settings: Settings,
    after_notes: AfterNotes | None = None,
) -> bool:
    """Process one lecture. Returns True on success. On failure the lecture is marked failed with a readable error."""
    stage = JobStage.CHECK_VIDEO

    async def step(next_stage: JobStage, progress: float, detail: str, **extra: Any) -> None:
        nonlocal stage
        stage = next_stage
        await update_job(pool, lecture_id, next_stage, progress, detail, **extra)

    try:
        async with pool.connection() as conn:
            row = await fetch_one(conn, "select video_path from lectures where id = %(id)s", {"id": lecture_id})
        if row is None or not row["video_path"]:
            raise VideoCheckError("The uploaded video file is missing. Please upload it again.")
        video = Path(row["video_path"])
        work = lecture_dir(settings.data_dir, lecture_id)

        await step(JobStage.CHECK_VIDEO, 0.02, "Checking the video")
        info = await asyncio.to_thread(stages.probe_video, video)
        if not info.has_video or not info.has_audio:
            raise VideoCheckError("The video needs both picture and sound.")
        await set_lecture(pool, lecture_id, duration_s=info.duration_s, width=info.width, height=info.height)
        audio = await asyncio.to_thread(stages.extract_audio, video, work / "audio")

        # Keyframes first, so the words seen on the board can prime speech recognition.
        await step(JobStage.SELECT_FRAMES, 0.1, "Finding frames with new board writing")
        keyframes = await stages.select_keyframes(video, work / "frames", llm, settings.frame_interval_s)

        await step(JobStage.TRANSCRIBE, 0.25, "Transcribing the audio")
        segments = await stages.transcribe(audio, glance_vocabulary(keyframes))
        await save_transcript(pool, lecture_id, segments)

        await step(JobStage.READ_BOARD, 0.45, f"Reading the board in {len(keyframes)} frames")
        readings = await stages.read_board(keyframes, llm, segments)

        await step(JobStage.MERGE_BLOCKS, 0.65, "Combining board readings")
        blocks = await asyncio.to_thread(stages.merge_blocks, readings)
        await step(JobStage.MERGE_BLOCKS, 0.66, "Checking that formulas display correctly")
        blocks = await stages.recheck_formulas(blocks, keyframes, llm)
        await step(JobStage.MERGE_BLOCKS, 0.68, "Making terms and symbols consistent")
        blocks = await stages.normalise_terms(blocks, llm)
        # redraw_diagrams (DiagramRedrawer) goes here: blocks = await stages.redraw_diagrams(blocks, keyframes, llm)
        await save_blocks(pool, lecture_id, blocks, keyframes)

        await step(JobStage.SECTION, 0.7, "Splitting the lecture into sections")
        plan = await stages.plan_sections(blocks, segments, llm)

        await step(JobStage.WRITE_NOTES, 0.8, f"Writing notes for {len(plan.sections)} sections")
        notes = await stages.write_notes(plan, blocks, segments, llm)
        report = await asyncio.to_thread(stages.validate_citations, notes, blocks, segments)
        for reason in report.dropped:
            log.info("lecture %s: dropped bullet: %s", lecture_id, reason)
        await save_notes(pool, lecture_id, report.valid)
        await set_lecture(pool, lecture_id, status=LectureStatus.DRAFT.value)

        await step(JobStage.RENDER_PDF, 0.95, "Making the PDF", sections_ready=len(report.valid))
        if after_notes is not None:
            try:
                await after_notes(lecture_id)
            except Exception:  # the notes are ready; a PDF problem shouldn't fail the lecture
                log.exception("lecture %s: PDF step failed", lecture_id)

        await step(JobStage.DONE, 1.0, "Notes ready")
        return True
    except Exception as exc:
        if isinstance(exc, VideoCheckError):
            message = str(exc)
        else:
            log.exception("lecture %s: job failed at %s", lecture_id, stage)
            message = f"Processing failed while {_STAGE_WORDS[stage]}. Please try uploading again."
        await update_job(pool, lecture_id, stage, 1.0, "Failed", error=message)
        await set_lecture(pool, lecture_id, status=LectureStatus.FAILED.value)
        return False


_STAGE_WORDS = {
    JobStage.CHECK_VIDEO: "checking the video",
    JobStage.TRANSCRIBE: "transcribing the audio",
    JobStage.SELECT_FRAMES: "finding board frames",
    JobStage.READ_BOARD: "reading the board",
    JobStage.MERGE_BLOCKS: "combining board readings",
    JobStage.SECTION: "splitting the lecture into sections",
    JobStage.WRITE_NOTES: "writing the notes",
    JobStage.RENDER_PDF: "making the PDF",
    JobStage.DONE: "finishing",
}


# ---------- Worker ----------
async def worker_loop(pool: Pool, wake: asyncio.Event, run: Callable[[str], Awaitable[bool]], idle_s: float = 2.0) -> None:
    """Claim and run queued jobs forever. `wake` is set when a job is queued so we don't wait for the poll."""
    while True:
        try:
            lecture_id = await claim_next_job(pool)
        except Exception:
            log.exception("worker: could not claim a job")
            lecture_id = None
        if lecture_id is None:
            wake.clear()
            try:
                await asyncio.wait_for(wake.wait(), timeout=idle_s)
            except TimeoutError:
                pass
            continue
        try:
            await run(lecture_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # run_job handles stage errors itself; this is a database failure while recording one
            log.exception("worker: job for lecture %s ended with an unhandled error", lecture_id)


async def requeue_interrupted(pool: Pool) -> list[str]:
    """Put jobs that were running when the server stopped back in the queue. Call once at startup, before the worker."""
    async with pool.connection() as conn:
        rows = await fetch_all(
            conn,
            """update jobs j set stage = 'check_video', progress = 0, detail = %(q)s, sections_ready = 0, updated_at = now()
               from lectures l where l.id = j.lecture_id and l.status = 'processing' and j.error is null and j.detail <> %(q)s
               returning j.lecture_id""",
            {"q": QUEUED},
        )
    return [r["lecture_id"] for r in rows]
