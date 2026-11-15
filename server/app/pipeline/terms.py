"""Consistent terms (Q-5): the same term or symbol should read the same way in every block of a lecture.

One model call per lecture lists variant spellings and their canonical form (e.g. "eigen value" -> "eigenvalue",
"\\lamda" -> "\\lambda"). The mapping is applied in code, conservatively:
- exact replacement of whole tokens / LaTeX fragments only (never inside a longer word or command), in one pass so
  replacements never chain; blocks are never rewritten wholesale;
- single-character variants are ignored (too easy to change meaning), as are LaTeX commands in plain text;
- a LaTeX change that stops the formula rendering (KaTeX) is undone.
Blocks that become identical are then merged. Generic across subjects.
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
    lines = [f"{b.id} | {b.text[:MAX_BLOCK_CHARS]} | {(b.latex or '')[:MAX_BLOCK_CHARS]}".replace("\n", " ") for b in blocks]
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
    """Whole-token match for any variant: not preceded by a letter, digit, _ or \\, nor followed by a letter, digit or _.
    Longest first so a longer variant wins over a shorter one it contains."""
    if not variants:
        return None
    alts = "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9_\\])(?:{alts})(?![A-Za-z0-9_])")


def replace_terms(value: str, pairs: dict[str, str], pattern: re.Pattern[str] | None) -> str:
    if pattern is None:
        return value
    return pattern.sub(lambda m: pairs[m.group(0)], value)


def apply_terms(blocks: list[BoardBlock], pairs: dict[str, str]) -> list[BoardBlock]:
    """Apply the replacements to block text and LaTeX. LaTeX commands are never put into plain text."""
    text_pairs = {v: c for v, c in pairs.items() if "\\" not in c}
    text_re, latex_re = _pattern(list(text_pairs)), _pattern(list(pairs))
    out: list[BoardBlock] = []
    for b in blocks:
        text = replace_terms(b.text, text_pairs, text_re)
        latex = replace_terms(b.latex, pairs, latex_re) if b.latex else b.latex
        out.append(b if (text, latex) == (b.text, b.latex) else b.model_copy(update={"text": text, "latex": latex}))
    return out


def merge_identical(blocks: list[BoardBlock]) -> list[BoardBlock]:
    """Merge blocks with the same type, text and LaTeX. The first keeps its id and earliest time; the most confident
    reading's frame, position and confidence win."""
    kept: dict[tuple[str, str, str | None], BoardBlock] = {}
    for b in blocks:
        key = (b.type.value, b.text, b.latex)
        first = kept.get(key)
        if first is None:
            kept[key] = b
            continue
        best = b if b.confidence > first.confidence else first
        kept[key] = first.model_copy(
            update={
                "first_seen_s": min(first.first_seen_s, b.first_seen_s),
                "best_frame_s": best.best_frame_s,
                "bbox": best.bbox,
                "confidence": best.confidence,
                "figure": first.figure or b.figure,
            }
        )
    return list(kept.values())


async def _keep_rendering(before: list[BoardBlock], after: list[BoardBlock]) -> list[BoardBlock]:
    """Undo LaTeX changes that made a formula fail to render."""
    changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if b.latex and a.latex != b.latex]
    results = await asyncio.to_thread(check_latex, [after[i].latex or "" for i in changed])
    out = list(after)
    for i, result in zip(changed, results, strict=True):
        if isinstance(result, LatexError):
            out[i] = out[i].model_copy(update={"latex": before[i].latex})
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
    merged = merge_identical(updated)
    log.info("normalise_terms: %d replacements, %d blocks merged", len(pairs), len(blocks) - len(merged))
    return merged
