"""Rewrite the notes of an already-processed lecture from its stored board reading and transcript.

Skips the video, transcription and board-reading stages: re-runs diagram curation (code only), sectioning and note
writing (Opus: about 4-6 model calls, roughly $0.15-0.30 for a 5-minute lecture when LLM_MODE=live), and the citation
check. Existing sections, bullets and their suggestions are replaced. Restart the API afterwards so the PDF is rebuilt.

Usage: LLM_MODE=live uv run --project server python scripts/rewrite_notes.py <lecture_id>
"""

import asyncio
import sys

from psycopg.types.json import Jsonb

from app import repo
from app.config import settings
from app.contracts.ai import TranscriptSegment
from app.contracts.enums import LectureStatus
from app.db import create_pool, execute
from app.jobs.runner import save_notes, set_lecture
from app.llm.client import get_llm
from app.pipeline.board import drop_fragments
from app.pipeline.citations import validate_citations
from app.pipeline.diagrams import curate_figures
from app.pipeline.notes import plan_sections, write_notes


async def main(lecture_id: str) -> None:
    pool = create_pool(settings.database_url)
    await pool.open()
    llm = get_llm()
    try:
        async with pool.connection() as conn:
            blocks = await repo.board_blocks(conn, lecture_id)
            lines = await repo.transcript(conn, lecture_id)
        segments = [TranscriptSegment(start_s=t.start_s, end_s=t.end_s, speaker=t.speaker, text=t.text) for t in lines]
        if not blocks and not segments:
            sys.exit(f"{lecture_id}: no board blocks or transcript stored")

        blocks = drop_fragments(blocks)  # unsure pieces of other blocks stay in the database but are not given to the notes
        curated = curate_figures(blocks)
        async with pool.connection() as conn:
            for before, after in zip(blocks, curated, strict=True):
                if before.figure != after.figure:
                    fig = Jsonb(after.figure.model_dump()) if after.figure else None
                    await execute(conn, "update board_blocks set figure = %(f)s where id = %(id)s", {"f": fig, "id": after.id})
        hidden = sum(1 for a, b in zip(blocks, curated, strict=True) if a.figure is not None and b.figure is None)
        print(f"{len(blocks)} board blocks, {len(segments)} transcript segments; hid {hidden} blank/repeated diagram(s)")

        plan = await plan_sections(curated, segments, llm)
        notes = await write_notes(plan, curated, segments, llm)
        report = validate_citations(notes, curated, segments)
        for reason in report.dropped:
            print("  citation check:", reason)
        await save_notes(pool, lecture_id, report.valid)
        await set_lecture(pool, lecture_id, status=LectureStatus.DRAFT.value)
        async with pool.connection() as conn:
            await execute(conn, "delete from pdfs where lecture_id = %(lec)s", {"lec": lecture_id})
        for s in report.valid:
            kinds = ", ".join(b.kind for b in s.bullets)
            figs = sum(1 for b in s.bullets if b.figure_block_id)
            print(f"  · {s.heading}: {len(s.bullets)} bullets [{kinds}], {figs} figure(s), {len(s.said_not_written)} said-not-written")
        u = llm.usage
        print(f"model calls: {u.calls}, input tokens {u.input_tokens}, output tokens {u.output_tokens}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
