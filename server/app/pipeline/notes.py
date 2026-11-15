"""Sectioning and note writing (B-3). Board blocks and the transcript are untrusted data: they only ever go in
`LLMRequest.untrusted`, rendered compactly with ids and times so the model can cite them."""

import asyncio

from app.contracts.ai import BoardBlock, SectionNotes, SectionPlan, TranscriptSegment
from app.llm.client import LLM, LLMRequest

MAX_SECTIONS = 30  # hard cap on sections (one Opus call each), whatever the model returns
MIN_SECTION_S = 20.0  # shorter sections are merged into a neighbour
NOTES_CONCURRENCY = 4  # Opus calls in flight at once


class NotesError(RuntimeError):
    """Raised when a lecture with content gets no usable section plan."""


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

Organise first, then write
- Write the notes a strong student would keep, not a transcript of everything on the board. Merge points that repeat
  the same idea, put them in a logical order (motivation, definitions, method, worked example, result), and leave out
  housekeeping (e.g. "pause the video", "let's start", greetings) and anything a student would not revise from.
- Aim for the fewest bullets that cover the section fully: usually 3-8.

Bullets
- Each bullet states one idea, definition, result or step a student needs. Keep bullets short; no filler.
- kind: "definition" when the bullet defines a term; "example" for a worked example or exercise (put its steps in the
  text and the key line in latex); "result" for a key formula, rule or conclusion worth boxing; "remark" for an
  important intuition or warning; otherwise "point". Use boxes sparingly: most bullets are "point".
- title: for definition/example/result/remark, a short box title (the term defined, or e.g. "Solving by substitution");
  otherwise null.
- figure_block_id: the id of a diagram block (type diagram, marked "figure:" below) that genuinely helps this bullet,
  or null. Show each drawing at most once in the section, never pick one marked "(no figure)", and skip diagrams that
  only show empty axes or repeat a drawing already chosen.
- Every bullet MUST cite its sources: board_block_ids (ids exactly as given, e.g. "b_0003") and/or transcript_ranges
  (start_s/end_s copied from transcript segments in this section). Cite only what you used. A bullet you cannot cite
  must be left out.
- Prefer the lecturer's explanation for meaning and order: use the board for exact formulas, and the transcript for why
  and how. Ignore student questions unless the lecturer's answer adds content.
- latex: the bullet's key formula in KaTeX-compatible LaTeX (no $ signs), copied from the cited board block where there is
  one; otherwise null.
- confidence (0-1, calibrated; be decisive): how sure you are the bullet is faithful to the lecture.
  0.9+: the board and the lecturer's speech agree, or one of them states it clearly. This is the normal case.
  0.75-0.9: supported clearly by one source, with minor uncertainty in wording or a symbol.
  below 0.75: only when you genuinely doubt the content itself: the sources disagree, the key writing is illegible and
  the speech doesn't settle it, or you are inferring something not clearly stated.
  A clear reading of a formula plus a blurry duplicate of it is still clear: judge by the best evidence, and when the
  speech confirms writing that is partly cut off, trust it. Prefer citing the clearest board block for each fact.
- Do not add facts, examples or steps that are not in the lecture.

said_not_written
- List important things the lecturer said that are not on the board (an intuition, a warning, a reason), each with
  at_s set to the start of the transcript segment where it was said. At most 3, only content a student would revise
  from (no instructions about the video), and nothing already stated in a bullet. Leave the list empty if there are none.

Set heading to the given section heading, start_s to {start:.1f} and end_s to {end:.1f}."""


def _one_line(text: str) -> str:
    return " ".join(text.split())


def render_blocks(blocks: list[BoardBlock]) -> str:
    """One compact line per block: `b_0001 @12.0s math conf=0.82: <latex or text>`. Diagram blocks also say what
    their figure shows, or "(no figure)" when curation hid it (blank or repeated)."""
    lines = []
    for b in blocks:
        content = b.latex if b.latex else b.text
        line = f"{b.id} @{b.first_seen_s:.1f}s {b.type} conf={b.confidence:.2f}: {_one_line(content)}"
        if b.type == "diagram":
            line += f" | figure: {_one_line(b.figure.caption)}" if b.figure is not None else " | (no figure)"
        lines.append(line)
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


def _merge_into_neighbour(spans: list[SectionPlan.Span], i: int) -> None:
    """Fold section i into the one before it (or after it, for the first), keeping the neighbour's heading."""
    if i > 0:
        spans[i - 1] = spans[i - 1].model_copy(update={"end_s": spans[i].end_s})
    else:
        spans[1] = spans[1].model_copy(update={"start_s": spans[0].start_s})
    del spans[i]


def clean_plan(plan: SectionPlan, lecture_end_s: float) -> SectionPlan:
    """Turn the model's plan into a clean split of 0..lecture_end_s.

    Drops empty, reversed and out-of-range spans, then uses each remaining section's start as a cut point, so overlaps
    and gaps are repaired (a gap joins the section before it) and the first and last sections reach the lecture's ends.
    Sections shorter than MIN_SECTION_S are merged into a neighbour, and the shortest are merged until at most
    MAX_SECTIONS remain (the section count comes from the model, which reads untrusted text)."""
    usable = sorted((s for s in plan.sections if s.end_s > s.start_s and s.start_s < lecture_end_s), key=lambda s: s.start_s)
    if not usable:
        return SectionPlan(sections=[])
    starts = [0.0] + [s.start_s for s in usable[1:]]
    ends = starts[1:] + [lecture_end_s]
    spans = [SectionPlan.Span(heading=s.heading, start_s=a, end_s=b) for s, a, b in zip(usable, starts, ends, strict=True) if b > a]
    i = 0
    while i < len(spans) and len(spans) > 1:
        if spans[i].end_s - spans[i].start_s < MIN_SECTION_S:
            _merge_into_neighbour(spans, i)
        else:
            i += 1
    while len(spans) > MAX_SECTIONS:
        shortest = min(range(len(spans)), key=lambda k: spans[k].end_s - spans[k].start_s)
        _merge_into_neighbour(spans, shortest)
    return SectionPlan(sections=spans)


async def plan_sections(blocks: list[BoardBlock], transcript: list[TranscriptSegment], llm: LLM) -> SectionPlan:
    """Ask the model for sections and clean them up. Raises NotesError if a lecture with content gets none."""
    _, end = lecture_span(blocks, transcript)
    plan = clean_plan(await llm.structured(plan_request(blocks, transcript), SectionPlan), end)
    if end > 0 and not plan.sections:
        raise NotesError("the model returned no usable sections for this lecture")
    return plan


def blocks_in(span: SectionPlan.Span, blocks: list[BoardBlock], *, last: bool = False) -> list[BoardBlock]:
    """Blocks that first appear, or are best seen, during the section. The last section includes its end time."""

    def inside(t: float) -> bool:
        return span.start_s <= t < span.end_s or (last and t == span.end_s)

    return [b for b in blocks if inside(b.first_seen_s) or inside(b.best_frame_s)]


def segments_in(span: SectionPlan.Span, transcript: list[TranscriptSegment]) -> list[TranscriptSegment]:
    """Transcript segments overlapping the section."""
    return [s for s in transcript if s.start_s < span.end_s and s.end_s > span.start_s]


def notes_request(
    span: SectionPlan.Span, blocks: list[BoardBlock], transcript: list[TranscriptSegment], *, last: bool = False
) -> LLMRequest:
    return LLMRequest(
        task="write_notes",
        tier="notes",
        instructions=NOTES_INSTRUCTIONS.format(start=span.start_s, end=span.end_s),
        untrusted={
            "section_heading": span.heading,
            "board_blocks": render_blocks(blocks_in(span, blocks, last=last)),
            "transcript": render_transcript(segments_in(span, transcript)),
        },
        effort="medium",
    )


async def _write_section(
    span: SectionPlan.Span, blocks: list[BoardBlock], transcript: list[TranscriptSegment], llm: LLM, sem: asyncio.Semaphore, *, last: bool
) -> SectionNotes:
    async with sem:
        notes = await llm.structured(notes_request(span, blocks, transcript, last=last), SectionNotes)
    # The plan is the source of truth for where a section sits.
    return notes.model_copy(update={"heading": span.heading, "start_s": span.start_s, "end_s": span.end_s})


async def write_notes(plan: SectionPlan, blocks: list[BoardBlock], transcript: list[TranscriptSegment], llm: LLM) -> list[SectionNotes]:
    """Write every section's notes, one model call per section (at most NOTES_CONCURRENCY at once), in plan order."""
    sem = asyncio.Semaphore(NOTES_CONCURRENCY)
    n = len(plan.sections)
    return list(
        await asyncio.gather(*(_write_section(span, blocks, transcript, llm, sem, last=i == n - 1) for i, span in enumerate(plan.sections)))
    )
