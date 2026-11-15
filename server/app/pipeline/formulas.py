"""Formula render check (Q-2): board LaTeX that KaTeX can't render gets one closer look.

1. Every block with LaTeX is checked with KaTeX (`check_latex`, the web renderer).
2. Each failing block is re-read once at tier "notes", from a crop of its best keyframe around its bbox, at most
   MAX_REREADS per lecture (lowest confidence first); the rest are marked uncertain without a re-read.
3. If the new reading renders, it replaces the old one. Otherwise the text is kept, the LaTeX dropped and the
   confidence capped below LOW_CONFIDENCE so the block shows as uncertain.
If KaTeX can't run ("unknown"), nothing is changed. Generic across subjects: only rendering is checked.
"""

import asyncio
import io
import logging

from PIL import Image as PILImage

from app.contracts.ai import BoardBlock, BoardReadBlock
from app.llm.client import LLM, Image, LLMRequest

from .board import MAX_IMAGE_PIXELS, load_image
from .citations import UNCERTAIN_CAP, LatexError, check_latex
from .interfaces import Keyframe

log = logging.getLogger(__name__)

CROP_MARGIN = 0.05  # extra context around the block, as a share of the frame on each side
REREAD_CONCURRENCY = 4
MAX_REREADS = 20  # per lecture; beyond this, failing blocks (highest confidence first) are marked uncertain unread

FORMULA_REREAD_INSTRUCTIONS = """\
You are re-reading one piece of writing from a lecture blackboard or whiteboard. The image is a crop of a video frame
around it. An earlier reading produced LaTeX that does not render; that reading and the renderer's error are given
as data below. They may be wrong: read the image yourself.

Return one block for the main piece of writing in the centre of the crop:
- type: "math" for anything mathematical, "text" for words, "diagram" for drawings.
- text: a plain-text reading of exactly what is written.
- latex: valid KaTeX-compatible LaTeX of exactly what is written, without surrounding $ signs (null if not maths).
  Use only standard commands and environments (frac, sqrt, cases, pmatrix, bmatrix, aligned, ...), and make sure every
  brace and environment is closed.
- bbox: [x0, y0, x1, y1] of the writing within this crop, normalised 0-1.
- confidence (0-1, calibrated): lower it if any symbol is unclear, cut off or hidden.

Transcribe what is written, not what you think should be written. Do not correct, complete or add to it."""


def nearest_keyframe(keyframes: list[Keyframe], time_s: float) -> Keyframe | None:
    return min(keyframes, key=lambda k: abs(k.time_s - time_s), default=None)


def crop_box(bbox: list[float], width: int, height: int, margin: float = CROP_MARGIN) -> tuple[int, int, int, int]:
    """Pixel box for a normalised bbox plus `margin` on each side, clamped to the frame and at least 1 px."""
    x0, y0, x1, y1 = bbox
    left = max(0, int((min(x0, x1) - margin) * width))
    top = max(0, int((min(y0, y1) - margin) * height))
    right = min(width, max(left + 1, round((max(x0, x1) + margin) * width)))
    bottom = min(height, max(top + 1, round((max(y0, y1) + margin) * height)))
    return left, top, right, bottom


def crop_block(frame: bytes, bbox: list[float]) -> Image:
    """The block's region of a keyframe image (with margin), ready to send to the model."""
    with PILImage.open(io.BytesIO(frame)) as img:
        if img.size[0] * img.size[1] > MAX_IMAGE_PIXELS:
            raise ValueError(f"frame is too large ({img.size[0]}x{img.size[1]})")
        region = img.convert("RGB").crop(crop_box(bbox, *img.size))
        out = io.BytesIO()
        region.save(out, format="JPEG", quality=92)
    return load_image(out.getvalue())


def reread_request(block: BoardBlock, image: Image, error: str) -> LLMRequest:
    return LLMRequest(
        task="formula_reread",
        tier="notes",
        instructions=FORMULA_REREAD_INSTRUCTIONS,
        untrusted={"previous_text": block.text, "previous_latex": block.latex or "", "render_error": error},
        images=[image],
        effort="medium",
        max_tokens=2000,
    )


async def _reread(block: BoardBlock, error: str, keyframes: list[Keyframe], llm: LLM, sem: asyncio.Semaphore) -> BoardReadBlock | None:
    frame = nearest_keyframe(keyframes, block.best_frame_s)
    if frame is None:
        return None
    async with sem:
        try:
            data = await asyncio.to_thread(frame.path.read_bytes)
            image = await asyncio.to_thread(crop_block, data, block.bbox)
            return await llm.structured(reread_request(block, image, error), BoardReadBlock)
        except Exception as exc:
            log.warning("recheck_formulas: re-reading %s failed: %s", block.id, exc)
            return None


def _uncertain(block: BoardBlock) -> BoardBlock:
    return block.model_copy(update={"latex": None, "confidence": min(block.confidence, UNCERTAIN_CAP)})


async def recheck_formulas(blocks: list[BoardBlock], keyframes: list[Keyframe], llm: LLM) -> list[BoardBlock]:
    """Pipeline stage (FormulaRechecker). Returns the blocks in the same order, with failing formulas fixed or
    marked uncertain. See the module docstring."""
    with_latex = [i for i, b in enumerate(blocks) if b.latex]
    results = await asyncio.to_thread(check_latex, [blocks[i].latex or "" for i in with_latex])
    failing = {i: r.message for i, r in zip(with_latex, results, strict=True) if isinstance(r, LatexError)}
    if not failing:
        return blocks

    sem = asyncio.Semaphore(REREAD_CONCURRENCY)
    order = list(failing)
    to_reread = sorted(order, key=lambda i: blocks[i].confidence)[:MAX_REREADS]
    rereads = await asyncio.gather(*(_reread(blocks[i], failing[i], keyframes, llm, sem) for i in to_reread))
    candidates = {i: r for i, r in zip(to_reread, rereads, strict=True) if r is not None and r.latex}
    cand_order = list(candidates)
    checks = await asyncio.to_thread(check_latex, [candidates[i].latex or "" for i in cand_order])

    out = list(blocks)
    for i in order:
        out[i] = _uncertain(blocks[i])
    for i, result in zip(cand_order, checks, strict=True):
        new = candidates[i]
        if result is True:
            out[i] = blocks[i].model_copy(update={"type": new.type, "text": new.text, "latex": new.latex, "confidence": new.confidence})
        elif result == "unknown":
            out[i] = blocks[i]  # KaTeX stopped working between the checks: leave the block as it was
    log.info("recheck_formulas: %d failing formulas, %d fixed by re-reading", len(order), sum(r is True for r in checks))
    return out
