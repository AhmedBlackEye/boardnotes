"""Consistent terms (Q-5): the same term or symbol should read the same way in every block of a lecture.

One model call per lecture lists variant spellings and their canonical form (e.g. "eigen value" -> "eigenvalue",
"\\lamda" -> "\\lambda"). The mapping is applied in code, conservatively:
- exact replacement of whole tokens / LaTeX fragments only (never inside a longer word or command), in one pass so
  replacements never chain; blocks are never rewritten wholesale;
- single-character variants are ignored (too easy to change meaning), as are LaTeX commands in plain text;
- a LaTeX change that stops the formula rendering (KaTeX) undoes that block's whole change (text and LaTeX).
Blocks that become identical are then merged, but only when normalisation changed at least one of them: writing that
was already identical (e.g. "x = 0" in two worked examples) stays separate. Generic across subjects.
"""

import asyncio
import logging
import re

from pydantic import Field

from app.contracts.ai import BoardBlock, Strict
from app.llm.client import LLM, LLMRequest

from .citations import LatexError, check_latex

log = logging.getLogger(__name__)

MIN_VARIANT_CHARS = 2
MAX_TERM_CHARS = 60
MAX_BLOCK_CHARS = 400  # per block in the request; longer readings are cut
MAX_REQUEST_CHARS = 40_000  # all blocks in the request; blocks beyond this are left out of the check


class TermVariant(Strict):
    variant: str = Field(description="A spelling exactly as it appears in the blocks")
    canonical: str = Field(description="The spelling to use everywhere instead")


class TermMap(Strict):
    replacements: list[TermVariant] = Field(max_length=100)


NORMALISE_INSTRUCTIONS = """\
You are checking a lecture's board readings for consistency. The blocks are given as data below, one per line as
"id | text | latex". They were read from handwriting frame by frame, so the same term or symbol is sometimes spelt
or typeset differently in different blocks (for example a word split in two, a misspelt name, or the same symbol
written with different LaTeX commands).

List each variant that should be changed to match the form used elsewhere in the lecture:
- variant: copied exactly as it appears in the text or LaTeX of a block.
- canonical: the form to use instead; prefer the form that appears most often or is clearly correct.
Only list true variants of the same term or symbol. Do not change meaning, notation the lecturer deliberately uses
differently, or anything that is merely similar. Do not list whole sentences or formulas, only the varying term or
fragment. If everything is already consistent, return an empty list."""


def terms_request(blocks: list[BoardBlock]) -> LLMRequest:
    lines: list[str] = []
    total = 0
    for b in blocks:
        line = f"{b.id} | {b.text[:MAX_BLOCK_CHARS]} | {(b.latex or '')[:MAX_BLOCK_CHARS]}".replace("\n", " ")
        total += len(line) + 1
        if total > MAX_REQUEST_CHARS:
            break
        lines.append(line)
    return LLMRequest(
        task="normalise_terms",
        tier="board",
        instructions=NORMALISE_INSTRUCTIONS,
        untrusted={"blocks": "\n".join(lines)},
        effort="low",
        max_tokens=4000,
    )


def usable_pairs(term_map: TermMap) -> dict[str, str]:
    """variant -> canonical, keeping only pairs that are safe to apply as exact replacements."""
    pairs: dict[str, str] = {}
    for r in term_map.replacements:
        variant, canonical = r.variant.strip(), r.canonical.strip()
        if variant == canonical or not canonical or len(variant) < MIN_VARIANT_CHARS:
            continue
        if len(variant) > MAX_TERM_CHARS or len(canonical) > MAX_TERM_CHARS or "\n" in canonical:
            continue
        pairs.setdefault(variant, canonical)
    return pairs


def _pattern(variants: list[str]) -> re.Pattern[str] | None:
    """Whole-token match for any variant, longest first so a longer variant wins over a shorter one it contains.
    - A plain variant must not be preceded by a letter, digit, _ or \\, nor followed by a letter, digit or _.
    - A variant starting with a LaTeX command must not be preceded by \\ (an escaped backslash), and if it ends in a
      letter it must not be followed by one (that would be a longer command). So `\\lamda_1` and `2\\lamda` match,
      `\\lamdax` does not."""
    if not variants:
        return None
    alts: list[str] = []
    for v in sorted(variants, key=len, reverse=True):
        if v.startswith("\\"):
            after = r"(?![A-Za-z])" if v[-1].isalpha() else ""
            alts.append(rf"(?<!\\){re.escape(v)}{after}")
        else:
            alts.append(rf"(?<![A-Za-z0-9_\\]){re.escape(v)}(?![A-Za-z0-9_])")
    return re.compile("|".join(alts))


def replace_terms(value: str, pairs: dict[str, str], pattern: re.Pattern[str] | None) -> str:
    if pattern is None:
        return value
    return pattern.sub(lambda m: pairs[m.group(0)], value)


def apply_terms(blocks: list[BoardBlock], pairs: dict[str, str]) -> list[BoardBlock]:
    """Apply the replacements to block text and LaTeX. LaTeX commands are never put into plain text.
    Unchanged blocks are returned as the same objects."""
    text_pairs = {v: c for v, c in pairs.items() if "\\" not in c}
    text_re, latex_re = _pattern(list(text_pairs)), _pattern(list(pairs))
    out: list[BoardBlock] = []
    for b in blocks:
        text = replace_terms(b.text, text_pairs, text_re)
        latex = replace_terms(b.latex, pairs, latex_re) if b.latex else b.latex
        out.append(b if (text, latex) == (b.text, b.latex) else b.model_copy(update={"text": text, "latex": latex}))
    return out


BlockKey = tuple[str, str, str | None]


def _key(b: BoardBlock) -> BlockKey:
    return (b.type.value, b.text, b.latex)


def merge_identical(blocks: list[BoardBlock], changed: set[str]) -> list[BoardBlock]:
    """Merge blocks with the same type, text and LaTeX, only in groups where at least one block's id is in `changed`
    (normalisation made them identical). The first keeps its id, place and earliest time; the most confident
    reading's frame, position and confidence win. Other blocks are kept as they are, in order."""
    groups: dict[BlockKey, list[BoardBlock]] = {}
    for b in blocks:
        groups.setdefault(_key(b), []).append(b)
    mergeable = {key for key, group in groups.items() if len(group) > 1 and any(b.id in changed for b in group)}

    out: list[BoardBlock] = []
    slot: dict[BlockKey, int] = {}  # mergeable key -> index of its first block in out
    for b in blocks:
        key = _key(b)
        if key not in mergeable:
            out.append(b)
            continue
        if key not in slot:
            slot[key] = len(out)
            out.append(b)
            continue
        first = out[slot[key]]
        best = b if b.confidence > first.confidence else first
        out[slot[key]] = first.model_copy(
            update={
                "first_seen_s": min(first.first_seen_s, b.first_seen_s),
                "best_frame_s": best.best_frame_s,
                "bbox": best.bbox,
                "confidence": best.confidence,
                "figure": first.figure or b.figure,
            }
        )
    return out


async def _keep_rendering(before: list[BoardBlock], after: list[BoardBlock]) -> list[BoardBlock]:
    """Undo the whole change (text and LaTeX) of any block whose new LaTeX fails to render, keeping them consistent."""
    changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if b.latex and a.latex != b.latex]
    results = await asyncio.to_thread(check_latex, [after[i].latex or "" for i in changed])
    out = list(after)
    for i, result in zip(changed, results, strict=True):
        if isinstance(result, LatexError):
            out[i] = before[i]
    return out


async def normalise_terms(blocks: list[BoardBlock], llm: LLM) -> list[BoardBlock]:
    """Pipeline stage (TermNormaliser). See the module docstring. On a model failure the blocks are returned as they were."""
    if len(blocks) < 2:
        return blocks
    try:
        term_map = await llm.structured(terms_request(blocks), TermMap)
    except Exception as exc:
        log.warning("normalise_terms: skipped, model call failed: %s", exc)
        return blocks
    pairs = usable_pairs(term_map)
    if not pairs:
        return blocks
    updated = await _keep_rendering(blocks, apply_terms(blocks, pairs))
    changed = {new.id for old, new in zip(blocks, updated, strict=True) if new is not old}
    merged = merge_identical(updated, changed)
    log.info("normalise_terms: %d replacements, %d blocks merged", len(pairs), len(blocks) - len(merged))
    return merged
