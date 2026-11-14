import json

import httpx
import pytest
from fastapi import FastAPI

from app.contracts.ai import AnswerCitation, LectureAnswer
from app.contracts.enums import CitationKind
from app.llm.client import LLMRequest, T
from app.llm.fake import FakeLLM
from app.pdfs import PdfRenderers, PdfUnavailableError
from app.state import AppState
from tests.conftest import FAKE_PDF, Db, PdfCalls, seed_lecture

pytestmark = pytest.mark.db


class ScriptedLLM(FakeLLM):
    async def structured(self, req: LLMRequest, schema: type[T]) -> T:
        if "unrelated" in req.untrusted.get("question", ""):
            req.untrusted["fixture_key"] = "not_covered"
        return await super().structured(req, schema)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return ScriptedLLM()


def events(response: httpx.Response) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    name = ""
    for line in response.text.splitlines():
        if line.startswith("event: "):
            name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            out[name] = json.loads(line.removeprefix("data: ")) if line.startswith("data: {") else {"raw": line}
    return out


# ---------- Ask ----------
async def test_ask_streams_a_covered_answer_with_valid_citations(sam: httpx.AsyncClient, db: Db, fake_llm: FakeLLM) -> None:
    await seed_lecture(db)
    response = await sam.post("/lectures/lec_1/ask", json={"question": "What is the row picture?"})
    assert response.headers["content-type"].startswith("text/event-stream")
    got = events(response)
    assert got["answer"]["covered"] is True
    assert got["answer"]["citations"] == [
        {"kind": "transcript", "ref": "transcript", "at_s": 110.0},
        {"kind": "section", "ref": "sec_2", "at_s": None},
    ]
    assert "done" in got

    request = fake_llm.requests[-1]
    assert (request.task, request.tier, request.effort) == ("ask", "board", "low")
    assert request.untrusted["question"] == "What is the row picture?"
    assert "x equals two y minus one" in request.untrusted["transcript"] and "[sec_2] Elimination" in request.untrusted["notes"]
    assert "row picture" not in request.instructions


async def test_ask_not_covered(sam: httpx.AsyncClient, db: Db) -> None:
    await seed_lecture(db)
    got = events(await sam.post("/lectures/lec_1/ask", json={"question": "Something unrelated?"}))
    assert got["answer"]["covered"] is False and got["answer"]["citations"] == []


async def test_invalid_citations_are_dropped_and_an_unsupported_answer_becomes_not_covered(
    sam: httpx.AsyncClient, db: Db, fake_llm: FakeLLM
) -> None:
    await seed_lecture(db)

    async def invented(req: LLMRequest, schema: type[LectureAnswer]) -> LectureAnswer:
        return LectureAnswer(covered=True, answer="Made up", citations=[AnswerCitation(kind=CitationKind.SECTION, ref="sec_99", at_s=None)])

    fake_llm.structured = invented  # type: ignore[method-assign]
    got = events(await sam.post("/lectures/lec_1/ask", json={"question": "What is the row picture?"}))
    assert got["answer"]["covered"] is False
    assert got["answer"]["citations"] == []
    assert "doesn't cover" in str(got["answer"]["answer"])


async def test_partly_valid_citations_keep_the_valid_ones() -> None:
    from app.api.ask import check_answer

    answer = LectureAnswer(
        covered=True,
        answer="a",
        citations=[
            AnswerCitation(kind=CitationKind.BOARD, ref="b_1", at_s=5),
            AnswerCitation(kind=CitationKind.BOARD, ref="b_99", at_s=5),
            AnswerCitation(kind=CitationKind.TRANSCRIPT, ref="transcript", at_s=9999),
            AnswerCitation(kind=CitationKind.SECTION, ref="nope", at_s=None),
        ],
    )
    out = check_answer(answer, {"sec_1"}, {"b_1"}, 200.0)
    assert out.covered and [c.ref for c in out.citations] == ["b_1"]


async def test_ask_access_and_validation(anon: httpx.AsyncClient, sam: httpx.AsyncClient, db: Db) -> None:
    await seed_lecture(db, status="processing")
    assert (await anon.post("/lectures/lec_1/ask", json={"question": "hi"})).status_code == 401
    assert (await sam.post("/lectures/lec_1/ask", json={"question": "hi"})).status_code == 409
    assert (await sam.post("/lectures/missing/ask", json={"question": "hi"})).status_code == 404
    assert (await sam.post("/lectures/lec_1/ask", json={"question": ""})).status_code == 422


async def test_repeated_question_is_answered_from_cache(sam: httpx.AsyncClient, db: Db, fake_llm: FakeLLM) -> None:
    await seed_lecture(db)
    await sam.post("/lectures/lec_1/ask", json={"question": "What is the row picture?"})
    await sam.post("/lectures/lec_1/ask", json={"question": "  what is the ROW picture? "})
    assert len(fake_llm.requests) == 1


# ---------- PDFs ----------
async def test_pdf_is_rendered_once_then_served_from_cache(sam: httpx.AsyncClient, db: Db, pdf_calls: PdfCalls) -> None:
    await seed_lecture(db)
    first = await sam.get("/lectures/lec_1/pdf")
    assert first.status_code == 200 and first.headers["content-type"] == "application/pdf" and first.content == FAKE_PDF
    await sam.get("/lectures/lec_1/pdf")
    assert pdf_calls.lectures == ["lec_1"]


async def test_module_pdf_and_listing(sam: httpx.AsyncClient, db: Db, pdf_calls: PdfCalls) -> None:
    await seed_lecture(db)
    assert (await sam.get("/pdfs")).json() == []
    assert (await sam.get("/module/pdf")).content == FAKE_PDF
    await sam.get("/lectures/lec_1/pdf")
    listing = (await sam.get("/pdfs")).json()
    assert [(p["lecture_id"], p["title"], p["pages"], p["url"]) for p in listing] == [
        (None, "All lectures", 1, "/module/pdf"),
        ("lec_1", "Linear systems", 1, "/lectures/lec_1/pdf"),
    ]
    assert listing[1]["status"] == "draft"
    assert pdf_calls.modules == 1


async def test_pdf_not_available_before_notes_are_ready(sam: httpx.AsyncClient, db: Db) -> None:
    await seed_lecture(db, status="processing")
    assert (await sam.get("/lectures/lec_1/pdf")).status_code == 409


async def test_missing_renderer_gives_a_clear_error(sam: httpx.AsyncClient, db: Db, app: FastAPI) -> None:
    await seed_lecture(db)

    async def unavailable(*args: object) -> bytes:
        raise PdfUnavailableError("PDF export is not available yet")

    state: AppState = app.state.boardnotes
    state.pdfs.renderers = PdfRenderers(lecture=unavailable, module=unavailable)
    response = await sam.get("/lectures/lec_1/pdf")
    assert response.status_code == 503 and "not available" in response.json()["detail"]
