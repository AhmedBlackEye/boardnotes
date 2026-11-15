"""ChartSpec -> SVG, for the PDF. Mirrors web/src/components/diagrams/chartGeometry.ts so both look the same.

The spec comes from a model, so it is treated as data: every piece of text is escaped, numbers are formatted by us,
and only a fixed set of SVG elements is produced. Colours come from CSS classes (design tokens) in the template.
"""

import math
from html import escape

from app.contracts.ai import ChartElement, ChartSpec

WIDTH = 480
HEIGHT = 320
PAD_LEFT = 44
PAD_RIGHT = 20
PAD_TOP = 16
PAD_BOTTOM = 36
TITLE_SPACE = 20
SERIES = 4  # colour classes series-0 .. series-3


def _num(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".") if math.isfinite(v) else "0"


def nice_step(span: float, target: int = 5) -> float:
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def ticks(lo: float, hi: float) -> list[float]:
    step = nice_step(hi - lo)
    start = math.ceil(lo / step - 1e-9)
    out: list[float] = []
    i = start
    while i * step <= hi + 1e-9 and len(out) < 20:
        out.append(round(i * step, 10))
        i += 1
    return out


def tick_label(v: float) -> str:
    return f"{v:.6g}" if v != 0 else "0"


class Frame:
    """Maps data coordinates to SVG pixels inside the plot area."""

    def __init__(self, spec: ChartSpec) -> None:
        self.x0, self.x1 = spec.x_range
        self.y0, self.y1 = spec.y_range
        self.left = PAD_LEFT
        self.right = WIDTH - PAD_RIGHT
        self.top = PAD_TOP + (TITLE_SPACE if spec.title else 0)
        self.bottom = HEIGHT - PAD_BOTTOM

    def sx(self, x: float) -> float:
        return self.left + (x - self.x0) / (self.x1 - self.x0) * (self.right - self.left)

    def sy(self, y: float) -> float:
        return self.bottom - (y - self.y0) / (self.y1 - self.y0) * (self.bottom - self.top)

    def px(self, p: list[float]) -> tuple[float, float]:
        return self.sx(p[0]), self.sy(p[1])


def clip_line(
    p: tuple[float, float], q: tuple[float, float], box: tuple[float, float, float, float]
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """The part of the infinite line through p and q inside box (left, top, right, bottom), or None (Liang-Barsky)."""
    (x, y), (qx, qy) = p, q
    dx, dy = qx - x, qy - y
    if dx == 0 and dy == 0:
        return None
    left, top, right, bottom = box
    t0, t1 = -math.inf, math.inf
    for d, lo, hi, v in ((dx, left, right, x), (dy, top, bottom, y)):
        if d == 0:
            if not lo <= v <= hi:
                return None
            continue
        a, b = (lo - v) / d, (hi - v) / d
        t0, t1 = max(t0, min(a, b)), min(t1, max(a, b))
    if t0 > t1:
        return None
    return (x + t0 * dx, y + t0 * dy), (x + t1 * dx, y + t1 * dy)


def _text(x: float, y: float, text: str, cls: str, anchor: str = "start") -> str:
    return f'<text x="{_num(x)}" y="{_num(y)}" class="{cls}" text-anchor="{anchor}">{escape(text)}</text>'


def _bar_width(spec: ChartSpec, f: Frame) -> float:
    xs = sorted({f.sx(e.points[0][0]) for e in spec.elements if e.type == "bar" and e.points})
    gaps = [b - a for a, b in zip(xs, xs[1:], strict=False) if b - a > 0]
    width = 0.6 * min(gaps) if gaps else 0.08 * (f.right - f.left)
    return max(2.0, min(width, 0.25 * (f.right - f.left)))


def _element(el: ChartElement, i: int, spec: ChartSpec, f: Frame, uid: str) -> list[str]:
    cls = f"series-{i % SERIES}"
    pts = [f.px(p) for p in el.points]
    out: list[str] = []
    anchor: tuple[float, float] | None = None
    if el.type == "line":
        clipped = clip_line(pts[0], pts[1], (f.left, f.top, f.right, f.bottom))
        if clipped is None:
            return []
        (ax, ay), (bx, by) = clipped
        out.append(f'<line x1="{_num(ax)}" y1="{_num(ay)}" x2="{_num(bx)}" y2="{_num(by)}" class="chart-stroke {cls}"/>')
        anchor = (bx, by) if bx >= ax else (ax, ay)
    elif el.type in ("segment", "vector"):
        (ax, ay), (bx, by) = pts
        marker = f' marker-end="url(#{uid}-arrow)"' if el.type == "vector" else ""
        out.append(f'<line x1="{_num(ax)}" y1="{_num(ay)}" x2="{_num(bx)}" y2="{_num(by)}" class="chart-stroke {cls}"{marker}/>')
        anchor = (bx, by)
    elif el.type == "polyline":
        coords = " ".join(f"{_num(x)},{_num(y)}" for x, y in pts)
        out.append(f'<polyline points="{coords}" class="chart-stroke chart-curve {cls}"/>')
        anchor = pts[-1]
    elif el.type == "point":
        x, y = pts[0]
        out.append(f'<circle cx="{_num(x)}" cy="{_num(y)}" r="3.5" class="chart-dot {cls}"/>')
        anchor = (x + 5, y - 6)
    elif el.type == "bar":
        x, top = pts[0]
        base = f.sy(min(max(0.0, f.y0), f.y1))
        w = _bar_width(spec, f)
        y, h = min(top, base), abs(base - top)
        out.append(f'<rect x="{_num(x - w / 2)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}" class="chart-bar {cls}"/>')
        anchor = (x, y - 4)
    elif el.type == "label":
        x, y = pts[0]
        return [_text(x, y, el.label or "", "chart-label", "middle")]
    if el.label and anchor is not None:
        ax, ay = anchor
        side = "end" if ax > f.right - 60 else "start"
        dx = -4 if side == "end" else 4
        out.append(_text(ax + dx, max(f.top + 10, min(f.bottom - 4, ay - 4)), el.label, f"chart-label {cls}", side))
    return out


def _axes(spec: ChartSpec, f: Frame) -> list[str]:
    out: list[str] = []
    for x in ticks(f.x0, f.x1):
        px = f.sx(x)
        out.append(f'<line x1="{_num(px)}" y1="{f.top}" x2="{_num(px)}" y2="{f.bottom}" class="chart-grid"/>')
        out.append(_text(px, f.bottom + 14, tick_label(x), "chart-tick", "middle"))
    for y in ticks(f.y0, f.y1):
        py = f.sy(y)
        out.append(f'<line x1="{f.left}" y1="{_num(py)}" x2="{f.right}" y2="{_num(py)}" class="chart-grid"/>')
        out.append(_text(f.left - 6, py + 3.5, tick_label(y), "chart-tick", "end"))
    if spec.show_axes:
        ay = f.sy(0) if f.y0 <= 0 <= f.y1 else f.bottom
        ax = f.sx(0) if f.x0 <= 0 <= f.x1 else f.left
        out.append(f'<line x1="{f.left}" y1="{_num(ay)}" x2="{f.right}" y2="{_num(ay)}" class="chart-axis"/>')
        out.append(f'<line x1="{_num(ax)}" y1="{f.top}" x2="{_num(ax)}" y2="{f.bottom}" class="chart-axis"/>')
    if spec.x_label:
        out.append(_text(f.right, f.bottom + 30, spec.x_label, "chart-axis-label", "end"))
    if spec.y_label:
        out.append(_text(4, f.top - 4, spec.y_label, "chart-axis-label"))
    return out


def chart_svg(spec: ChartSpec, uid: str = "chart") -> str:
    """A self-contained <svg> for the chart. All text is escaped; only numbers we format reach attributes.

    `uid` (letters, digits, '-') keeps the marker and clip-path ids unique when a page has several charts."""
    uid = "".join(c for c in uid if c.isalnum() or c == "-") or "chart"
    f = Frame(spec)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" class="chart" role="img"'
        f' aria-label="{escape(spec.title or "Chart", quote=True)}">',
        f'<defs><marker id="{uid}-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"'
        ' orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="chart-arrowhead"/></marker>'
        f'<clipPath id="{uid}-plot"><rect x="{f.left}" y="{f.top}" width="{f.right - f.left}"'
        f' height="{f.bottom - f.top}"/></clipPath></defs>',
    ]
    if spec.title:
        parts.append(_text(WIDTH / 2, PAD_TOP + 4, spec.title, "chart-title", "middle"))
    parts.extend(_axes(spec, f))
    parts.append(f'<g clip-path="url(#{uid}-plot)">')
    shapes: list[str] = []
    labels: list[str] = []
    for i, el in enumerate(spec.elements):
        for piece in _element(el, i, spec, f, uid):
            (labels if piece.startswith("<text") else shapes).append(piece)
    parts.extend(shapes)
    parts.append("</g>")
    parts.extend(labels)
    parts.append("</svg>")
    return "".join(parts)
