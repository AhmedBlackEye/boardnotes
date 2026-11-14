"""D-3: chunked upload with limits, job runner via interfaces, progress over SSE."""

import asyncio
from pathlib import Path

import httpx
import pytest
from PIL import Image

from app.contracts.ai import BoardBlock, BoardRead, BoardReadBlock, NoteBullet, SectionNotes, SectionPlan, TimeRange, TranscriptSegment
from app.contracts.api import JobProgress, UploadSession
from app.contracts.enums import BlockType, JobStage
from app.jobs.runner import Stages
from app.main import create_app
from app.pdfs import PdfRenderers
from app.pipeline.interfaces import CitationReport, FrameReading, Keyframe, VideoCheckError, VideoInfo

from .helpers import parse_sse

pytestmark = pytest.mark.asyncio

DATA = bytes(range(100)) * 10  # 1000 bytes, under the 10_000 test limit


async def start(lecturer, filename="lec.mp4", size=1000, title="Week 1"):
    return await lecturer.post("/uploads", json={"filename": filename, "size_bytes": size, "title": title})


async def put(lecturer, uid, a, b, total=1000, data=DATA):
    return await lecturer.put(f"/uploads/{uid}", content=data[a : b + 1], headers={"Content-Range": f"bytes {a}-{b}/{total}"})


# ---------- limits and validation ----------
@pytest.mark.parametrize("name", ["a.exe", "a.mp4.exe", "a", "a.txt", "a.pdf", "a.sh"])
async def test_disallowed_file_types(lecturer, name):
    assert (await start(lecturer, filename=name)).status_code in (400, 415, 422)


@pytest.mark.parametrize("name", ["a.mp4", "A.MP4", "a.mov", "a.mkv", "a.webm"])
async def test_allowed_file_types(lecturer, name):
    assert (await start(lecturer, filename=name)).status_code == 201


async def test_size_limit(lecturer):
    assert (await start(lecturer, size=10_001)).status_code == 413
    assert (await start(lecturer, size=10_000)).status_code == 201


@pytest.mark.parametrize("size", [0, -5])
async def test_nonpositive_size_rejected(lecturer, size):
    assert (await start(lecturer, size=size)).status_code == 422


async def test_blank_title_rejected(lecturer):
    assert (await start(lecturer, title="   ")).status_code in (400, 422)


async def test_students_and_anon_cannot_upload(sam, anon):
    body = {"filename": "a.mp4", "size_bytes": 10, "title": "t"}
    assert (await sam.post("/uploads", json=body)).status_code == 403
    assert (await anon.post("/uploads", json=body)).status_code == 401


async def test_client_filename_cannot_escape_data_dir(lecturer, settings, tmp_path):
    r = await start(lecturer, filename="../../../evil.mp4")
    assert r.status_code == 201
    uid = r.json()["upload_id"]
    assert (await put(lecturer, uid, 0, 999)).status_code == 200
    assert not list(tmp_path.rglob("evil*"))
    assert [p for p in settings.data_dir.rglob("*") if p.is_file() and p.stat().st_size == 1000]


# ---------- chunking and resume ----------
async def test_full_chunked_upload_and_resume(lecturer, settings):
    s = UploadSession.model_validate((await start(lecturer)).json())
    assert s.received_bytes == 0 and s.chunk_size > 0
    r = await put(lecturer, s.upload_id, 0, 399)
    assert UploadSession.model_validate(r.json()).received_bytes == 400
    # resume: ask the server
    assert (await lecturer.get(f"/uploads/{s.upload_id}")).json()["received_bytes"] == 400
    # out-of-order chunk rejected
    assert (await put(lecturer, s.upload_id, 500, 999)).status_code == 409
    # retry of an already-received chunk rejected without corrupting
    assert (await put(lecturer, s.upload_id, 0, 399)).status_code == 409
    # early complete refused
    assert (await lecturer.post(f"/uploads/{s.upload_id}/complete")).status_code == 409
    assert (await put(lecturer, s.upload_id, 400, 999)).json()["received_bytes"] == 1000
    r = await lecturer.post(f"/uploads/{s.upload_id}/complete")
    assert r.status_code == 200
    jp = JobProgress.model_validate(r.json())
    assert jp.error is None
    stored = [p for p in settings.data_dir.rglob("*") if p.is_file() and p.stat().st_size == 1000]
    assert len(stored) == 1 and stored[0].read_bytes() == DATA
    # finished uploads are closed
    assert (await lecturer.post(f"/uploads/{s.upload_id}/complete")).status_code == 409
    assert (await put(lecturer, s.upload_id, 0, 9)).status_code == 409


@pytest.mark.parametrize("hdr", [None, "bytes 0-9", "0-9/1000", "bytes 9-0/1000", "bytes 0-1000/1000", "bytes a-b/c"])
async def test_bad_content_range(lecturer, hdr):
    uid = (await start(lecturer)).json()["upload_id"]
    headers = {"Content-Range": hdr} if hdr else {}
    r = await lecturer.put(f"/uploads/{uid}", content=DATA[:10], headers=headers)
    assert r.status_code == 400


async def test_wrong_total_and_length_mismatch(lecturer):
    uid = (await start(lecturer)).json()["upload_id"]
    assert (await put(lecturer, uid, 0, 9, total=2000)).status_code == 400
    r = await lecturer.put(f"/uploads/{uid}", content=DATA[:5], headers={"Content-Range": "bytes 0-9/1000"})
    assert r.status_code == 400
    r = await lecturer.put(f"/uploads/{uid}", content=DATA[:20], headers={"Content-Range": "bytes 0-9/1000"})
    assert r.status_code == 400
    # a failed chunk does not advance progress
    assert (await lecturer.get(f"/uploads/{uid}")).json()["received_bytes"] == 0


async def test_unknown_upload_404(lecturer):
    assert (await lecturer.get("/uploads/up_nope")).status_code == 404
    assert (await put(lecturer, "up_nope", 0, 9)).status_code == 404
    assert (await lecturer.post("/uploads/up_nope/complete")).status_code == 404


async def test_upload_creates_processing_lecture_hidden_from_students(lecturer, sam):
    uid = (await start(lecturer, title="Hidden")).json()["upload_id"]
    await put(lecturer, uid, 0, 999)
    await lecturer.post(f"/uploads/{uid}/complete")
    mine = [x for x in (await lecturer.get("/lectures")).json() if x["title"] == "Hidden"]
    assert len(mine) == 1 and mine[0]["status"] == "processing"
    lec_id = mine[0]["id"]
    assert (await sam.get(f"/lectures/{lec_id}")).status_code in (404, 409)
    assert (await sam.get(f"/lectures/{lec_id}/video")).status_code in (404, 409)


# ---------- progress over SSE ----------
async def test_progress_sse_roles_and_events(lecturer, sam, anon, db):
    await db.execute("insert into lectures (id, title, status) values ('lec_p','P','processing')")
    await db.execute("insert into jobs (lecture_id, stage, progress, detail) values ('lec_p','done',1.0,'Notes ready')")
    assert (await sam.get("/lectures/lec_p/progress")).status_code == 403
    assert (await anon.get("/lectures/lec_p/progress")).status_code == 401
    assert (await lecturer.get("/lectures/nope/progress")).status_code == 404
    r = await lecturer.get("/lectures/lec_p/progress")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = [d for e, d in parse_sse(r.text) if e == "progress"]
    jp = JobProgress.model_validate_json(ev[-1])
    assert jp.stage == JobStage.DONE and jp.progress == 1.0


async def test_progress_sse_reports_failure_and_ends(lecturer, db):
    await db.execute("insert into lectures (id, title, status) values ('lec_f','F','failed')")
    await db.execute("insert into jobs (lecture_id, stage, progress, detail, error) values ('lec_f','transcribe',1.0,'Failed','boom')")
    r = await asyncio.wait_for(lecturer.get("/lectures/lec_f/progress"), 10)
    jp = JobProgress.model_validate_json([d for e, d in parse_sse(r.text) if e == "progress"][-1])
    assert jp.error == "boom"


# ---------- job runner through the stage interfaces ----------
class Recorder:
    def __init__(self, tmp: Path, info: VideoInfo | None = None, fail_at: str | None = None, fail_exc: Exception | None = None):
        self.calls: list[str] = []
        self.llms: list[object] = []
        self.tmp = tmp
        self.info = info or VideoInfo(duration_s=60.0, width=1280, height=720, has_video=True, has_audio=True, warnings=[])
        self.fail_at = fail_at
        self.fail_exc = fail_exc or RuntimeError("secret-internal sk-ant-xyz")
        self.frame = tmp / "kf.jpg"
        Image.new("RGB", (100, 60), "white").save(self.frame)

    def _hit(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_at == name:
            raise self.fail_exc

    def stages(self) -> Stages:
        kf = Keyframe(time_s=12.0, path=self.frame, lines=["x"], readable=0.9)
        block = BoardBlock(
            id="b_1", type=BlockType.MATH, text="x=1", latex=None, confidence=0.9, first_seen_s=10.0, best_frame_s=12.0, bbox=[0, 0, 1, 1]
        )

        def probe(video):
            self._hit("probe")
            if isinstance(self.info, Exception):
                raise self.info
            return self.info

        def audio(video, out_dir):
            self._hit("audio")
            return self.tmp / "a.wav"

        async def transcribe(audio):
            self._hit("transcribe")
            return [TranscriptSegment(start_s=0.0, end_s=5.0, speaker="lecturer", text="hello there")]

        async def select(video, out_dir, llm, interval_s):
            self._hit("select")
            self.llms.append(llm)
            return [kf]

        async def read(keyframes, llm):
            self._hit("read")
            self.llms.append(llm)
            return [
                FrameReading(
                    keyframe=keyframes[0],
                    read=BoardRead(
                        blocks=[BoardReadBlock(type=BlockType.MATH, text="x=1", latex=None, bbox=[0, 0, 1, 1], confidence=0.9)],
                        frame_quality="good",
                    ),
                )
            ]

        def merge(readings):
            self._hit("merge")
            return [block]

        async def plan(blocks, transcript, llm):
            self._hit("plan")
            return SectionPlan(sections=[SectionPlan.Span(heading="S1", start_s=0.0, end_s=60.0)])

        async def write(plan, blocks, transcript, llm):
            self._hit("write")
            good = NoteBullet(
                text="Keep", latex=None, board_block_ids=["b_1"], transcript_ranges=[TimeRange(start_s=0.0, end_s=5.0)], confidence=0.9
            )
            bad = NoteBullet(text="Uncited", latex=None, board_block_ids=[], transcript_ranges=[], confidence=0.9)
            return [SectionNotes(heading="S1", start_s=0.0, end_s=60.0, bullets=[good, bad], said_not_written=[])]

        def validate(notes, blocks, transcript):
            self._hit("validate")
            kept = [n.model_copy(update={"bullets": [b for b in n.bullets if b.board_block_ids or b.transcript_ranges]}) for n in notes]
            return CitationReport(valid=kept, dropped=["Uncited removed"], flagged_bullets=0)

        return Stages(probe, audio, transcribe, select, read, merge, plan, write, validate)


async def _wait_job(client, lec_id: str, limit_s=15.0) -> dict:
    loop = asyncio.get_event_loop()
    end = loop.time() + limit_s
    while loop.time() < end:
        r = await client.get(f"/lectures/{lec_id}/progress")
        if r.status_code == 200:
            evs = [d for e, d in parse_sse(r.text) if e == "progress"]
            if evs:
                jp = JobProgress.model_validate_json(evs[-1])
                if jp.stage == JobStage.DONE or jp.error:
                    return jp.model_dump()
        await asyncio.sleep(0.2)
    raise AssertionError("job did not finish")


async def _upload_and_process(settings, db, fake_llm, rec, pdf_calls):
    application = create_app(
        settings,
        llm=fake_llm,
        stages=rec.stages(),
        renderers=PdfRenderers(lecture=pdf_calls.lecture, module=pdf_calls.module),
        run_worker=True,
    )
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as c:
            await c.post("/auth/demo-login", json={"user_id": "u_lecturer"})
            r = await c.post("/uploads", json={"filename": "l.mp4", "size_bytes": 1000, "title": "Run"})
            uid = r.json()["upload_id"]
            await c.put(f"/uploads/{uid}", content=DATA, headers={"Content-Range": "bytes 0-999/1000"})
            lec_id = (await c.post(f"/uploads/{uid}/complete")).json()["lecture_id"]
            result = await _wait_job(c, lec_id)
            detail = (await c.get(f"/lectures/{lec_id}")).json()
            return c, lec_id, result, detail


async def test_job_runs_stages_in_order_and_stores_results(settings, db, fake_llm, pdf_calls, tmp_path):
    rec = Recorder(tmp_path)
    app_client = None
    application = create_app(
        settings,
        llm=fake_llm,
        stages=rec.stages(),
        renderers=PdfRenderers(lecture=pdf_calls.lecture, module=pdf_calls.module),
        run_worker=True,
    )
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as c:
            await c.post("/auth/demo-login", json={"user_id": "u_lecturer"})
            uid = (await c.post("/uploads", json={"filename": "l.mp4", "size_bytes": 1000, "title": "Run"})).json()["upload_id"]
            await c.put(f"/uploads/{uid}", content=DATA, headers={"Content-Range": "bytes 0-999/1000"})
            lec_id = (await c.post(f"/uploads/{uid}/complete")).json()["lecture_id"]
            result = await _wait_job(c, lec_id)
            app_client = c
            assert result["error"] is None and result["stage"] == "done" and result["progress"] == 1.0
            assert rec.calls == ["probe", "audio", "transcribe", "select", "read", "merge", "plan", "write", "validate"]
            assert all(x is fake_llm for x in rec.llms)
            d = (await c.get(f"/lectures/{lec_id}")).json()
            assert d["summary"]["status"] == "draft"
            assert d["summary"]["duration_s"] == 60.0
            assert [b["text"] for b in d["sections"][0]["bullets"]] == ["Keep"]  # uncited bullet not stored
            assert [b["id"] for b in d["board_blocks"]] == ["b_1"]
            assert d["sections"][0]["bullets"][0]["board_block_ids"] == ["b_1"]
            row = await (await db.execute("select count(*) n from transcript_segments where lecture_id=%s", (lec_id,))).fetchone()
            assert row["n"] == 1
            assert (await c.get(f"/lectures/{lec_id}/pdf")).status_code == 200
    assert app_client is not None


@pytest.mark.parametrize(
    ("info", "needle"),
    [
        (VideoInfo(duration_s=10.0, width=640, height=480, has_video=True, has_audio=False, warnings=[]), "sound"),
        (VideoInfo(duration_s=10.0, width=640, height=480, has_video=False, has_audio=True, warnings=[]), "picture"),
    ],
)
async def test_job_fails_for_missing_stream(settings, db, fake_llm, pdf_calls, tmp_path, info, needle):
    rec = Recorder(tmp_path, info=info)
    c, lec_id, result, detail = await _upload_and_process(settings, db, fake_llm, rec, pdf_calls)
    assert result["error"] and needle in result["error"].lower()
    assert detail["summary"]["status"] == "failed"
    assert rec.calls == ["probe"]  # nothing runs after a bad video


async def test_video_check_error_message_shown(settings, db, fake_llm, pdf_calls, tmp_path):
    rec = Recorder(tmp_path, fail_at="probe", fail_exc=VideoCheckError("Not a video file"))
    c, lec_id, result, detail = await _upload_and_process(settings, db, fake_llm, rec, pdf_calls)
    assert result["error"] == "Not a video file"
    assert detail["summary"]["status"] == "failed"


async def test_unexpected_failure_hides_internals(settings, db, fake_llm, pdf_calls, tmp_path):
    rec = Recorder(tmp_path, fail_at="read")
    c, lec_id, result, detail = await _upload_and_process(settings, db, fake_llm, rec, pdf_calls)
    assert result["error"]
    assert "secret-internal" not in result["error"] and "sk-ant" not in result["error"]
    assert detail["summary"]["status"] == "failed"
    assert rec.calls[-1] == "read"
