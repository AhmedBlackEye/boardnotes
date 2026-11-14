"""Lecturer review queue and decisions (D-4)."""

import math
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from app import repo
from app.auth import Lecturer
from app.contracts.ai import LOW_CONFIDENCE
from app.contracts.api import LectureSummary, ReviewDecisionIn, ReviewItem
from app.contracts.enums import LectureStatus, ReviewDecision, SectionStatus, Verdict
from app.db import Conn, execute, fetch_all, fetch_one
from app.state import ConnDep, StateDep

router = APIRouter(tags=["review"])

BULLET_PREFIX = "bullet:"


def priority(confidence: float, upvotes: int, agrees: bool, flagged: bool) -> float:
    """docs/architecture.md#review-priority"""
    return 2 * (1 - confidence) + math.log2(1 + upvotes) + (1 if agrees else 0) - (2 if flagged else 0)


_UNCERTAIN_SQL = """
select b.id as bullet_id, b.text, b.confidence, b.board_block_ids, s.id as section_id, s.heading, s.lecture_id
from bullets b join sections s on s.id = b.section_id
where not b.verified and b.confidence < %(low)s and (%(lec)s::text is null or s.lecture_id = %(lec)s)
  and not exists (select 1 from suggestions g where g.bullet_id = b.id and g.status = 'open')
"""


async def _item(conn: Conn, row: dict[str, Any], suggestion_id: str | None, me: str) -> ReviewItem:
    lecture_id = row["lecture_id"]
    block_ids = list(row["board_block_ids"])
    blocks = await repo.board_blocks(conn, lecture_id, block_ids[:1]) if block_ids else []
    suggestion = await repo.suggestion(conn, suggestion_id, me) if suggestion_id else None
    if suggestion is None:
        score = priority(row["confidence"], 0, False, False)
    else:
        score = priority(row["confidence"], suggestion.upvotes, suggestion.verdict == Verdict.AGREES, suggestion.flagged)
    return ReviewItem(
        id=suggestion_id or f"{BULLET_PREFIX}{row['bullet_id']}",
        lecture_id=lecture_id,
        section_id=row["section_id"],
        section_heading=row["heading"],
        bullet_id=row["bullet_id"],
        current_text=row["text"],
        suggestion=suggestion,
        board_block=blocks[0] if blocks else None,
        snapshot_url=repo.snapshot_url(lecture_id, blocks[0].id) if blocks else None,
        priority=score,
    )


@router.get("/review")
async def review_queue(user: Lecturer, conn: ConnDep, lecture_id: str | None = Query(default=None)) -> list[ReviewItem]:
    params = {"lec": lecture_id}
    items: list[ReviewItem] = []
    for row in await fetch_all(
        conn,
        """select g.id as suggestion_id, b.id as bullet_id, b.text, b.confidence, b.board_block_ids,
               s.id as section_id, s.heading, s.lecture_id
            from suggestions g join bullets b on b.id = g.bullet_id join sections s on s.id = b.section_id
            where g.status = 'open' and (%(lec)s::text is null or s.lecture_id = %(lec)s)""",
        params,
    ):
        items.append(await _item(conn, row, row["suggestion_id"], user.id))
    for row in await fetch_all(
        conn,
        _UNCERTAIN_SQL,
        {**params, "low": LOW_CONFIDENCE},
    ):
        items.append(await _item(conn, row, None, user.id))
    items.sort(key=lambda i: (-i.priority, i.id))
    return items


async def _open_items(conn: Conn, lecture_id: str, section_id: str | None = None) -> int:
    row = await fetch_one(
        conn,
        """select
             (select count(*) from suggestions g join bullets b on b.id = g.bullet_id join sections s on s.id = b.section_id
                where g.status = 'open' and s.lecture_id = %(lec)s and (%(sec)s::text is null or s.id = %(sec)s))
           + (select count(*) from bullets b join sections s on s.id = b.section_id
                where s.lecture_id = %(lec)s and (%(sec)s::text is null or s.id = %(sec)s) and not b.verified and b.confidence < %(low)s
                  and not exists (select 1 from suggestions g where g.bullet_id = b.id and g.status = 'open')) as n""",
        {"lec": lecture_id, "sec": section_id, "low": LOW_CONFIDENCE},
    )
    assert row is not None
    return int(row["n"])


async def _record_training_example(conn: Conn, bullet: dict[str, Any], corrected: str) -> None:
    block_id = bullet["board_block_ids"][0] if bullet["board_block_ids"] else None
    snapshot = None
    if block_id:
        block = await fetch_one(
            conn,
            "select snapshot_path from board_blocks where lecture_id = %(lec)s and id = %(id)s",
            {"lec": bullet["lecture_id"], "id": block_id},
        )
        snapshot = block["snapshot_path"] if block else None
    await execute(
        conn,
        """insert into training_examples (lecture_id, board_block_id, snapshot_path, model_reading, corrected_text)
           values (%(lec)s, %(blk)s, %(snap)s, %(old)s, %(new)s)""",
        {"lec": bullet["lecture_id"], "blk": block_id, "snap": snapshot, "old": bullet["text"], "new": corrected},
    )


@router.post("/review/{item_id}/decision")
async def decide(
    item_id: str, body: ReviewDecisionIn, user: Lecturer, state: StateDep, conn: ConnDep, background: BackgroundTasks
) -> LectureSummary:
    suggestion_id: str | None = None
    proposed: str | None = None
    if item_id.startswith(BULLET_PREFIX):
        bullet_id = item_id.removeprefix(BULLET_PREFIX)
    else:
        suggestion_id = item_id
        sug = await fetch_one(
            conn, "select bullet_id, status, proposed_text from suggestions where id = %(id)s for update", {"id": item_id}
        )
        if sug is None:
            raise repo.not_found("Review item not found")
        if sug["status"] != "open":
            raise HTTPException(status.HTTP_409_CONFLICT, "This item has already been decided")
        bullet_id = sug["bullet_id"]
        proposed = sug["proposed_text"]
    bullet = await repo.bullet_row(conn, bullet_id)
    if bullet is None:
        raise repo.not_found("Review item not found")
    if suggestion_id is None and not (repo.is_uncertain(bullet["confidence"], bullet["verified"])):
        raise HTTPException(status.HTTP_409_CONFLICT, "This item has already been decided")

    new_text: str | None = None
    if body.decision == ReviewDecision.EDIT:
        if not body.edited_text or not body.edited_text.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "edited_text is required when editing")
        new_text = body.edited_text.strip()
    elif body.decision == ReviewDecision.APPROVE:
        new_text = proposed

    lecture_id = bullet["lecture_id"]
    if suggestion_id is None and body.decision == ReviewDecision.REJECT:
        await execute(conn, "delete from bullets where id = %(id)s", {"id": bullet_id})  # an uncertain reading the lecturer says is wrong
    else:
        if new_text is not None and new_text != bullet["text"]:
            await _record_training_example(conn, bullet, new_text)
            await execute(
                conn, "update bullets set text = %(t)s, latex = null, verified = true where id = %(id)s", {"t": new_text, "id": bullet_id}
            )
        elif body.decision != ReviewDecision.REJECT:
            await execute(conn, "update bullets set verified = true where id = %(id)s", {"id": bullet_id})
    if suggestion_id is not None:
        outcome = "rejected" if body.decision == ReviewDecision.REJECT else "approved"
        await execute(conn, "update suggestions set status = %(s)s where id = %(id)s", {"s": outcome, "id": suggestion_id})
        if outcome == "approved":  # other open fixes for this line are now out of date
            await execute(conn, "update suggestions set status = 'rejected' where bullet_id = %(b)s and status = 'open'", {"b": bullet_id})
        else:
            # Rejecting a fix keeps the current reading; the lecturer saw the evidence, so it counts as checked once no
            # other fixes for this line are waiting.
            await execute(
                conn,
                """update bullets set verified = true where id = %(b)s
                   and not exists (select 1 from suggestions where bullet_id = %(b)s and status = 'open')""",
                {"b": bullet_id},
            )

    await _refresh_status(conn, lecture_id, bullet["section_id"])
    stale_pdfs = await state.pdfs.invalidate(conn, lecture_id)
    state.ask_cache.invalidate(lecture_id)
    # Background tasks run after this route's transaction has committed; invalidating again then drops anything
    # computed from the notes as they were before the commit.
    background.add_task(state.ask_cache.invalidate, lecture_id)
    background.add_task(state.pdfs.refresh_after_commit, lecture_id, stale_pdfs)
    summary = await repo.get_summary(conn, lecture_id)
    assert summary is not None
    return summary


async def _refresh_status(conn: Conn, lecture_id: str, section_id: str) -> None:
    section_open = await _open_items(conn, lecture_id, section_id)
    section_status = SectionStatus.VERIFIED if section_open == 0 else SectionStatus.UNCERTAIN
    await execute(conn, "update sections set status = %(s)s where id = %(id)s", {"s": section_status.value, "id": section_id})
    lecture_status = LectureStatus.VERIFIED if await _open_items(conn, lecture_id) == 0 else LectureStatus.IN_REVIEW
    await execute(conn, "update lectures set status = %(s)s where id = %(id)s", {"s": lecture_status.value, "id": lecture_id})
