"""Per-app dependencies, created in the app lifespan and reached from routes via FastAPI dependencies."""

import asyncio
import time
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Callable
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


class RateLimiter:
    """In-memory sliding-window limits per key (one API process, so this is enough for the demo)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, limit: int, window_s: float) -> bool:
        """Record a hit for `key` and return True, or return False if `limit` hits already fell inside the window."""
        now = self.clock()
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - window_s:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


@dataclass
class AppState:
    settings: Settings
    pool: Pool
    llm: LLM
    stages: "Stages"
    pdfs: "PdfService"
    ask_cache: AskCache = field(default_factory=AskCache)
    wake: asyncio.Event = field(default_factory=asyncio.Event)  # set when a job is queued
    limits: RateLimiter = field(default_factory=RateLimiter)
    upload_locks: dict[str, asyncio.Lock] = field(default_factory=dict[str, asyncio.Lock])  # uploads with a chunk being written
    llm_slots: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(4))  # interactive LLM calls at once


def get_state(request: Request) -> AppState:
    return request.app.state.boardnotes


async def get_conn(request: Request) -> AsyncIterator[Conn]:
    """One pooled connection per route call; committed when the route returns, rolled back on error.

    Used with scope="function", so the connection is committed and back in the pool before the response is sent
    (file downloads and streams never hold one). Routes that wait on slow work (LLM calls, request bodies) don't use
    this; they take short-lived connections from `state.pool` around the database steps.
    """
    async with get_state(request).pool.connection() as conn:
        yield conn


StateDep = Annotated[AppState, Depends(get_state)]
ConnDep = Annotated[Conn, Depends(get_conn, scope="function")]
