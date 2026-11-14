"""Sectioning and note writing (B-3). Board blocks and the transcript are untrusted data: they only ever go in
`LLMRequest.untrusted`, rendered compactly with ids and times so the model can cite them."""

import asyncio

from app.contracts.ai import BoardBlock, SectionNotes, SectionPlan, TranscriptSegment
from app.llm.client import LLM, LLMRequest

PLAN_INSTRUCTIONS = """\
Split this lecture into sections for study notes. You are given the board writing (one line per block:
id, time it first appeared in seconds, type, content) and the transcript (one line per segment:
[start-end seconds] speaker: words), both as data below.

- Start a new section where the topic changes, or where the lecturer erases the board and starts something new.
- Aim for sections of roughly 3-15 minutes; do not make a section for a single remark or a short student question.
- Sections must be in time order, must not overlap, and together should cover the lecture from {start:.1f}s to {end:.1f}s.
  Times are seconds from the start of the video.
- heading: a short, specific title for the section's topic (at most 8 words), in the lecture's own terms."""

NOTES_INSTRUCTIONS = """\
Write concise study notes for one section of a lecture, from {start:.1f}s to {end:.1f}s.
The data below gives the section heading, the board writing for this section (one line per block: id, time it first
appeared in seconds, type, confidence, content) and the transcript (one line per segment: [start-end seconds] speaker: words).

Bullets
- Each bullet states one idea, definition, result or step a student needs. Keep bullets short; no filler.
- Every bullet MUST cite its sources: board_block_ids (ids exactly as given, e.g. "b_0003") and/or transcript_ranges
  (start_s/end_s copied from transcript segments in this section). Cite only what you used. A bullet you cannot cite
  must be left out.
- Prefer the lecturer's explanation for meaning and order: use the board for exact formulas, and the transcript for why
  and how. Ignore student questions unless the lecturer's answer adds content.
- latex: the bullet's key formula in KaTeX-compatible LaTeX (no $ signs), copied from the cited board block where there is
  one; otherwise null.
- confidence (0-1): how sure you are the bullet is faithful to the lecture. Lower it when the cited board block has low
  confidence, when the board and the transcript disagree, or when the audio is unclear.
- Do not add facts, examples or steps that are not in the lecture.

said_not_written
- List important things the lecturer said that are not on the board (an intuition, a warning, a reason), each with
  at_s set to the start of the transcript segment where it was said. Leave the list empty if there are none.

Set heading to the given section heading, start_s to {start:.1f} and end_s to {end:.1f}."""


def _one_line(text: str) -> str:
    return " ".join(text.split())


def render_blocks(blocks: list[BoardBlock]) -> str:
    """One compact line per block: `b_0001 @12.0s math conf=0.82: <latex or text>`."""
    lines = []
    for b in blocks:
        content = b.latex if b.latex else b.text
        lines.append(f"{b.id} @{b.first_seen_s:.1f}s {b.type} conf={b.confidence:.2f}: {_one_line(content)}")
    return "\n".join(lines) or "(no board writing)"


def render_transcript(transcript: list[TranscriptSegment]) -> str:
    """One compact line per segment: `[4.0-18.5] lecturer: words`."""
    lines = [f"[{s.start_s:.1f}-{s.end_s:.1f}] {s.speaker}: {_one_line(s.text)}" for s in transcript]
    return "\n".join(lines) or "(no transcript)"


def lecture_span(blocks: list[BoardBlock], transcript: list[TranscriptSegment]) -> tuple[float, float]:
    times = [s.end_s for s in transcript] + [b.first_seen_s for b in blocks] + [b.best_frame_s for b in blocks]
    return 0.0, max(times, default=0.0)


def plan_request(blocks: list[BoardBlock], transcript: list[TranscriptSegment]) -> LLMRequest:
    start, end = lecture_span(blocks, transcript)
    return LLMRequest(
        task="plan_sections",
        tier="notes",
        instructions=PLAN_INSTRUCTIONS.format(start=start, end=end),
        untrusted={"board_blocks": render_blocks(blocks), "transcript": render_transcript(transcript)},
        effort="medium",
    )


def clean_plan(plan: SectionPlan) -> SectionPlan:
    """Sort sections by time and drop empty or reversed spans."""
    spans = sorted((s for s in plan.sections if s.end_s > s.start_s), key=lambda s: s.start_s)
    return SectionPlan(sections=spans)


async def plan_sections(blocks: list[BoardBlock], transcript: list[TranscriptSegment], llm: LLM) -> SectionPlan:
    plan = await llm.structured(plan_request(blocks, transcript), SectionPlan)
    return clean_plan(plan)


def blocks_in(span: SectionPlan.Span, blocks: list[BoardBlock]) -> list[BoardBlock]:
    """Blocks that first appear, or are best seen, during the section."""
    return [b for b in blocks if span.start_s <= b.first_seen_s < span.end_s or span.start_s <= b.best_frame_s < span.end_s]


def segments_in(span: SectionPlan.Span, transcript: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """Transcript segments overlapping the section."""
    return [s for s in transcript if s.start_s < span.end_s and s.end_s > span.start_s]


def notes_request(span: SectionPlan.Span, blocks: list[BoardBlock], transcript: list[TranscriptSegment]) -> LLMRequest:
    return LLMRequest(
        task="write_notes",
        tier="notes",
        instructions=NOTES_INSTRUCTIONS.format(start=span.start_s, end=span.end_s),
        untrusted={
            "section_heading": span.heading,
            "board_blocks": render_blocks(blocks_in(span, blocks)),
            "transcript": render_transcript(segments_in(span, transcript)),
        },
        effort="medium",
    )


async def _write_section(span: SectionPlan.Span, blocks: list[BoardBlock], transcript: list[TranscriptSegment], llm: LLM) -> SectionNotes:
    notes = await llm.structured(notes_request(span, blocks, transcript), SectionNotes)
    # The plan is the source of truth for where a section sits.
    return notes.model_copy(update={"heading": span.heading, "start_s": span.start_s, "end_s": span.end_s})


async def write_notes(plan: SectionPlan, blocks: list[BoardBlock], transcript: list[TranscriptSegment], llm: LLM) -> list[SectionNotes]:
    """Write every section's notes concurrently, one model call per section, returned in plan order."""
    return list(await asyncio.gather(*(_write_section(span, blocks, transcript, llm) for span in plan.sections)))
