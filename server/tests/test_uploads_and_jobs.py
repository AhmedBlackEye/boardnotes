import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.contracts.ai import BoardBlock, BoardRead, NoteBullet, SectionNotes, SectionPlan, TimeRange, TranscriptSegment
from app.contracts.enums import BlockType
from app.db import Pool, create_pool
from app.jobs.runner import QUEUED, Stages, claim_next_job, enqueue, run_job
from app.llm.fake import FakeLLM
from app.pipeline.interfaces import CitationReport, FrameReading, Keyframe, VideoCheckError, VideoInfo
from tests.conftest import Db

pytestmark = pytest.mark.db


# ---------- Upload ----------
async def start(lecturer: httpx.AsyncClient, size: int = 30, filename: str = "../../etc/lecture.MP4") -> httpx.Response:
    return await lecturer.post("/uploads", json={"filename": filename, "size_bytes": size, "title": "  Week 1  "})


async def put(lecturer: httpx.AsyncClient, upload_id: str, data: bytes, start: int, total: int) -> httpx.Response:
    end = start + len(data) - 1
    return await lecturer.put(f"/uploads/{upload_id}", content=data, headers={"Content-Range": f"bytes {start}-{end}/{total}"})


async def test_chunked_upload_with_resume_creates_a_job(lecturer: httpx.AsyncClient, settings: Settings, db: Db) -> None:
    video = bytes(range(30))
    upload = (await start(lecturer)).json()
    uid = upload["upload_id"]
    assert upload["received_bytes"] == 0

    assert (await put(lecturer, uid, video[:10], 0, 30)).json()["received_bytes"] == 10
    # A chunk that doesn't continue where the server is: refused, and the client can ask where to resume.
    assert (await put(lecturer, uid, video[20:], 20, 30)).status_code == 409
    assert (await lecturer.get(f"/uploads/{uid}")).json()["received_bytes"] == 10
    # Retrying the same offset after a failure overwrites cleanly.
    assert (await put(lecturer, uid, video[10:20], 10, 30)).json()["received_bytes"] == 20
    assert (await lecturer.post(f"/uploads/{uid}/complete")).status_code == 409  # not all bytes yet
    assert (await put(lecturer, uid, video[20:], 20, 30)).json()["received_bytes"] == 30

    done = await lecturer.post(f"/uploads/{uid}/complete")
    assert done.status_code == 200
    assert done.json()["detail"] == QUEUED
    lecture = await (await db.execute("select * from lectures")).fetchone()
    assert lecture is not None
    assert lecture["status"] == "processing" and lecture["title"] == "Week 1"
    path = Path(lecture["video_path"])
    assert path.read_bytes() == video
    assert path.name == "video.mp4" and path.is_relative_to(settings.data_dir)  # generated name, never the client's
    assert (await lecturer.post(f"/uploads/{uid}/complete")).status_code == 409
    assert (await put(lecturer, uid, b"x", 30, 31)).status_code in (400, 409)


async def test_upload_limits(lecturer: httpx.AsyncClient) -> None:
    assert (await start(lecturer, size=10_001)).status_code == 413  # max_upload_bytes is 10_000 in tests
    assert (await start(lecturer, filename="notes.pdf")).status_code == 400
    assert (await start(lecturer, filename="noextension")).status_code == 400
    uid = (await start(lecturer, size=20)).json()["upload_id"]
    assert (await put(lecturer, uid, b"x" * 10, 0, 99)).status_code == 400  # total doesn't match
    assert (await lecturer.put(f"/uploads/{uid}", content=b"x")).status_code == 400  # no Content-Range
    short = await lecturer.put(f"/uploads/{uid}", content=b"x" * 5, headers={"Content-Range": "bytes 0-9/20"})
    assert short.status_code == 400
    long = await lecturer.put(f"/uploads/{uid}", content=b"x" * 15, headers={"Content-Range": "bytes 0-9/20"})
    assert long.status_code == 400
    assert (await lecturer.get(f"/uploads/{uid}")).json()["received_bytes"] == 0
    assert (await lecturer.get("/uploads/up_missing")).status_code == 404


async def test_progress_stream_sends_job_state(lecturer: httpx.AsyncClient, db: Db) -> None:
    await db.execute("insert into lectures (id, title, status) values ('lec_p', 't', 'draft')")
    await db.execute("insert into jobs (lecture_id, stage, progress, detail, sections_ready) values ('lec_p', 'done', 1, 'Notes ready', 3)")
    response = await lecturer.get("/lectures/lec_p/progress")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    data = [line.removeprefix("data: ") for line in response.text.splitlines() if line.startswith("data: ")]
    assert json.loads(data[0]) == {
        "lecture_id": "lec_p",
        "stage": "done",
        "progress": 1.0,
        "detail": "Notes ready",
        "sections_ready": 3,
        "error": None,
    }
    assert (await lecturer.get("/lectures/nope/progress")).status_code == 404


# ---------- Job runner ----------
@pytest.fixture
async def pool(test_db_url: str, db: Db) -> AsyncIterator[Pool]:
    p = create_pool(test_db_url)
    await p.open()
    yield p
    await p.close()


class Calls:
    def __init__(self, tmp_path: Path) -> None:
        self.order: list[str] = []
        self.frame = tmp_path / "frame.jpg"
        self.fail_at: str | None = None
        self.vocabulary: list[str] | None = None
        self.transcript: list[TranscriptSegment] | None = None
        self.probe = VideoInfo(duration_s=120.0, width=1280, height=720, has_video=True, has_audio=True, warnings=[])

    def hit(self, name: str) -> None:
        self.order.append(name)
        if self.fail_at == name:
            raise RuntimeError("boom with /secret/path")

    def stages(self) -> Stages:
        block = BoardBlock(
            id="b_1", type=BlockType.MATH, text="x=1", latex=None, confidence=0.9, first_seen_s=5, best_frame_s=6, bbox=[0.1, 0.1, 0.5, 0.5]
        )
        notes = [
            SectionNotes(
                heading="Intro",
                start_s=0,
                end_s=60,
                bullets=[
                    NoteBullet(text="sure", latex=None, board_block_ids=["b_1"], transcript_ranges=[], confidence=0.9),
                    NoteBullet(
                        text="unsure", latex=None, board_block_ids=[], transcript_ranges=[TimeRange(start_s=1, end_s=2)], confidence=0.4
                    ),
                ],
                said_not_written=[],
            )
        ]
        frame = Keyframe(time_s=6.0, path=self.frame, lines=["x=1", " x=1 ", "eigen  value", ""], readable=0.9)

        def probe(video: Path) -> VideoInfo:
            self.hit("probe_video")
            return self.probe

        def extract_audio(video: Path, out_dir: Path) -> Path:
            self.hit("extract_audio")
            return out_dir / "a.wav"

        async def transcribe(audio: Path, vocabulary: list[str] | None = None) -> list[TranscriptSegment]:
            self.hit("transcribe")
            self.vocabulary = vocabulary
            return [TranscriptSegment(start_s=0, end_s=5, speaker="lecturer", text="hello")]

        async def select_keyframes(video: Path, out_dir: Path, llm: Any, interval_s: float) -> list[Keyframe]:
            self.hit("select_keyframes")
            return [frame]

        async def read_board(keyframes: list[Keyframe], llm: Any, transcript: list[TranscriptSegment] | None = None) -> list[FrameReading]:
            self.hit("read_board")
            self.transcript = transcript
            return [FrameReading(keyframe=frame, read=BoardRead(blocks=[], frame_quality="good"))]

        def merge_blocks(readings: list[FrameReading]) -> list[BoardBlock]:
            self.hit("merge_blocks")
            return [block]

        async def recheck_formulas(blocks: list[BoardBlock], keyframes: list[Keyframe], llm: Any) -> list[BoardBlock]:
            self.hit("recheck_formulas")
            return blocks

        async def normalise_terms(blocks: list[BoardBlock], llm: Any) -> list[BoardBlock]:
            self.hit("normalise_terms")
            return [b.model_copy(update={"text": "x = 1"}) for b in blocks]

        async def plan_sections(blocks: list[BoardBlock], transcript: list[TranscriptSegment], llm: Any) -> SectionPlan:
            self.hit("plan_sections")
            return SectionPlan(sections=[SectionPlan.Span(heading="Intro", start_s=0, end_s=60)])

        async def write_notes(
            plan: SectionPlan, blocks: list[BoardBlock], transcript: list[TranscriptSegment], llm: Any
        ) -> list[SectionNotes]:
            self.hit("write_notes")
            return notes

        def validate_citations(notes: list[SectionNotes], blocks: list[BoardBlock], transcript: list[TranscriptSegment]) -> CitationReport:
            self.hit("validate_citations")
            return CitationReport(valid=notes, dropped=[], flagged_bullets=1)

        return Stages(
            probe_video=probe,
            extract_audio=extract_audio,
            transcribe=transcribe,
            select_keyframes=select_keyframes,
            read_board=read_board,
            merge_blocks=merge_blocks,
            plan_sections=plan_sections,
            write_notes=write_notes,
            validate_citations=validate_citations,
            recheck_formulas=recheck_formulas,
            normalise_terms=normalise_terms,
        )


async def queue_lecture(pool: Pool, db: Db, settings: Settings, lecture_id: str = "lec_j") -> None:
    video = settings.data_dir / "lectures" / lecture_id / "video.mp4"
    await db.execute("insert into lectures (id, title, status, video_path) values (%s, 't', 'processing', %s)", (lecture_id, str(video)))
    async with pool.connection() as conn:
        await enqueue(conn, lecture_id)


async def test_job_runs_stages_in_order_and_stores_results(pool: Pool, db: Db, settings: Settings, tmp_path: Path) -> None:
    calls = Calls(tmp_path)
    await queue_lecture(pool, db, settings)
    pdf_for: list[str] = []

    async def after_notes(lecture_id: str) -> None:
        pdf_for.append(lecture_id)

    ok = await run_job(pool, "lec_j", stages=calls.stages(), llm=FakeLLM(), settings=settings, after_notes=after_notes)
    assert ok
    assert calls.order == [
        "probe_video",
        "extract_audio",
        "select_keyframes",
        "transcribe",
        "read_board",
        "merge_blocks",
        "recheck_formulas",
        "normalise_terms",
        "plan_sections",
        "write_notes",
        "validate_citations",
    ]
    lecture = await (await db.execute("select * from lectures where id = 'lec_j'")).fetchone()
    assert lecture is not None
    assert (lecture["status"], lecture["duration_s"], lecture["width"], lecture["height"]) == ("draft", 120.0, 1280, 720)
    job = await (await db.execute("select * from jobs where lecture_id = 'lec_j'")).fetchone()
    assert job is not None
    assert (job["stage"], job["progress"], job["sections_ready"], job["error"]) == ("done", 1.0, 1, None)
    assert (await (await db.execute("select count(*) as n from transcript_segments")).fetchone()) == {"n": 1}
    block = await (await db.execute("select snapshot_path, text from board_blocks where id = 'b_1'")).fetchone()
    assert block is not None and block["snapshot_path"] == str(calls.frame)
    assert block["text"] == "x = 1"  # blocks are stored after recheck and normalisation
    section = await (await db.execute("select * from sections")).fetchone()
    assert section is not None and section["status"] == "uncertain"
    bullets = await (await db.execute("select text, confidence from bullets order by ord")).fetchall()
    assert [b["text"] for b in bullets] == ["sure", "unsure"]
    assert pdf_for == ["lec_j"]
    assert calls.vocabulary == ["x=1", "eigen value"]  # distinct glance lines prime transcription
    assert calls.transcript is not None and [s.text for s in calls.transcript] == ["hello"]  # speech goes to board reading


@pytest.mark.parametrize("fail_at", ["probe_video", "transcribe", "write_notes"])
async def test_failed_stage_marks_lecture_failed_with_readable_error(
    pool: Pool, db: Db, settings: Settings, tmp_path: Path, fail_at: str
) -> None:
    calls = Calls(tmp_path)
    calls.fail_at = fail_at
    await queue_lecture(pool, db, settings)
    assert not await run_job(pool, "lec_j", stages=calls.stages(), llm=FakeLLM(), settings=settings)
    lecture = await (await db.execute("select status from lectures")).fetchone()
    job = await (await db.execute("select * from jobs")).fetchone()
    assert lecture == {"status": "failed"}
    assert job is not None and job["error"] and "boom" not in job["error"] and "/secret" not in job["error"]


async def test_video_without_sound_fails_with_the_reason(pool: Pool, db: Db, settings: Settings, tmp_path: Path) -> None:
    calls = Calls(tmp_path)
    calls.probe = VideoInfo(duration_s=10, width=1280, height=720, has_video=True, has_audio=False, warnings=[])
    await queue_lecture(pool, db, settings)
    assert not await run_job(pool, "lec_j", stages=calls.stages(), llm=FakeLLM(), settings=settings)
    job = await (await db.execute("select error from jobs")).fetchone()
    assert job == {"error": "The video needs both picture and sound."}


async def test_video_check_error_message_is_shown_to_the_lecturer(pool: Pool, db: Db, settings: Settings, tmp_path: Path) -> None:
    calls = Calls(tmp_path)

    def bad_probe(video: Path) -> VideoInfo:
        raise VideoCheckError("This file isn't a video.")

    stages = calls.stages()
    stages = Stages(**{**stages.__dict__, "probe_video": bad_probe})
    await queue_lecture(pool, db, settings)
    await run_job(pool, "lec_j", stages=stages, llm=FakeLLM(), settings=settings)
    assert (await (await db.execute("select error from jobs")).fetchone()) == {"error": "This file isn't a video."}


async def test_workers_never_claim_the_same_job(pool: Pool, db: Db, settings: Settings) -> None:
    await queue_lecture(pool, db, settings, "lec_a")
    await queue_lecture(pool, db, settings, "lec_b")
    first = await claim_next_job(pool)
    second = await claim_next_job(pool)
    assert {first, second} == {"lec_a", "lec_b"}
    assert await claim_next_job(pool) is None
