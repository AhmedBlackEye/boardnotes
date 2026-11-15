import secrets
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from PIL import Image
from psycopg import AsyncConnection, sql
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb

from app.config import REPO_ROOT, Settings
from app.config import settings as default_settings
from app.contracts.api import LectureDetail
from app.llm.fake import FakeLLM
from app.main import create_app
from app.pdfs import PdfRenderers
from app.pipeline import board

Db = AsyncConnection[DictRow]


@pytest.fixture(autouse=True)
def _no_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(board, "RETRY_BACKOFF_S", 0.0)


@pytest.fixture(autouse=True)
def _no_real_transcriber(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ignore TRANSCRIBER from a developer's .env so tests never reach a real speech-to-text API."""
    monkeypatch.setattr(default_settings, "transcriber", None)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


# ---------- A throwaway database per test session ----------
def _with_db(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{name}"))


@pytest.fixture(scope="session")
def test_db_url() -> Iterator[str]:
    """A fresh database (boardnotes_test_<random>) with the migrations applied; dropped at the end. Never touches the main database."""
    admin_url = default_settings.database_url
    name = f"boardnotes_test_{secrets.token_hex(4)}"
    try:
        admin = psycopg.connect(admin_url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not reachable (run `make db`): {exc}")
    url = _with_db(admin_url, name)
    try:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
        with psycopg.connect(url, autocommit=True) as conn:
            for migration in sorted((REPO_ROOT / "supabase" / "migrations").glob("*.sql")):
                conn.execute(migration.read_text().encode())
        yield url
    finally:
        admin.execute(sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(name)))
        admin.close()


@pytest.fixture
async def db(test_db_url: str) -> AsyncIterator[Db]:
    """An autocommit connection for seeding and inspecting; tables are emptied before each test (demo users stay)."""
    conn = await Db.connect(test_db_url, autocommit=True, row_factory=dict_row)
    await conn.execute("truncate lectures, training_examples cascade")
    yield conn
    await conn.close()


# ---------- App and clients ----------
FAKE_PDF = b"%PDF-1.4\n1 0 obj << /Type /Page >> endobj\n2 0 obj << /Type /Pages >> endobj\n%%EOF"


class PdfCalls:
    def __init__(self) -> None:
        self.lectures: list[str] = []
        self.modules = 0

    async def lecture(self, detail: LectureDetail) -> bytes:
        self.lectures.append(detail.summary.id)
        return FAKE_PDF

    async def module(self, details: list[LectureDetail]) -> bytes:
        self.modules += 1
        return FAKE_PDF


@pytest.fixture
def pdf_calls() -> PdfCalls:
    return PdfCalls()


@pytest.fixture
def settings(test_db_url: str, tmp_path: Path) -> Settings:
    return Settings(database_url=test_db_url, data_dir=tmp_path / "data", session_secret="test-secret", max_upload_bytes=10_000)


@pytest.fixture
async def app(settings: Settings, db: Db, fake_llm: FakeLLM, pdf_calls: PdfCalls) -> AsyncIterator[FastAPI]:
    application = create_app(
        settings, llm=fake_llm, renderers=PdfRenderers(lecture=pdf_calls.lecture, module=pdf_calls.module), run_worker=False
    )
    async with application.router.lifespan_context(application):
        yield application


async def _client(app: FastAPI, user_id: str | None) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        if user_id:
            response = await client.post("/auth/demo-login", json={"user_id": user_id})
            assert response.status_code == 200
        yield client


@pytest.fixture
async def anon(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async for c in _client(app, None):
        yield c


@pytest.fixture
async def lecturer(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async for c in _client(app, "u_lecturer"):
        yield c


@pytest.fixture
async def sam(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async for c in _client(app, "u_sam"):
        yield c


@pytest.fixture
async def riya(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async for c in _client(app, "u_riya"):
        yield c


# ---------- Seed data ----------
async def seed_lecture(db: Db, data_dir: Path | None = None, status: str = "draft") -> None:
    """Lecture lec_1: sections sec_1 and sec_2; bullets bul_1 (confident), bul_2 and bul_3 (uncertain); blocks b_1, b_2; transcript 0-120 s."""
    snapshot: str | None = None
    if data_dir is not None:
        data_dir.mkdir(parents=True, exist_ok=True)
        frame = data_dir / "frame.jpg"
        Image.new("RGB", (200, 100), "white").save(frame)
        snapshot = str(frame)
    await db.execute("insert into lectures (id, title, status, duration_s) values ('lec_1', 'Linear systems', %s, 200)", (status,))
    for sec_id, order, heading in (("sec_1", 0, "Row picture"), ("sec_2", 1, "Elimination")):
        await db.execute(
            "insert into sections (id, lecture_id, ord, heading, start_s, end_s) values (%s, 'lec_1', %s, %s, %s, %s)",
            (sec_id, order, heading, order * 100.0, order * 100.0 + 100),
        )
    for block_id, text in (("b_1", "x + 2y = 3"), ("b_2", "x = 2y - 1")):
        await db.execute(
            """insert into board_blocks (id, lecture_id, type, text, latex, confidence, first_seen_s, best_frame_s, bbox, snapshot_path)
               values (%s, 'lec_1', 'math', %s, null, 0.9, 10, 12, %s, %s)""",
            (block_id, text, [0.1, 0.1, 0.6, 0.4], snapshot),
        )
    for bullet_id, section, order, text, confidence, block in (
        ("bul_1", "sec_1", 0, "Each equation is a line", 0.95, "b_1"),
        ("bul_2", "sec_2", 0, "x = 2y + 1", 0.5, "b_2"),
        ("bul_3", "sec_2", 1, "Subtract the rows", 0.6, "b_2"),
    ):
        await db.execute(
            """insert into bullets (id, section_id, ord, text, confidence, board_block_ids, transcript_ranges)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            (bullet_id, section, order, text, confidence, [block], Jsonb([{"start_s": 10, "end_s": 30}])),
        )
    for start, text in ((0, "Welcome"), (10, "So x equals two y minus one"), (100, "Now elimination")):
        await db.execute(
            "insert into transcript_segments (lecture_id, start_s, end_s, speaker, text) values ('lec_1', %s, %s, 'lecturer', %s)",
            (start, start + 20, text),
        )
