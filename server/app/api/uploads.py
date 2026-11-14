"""Resumable chunked upload and job progress (D-3). Lecturers only.

Flow: POST /uploads -> PUT /uploads/{id} chunks (Content-Range: bytes start-end/total) -> POST /uploads/{id}/complete.
If a chunk fails, GET /uploads/{id} says how many bytes the server has, and the client resumes from there.
The client's filename is only used to pick an allowed extension; the file path is generated.
"""

import asyncio
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sse_starlette.event import ServerSentEvent
from sse_starlette.sse import EventSourceResponse

from app import repo
from app.auth import Lecturer, authenticate_stream
from app.contracts.api import JobProgress, UploadInit, UploadSession
from app.contracts.enums import LectureStatus, Role
from app.db import Conn, execute, fetch_one
from app.jobs.runner import enqueue, job_progress
from app.media import lecture_dir
from app.state import AppState, ConnDep, StateDep

router = APIRouter(tags=["uploads"])

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
CHUNK_SIZE = 8 * 1024 * 1024
_RANGE_RE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")


def parse_content_range(header: str | None) -> tuple[int, int, int]:
    """(start, end_inclusive, total) from 'bytes start-end/total'."""
    match = _RANGE_RE.match(header.strip()) if header else None
    if not match:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Content-Range header must look like 'bytes 0-1023/4096'")
    start, end, total = (int(g) for g in match.groups())
    if end < start or end >= total:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Content-Range")
    return start, end, total


def allowed_extension(filename: str) -> str | None:
    ext = Path(filename.replace("\\", "/")).suffix.lower()
    return ext if ext in ALLOWED_EXTENSIONS else None


def _session(row: dict[str, Any]) -> UploadSession:
    return UploadSession(upload_id=row["id"], chunk_size=CHUNK_SIZE, received_bytes=row["received_bytes"])


def upload_path(data_dir: Path, lecture_id: str, filename: str) -> Path:
    ext = allowed_extension(filename)
    assert ext is not None
    return lecture_dir(data_dir, lecture_id) / f"video{ext}"


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
async def start_upload(body: UploadInit, user: Lecturer, state: StateDep, conn: ConnDep) -> UploadSession:
    if allowed_extension(body.filename) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported file type. Use .mp4, .mov, .mkv or .webm")
    if body.size_bytes > state.settings.max_upload_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "That file is too large")
    title = " ".join(body.title.split())[:200]
    if not title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Please give the lecture a title")
    lecture = await fetch_one(
        conn, "insert into lectures (title, uploaded_by) values (%(t)s, %(u)s) returning id", {"t": title, "u": user.id}
    )
    assert lecture is not None
    row = await fetch_one(
        conn,
        "insert into uploads (lecture_id, filename, size_bytes) values (%(lec)s, %(f)s, %(n)s) returning *",
        {"lec": lecture["id"], "f": body.filename[:255], "n": body.size_bytes},
    )
    assert row is not None
    return _session(row)


_UPLOAD_SQL = """select u.*, l.status as lecture_status from uploads u join lectures l on l.id = u.lecture_id where u.id = %(id)s"""


async def _upload_row(conn: Conn, upload_id: str, *, lock: bool = False) -> dict[str, Any]:
    row = await fetch_one(conn, _UPLOAD_SQL + (" for update of u" if lock else ""), {"id": upload_id})
    if row is None:
        raise repo.not_found("Upload not found")
    return row


@router.get("/uploads/{upload_id}")
async def upload_status(upload_id: str, user: Lecturer, conn: ConnDep) -> UploadSession:
    return _session(await _upload_row(conn, upload_id))


@router.put("/uploads/{upload_id}")
async def upload_chunk(upload_id: str, request: Request, user: Lecturer, state: StateDep, conn: ConnDep) -> UploadSession:
    start, end, total = parse_content_range(request.headers.get("content-range"))
    row = await _upload_row(conn, upload_id, lock=True)  # the row lock stops two chunks for one upload running at once
    if row["lecture_status"] != LectureStatus.UPLOADING.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "This upload is already finished")
    if total != row["size_bytes"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Total size doesn't match the upload")
    if start != row["received_bytes"]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Expected the next chunk to start at byte {row['received_bytes']}")
    expected = end - start + 1
    if expected > CHUNK_SIZE:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"Chunks can be at most {CHUNK_SIZE} bytes")

    path = upload_path(state.settings.data_dir, row["lecture_id"], row["filename"])
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("r+b" if path.exists() else "wb") as out:
        out.seek(start)
        out.truncate()  # drop anything left by an earlier chunk that failed half way
        async for part in request.stream():
            written += len(part)
            if written > expected:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Chunk is longer than its Content-Range")
            await asyncio.to_thread(out.write, part)
    if written != expected:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Chunk is shorter than its Content-Range")
    row = await fetch_one(conn, "update uploads set received_bytes = %(n)s where id = %(id)s returning *", {"n": end + 1, "id": upload_id})
    assert row is not None
    return _session(row)


@router.post("/uploads/{upload_id}/complete")
async def complete_upload(upload_id: str, user: Lecturer, state: StateDep, conn: ConnDep) -> JobProgress:
    row = await _upload_row(conn, upload_id, lock=True)
    if row["lecture_status"] != LectureStatus.UPLOADING.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "This upload is already finished")
    if row["received_bytes"] != row["size_bytes"]:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Only {row['received_bytes']} of {row['size_bytes']} bytes received")
    path = upload_path(state.settings.data_dir, row["lecture_id"], row["filename"])
    await execute(
        conn,
        "update lectures set status = 'processing', video_path = %(p)s where id = %(id)s",
        {"p": str(path), "id": row["lecture_id"]},
    )
    await enqueue(conn, row["lecture_id"])
    await conn.commit()  # the worker must see the job before we wake it
    state.wake.set()
    progress = await job_progress(conn, row["lecture_id"])
    assert progress is not None
    return progress


# ---------- Progress (Server-Sent Events) ----------
async def progress_events(state: AppState, lecture_id: str, poll_s: float = 1.0) -> AsyncIterator[ServerSentEvent]:
    last: JobProgress | None = None
    while True:
        async with state.pool.connection() as conn:
            current = await job_progress(conn, lecture_id)
        if current is not None and current != last:
            last = current
            yield ServerSentEvent(data=current.model_dump_json(), event="progress")
        if current is not None and (current.error is not None or current.stage.value == "done"):
            return
        await asyncio.sleep(poll_s)


@router.get("/lectures/{lecture_id}/progress")
async def lecture_progress(lecture_id: str, request: Request, state: StateDep) -> EventSourceResponse:
    user = await authenticate_stream(request, state)
    if user.role != Role.LECTURER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Lecturers only")
    async with state.pool.connection() as conn:
        if await job_progress(conn, lecture_id) is None:
            raise repo.not_found("No processing job for this lecture")
    return EventSourceResponse(progress_events(state, lecture_id))
