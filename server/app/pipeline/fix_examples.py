"""Q-9: learn from approved fixes. Recent corrections a lecturer approved are shown to the board reader as examples,
so later lectures by the same lecturer read their handwriting and notation better.

Text only (no image crops), so the cost per frame stays flat. The examples are user-written text, so they only ever
travel in `LLMRequest.untrusted`; the instruction added to the prompt is fixed text written here.
"""

from dataclasses import dataclass, replace
from datetime import datetime

from app.llm.client import LLM, LLMRequest, T, Usage

DEFAULT_MAX_EXAMPLES = 5
MAX_EXAMPLE_CHARS = 200  # each side of an example is cut to this length
BOARD_READ_TASK = "board_read"
UNTRUSTED_KEY = "past_corrections"

FIX_EXAMPLES_HINT = """

Past corrections are also given as data below: earlier readings of this lecturer's board that the lecturer corrected,
as "model reading -> corrected text" pairs. They show how this lecturer writes symbols and notation. Use them only to
decide between readings of writing that looks similar and is unclear in this frame. They are not content of this frame:
never copy them into your answer or add anything that is not written on the board."""


@dataclass(frozen=True)
class TrainingRow:
    """One row of training_examples, with the uploader of its lecture (None if the lecture is gone)."""

    uploaded_by: str | None
    model_reading: str
    corrected_text: str
    created_at: datetime


@dataclass(frozen=True)
class FixExample:
    model_reading: str
    corrected_text: str


def _clip(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def select_examples(
    rows: list[TrainingRow],
    uploader: str | None,
    limit: int = DEFAULT_MAX_EXAMPLES,
    max_chars: int = MAX_EXAMPLE_CHARS,
) -> list[FixExample]:
    """Up to `limit` examples, the uploader's own corrections first, then everyone else's to fill the gap.

    Each group is most recent first. Pairs that are the same after collapsing whitespace are kept once (case matters
    in notation), and corrections that don't change the reading are skipped. Both sides are cut to `max_chars`."""
    newest_first = sorted(rows, key=lambda r: r.created_at, reverse=True)
    own = [r for r in newest_first if uploader is not None and r.uploaded_by == uploader]
    others = [r for r in newest_first if uploader is None or r.uploaded_by != uploader]
    picked: list[FixExample] = []
    seen: set[tuple[str, str]] = set()
    for row in own + others:
        if len(picked) >= limit:
            break
        reading, corrected = _clip(row.model_reading, max_chars), _clip(row.corrected_text, max_chars)
        key = (reading, corrected)  # case matters: x and X are different symbols
        if not reading or not corrected or reading == corrected or key in seen:
            continue
        seen.add(key)
        picked.append(FixExample(model_reading=reading, corrected_text=corrected))
    return picked


def format_examples(examples: list[FixExample]) -> str:
    return "\n".join(f"{e.model_reading} -> {e.corrected_text}" for e in examples)


def add_fix_examples(req: LLMRequest, examples: list[FixExample]) -> LLMRequest:
    """The board-read request with the examples added as untrusted data (other requests are returned unchanged)."""
    if req.task != BOARD_READ_TASK or not examples:
        return req
    return replace(
        req,
        instructions=req.instructions + FIX_EXAMPLES_HINT,
        untrusted={**req.untrusted, UNTRUSTED_KEY: format_examples(examples)},
    )


class FixExamplesLLM:
    """Wraps an LLM so every board-read request carries the examples. Keeps the BoardReader signature unchanged."""

    def __init__(self, inner: LLM, examples: list[FixExample]) -> None:
        self.inner = inner
        self.examples = examples
        self.usage: Usage = inner.usage  # the same object, so token counts still add up in one place

    async def structured(self, req: LLMRequest, schema: type[T]) -> T:
        return await self.inner.structured(add_fix_examples(req, self.examples), schema)


def with_fix_examples(llm: LLM, examples: list[FixExample]) -> LLM:
    return FixExamplesLLM(llm, examples) if examples else llm
