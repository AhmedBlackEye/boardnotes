"""Board stages: read each keyframe accurately (B-1) and merge the same writing across frames (B-2)."""

import asyncio
import io
import logging

from PIL import Image as PILImage

from app.contracts.ai import BoardRead
from app.llm.client import LLM, Image, LLMRequest

from .interfaces import FrameReading, Keyframe

log = logging.getLogger(__name__)

MAX_EDGE_PX = 1568  # long-edge limit for vision input; larger images are downscaled
READ_CONCURRENCY = 6
READ_ATTEMPTS = 2  # first try + one retry

BOARD_READ_INSTRUCTIONS = """\
You are transcribing the writing on a lecture blackboard or whiteboard from one video frame.

Read every distinct piece of writing on the board and return it as blocks, in reading order
(top to bottom, then left to right; for boards split into panels, finish one panel before the next).

Blocks
- One block per visually separate unit: an equation or derivation step, a line or short paragraph of text,
  a heading, or a diagram. Do not merge writing from different panels into one block.
- type "math" for anything mathematical (equations, expressions, matrices, inequalities, set notation);
  "text" for words; "diagram" for drawings, graphs and sketches.
- text: a plain-text reading of the block exactly as written (for a diagram, a short description of what it shows
  and any labels on it).
- latex: for math blocks, valid KaTeX-compatible LaTeX of exactly what is written, without surrounding $ signs.
  Use environments such as cases, pmatrix, bmatrix and aligned where the board uses them. null for text and diagrams.
- bbox: [x0, y0, x1, y1] of the block within this frame, normalised 0-1 with (0, 0) at the top-left.

Handwriting (chalk and marker)
- Transcribe what is written, not what you think should be written. Do not correct the lecturer's maths,
  complete derivations, or add steps that are not on the board.
- Watch for common confusions: 1/l/I, 0/O, 2/z/Z, 5/s/S, x/× (times), u/v, n/h, a/α, B/β, t/+, minus signs vs dashes,
  primes vs commas, subscripts vs exponents. Decide using the surrounding maths.
- Skip faint ghosts of erased writing, smudges and reflections.
- If writing is cut off by the frame edge or hidden by the lecturer, transcribe only the visible part
  and lower its confidence; do not guess the hidden part.

Confidence (0-1, be calibrated)
- 0.95+: every symbol clearly legible.
- 0.8-0.95: legible, but one or two symbols needed context to decide.
- 0.5-0.8: partly hidden, cut off, blurry or ambiguous; the reading may be wrong in places.
- below 0.5: mostly a guess.

frame_quality: "good" if the board is clearly visible; "partly_hidden" if the lecturer, glare or the frame edge hides
part of the writing; "poor" if blur, lighting or distance makes most of it hard to read.
If the frame shows no board writing, return no blocks and frame_quality "poor".

A cheaper first pass listed lines it thought were visible; they are given as data below and may be wrong or incomplete.
Use them only as a hint, and read the image yourself."""


def load_image(data: bytes) -> Image:
    """Return the image for the model, downscaled so the long edge is at most MAX_EDGE_PX."""
    with PILImage.open(io.BytesIO(data)) as img:
        fmt = img.format
        if max(img.size) <= MAX_EDGE_PX and fmt in ("JPEG", "PNG"):
            return Image(data=data, media_type="image/jpeg" if fmt == "JPEG" else "image/png")
        rgb = img.convert("RGB")
        rgb.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), PILImage.Resampling.LANCZOS)
        out = io.BytesIO()
        rgb.save(out, format="JPEG", quality=92)
        return Image(data=out.getvalue(), media_type="image/jpeg")


def board_read_request(keyframe: Keyframe, image: Image) -> LLMRequest:
    return LLMRequest(
        task="board_read",
        tier="board",
        instructions=BOARD_READ_INSTRUCTIONS,
        untrusted={"first_pass_lines": "\n".join(keyframe.lines)},
        images=[image],
        effort="low",
    )


async def _read_one(keyframe: Keyframe, llm: LLM, sem: asyncio.Semaphore) -> FrameReading | None:
    async with sem:
        try:
            data = await asyncio.to_thread(keyframe.path.read_bytes)
            image = await asyncio.to_thread(load_image, data)
        except Exception:
            log.exception("board_read: cannot load frame at %.1fs (%s); skipping", keyframe.time_s, keyframe.path)
            return None
        req = board_read_request(keyframe, image)
        for attempt in range(1, READ_ATTEMPTS + 1):
            try:
                read = await llm.structured(req, BoardRead)
                return FrameReading(keyframe=keyframe, read=read)
            except Exception as exc:
                log.warning("board_read: frame at %.1fs failed (attempt %d/%d): %s", keyframe.time_s, attempt, READ_ATTEMPTS, exc)
        log.error("board_read: skipping frame at %.1fs after %d attempts", keyframe.time_s, READ_ATTEMPTS)
        return None


async def read_board(keyframes: list[Keyframe], llm: LLM) -> list[FrameReading]:
    """Read every keyframe at full resolution. Frames that fail twice are skipped. Output is in time order."""
    sem = asyncio.Semaphore(READ_CONCURRENCY)
    results = await asyncio.gather(*(_read_one(kf, llm, sem) for kf in keyframes))
    return sorted((r for r in results if r is not None), key=lambda r: r.keyframe.time_s)
