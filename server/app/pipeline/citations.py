"""Citation check (B-4): pure code that keeps notes honest.

- A bullet needs at least one valid citation: a known board block id, or a transcript range inside its section that
  overlaps a real transcript segment. Invalid citations are removed; bullets left with none are dropped.
- A bullet can't be more confident than the board blocks it cites.
- Bullets with weak support are kept but marked uncertain (confidence below LOW_CONFIDENCE).
- check_latex validates LaTeX with KaTeX (the web renderer) through scripts/katex_check.mjs.
"""

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from typing import Literal

from app.config import REPO_ROOT
from app.contracts.ai import LOW_CONFIDENCE, BoardBlock, NoteBullet, SaidNotWritten, SectionNotes, TimeRange, TranscriptSegment

from .interfaces import CitationReport

log = logging.getLogger(__name__)

TIME_TOLERANCE_S = 2.0  # slack for rounding when matching cited times to sections and transcript segments
UNCERTAIN_CAP = round(LOW_CONFIDENCE - 0.05, 2)  # confidence given to bullets with weak citations


def _overlaps(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    return a_start <= b_end + TIME_TOLERANCE_S and a_end >= b_start - TIME_TOLERANCE_S


def _range_problem(r: TimeRange, section: SectionNotes, transcript: list[TranscriptSegment]) -> str | None:
    label = f"{r.start_s:.1f}-{r.end_s:.1f}s"
    if r.end_s < r.start_s:
        return f"transcript range {label} ends before it starts"
    if not _overlaps(r.start_s, r.end_s, section.start_s, section.end_s):
        return f"transcript range {label} is outside the section ({section.start_s:.1f}-{section.end_s:.1f}s)"
    if not any(_overlaps(r.start_s, r.end_s, s.start_s, s.end_s) for s in transcript):
        return f"transcript range {label} matches no transcript segment"
    return None


def _check_bullet(
    bullet: NoteBullet, section: SectionNotes, blocks: dict[str, BoardBlock], transcript: list[TranscriptSegment]
) -> tuple[NoteBullet | None, list[str]]:
    """Return the bullet with only valid citations (or None if none are left) and the problems found."""
    problems: list[str] = []
    ids = []
    for block_id in bullet.board_block_ids:
        if block_id in blocks:
            ids.append(block_id)
        else:
            problems.append(f"unknown board block {block_id!r}")
    ranges = []
    for r in bullet.transcript_ranges:
        problem = _range_problem(r, section, transcript)
        if problem:
            problems.append(problem)
        else:
            ranges.append(r)

    if not ids and not ranges:
        return None, problems or ["no citations"]

    confidence = bullet.confidence
    if ids:
        confidence = min(confidence, *(blocks[i].confidence for i in ids))
    weak = bool(problems) or (bullet.latex is not None and not ids)  # some citations were bad, or maths only heard
    if weak:
        confidence = min(confidence, UNCERTAIN_CAP)
    return bullet.model_copy(update={"board_block_ids": ids, "transcript_ranges": ranges, "confidence": confidence}), problems


def _said_ok(item: SaidNotWritten, section: SectionNotes, transcript: list[TranscriptSegment]) -> bool:
    in_section = _overlaps(item.at_s, item.at_s, section.start_s, section.end_s)
    return in_section and any(_overlaps(item.at_s, item.at_s, s.start_s, s.end_s) for s in transcript)


def validate_citations(notes: list[SectionNotes], blocks: list[BoardBlock], transcript: list[TranscriptSegment]) -> CitationReport:
    by_id = {b.id: b for b in blocks}
    valid: list[SectionNotes] = []
    dropped: list[str] = []
    flagged = 0
    for section in notes:
        kept: list[NoteBullet] = []
        for bullet in section.bullets:
            checked, problems = _check_bullet(bullet, section, by_id, transcript)
            where = f"[{section.heading}] {bullet.text[:80]!r}"
            if checked is None:
                dropped.append(f"Dropped bullet {where}: {'; '.join(problems)}")
                continue
            if problems:
                dropped.append(f"Removed citations from {where}: {'; '.join(problems)}")
            if checked.confidence < LOW_CONFIDENCE:
                flagged += 1
            kept.append(checked)
        said = []
        for item in section.said_not_written:
            if _said_ok(item, section, transcript):
                said.append(item)
            else:
                where = f"[{section.heading}] {item.text[:80]!r}"
                dropped.append(f"Dropped said-not-written {where}: {item.at_s:.1f}s is not in this section's transcript")
        valid.append(section.model_copy(update={"bullets": kept, "said_not_written": said}))
    for reason in dropped:
        log.info("citations: %s", reason)
    return CitationReport(valid=valid, dropped=dropped, flagged_bullets=flagged)


# ---------- LaTeX check ----------


@dataclass(frozen=True)
class LatexError:
    message: str


LatexResult = Literal[True, "unknown"] | LatexError
KATEX_SCRIPT = REPO_ROOT / "scripts" / "katex_check.mjs"
KATEX_TIMEOUT_S = 30


def check_latex(latex_list: list[str]) -> list[LatexResult]:
    """Validate each expression with KaTeX in one batch: True if it renders, LatexError if not,
    "unknown" for all of them if node or KaTeX isn't available."""
    if not latex_list:
        return []
    unknown: list[LatexResult] = ["unknown"] * len(latex_list)
    node = shutil.which("node")
    if node is None or not KATEX_SCRIPT.exists():
        log.warning("check_latex: node or %s not found; LaTeX not checked", KATEX_SCRIPT)
        return unknown
    try:
        proc = subprocess.run(  # noqa: S603 - fixed script path, data goes via stdin
            [node, str(KATEX_SCRIPT)], input=json.dumps(latex_list), capture_output=True, text=True, timeout=KATEX_TIMEOUT_S, check=False
        )
        if proc.returncode != 0:
            log.warning("check_latex: KaTeX check failed (exit %d): %s", proc.returncode, proc.stderr.strip()[:500])
            return unknown
        raw = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        log.warning("check_latex: KaTeX check unavailable: %s", exc)
        return unknown
    if not isinstance(raw, list) or len(raw) != len(latex_list):
        log.warning("check_latex: unexpected output from KaTeX check")
        return unknown
    return [True if r.get("ok") else LatexError(str(r.get("error", "invalid LaTeX"))) for r in raw]
