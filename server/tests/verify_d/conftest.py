"""V2 fixtures: a scripted LLM so tests control verdicts and can inspect request placement."""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from PIL import Image
from psycopg.types.json import Jsonb

from app.contracts.ai import AnswerCitation, FixCheck, LectureAnswer
from app.contracts.enums import CitationKind, Verdict
from app.llm.client import LLMRequest, Usage


class ScriptedLLM:
    def __init__(self) -> None:
        self.usage = Usage()
        self.requests: list[LLMRequest] = []
        self.fix = FixCheck(verdict=Verdict.AGREES, reason="Matches the board.", looks_like_instructions=False)
        self.answer = LectureAnswer(
            covered=True,
            answer="Each equation is a line.",
            citations=[AnswerCitation(kind=CitationKind.BOARD, ref="b_1", at_s=12.0)],
        )

    async def structured(self, req, schema):
        self.requests.append(req)
        self.usage.calls += 1
        if schema is FixCheck:
            return self.fix
        if schema is LectureAnswer:
            return self.answer
        raise AssertionError(f"unexpected schema {schema}")


@pytest.fixture
def fake_llm() -> ScriptedLLM:  # overrides the builder's fixture of the same name
    return ScriptedLLM()


class CapturingPdf:
    """Replaces the builder's pdf_calls fixture: records the LectureDetail each render received."""

    def __init__(self) -> None:
        self.lectures: list[str] = []
        self.details: list = []
        self.modules = 0
        self.module_details: list = []

    async def lecture(self, detail) -> bytes:
        self.lectures.append(detail.summary.id)
        self.details.append(detail)
        return b"%PDF-1.4\n1 0 obj << /Type /Page >> endobj\n%%EOF"

    async def module(self, details) -> bytes:
        self.modules += 1
        self.module_details.append(details)
        return b"%PDF-1.4\n1 0 obj << /Type /Page >> endobj\n2 0 obj << /Type /Page >> endobj\n%%EOF"


@pytest.fixture
def pdf_calls() -> CapturingPdf:
    return CapturingPdf()


@pytest.fixture
async def tom(app) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/auth/demo-login", json={"user_id": "u_tom"})).status_code == 200
        yield c


async def seed(db, data_dir: Path | None = None, status: str = "draft"):
    snap = None
    if data_dir is not None:
        data_dir.mkdir(parents=True, exist_ok=True)
        f = data_dir / "frame.jpg"
        Image.new("RGB", (200, 100), "white").save(f)
        snap = str(f)
    await db.execute("insert into lectures (id, title, status, duration_s) values ('lec_1','Linear systems',%s,200)", (status,))
    for sid, o, h in (("sec_1", 0, "Row picture"), ("sec_2", 1, "Elimination")):
        await db.execute(
            "insert into sections (id, lecture_id, ord, heading, start_s, end_s) values (%s,'lec_1',%s,%s,%s,%s)",
            (sid, o, h, o * 100.0, o * 100.0 + 100),
        )
    for bid, t in (("b_1", "x + 2y = 3"), ("b_2", "x = 2y - 1")):
        await db.execute(
            "insert into board_blocks (id, lecture_id, type, text, latex, confidence, first_seen_s, best_frame_s, bbox, snapshot_path)"
            " values (%s,'lec_1','math',%s,null,0.9,10,12,%s,%s)",
            (bid, t, [0.1, 0.1, 0.6, 0.4], snap),
        )
    for bid, sec, o, t, c, blk in (
        ("bul_1", "sec_1", 0, "Each equation is a line", 0.95, "b_1"),
        ("bul_2", "sec_2", 0, "x = 2y + 1", 0.5, "b_2"),
        ("bul_3", "sec_2", 1, "Subtract the rows", 0.6, "b_2"),
    ):
        await db.execute(
            "insert into bullets (id, section_id, ord, text, confidence, board_block_ids, transcript_ranges) values (%s,%s,%s,%s,%s,%s,%s)",
            (bid, sec, o, t, c, [blk], Jsonb([{"start_s": 10, "end_s": 30}])),
        )
    for s, t in ((0, "Welcome"), (10, "So x equals two y minus one"), (100, "Now elimination")):
        await db.execute(
            "insert into transcript_segments (lecture_id,start_s,end_s,speaker,text) values ('lec_1',%s,%s,'lecturer',%s)", (s, s + 20, t)
        )
