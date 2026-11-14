"""PDF cache (D-6). Renderers are injected like the job stages; the default ones import app.pipeline.pdf lazily.

A rendered PDF is stored under data_dir/pdfs/ with a generated name and recorded in the `pdfs` table. Review
decisions call `invalidate`, and the next request renders it again.
"""

import asyncio
import importlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from app import repo
from app.contracts.api import LectureDetail, PdfInfo
from app.contracts.enums import LectureStatus
from app.db import Conn, Pool, execute, fetch_all, fetch_one

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


def default_renderers() -> PdfRenderers:
    return PdfRenderers(lecture=_lazy("render_pdf"), module=_lazy("render_module_pdf"))


def count_pages(pdf: bytes) -> int:
    return max(1, len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", pdf)))


def module_status(statuses: list[LectureStatus]) -> LectureStatus:
    if statuses and all(s == LectureStatus.VERIFIED for s in statuses):
        return LectureStatus.VERIFIED
    if any(s == LectureStatus.IN_REVIEW for s in statuses):
        return LectureStatus.IN_REVIEW
    return LectureStatus.DRAFT


class PdfService:
    def __init__(self, pool: Pool, data_dir: Path, renderers: PdfRenderers) -> None:
        self.pool = pool
        self.dir = data_dir / "pdfs"
        self.renderers = renderers
        self._locks: dict[str | None, asyncio.Lock] = {}

    def _lock(self, lecture_id: str | None) -> asyncio.Lock:
        return self._locks.setdefault(lecture_id, asyncio.Lock())

    async def invalidate(self, conn: Conn, lecture_id: str) -> None:
        """Forget the cached PDFs of a lecture and of the module; they are rendered again on the next request."""
        await execute(conn, "delete from pdfs where lecture_id = %(lec)s or lecture_id is null", {"lec": lecture_id})

    async def _cached(self, conn: Conn, lecture_id: str | None) -> Path | None:
        row = await fetch_one(
            conn,
            "select path from pdfs where lecture_id is not distinct from %(lec)s order by generated_at desc limit 1",
            {"lec": lecture_id},
        )
        if row is None:
            return None
        path = Path(row["path"])
        return path if await asyncio.to_thread(path.is_file) else None

    async def _store(self, lecture_id: str | None, pdf: bytes) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{lecture_id or 'module'}.pdf"
        tmp = path.with_suffix(".tmp")
        await asyncio.to_thread(tmp.write_bytes, pdf)
        tmp.replace(path)
        async with self.pool.connection() as conn:
            await execute(conn, "delete from pdfs where lecture_id is not distinct from %(lec)s", {"lec": lecture_id})
            await execute(
                conn,
                "insert into pdfs (lecture_id, path, pages) values (%(lec)s, %(path)s, %(pages)s)",
                {"lec": lecture_id, "path": str(path), "pages": count_pages(pdf)},
            )
        return path

    async def lecture_pdf(self, conn: Conn, lecture_id: str) -> Path:
        cached = await self._cached(conn, lecture_id)
        if cached:
            return cached
        summary = await repo.get_summary(conn, lecture_id)
        if summary is None:
            raise repo.not_found("Lecture not found")
        detail = await repo.lecture_detail(conn, summary)
        async with self._lock(lecture_id):
            return await self._store(lecture_id, await self.renderers.lecture(detail))

    async def module_pdf(self, conn: Conn) -> Path:
        cached = await self._cached(conn, None)
        if cached:
            return cached
        details = await self._ready_details(conn)
        async with self._lock(None):
            return await self._store(None, await self.renderers.module(details))

    async def _ready_details(self, conn: Conn) -> list[LectureDetail]:
        ready = [s.value for s in repo.READY_STATUSES]
        rows = await fetch_all(conn, "select id from lectures where status = any(%(ready)s) order by uploaded_at, id", {"ready": ready})
        details: list[LectureDetail] = []
        for row in rows:
            summary = await repo.get_summary(conn, row["id"])
            if summary is not None:
                details.append(await repo.lecture_detail(conn, summary))
        return details

    async def list_info(self, conn: Conn) -> list[PdfInfo]:
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
