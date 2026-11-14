"""Per-app dependencies, created in the app lifespan and reached from routes via FastAPI dependencies."""

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

from app.config import Settings
from app.contracts.api import AskOut
from app.db import Conn, Pool
from app.llm.client import LLM

if TYPE_CHECKING:
    from app.jobs.runner import Stages
    from app.pdfs import PdfService


class AskCache:
    """Small LRU of answers keyed by (lecture, normalised question). Cleared for a lecture when its notes change."""

    def __init__(self, max_items: int = 256) -> None:
        self.max_items = max_items
        self._items: OrderedDict[tuple[str, str], AskOut] = OrderedDict()

    @staticmethod
    def key(lecture_id: str, question: str) -> tuple[str, str]:
        return lecture_id, " ".join(question.lower().split())

    def get(self, lecture_id: str, question: str) -> AskOut | None:
        k = self.key(lecture_id, question)
        hit = self._items.get(k)
        if hit is not None:
            self._items.move_to_end(k)
        return hit

    def put(self, lecture_id: str, question: str, answer: AskOut) -> None:
        self._items[self.key(lecture_id, question)] = answer
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)

    def invalidate(self, lecture_id: str) -> None:
        for k in [k for k in self._items if k[0] == lecture_id]:
            del self._items[k]


@dataclass
class AppState:
    settings: Settings
    pool: Pool
    llm: LLM
    stages: "Stages"
    pdfs: "PdfService"
    ask_cache: AskCache = field(default_factory=AskCache)
    wake: asyncio.Event = field(default_factory=asyncio.Event)  # set when a job is queued


def get_state(request: Request) -> AppState:
    return request.app.state.boardnotes


async def get_conn(request: Request) -> AsyncIterator[Conn]:
    """One pooled connection per request; committed when the route returns, rolled back on error."""
    async with get_state(request).pool.connection() as conn:
        yield conn


StateDep = Annotated[AppState, Depends(get_state)]
ConnDep = Annotated[Conn, Depends(get_conn)]
