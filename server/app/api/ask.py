"""Ask the lecture (D-5). The answer is sent as server-sent events.

LLM.structured isn't streaming, so we send one `answer` event holding the final AskOut and then `done`.
The event shape lets real token streaming be added later without changing clients.
"""

import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request, status
from sse_starlette.event import ServerSentEvent
from sse_starlette.sse import EventSourceResponse

from app import repo
from app.auth import authenticate_stream
from app.contracts.ai import AnswerCitation, BoardBlock, LectureAnswer
from app.contracts.api import AskIn, AskOut, Section, TranscriptLine
from app.contracts.enums import CitationKind
from app.llm.client import LLM, LLMRequest
from app.state import AppState, StateDep

log = logging.getLogger(__name__)
router = APIRouter(tags=["ask"])

NOT_COVERED = "This lecture doesn't cover that, so I can't answer it from here."
MAX_TRANSCRIPT_CHARS = 150_000

ASK_INSTRUCTIONS = (
    "Answer the student's question using only the lecture material provided (notes, board writing and transcript). "
    "If the lecture does not contain the answer, set covered to false and say so; do not use outside knowledge. "
    "Cite where the answer comes from: kind 'section' with the section id, kind 'board' with the board block id and the video time, "
    "or kind 'transcript' with ref 'transcript' and the video time in seconds."
)


def lecture_context(sections: list[Section], blocks: list[BoardBlock], lines: list[TranscriptLine]) -> dict[str, str]:
    notes = "\n".join(f"[{s.id}] {s.heading}\n" + "\n".join(f"  - {b.text}" for b in s.bullets) for s in sections)
    board = "\n".join(f"[{b.id}] at {b.best_frame_s:.0f}s: {b.text}" for b in blocks)
    transcript = "\n".join(f"[{line.start_s:.1f}s] {line.text}" for line in lines)[:MAX_TRANSCRIPT_CHARS]
    return {"notes": notes or "(none)", "board": board or "(none)", "transcript": transcript or "(none)"}


def valid_citation(c: AnswerCitation, section_ids: set[str], block_ids: set[str], duration_s: float) -> bool:
    if c.kind == CitationKind.SECTION:
        return c.ref in section_ids
    if c.kind == CitationKind.BOARD:
        return c.ref in block_ids
    return c.ref == "transcript" and c.at_s is not None and 0 <= c.at_s <= duration_s


def check_answer(answer: LectureAnswer, section_ids: set[str], block_ids: set[str], duration_s: float) -> AskOut:
    """Drop citations that don't exist in this lecture. An answer left with none is not an answer."""
    citations = [c for c in answer.citations if valid_citation(c, section_ids, block_ids, duration_s)]
    if answer.covered and not citations:
        return AskOut(covered=False, answer=NOT_COVERED, citations=[])
    return AskOut(covered=answer.covered, answer=answer.answer, citations=citations if answer.covered else [])


async def answer_question(state: AppState, llm: LLM, lecture_id: str, question: str) -> AskOut:
    async with state.pool.connection() as conn:
        sections = await repo.sections(conn, lecture_id)
        blocks = await repo.board_blocks(conn, lecture_id)
        lines = await repo.transcript(conn, lecture_id)
    context = lecture_context(sections, blocks, lines)
    request = LLMRequest(
        task="ask",
        tier="board",
        instructions=ASK_INSTRUCTIONS,
        untrusted={**context, "question": question},
        effort="low",
        max_tokens=1500,
    )
    async with state.llm_slots:
        result = await llm.structured(request, LectureAnswer)
    duration = max([line.end_s for line in lines] + [s.end_s for s in sections] + [0.0])
    return check_answer(result, {s.id for s in sections}, {b.id for b in blocks}, duration)


async def ask_events(state: AppState, lecture_id: str, question: str) -> AsyncIterator[ServerSentEvent]:
    cached = state.ask_cache.get(lecture_id, question)
    generation = state.ask_cache.generation(lecture_id)  # read before the notes are
    try:
        out = cached or await answer_question(state, state.llm, lecture_id, question)
        if cached is None:
            state.ask_cache.put(lecture_id, question, out, generation)
    except Exception:
        log.exception("ask failed for lecture %s", lecture_id)
        yield ServerSentEvent(data="The question could not be answered", event="error")
        return
    yield ServerSentEvent(data=out.model_dump_json(), event="answer")
    yield ServerSentEvent(data="{}", event="done")


def check_ask_limits(state: AppState, user_id: str, lecture_id: str) -> None:
    """Per-student limits so scripted questions can't run up model costs (cached answers count too; they are cheap)."""
    s = state.settings
    if not state.limits.allow(f"ask:{user_id}", s.ask_per_minute, 60) or not state.limits.allow(
        f"ask:{user_id}:{lecture_id}", s.ask_per_lecture_per_day, 24 * 3600
    ):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "You've asked a lot of questions. Please wait a little and try again.")


@router.post("/lectures/{lecture_id}/ask")
async def ask(lecture_id: str, body: AskIn, request: Request, state: StateDep) -> EventSourceResponse:
    user = await authenticate_stream(request, state)
    async with state.pool.connection() as conn:
        await repo.visible_lecture(conn, lecture_id, user)
    check_ask_limits(state, user.id, lecture_id)
    return EventSourceResponse(ask_events(state, lecture_id, body.question))
