"""Tests for the V1/V3 review fixes: connections not held across slow work, limits, PDF refresh, worker robustness."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, get_args

import httpx
import pytest
from fastapi import FastAPI

from app.api.uploads import CHUNK_SIZE, progress_events
from app.config import Settings, check_production_settings
from app.contracts.api import LectureDetail
from app.db import Pool, create_pool
from app.jobs.runner import QUEUED, claim_next_job, requeue_interrupted, worker_loop
from app.llm.client import LLMRequest, T
from app.llm.fake import FakeLLM
from app.main import create_app
from app.media import make_snapshot
from app.pdfs import PdfRenderers, PdfService
from app.state import ConnDep, RateLimiter
from tests.conftest import FAKE_PDF, Db, PdfCalls, _client, seed_lecture

pytestmark = pytest.mark.db


class PoolWatchingLLM(FakeLLM):
    """Records how many pooled connections are checked out while a model call runs."""

    def __init__(self) -> None:
        super().__init__()
        self.pool: Pool | None = None
        self.in_use: list[int] = []

    async def structured(self, req: LLMRequest, schema: type[T]) -> T:
        if self.pool is not None:
            stats = self.pool.get_stats()
            self.in_use.append(stats["pool_size"] - stats["pool_available"])
        return await super().structured(req, schema)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return PoolWatchingLLM()


def state_of(app: FastAPI) -> Any:
    return app.state.boardnotes


# ---------- Connections ----------
def test_request_connection_is_released_before_the_response_is_sent() -> None:
    depends = get_args(ConnDep)[1]
    assert depends.scope == "function"


async def test_no_connection_is_held_during_the_fix_check(app: FastAPI, sam: httpx.AsyncClient, db: Db, settings: Settings) -> None:
    await seed_lecture(db, settings.data_dir)
    llm: PoolWatchingLLM = state_of(app).llm
    llm.pool = state_of(app).pool
    response = await sam.post("/suggestions", json={"bullet_id": "bul_2", "proposed_text": "x = 2y - 1"})
    assert response.status_code == 201 and response.json()["verdict"] == "agrees"
    assert llm.in_use == [0]


async def test_no_connection_is_held_while_answering(app: FastAPI, sam: httpx.AsyncClient, db: Db) -> None:
    await seed_lecture(db)
    llm: PoolWatchingLLM = state_of(app).llm
    llm.pool = state_of(app).pool
    assert (await sam.post("/lectures/lec_1/ask", json={"question": "What is the row picture?"})).status_code == 200
    assert llm.in_use == [0]


# ---------- Ask limits ----------
def test_rate_limiter_window() -> None:
    now = [0.0]
    limiter = RateLimiter(clock=lambda: now[0])
    assert [limiter.allow("k", 2, 60) for _ in range(3)] == [True, True, False]
    assert limiter.allow("other", 2, 60)
    now[0] = 61
    assert limiter.allow("k", 2, 60)


async def test_ask_is_rate_limited_per_student(app: FastAPI, sam: httpx.AsyncClient, riya: httpx.AsyncClient, db: Db) -> None:
    await seed_lecture(db)
    state_of(app).settings.ask_per_minute = 2
    codes = [(await sam.post("/lectures/lec_1/ask", json={"question": f"Question {i}?"})).status_code for i in range(3)]
    assert codes == [200, 200, 429]
    assert (await riya.post("/lectures/lec_1/ask", json={"question": "Question?"})).status_code == 200


# ---------- Review ----------
async def test_rejecting_one_fix_leaves_the_line_unverified_while_others_wait(
    sam: httpx.AsyncClient, riya: httpx.AsyncClient, lecturer: httpx.AsyncClient, db: Db
) -> None:
    await seed_lecture(db)
    first = (await sam.post("/suggestions", json={"bullet_id": "bul_2", "proposed_text": "x = 2y - 1"})).json()["id"]
    second = (await riya.post("/suggestions", json={"bullet_id": "bul_2", "proposed_text": "x = 2y - 2"})).json()["id"]
    await lecturer.post(f"/review/{first}/decision", json={"decision": "reject"})
    assert (await (await db.execute("select verified from bullets where id = 'bul_2'")).fetchone()) == {"verified": False}
    await lecturer.post(f"/review/{second}/decision", json={"decision": "reject"})
    assert (await (await db.execute("select verified from bullets where id = 'bul_2'")).fetchone()) == {"verified": True}


async def test_decision_clears_cached_answers(app: FastAPI, sam: httpx.AsyncClient, lecturer: httpx.AsyncClient, db: Db) -> None:
    await seed_lecture(db)
    await sam.post("/lectures/lec_1/ask", json={"question": "What is the row picture?"})
    assert state_of(app).ask_cache.get("lec_1", "What is the row picture?") is not None
    await lecturer.post("/review/bullet:bul_2/decision", json={"decision": "approve"})
    assert state_of(app).ask_cache.get("lec_1", "What is the row picture?") is None


# ---------- PDFs ----------
async def test_pdfs_are_rerendered_and_still_listed_after_a_decision(
    sam: httpx.AsyncClient, lecturer: httpx.AsyncClient, db: Db, pdf_calls: PdfCalls
) -> None:
    await seed_lecture(db)
    await sam.get("/lectures/lec_1/pdf")
    await sam.get("/module/pdf")
    await lecturer.post("/review/bullet:bul_2/decision", json={"decision": "approve"})
    assert pdf_calls.lectures == ["lec_1", "lec_1"] and pdf_calls.modules == 2  # re-rendered in the background
    listing = (await sam.get("/pdfs")).json()
    assert [p["lecture_id"] for p in listing] == [None, "lec_1"]


async def test_decision_does_not_render_pdfs_nobody_asked_for(lecturer: httpx.AsyncClient, db: Db, pdf_calls: PdfCalls) -> None:
    await seed_lecture(db)
    await lecturer.post("/review/bullet:bul_2/decision", json={"decision": "approve"})
    assert pdf_calls.lectures == [] and pdf_calls.modules == 0


async def test_render_that_overlaps_an_invalidation_is_not_cached(test_db_url: str, db: Db, tmp_path: Path) -> None:
    await seed_lecture(db)
    pool = create_pool(test_db_url)
    await pool.open()
    try:
        service: PdfService

        async def render(detail: LectureDetail) -> bytes:
            async with pool.connection() as conn:
                await service.invalidate(conn, detail.summary.id)  # a decision lands mid-render
            return FAKE_PDF

        async def module(details: list[LectureDetail]) -> bytes:
            return FAKE_PDF

        service = PdfService(pool, tmp_path, PdfRenderers(lecture=render, module=module))
        path = await service.lecture_pdf("lec_1")
        assert path.read_bytes() == FAKE_PDF  # the caller still gets a file
        assert await (await db.execute("select count(*) as n from pdfs")).fetchone() == {"n": 0}
    finally:
        await pool.close()


# ---------- Uploads ----------
async def test_oversized_chunk_is_rejected(lecturer: httpx.AsyncClient) -> None:
    upload = (await lecturer.post("/uploads", json={"filename": "a.mp4", "size_bytes": 100, "title": "t"})).json()
    response = await lecturer.put(
        f"/uploads/{upload['upload_id']}", content=b"x", headers={"Content-Range": f"bytes 0-{CHUNK_SIZE}/{CHUNK_SIZE + 1}"}
    )
    assert response.status_code == 413


async def test_another_lecturers_upload_is_not_found(app: FastAPI, lecturer: httpx.AsyncClient, db: Db) -> None:
    await db.execute("insert into profiles (id, name, role, initials) values ('u_lect2', 'Other', 'lecturer', 'OL') on conflict do nothing")
    upload_id = (await lecturer.post("/uploads", json={"filename": "a.mp4", "size_bytes": 3, "title": "t"})).json()["upload_id"]
    async for other in _client(app, "u_lect2"):
        assert (await other.get(f"/uploads/{upload_id}")).status_code == 404
        put = await other.put(f"/uploads/{upload_id}", content=b"abc", headers={"Content-Range": "bytes 0-2/3"})
        assert put.status_code == 404
        assert (await other.post(f"/uploads/{upload_id}/complete")).status_code == 404
    assert (await lecturer.put(f"/uploads/{upload_id}", content=b"abc", headers={"Content-Range": "bytes 0-2/3"})).json()[
        "received_bytes"
    ] == 3


class FakeRequest:
    def __init__(self, disconnected: bool) -> None:
        self.disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self.disconnected


async def test_progress_stream_ends_at_its_maximum_age_and_on_disconnect(app: FastAPI, db: Db) -> None:
    await db.execute("insert into lectures (id, title, status) values ('lec_p', 't', 'processing')")
    await db.execute("insert into jobs (lecture_id, stage, progress, detail) values ('lec_p', 'transcribe', 0.1, 'Working')")
    state = state_of(app)
    events = [e async for e in progress_events(state, "lec_p", FakeRequest(False), poll_s=0.01, max_s=0)]  # type: ignore[arg-type]
    assert len(events) == 1  # the current state, then the stream ends instead of polling forever
    assert [e async for e in progress_events(state, "lec_p", FakeRequest(True), poll_s=0.01)] == []  # type: ignore[arg-type]


# ---------- Worker ----------
@pytest.fixture
async def pool(test_db_url: str, db: Db) -> AsyncIterator[Pool]:
    p = create_pool(test_db_url)
    await p.open()
    yield p
    await p.close()


async def test_worker_survives_a_job_that_raises(pool: Pool, db: Db) -> None:
    for lec in ("lec_a", "lec_b"):
        await db.execute("insert into lectures (id, title, status) values (%s, 't', 'processing')", (lec,))
        await db.execute("insert into jobs (lecture_id, stage, progress, detail) values (%s, 'check_video', 0, %s)", (lec, QUEUED))
    ran: list[str] = []

    async def run(lecture_id: str) -> bool:
        ran.append(lecture_id)
        raise RuntimeError("database went away")

    task = asyncio.create_task(worker_loop(pool, asyncio.Event(), run, idle_s=0.01))
    for _ in range(200):
        if len(ran) == 2:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sorted(ran) == ["lec_a", "lec_b"]


async def test_interrupted_jobs_are_requeued_at_startup(pool: Pool, db: Db) -> None:
    await db.execute("insert into lectures (id, title, status) values ('lec_r', 't', 'processing'), ('lec_f', 't', 'failed')")
    await db.execute(
        """insert into jobs (lecture_id, stage, progress, detail, error) values
           ('lec_r', 'read_board', 0.45, 'Reading the board', null), ('lec_f', 'transcribe', 1, 'Failed', 'boom')"""
    )
    assert await requeue_interrupted(pool) == ["lec_r"]
    assert await claim_next_job(pool) == "lec_r"


async def test_app_with_worker_requeues_and_runs_interrupted_jobs(settings: Settings, db: Db, fake_llm: FakeLLM) -> None:
    await db.execute("insert into lectures (id, title, status) values ('lec_w', 't', 'processing')")
    await db.execute("insert into jobs (lecture_id, stage, progress, detail) values ('lec_w', 'transcribe', 0.1, 'Transcribing')")
    calls = PdfCalls()
    app = create_app(settings, llm=fake_llm, renderers=PdfRenderers(lecture=calls.lecture, module=calls.module), run_worker=True)
    row = None
    async with app.router.lifespan_context(app):
        for _ in range(300):
            row = await (await db.execute("select status from lectures where id = 'lec_w'")).fetchone()
            if row and row["status"] != "processing":
                break
            await asyncio.sleep(0.02)
    # The video is missing, so the re-run job fails with a readable reason instead of staying 'processing' forever.
    assert row == {"status": "failed"}
    job = await (await db.execute("select error from jobs where lecture_id = 'lec_w'")).fetchone()
    assert job is not None and "missing" in job["error"]


# ---------- Settings and login ----------
async def test_demo_login_can_be_turned_off(app: FastAPI, anon: httpx.AsyncClient) -> None:
    state_of(app).settings.demo_login = False
    assert (await anon.post("/auth/demo-login", json={"user_id": "u_lecturer"})).status_code == 404


async def test_cookie_secure_setting(app: FastAPI, anon: httpx.AsyncClient) -> None:
    state_of(app).settings.cookie_secure = True
    response = await anon.post("/auth/demo-login", json={"user_id": "u_sam"})
    assert "secure" in response.headers["set-cookie"].lower()


def test_live_mode_needs_a_real_session_secret() -> None:
    with pytest.raises(RuntimeError):
        check_production_settings(Settings(llm_mode="live"))
    check_production_settings(Settings(llm_mode="live", session_secret="s3cret"))
    check_production_settings(Settings())


def test_snapshot_leaves_no_temp_files(tmp_path: Path) -> None:
    from PIL import Image

    frame = tmp_path / "frame.jpg"
    Image.new("RGB", (100, 50), "white").save(frame)
    out = tmp_path / "snaps" / "b_1.jpg"
    assert make_snapshot(out, [0.1, 0.1, 0.5, 0.5], frame, None, 0)
    assert make_snapshot(out, [0.1, 0.1, 0.5, 0.5], frame, None, 0)
    assert [p.name for p in out.parent.iterdir()] == ["b_1.jpg"]
