"""PDF cache (D-6). Renderers are injected like the job stages; the default ones import app.pipeline.pdf lazily.

A rendered PDF is stored under data_dir/pdfs/ with a generated name and recorded in the `pdfs` table. Review
decisions call `invalidate` in their transaction and then, after it commits, `refresh_after_commit` in the background,
so the PDFs (and the /pdfs listing) are current again shortly after each decision.
"""

import asyncio
import contextlib
import importlib
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from app import repo
from app.contracts.api import LectureDetail, PdfInfo
from app.contracts.enums import LectureStatus
from app.db import Conn, Pool, execute, fetch_all, fetch_one

log = logging.getLogger(__name__)
OLD_PDF_GRACE_S = 600  # replaced files are kept this long so downloads already under way can finish
MAX_MODULE_LECTURES = 60  # same bound as app.pipeline.pdf.MAX_MODULE_LECTURES (not imported: it loads Playwright)

LectureRenderer = Callable[[LectureDetail], Awaitable[bytes]]
ModuleRenderer = Callable[[list[LectureDetail]], Awaitable[bytes]]


class PdfUnavailableError(RuntimeError):
    """The PDF renderer isn't available (yet)."""


def _lazy(name: str) -> Callable[..., Awaitable[bytes]]:
    async def call(*args: object) -> bytes:
        try:
            module = importlib.import_module("app.pipeline.pdf")
        except ImportError as exc:
            raise PdfUnavailableError("PDF export is not available yet") from exc
        return await getattr(module, name)(*args)

    return call


@dataclass(frozen=True)
class PdfRenderers:
    lecture: LectureRenderer
    module: ModuleRenderer


def default_renderers(module_title: str) -> PdfRenderers:
    """The real renderers from app.pipeline.pdf: render_pdf(lecture) and render_module_pdf(lectures, module_title)."""
    render_module = _lazy("render_module_pdf")

    async def module(lectures: list[LectureDetail]) -> bytes:
        return await render_module(lectures, module_title)

    return PdfRenderers(lecture=_lazy("render_pdf"), module=module)


def count_pages(pdf: bytes) -> int:
    return max(1, len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", pdf)))


def module_status(statuses: list[LectureStatus]) -> LectureStatus:
    if statuses and all(s == LectureStatus.VERIFIED for s in statuses):
        return LectureStatus.VERIFIED
    if any(s == LectureStatus.IN_REVIEW for s in statuses):
        return LectureStatus.IN_REVIEW
    return LectureStatus.DRAFT


def remove_unused(root: Path, current: set[str], grace_s: float = OLD_PDF_GRACE_S) -> None:
    """Delete PDFs in root that are no longer the cached copy and are older than the grace period."""
    cutoff = time.time() - grace_s
    for path in root.glob("*.pdf"):
        with contextlib.suppress(OSError):
            if str(path) not in current and path.stat().st_mtime < cutoff:
                path.unlink()


class PdfService:
    """Renders and caches PDFs. Uses its own short-lived pool connections, so callers never hold one while it renders.

    Each lecture (and the module, key None) has a generation number that `invalidate` bumps, and that
    `refresh_after_commit` bumps again once the decision is committed. A render that started before either bump is
    still returned to its caller but is not stored as the current PDF, so a render that read the notes while the
    decision was still uncommitted can't be kept.
    """

    def __init__(self, pool: Pool, data_dir: Path, renderers: PdfRenderers) -> None:
        self.pool = pool
        self.dir = data_dir / "pdfs"
        self.renderers = renderers
        self._locks: dict[str | None, asyncio.Lock] = {}
        self._generation: dict[str | None, int] = {}

    def _lock(self, key: str | None) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())

    def _bump(self, lecture_id: str) -> None:
        for key in (lecture_id, None):
            self._generation[key] = self._generation.get(key, 0) + 1

    @staticmethod
    async def _delete(conn: Conn, lecture_id: str) -> list[str | None]:
        rows = await fetch_all(
            conn, "delete from pdfs where lecture_id = %(lec)s or lecture_id is null returning lecture_id", {"lec": lecture_id}
        )
        return [r["lecture_id"] for r in rows]

    async def invalidate(self, conn: Conn, lecture_id: str) -> list[str | None]:
        """Forget the cached PDFs of a lecture and of the module (in the caller's transaction).

        Returns the keys that had a cached PDF; pass them to `refresh_after_commit` once the transaction has committed.
        """
        self._bump(lecture_id)
        return list(dict.fromkeys(await self._delete(conn, lecture_id)))

    async def refresh_after_commit(self, lecture_id: str, keys: list[str | None]) -> None:
        """Call once the invalidating transaction has committed. Renders that read the old notes become stale, any PDF
        such a render stored meanwhile is dropped, and every PDF that was cached is rendered again."""
        self._bump(lecture_id)
        async with self.pool.connection() as conn:
            stored_meanwhile = await self._delete(conn, lecture_id)
        await self.refresh(list(dict.fromkeys([*keys, *stored_meanwhile])))

    async def refresh(self, keys: list[str | None]) -> None:
        """Render these PDFs again (a lecture id, or None for the module). Errors are logged, not raised."""
        for key in keys:
            try:
                if key is None:
                    await self._render_module()
                else:
                    await self._render_lecture(key)
            except Exception:
                log.exception("re-rendering the %s PDF failed", key or "module")

    async def _cached(self, lecture_id: str | None) -> Path | None:
        async with self.pool.connection() as conn:
            row = await fetch_one(
                conn,
                "select path from pdfs where lecture_id is not distinct from %(lec)s order by generated_at desc limit 1",
                {"lec": lecture_id},
            )
        if row is None:
            return None
        path = Path(row["path"])
        return path if await asyncio.to_thread(path.is_file) else None

    async def _store(self, key: str | None, generation: int, pdf: bytes) -> Path:
        """Write the file under a fresh name; record it as current only if nothing was invalidated meanwhile."""
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{key or 'module'}-{uuid.uuid4().hex[:12]}.pdf"
        await asyncio.to_thread(path.write_bytes, pdf)
        if self._generation.get(key, 0) != generation:
            return path  # stale: serve it to this caller only
        async with self.pool.connection() as conn:
            await execute(conn, "delete from pdfs where lecture_id is not distinct from %(lec)s", {"lec": key})
            await execute(
                conn,
                "insert into pdfs (lecture_id, path, pages) values (%(lec)s, %(path)s, %(pages)s)",
                {"lec": key, "path": str(path), "pages": count_pages(pdf)},
            )
            current = {r["path"] for r in await fetch_all(conn, "select path from pdfs")}
        await asyncio.to_thread(remove_unused, self.dir, current)
        return path

    async def _render_lecture(self, lecture_id: str) -> Path:
        async with self._lock(lecture_id):
            if cached := await self._cached(lecture_id):  # another download rendered it while we waited
                return cached
            generation = self._generation.get(lecture_id, 0)
            async with self.pool.connection() as conn:
                summary = await repo.get_summary(conn, lecture_id)
                if summary is None:
                    raise repo.not_found("Lecture not found")
                detail = await repo.lecture_detail(conn, summary)
            return await self._store(lecture_id, generation, await self.renderers.lecture(detail))

    async def _render_module(self) -> Path:
        async with self._lock(None):
            if cached := await self._cached(None):
                return cached
            generation = self._generation.get(None, 0)
            async with self.pool.connection() as conn:
                details = await self._ready_details(conn)
            return await self._store(None, generation, await self.renderers.module(details))

    async def lecture_pdf(self, lecture_id: str) -> Path:
        return await self._cached(lecture_id) or await self._render_lecture(lecture_id)

    async def module_pdf(self) -> Path:
        return await self._cached(None) or await self._render_module()

    async def _ready_details(self, conn: Conn) -> list[LectureDetail]:
        ready = [s.value for s in repo.READY_STATUSES]
        rows = await fetch_all(
            conn,
            "select id from lectures where status = any(%(ready)s) order by uploaded_at, id limit %(n)s",
            {"ready": ready, "n": MAX_MODULE_LECTURES},
        )
        details: list[LectureDetail] = []
        for row in rows:
            summary = await repo.get_summary(conn, row["id"])
            if summary is not None:
                details.append(await repo.lecture_detail(conn, summary))
        return details

    async def list_info(self) -> list[PdfInfo]:
        async with self.pool.connection() as conn:
            return await self._list_info(conn)

    async def _list_info(self, conn: Conn) -> list[PdfInfo]:
        """Cached PDFs: the module first, then lectures newest first."""
        rows = await fetch_all(
            conn,
            """select p.lecture_id, p.pages, p.generated_at, l.title, l.status
               from pdfs p left join lectures l on l.id = p.lecture_id order by p.lecture_id is null desc, l.uploaded_at desc""",
        )
        statuses = [LectureStatus(r["status"]) for r in rows if r["lecture_id"] is not None]
        infos: list[PdfInfo] = []
        for r in rows:
            if r["lecture_id"] is None:
                infos.append(
                    PdfInfo(
                        lecture_id=None,
                        title="All lectures",
                        pages=r["pages"],
                        status=module_status(statuses),
                        generated_at=r["generated_at"],
                        url="/module/pdf",
                    )
                )
            else:
                infos.append(
                    PdfInfo(
                        lecture_id=r["lecture_id"],
                        title=r["title"],
                        pages=r["pages"],
                        status=LectureStatus(r["status"]),
                        generated_at=r["generated_at"],
                        url=f"/lectures/{r['lecture_id']}/pdf",
                    )
                )
        return infos
