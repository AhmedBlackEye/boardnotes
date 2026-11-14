"""App factory (D-1). `uvicorn app.main:app` serves the API and runs the job worker in the same process."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ask, lectures, pdfs, review, session, suggestions, uploads
from app.config import Settings
from app.config import settings as default_settings
from app.db import create_pool
from app.jobs.runner import Stages, default_stages, run_job, worker_loop
from app.llm.client import LLM, get_llm
from app.pdfs import PdfRenderers, PdfService, default_renderers
from app.state import AppState

log = logging.getLogger(__name__)
WEB_ORIGINS = ["http://localhost:3000"]


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLM | None = None,
    stages: Stages | None = None,
    renderers: PdfRenderers | None = None,
    run_worker: bool = True,
) -> FastAPI:
    """Build the app. Tests pass a fake LLM, fake stages and fake PDF renderers; `run_worker=False` skips the job worker."""
    settings = settings or default_settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = create_pool(settings.database_url)
        await pool.open()
        state = AppState(
            settings=settings,
            pool=pool,
            llm=llm or get_llm(),
            stages=stages or default_stages(),
            pdfs=PdfService(pool, settings.data_dir, renderers or default_renderers()),
        )
        app.state.boardnotes = state
        worker: asyncio.Task[None] | None = None
        if run_worker:

            async def run(lecture_id: str) -> bool:
                return await run_job(pool, lecture_id, stages=state.stages, llm=state.llm, settings=settings, after_notes=_make_pdf(state))

            worker = asyncio.create_task(worker_loop(pool, state.wake, run))
            state.wake.set()
        try:
            yield
        finally:
            if worker is not None:
                worker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker
            await pool.close()

    app = FastAPI(title="BoardNotes API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=WEB_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Content-Range"],
    )
    for module in (session, lectures, uploads, suggestions, review, ask, pdfs):
        app.include_router(module.router)
    return app


def _make_pdf(state: AppState):
    async def after_notes(lecture_id: str) -> None:
        async with state.pool.connection() as conn:
            await state.pdfs.invalidate(conn, lecture_id)
            await state.pdfs.lecture_pdf(conn, lecture_id)

    return after_notes


app = create_app()
