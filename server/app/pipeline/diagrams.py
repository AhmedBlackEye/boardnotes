"""Stage Q-4: redraw diagram blocks as a safe chart or Mermaid flowchart, or fall back to the board crop.

For each block of type diagram, the block is cropped from its best keyframe and sent with its text to the model
(task "diagram_redraw", tier "board"). A redraw is accepted only when the model is confident AND it passes the checks
below; otherwise the figure is the crop of the original. Model output is data: charts are drawn by our own renderers
and Mermaid source is checked here and rendered with securityLevel 'strict'. Nothing the model returns is executed.
"""

import asyncio
import io
import logging
import math
import re

from PIL import Image as PILImage

from app.contracts.ai import BoardBlock, ChartElement, ChartSpec, DiagramFigure, DiagramRedraw
from app.contracts.enums import BlockType
from app.llm.client import LLM, Image, LLMRequest
from app.media import crop_box

from .board import MAX_EDGE_PX, MAX_IMAGE_PIXELS
from .interfaces import Keyframe

log = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.8
REDRAW_CONCURRENCY = 4
CROP_MARGIN = 0.05  # extra frame around the block so arrows and labels at its edge are kept
MAX_CAPTION_CHARS = 300

# Chart limits
MAX_ELEMENTS = 50
MAX_POLYLINE_POINTS = 400
MAX_TOTAL_POINTS = 2000
MAX_ABS_COORD = 1e6
MIN_SPAN = 1e-6
MAX_LABEL_CHARS = 40
MAX_TITLE_CHARS = 80
POINT_COUNTS: dict[str, tuple[int, int]] = {
    "line": (2, 2),
    "segment": (2, 2),
    "vector": (2, 2),
    "polyline": (2, MAX_POLYLINE_POINTS),
    "point": (1, 1),
    "label": (1, 1),
    "bar": (1, 1),
}

# Mermaid limits
MAX_MERMAID_CHARS = 3000
MAX_MERMAID_LINES = 80
_MERMAID_HEADER = re.compile(r"^(flowchart|graph)(\s+(TB|TD|BT|RL|LR))?\s*;?$")
_MERMAID_FORBIDDEN = re.compile(r"%%\{|\b(click|href|script|init|javascript|callback|call)\b|<\s*[a-z/!?]|:::|@\{|`", re.IGNORECASE)
_MERMAID_STATEMENT_FORBIDDEN = re.compile(r"^(style|classDef|class|linkStyle|click)\b", re.IGNORECASE)
_MERMAID_EDGE = re.compile(r"--|==|-\.|~~~")
_MERMAID_LINE = re.compile(r"^(subgraph\b.*|end|direction\s+(TB|TD|BT|RL|LR)|[A-Za-z0-9_]+\b.*)$")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_PAIRS = {"(": ")", "[": "]", "{": "}"}

DIAGRAM_INSTRUCTIONS = """\
You are redrawing one diagram from a lecture blackboard or whiteboard so it can be shown cleanly in study notes.
The image is a crop of the board around the diagram. A plain-text reading of the board, which may be wrong, is given
as data below.

Choose one kind:
- "chart" for plots, axes, graphs of functions, vectors, geometry, number lines, bar charts and timelines.
  Describe it with a ChartSpec in data coordinates:
  - x_range and y_range: [min, max] covering everything drawn, with min < max.
  - elements (at most 50): line (2 points it passes through, drawn across the whole chart), segment and vector
    (start and end), polyline (points sampled along a curve, at most 400), point and label (1 point), bar ([[x, height]]).
  - label: short text shown next to the element (an equation, a point name, a value), or null.
  - show_axes: true when the board draws axes.
  - Only finite numbers. Read coordinates from what is drawn and written (intercepts, marked points, tick labels).
- "mermaid" for boxes and arrows: flowcharts, cycles, trees, state or process diagrams. Write Mermaid flowchart syntax
  only: the first line is "flowchart TD" (or LR/BT/RL), then nodes and edges such as A["Label"] --> B["Label"].
  Put every label in double quotes. Do not use click, style, classDef, class, linkStyle, init directives, HTML or links.
- "none" when neither can represent the diagram faithfully (pictures, sketches, anything you cannot read).

caption: one sentence saying what the diagram shows.
confidence (0-1, be calibrated): how faithfully the redraw matches the board. Use 0.9+ only when every element,
label and number is clearly readable and represented. Do not invent anything that is not on the board; if a part is
unreadable, lower the confidence or choose "none".
Set the field for the kind you did not choose to null."""


# ---------- validation (pure) ----------
def _finite(v: float) -> bool:
    return math.isfinite(v) and abs(v) <= MAX_ABS_COORD


def _text_ok(text: str | None, limit: int) -> bool:
    return text is None or (len(text) <= limit and not _CONTROL.search(text))


def chart_problems(chart: ChartSpec) -> list[str]:
    """Reasons the chart can't be drawn as given; empty if it is safe and sane."""
    problems: list[str] = []
    for name, (lo, hi) in (("x_range", chart.x_range), ("y_range", chart.y_range)):
        if not (_finite(lo) and _finite(hi)):
            problems.append(f"{name} is not finite")
        elif hi - lo < MIN_SPAN:
            problems.append(f"{name} is empty or reversed")
    for name, text in (("title", chart.title), ("x_label", chart.x_label), ("y_label", chart.y_label)):
        if not _text_ok(text, MAX_TITLE_CHARS):
            problems.append(f"{name} is too long or has control characters")
    if not chart.elements:
        problems.append("no elements")
    if len(chart.elements) > MAX_ELEMENTS:
        problems.append(f"{len(chart.elements)} elements (max {MAX_ELEMENTS})")
    total = 0
    for i, el in enumerate(chart.elements):
        problems.extend(f"element {i} ({el.type}): {p}" for p in element_problems(el))
        total += len(el.points)
    if total > MAX_TOTAL_POINTS:
        problems.append(f"{total} points in total (max {MAX_TOTAL_POINTS})")
    return problems


def element_problems(el: ChartElement) -> list[str]:
    problems: list[str] = []
    lo, hi = POINT_COUNTS[el.type]
    if not lo <= len(el.points) <= hi:
        problems.append(f"has {len(el.points)} points, needs {lo}" + ("" if lo == hi else f"-{hi}"))
    if any(len(p) != 2 for p in el.points):
        problems.append("a point is not [x, y]")
    elif not all(_finite(v) for p in el.points for v in p):
        problems.append("a coordinate is not finite")
    elif el.type == "line" and len(el.points) == 2 and el.points[0] == el.points[1]:
        problems.append("both points are the same")
    if not _text_ok(el.label, MAX_LABEL_CHARS):
        problems.append("label is too long or has control characters")
    if el.type == "label" and not (el.label and el.label.strip()):
        problems.append("label element without text")
    return problems


def _strip_quoted(line: str) -> str | None:
    """The line with double-quoted strings removed, or None if a quote is left open."""
    if line.count('"') % 2:
        return None
    return re.sub(r'"[^"]*"', '""', line)


def _balanced(line: str) -> bool:
    stack: list[str] = []
    for ch in line:
        if ch in _PAIRS:
            stack.append(_PAIRS[ch])
        elif ch in _PAIRS.values():
            if not stack or stack.pop() != ch:
                return False
    return not stack


def mermaid_problems(source: str) -> list[str]:
    """Reasons the Mermaid source is unsafe or unlikely to render; empty if it is a plain flowchart."""
    if len(source) > MAX_MERMAID_CHARS:
        return [f"{len(source)} characters (max {MAX_MERMAID_CHARS})"]
    if _CONTROL.search(source.replace("\t", " ")):
        return ["control characters"]
    match = _MERMAID_FORBIDDEN.search(source)
    if match:
        return [f"forbidden syntax {match.group(0)!r}"]
    lines = [ln.strip() for ln in source.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("%%")]
    if not lines:
        return ["empty"]
    if len(lines) > MAX_MERMAID_LINES:
        return [f"{len(lines)} lines (max {MAX_MERMAID_LINES})"]
    if not _MERMAID_HEADER.match(lines[0]):
        return ["not a flowchart/graph diagram"]
    problems: list[str] = []
    depth = 0
    for n, line in enumerate(lines[1:], start=2):
        bare = _strip_quoted(line)
        if bare is None:
            problems.append(f"line {n}: unclosed quote")
            continue
        if _MERMAID_STATEMENT_FORBIDDEN.match(bare):
            problems.append(f"line {n}: styling or interaction statement")
        elif not _MERMAID_LINE.match(bare):
            problems.append(f"line {n}: not a node, edge or subgraph")
        elif not _balanced(bare):
            problems.append(f"line {n}: unbalanced brackets")
        if bare.startswith("subgraph"):
            depth += 1
        elif bare == "end":
            depth -= 1
            if depth < 0:
                problems.append(f"line {n}: 'end' without subgraph")
    if depth > 0:
        problems.append("subgraph not closed")
    if not any(_MERMAID_EDGE.search(_strip_quoted(ln) or "") for ln in lines[1:]):
        problems.append("no edges")
    return problems


def _caption(text: str | None, fallback: str) -> str:
    caption = " ".join((text or "").split())
    if not caption or _CONTROL.search(caption):
        caption = " ".join(fallback.split())
    return caption[:MAX_CAPTION_CHARS]


def crop_figure(block: BoardBlock, caption: str | None = None) -> DiagramFigure:
    return DiagramFigure(kind="crop", chart=None, mermaid=None, caption=_caption(caption, block.text), redrawn_by_ai=False)


def figure_from_redraw(block: BoardBlock, redraw: DiagramRedraw) -> DiagramFigure:
    """The figure to show for a model redraw: the redraw if confident and valid, else the crop."""
    if redraw.confidence < MIN_CONFIDENCE or redraw.kind == "none":
        return crop_figure(block, redraw.caption)
    if redraw.kind == "chart":
        problems = ["missing chart"] if redraw.chart is None else chart_problems(redraw.chart)
        if not problems:
            return DiagramFigure(
                kind="chart", chart=redraw.chart, mermaid=None, caption=_caption(redraw.caption, block.text), redrawn_by_ai=True
            )
    else:
        source = (redraw.mermaid or "").strip()
        problems = ["missing mermaid"] if not source else mermaid_problems(source)
        if not problems:
            return DiagramFigure(
                kind="mermaid", chart=None, mermaid=source, caption=_caption(redraw.caption, block.text), redrawn_by_ai=True
            )
    log.info("diagram %s: %s redraw rejected: %s", block.id, redraw.kind, "; ".join(problems[:5]))
    return crop_figure(block, redraw.caption)


# ---------- image crop ----------
def crop_image(data: bytes, bbox: list[float], margin: float = CROP_MARGIN) -> Image:
    """JPEG crop of the block (with a margin), downscaled to the model's input limit. Blocking."""
    with PILImage.open(io.BytesIO(data)) as img:
        if img.size[0] * img.size[1] > MAX_IMAGE_PIXELS:
            raise ValueError(f"frame is too large ({img.size[0]}x{img.size[1]})")
        crop = img.convert("RGB").crop(crop_box(bbox, img.width, img.height, pad=margin))
    crop.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), PILImage.Resampling.LANCZOS)
    out = io.BytesIO()
    crop.save(out, format="JPEG", quality=90)
    return Image(data=out.getvalue(), media_type="image/jpeg")


def best_keyframe(keyframes: list[Keyframe], time_s: float) -> Keyframe | None:
    return min(keyframes, key=lambda k: abs(k.time_s - time_s), default=None)


def diagram_request(block: BoardBlock, image: Image) -> LLMRequest:
    return LLMRequest(
        task="diagram_redraw",
        tier="board",
        instructions=DIAGRAM_INSTRUCTIONS,
        untrusted={"board_reading": block.text},
        images=[image],
        effort="low",
    )


async def _redraw_one(block: BoardBlock, keyframes: list[Keyframe], llm: LLM, sem: asyncio.Semaphore) -> BoardBlock:
    async with sem:
        frame = best_keyframe(keyframes, block.best_frame_s)
        if frame is None:
            return block.model_copy(update={"figure": crop_figure(block)})
        try:
            data = await asyncio.to_thread(frame.path.read_bytes)
            image = await asyncio.to_thread(crop_image, data, block.bbox)
        except Exception:
            log.exception("diagram %s: cannot crop frame at %.1fs; using the crop fallback", block.id, frame.time_s)
            return block.model_copy(update={"figure": crop_figure(block)})
        try:
            redraw = await llm.structured(diagram_request(block, image), DiagramRedraw)
        except Exception as exc:
            log.warning("diagram %s: redraw failed (%s); using the crop", block.id, exc)
            return block.model_copy(update={"figure": crop_figure(block)})
        return block.model_copy(update={"figure": figure_from_redraw(block, redraw)})


async def redraw_diagrams(blocks: list[BoardBlock], keyframes: list[Keyframe], llm: LLM) -> list[BoardBlock]:
    """DiagramRedrawer: sets `figure` on every diagram block (redraw or crop). Other blocks are returned unchanged."""
    sem = asyncio.Semaphore(REDRAW_CONCURRENCY)

    async def one(block: BoardBlock) -> BoardBlock:
        if block.type != BlockType.DIAGRAM:
            return block
        return await _redraw_one(block, keyframes, llm, sem)

    return list(await asyncio.gather(*(one(b) for b in blocks)))
