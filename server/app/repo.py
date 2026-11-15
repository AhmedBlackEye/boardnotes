"""Read queries that turn database rows into API contract objects. Shared by the routes, the PDF service and Q&A."""

import re
from typing import Any

from fastapi import HTTPException, status

from app.contracts.ai import LOW_CONFIDENCE, BoardBlock, DiagramFigure, SaidNotWritten, TimeRange
from app.contracts.api import Bullet, LectureDetail, LectureSummary, Me, Section, Suggestion, TranscriptLine
from app.contracts.enums import LectureStatus, Role
from app.db import Conn, fetch_all, fetch_one

# Lectures students can open. Before this, students only see the summary card.
READY_STATUSES = {LectureStatus.DRAFT, LectureStatus.IN_REVIEW, LectureStatus.VERIFIED}
ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
_ID_RE = re.compile(ID_PATTERN)


def is_safe_id(value: str) -> bool:
    """Ids that end up in file paths must be plain tokens (no slashes, no dots)."""
    return bool(_ID_RE.match(value))


def not_found(what: str = "Not found") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, what)


# ---------- Lectures ----------
# An "open item" is an open suggestion or an uncertain, unverified bullet with no open suggestion (see review.py).
_SUMMARY_SQL = """
select l.id, l.title, l.duration_s, l.status, l.uploaded_at, j.progress as job_progress,
  (select count(*) from sections s where s.lecture_id = l.id) as section_count,
  (select count(*) from suggestions g join bullets b on b.id = g.bullet_id join sections s on s.id = b.section_id
     where s.lecture_id = l.id and g.status = 'open')
  + (select count(*) from bullets b join sections s on s.id = b.section_id
     where s.lecture_id = l.id and not b.verified and b.confidence < %(low)s
       and not exists (select 1 from suggestions g where g.bullet_id = b.id and g.status = 'open')) as open_items
from lectures l left join jobs j on j.lecture_id = l.id
"""


def summary_from_row(row: dict[str, Any]) -> LectureSummary:
    lecture_status = LectureStatus(row["status"])
    processing = lecture_status in (LectureStatus.UPLOADING, LectureStatus.PROCESSING)
    return LectureSummary(
        id=row["id"],
        title=row["title"],
        duration_s=row["duration_s"],
        section_count=row["section_count"],
        status=lecture_status,
        open_items=row["open_items"],
        progress=(row["job_progress"] or 0.0) if processing else None,
        uploaded_at=row["uploaded_at"],
    )


async def list_summaries(conn: Conn, user: Me) -> list[LectureSummary]:
    where = "" if user.role == Role.LECTURER else "where l.status <> 'failed'"
    rows = await fetch_all(conn, f"{_SUMMARY_SQL} {where} order by l.uploaded_at desc, l.id", {"low": LOW_CONFIDENCE})
    return [summary_from_row(r) for r in rows]


async def get_summary(conn: Conn, lecture_id: str) -> LectureSummary | None:
    row = await fetch_one(conn, f"{_SUMMARY_SQL} where l.id = %(id)s", {"low": LOW_CONFIDENCE, "id": lecture_id})
    return summary_from_row(row) if row else None


async def visible_lecture(conn: Conn, lecture_id: str, user: Me) -> LectureSummary:
    """The lecture if this user may open it. Students can't open lectures that are still uploading or processing."""
    summary = await get_summary(conn, lecture_id)
    if summary is None:
        raise not_found("Lecture not found")
    if user.role != Role.LECTURER and summary.status not in READY_STATUSES:
        if summary.status == LectureStatus.FAILED:
            raise not_found("Lecture not found")
        raise HTTPException(status.HTTP_409_CONFLICT, "This lecture is still being processed")
    return summary


# ---------- Board, sections, bullets, transcript ----------
def block_from_row(row: dict[str, Any]) -> BoardBlock:
    return BoardBlock(
        id=row["id"],
        type=row["type"],
        text=row["text"],
        latex=row["latex"],
        confidence=row["confidence"],
        first_seen_s=row["first_seen_s"],
        best_frame_s=row["best_frame_s"],
        bbox=list(row["bbox"]),
        figure=DiagramFigure.model_validate(row["figure"]) if row.get("figure") else None,
    )


async def board_blocks(conn: Conn, lecture_id: str, ids: list[str] | None = None) -> list[BoardBlock]:
    sql = "select * from board_blocks where lecture_id = %(lec)s"
    if ids is not None:
        sql += " and id = any(%(ids)s)"
    rows = await fetch_all(conn, sql + " order by first_seen_s, id", {"lec": lecture_id, "ids": ids})
    return [block_from_row(r) for r in rows]


def snapshot_url(lecture_id: str, block_id: str) -> str:
    return f"/snapshots/{lecture_id}/{block_id}.jpg"


def is_uncertain(confidence: float, verified: bool) -> bool:
    return not verified and confidence < LOW_CONFIDENCE


def bullet_from_row(row: dict[str, Any]) -> Bullet:
    return Bullet(
        id=row["id"],
        order=row["ord"],
        text=row["text"],
        latex=row["latex"],
        confidence=row["confidence"],
        uncertain=is_uncertain(row["confidence"], row["verified"]),
        board_block_ids=list(row["board_block_ids"]),
        transcript_ranges=[TimeRange.model_validate(r) for r in row["transcript_ranges"]],
        open_suggestions=row.get("open_suggestions", 0),
    )


async def sections(conn: Conn, lecture_id: str, viewer: Me | None = None) -> list[Section]:
    """Sections with their bullets. For a student `viewer`, open_suggestions leaves out other students' flagged fixes
    (hidden from that student's list too); without a viewer, or for a lecturer, every open fix counts."""
    see_flagged = viewer is None or viewer.role == Role.LECTURER
    section_rows = await fetch_all(conn, "select * from sections where lecture_id = %(lec)s order by ord, id", {"lec": lecture_id})
    bullet_rows = await fetch_all(
        conn,
        """select b.*, (select count(*) from suggestions g where g.bullet_id = b.id and g.status = 'open'
                          and (%(all)s or not g.flagged or g.author_id = %(me)s)) as open_suggestions
           from bullets b join sections s on s.id = b.section_id where s.lecture_id = %(lec)s order by b.ord, b.id""",
        {"lec": lecture_id, "all": see_flagged, "me": viewer.id if viewer else ""},
    )
    by_section: dict[str, list[Bullet]] = {}
    for row in bullet_rows:
        by_section.setdefault(row["section_id"], []).append(bullet_from_row(row))
    return [
        Section(
            id=s["id"],
            order=s["ord"],
            heading=s["heading"],
            start_s=s["start_s"],
            end_s=s["end_s"],
            status=s["status"],
            bullets=by_section.get(s["id"], []),
            said_not_written=[SaidNotWritten.model_validate(x) for x in s["said_not_written"]],
        )
        for s in section_rows
    ]


async def transcript(conn: Conn, lecture_id: str) -> list[TranscriptLine]:
    rows = await fetch_all(
        conn,
        "select start_s, end_s, speaker, text from transcript_segments where lecture_id = %(lec)s order by start_s",
        {"lec": lecture_id},
    )
    return [TranscriptLine.model_validate(r) for r in rows]


def lines_in_ranges(lines: list[TranscriptLine], ranges: list[TimeRange]) -> list[TranscriptLine]:
    """Transcript lines that overlap any of the ranges, in time order."""
    return [line for line in lines if any(line.start_s <= r.end_s and line.end_s >= r.start_s for r in ranges)]


def pdf_url(summary: LectureSummary) -> str | None:
    return f"/lectures/{summary.id}/pdf" if summary.status in READY_STATUSES else None


async def lecture_detail(conn: Conn, summary: LectureSummary, viewer: Me | None = None) -> LectureDetail:
    return LectureDetail(
        summary=summary,
        sections=await sections(conn, summary.id, viewer),
        board_blocks=await board_blocks(conn, summary.id),
        video_url=f"/lectures/{summary.id}/video",
        pdf_url=pdf_url(summary),
    )


async def bullet_row(conn: Conn, bullet_id: str) -> dict[str, Any] | None:
    """A bullet with its section and lecture ids."""
    return await fetch_one(
        conn,
        """select b.*, s.lecture_id, s.heading as section_heading
           from bullets b join sections s on s.id = b.section_id where b.id = %(id)s""",
        {"id": bullet_id},
    )


# ---------- Suggestions ----------
_SUGGESTION_SQL = """
select g.*, p.name as author_name, p.initials as author_initials,
  (select count(*) from votes v where v.suggestion_id = g.id) as upvotes,
  exists (select 1 from votes v where v.suggestion_id = g.id and v.user_id = %(me)s) as voted_by_me
from suggestions g join profiles p on p.id = g.author_id
"""


def suggestion_from_row(row: dict[str, Any]) -> Suggestion:
    return Suggestion(
        id=row["id"],
        bullet_id=row["bullet_id"],
        author_name="Anonymous" if row["anonymous"] else row["author_name"],
        author_initials="?" if row["anonymous"] else row["author_initials"],
        anonymous=row["anonymous"],
        proposed_text=row["proposed_text"],
        created_at=row["created_at"],
        verdict=row["verdict"],
        verdict_reason=row["verdict_reason"],
        flagged=row["flagged"],
        upvotes=row["upvotes"],
        voted_by_me=row["voted_by_me"],
        status=row["status"],
    )


async def suggestion(conn: Conn, suggestion_id: str, me: str) -> Suggestion | None:
    row = await fetch_one(conn, f"{_SUGGESTION_SQL} where g.id = %(id)s", {"me": me, "id": suggestion_id})
    return suggestion_from_row(row) if row else None


async def suggestions_for_bullet(conn: Conn, bullet_id: str, me: str, *, see_flagged: bool = True) -> list[Suggestion]:
    """Suggestions on a bullet, most upvoted first. Flagged ones are hidden from everyone but their author unless `see_flagged`."""
    rows = await fetch_all(
        conn,
        f"""{_SUGGESTION_SQL} where g.bullet_id = %(b)s and (%(all)s or not g.flagged or g.author_id = %(me)s)
            order by upvotes desc, g.created_at""",
        {"me": me, "b": bullet_id, "all": see_flagged},
    )
    return [suggestion_from_row(r) for r in rows]


async def open_suggestions(conn: Conn, lecture_id: str | None, me: str) -> list[Suggestion]:
    rows = await fetch_all(
        conn,
        f"""{_SUGGESTION_SQL} join bullets b on b.id = g.bullet_id join sections s on s.id = b.section_id
            where g.status = 'open' and (%(lec)s::text is null or s.lecture_id = %(lec)s)""",
        {"me": me, "lec": lecture_id},
    )
    return [suggestion_from_row(r) for r in rows]
