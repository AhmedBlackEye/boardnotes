"""PDF downloads (D-6)."""

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app import repo
from app.auth import CurrentUser
from app.contracts.api import PdfInfo
from app.pdfs import PdfUnavailableError
from app.state import ConnDep, StateDep

router = APIRouter(tags=["pdfs"])


def _file(path: object, name: str) -> FileResponse:
    return FileResponse(str(path), media_type="application/pdf", filename=name, content_disposition_type="inline")


@router.get("/lectures/{lecture_id}/pdf")
async def lecture_pdf(lecture_id: str, user: CurrentUser, state: StateDep, conn: ConnDep) -> FileResponse:
    summary = await repo.visible_lecture(conn, lecture_id, user)
    if repo.pdf_url(summary) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The notes aren't ready yet")
    try:
        path = await state.pdfs.lecture_pdf(conn, lecture_id)
    except PdfUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return _file(path, f"{lecture_id}.pdf")


@router.get("/module/pdf")
async def module_pdf(user: CurrentUser, state: StateDep, conn: ConnDep) -> FileResponse:
    try:
        path = await state.pdfs.module_pdf(conn)
    except PdfUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return _file(path, "module.pdf")


@router.get("/pdfs")
async def list_pdfs(user: CurrentUser, state: StateDep, conn: ConnDep) -> list[PdfInfo]:
    return await state.pdfs.list_info(conn)
