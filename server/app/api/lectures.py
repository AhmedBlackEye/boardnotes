"""Lecture list/detail, the Source panel, video playback and board snapshots (D-2)."""

import asyncio
import mimetypes
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter
from fastapi import Path as PathParam
from fastapi.responses import FileResponse

from app import repo
from app.auth import CurrentUser
from app.contracts.api import LectureDetail, LectureSummary, SourceView
from app.db import Conn, fetch_one
from app.media import inside, lecture_dir, make_snapshot
from app.state import AppState, ConnDep, StateDep

router = APIRouter(tags=["lectures"])
SafeId = Annotated[str, PathParam(pattern=repo.ID_PATTERN)]


@router.get("/lectures")
async def list_lectures(user: CurrentUser, conn: ConnDep) -> list[LectureSummary]:
    return await repo.list_summaries(conn, user)


@router.get("/lectures/{lecture_id}")
async def get_lecture(lecture_id: str, user: CurrentUser, conn: ConnDep) -> LectureDetail:
    summary = await repo.visible_lecture(conn, lecture_id, user)
    return await repo.lecture_detail(conn, summary)


@router.get("/bullets/{bullet_id}/source")
async def bullet_source(bullet_id: str, user: CurrentUser, conn: ConnDep) -> SourceView:
    row = await repo.bullet_row(conn, bullet_id)
    if row is None:
        raise repo.not_found("Bullet not found")
    await repo.visible_lecture(conn, row["lecture_id"], user)
    bullet = repo.bullet_from_row(row)
    blocks = await repo.board_blocks(conn, row["lecture_id"], bullet.board_block_ids)
    lines = repo.lines_in_ranges(await repo.transcript(conn, row["lecture_id"]), bullet.transcript_ranges)
    return SourceView(
        bullet_id=bullet.id,
        board_blocks=blocks,
        snapshot_urls=[repo.snapshot_url(row["lecture_id"], b.id) for b in blocks],
        transcript=lines,
    )


def _stored_path(state: AppState, value: str | None) -> Path | None:
    """A path read from the database, only if it points inside data_dir."""
    if not value:
        return None
    path = Path(value)
    return path if inside(path, state.settings.data_dir) else None


@router.get("/lectures/{lecture_id}/video")
async def lecture_video(lecture_id: str, user: CurrentUser, state: StateDep, conn: ConnDep) -> FileResponse:
    """The playback file. Starlette's FileResponse answers Range requests with 206 Partial Content."""
    await repo.visible_lecture(conn, lecture_id, user)
    row = await fetch_one(conn, "select video_path, playback_path from lectures where id = %(id)s", {"id": lecture_id})
    path = _stored_path(state, row["playback_path"] or row["video_path"]) if row else None
    if path is None or not path.is_file():
        raise repo.not_found("Video not available")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


async def ensure_snapshot(state: AppState, conn: Conn, lecture_id: str, block_id: str) -> Path | None:
    """Path of the cached crop for a board block, creating it from the best frame on first use."""
    if not (repo.is_safe_id(lecture_id) and repo.is_safe_id(block_id)):
        return None
    out = lecture_dir(state.settings.data_dir, lecture_id) / "snapshots" / f"{block_id}.jpg"
    if out.is_file():
        return out
    row = await fetch_one(
        conn,
        """select b.bbox, b.best_frame_s, b.snapshot_path, l.video_path, l.playback_path
           from board_blocks b join lectures l on l.id = b.lecture_id where b.lecture_id = %(lec)s and b.id = %(id)s""",
        {"lec": lecture_id, "id": block_id},
    )
    if row is None:
        return None
    frame = _stored_path(state, row["snapshot_path"])
    video = _stored_path(state, row["video_path"] or row["playback_path"])
    made = await asyncio.to_thread(make_snapshot, out, list(row["bbox"]), frame, video, row["best_frame_s"])
    return out if made else None


@router.get("/snapshots/{lecture_id}/{block_id}.jpg")
async def snapshot(
    user: CurrentUser,
    state: StateDep,
    conn: ConnDep,
    lecture_id: SafeId,
    block_id: SafeId,
) -> FileResponse:
    await repo.visible_lecture(conn, lecture_id, user)
    path = await ensure_snapshot(state, conn, lecture_id, block_id)
    if path is None:
        raise repo.not_found("Snapshot not available")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})
