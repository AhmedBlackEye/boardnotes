/**
 * ChartSpec -> plain shapes in SVG pixels. Mirrors server/app/pipeline/chart_svg.py (the PDF renderer) so the web
 * and the PDF draw the same chart. Pure: no DOM, no eval. Text is returned as strings and rendered by React (escaped).
 */
import type { ChartElement, ChartSpec } from "@/contracts/ChartSpec";

export const WIDTH = 480;
export const HEIGHT = 320;
const PAD_LEFT = 44;
const PAD_RIGHT = 20;
const PAD_TOP = 16;
const PAD_BOTTOM = 36;
const TITLE_SPACE = 20;
export const SERIES = 4;

type Pt = [number, number];
export type Anchor = "start" | "middle" | "end";

export type Shape =
  | { kind: "line"; x1: number; y1: number; x2: number; y2: number; series: number; arrow: boolean }
  | { kind: "polyline"; points: Pt[]; series: number }
  | { kind: "dot"; cx: number; cy: number; series: number }
  | { kind: "bar"; x: number; y: number; width: number; height: number; series: number };

export type Label = { x: number; y: number; text: string; anchor: Anchor; series: number | null };

export type Box = { left: number; top: number; right: number; bottom: number };

export type ChartLayout = {
  plot: Box;
  title: Label | null;
  grid: { x: number[]; y: number[] };
  ticks: Label[];
  axes: { x: number; y: number } | null; // pixel position of the y axis (x) and the x axis (y)
  axisLabels: Label[];
  shapes: Shape[];
  labels: Label[];
};

export function niceStep(span: number, target = 5): number {
  const raw = span / target;
  const mag = 10 ** Math.floor(Math.log10(raw));
  for (const m of [1, 2, 5, 10]) if (raw <= m * mag) return m * mag;
  return 10 * mag;
}

export function ticks(lo: number, hi: number): number[] {
  const step = niceStep(hi - lo);
  const out: number[] = [];
  for (let i = Math.ceil(lo / step - 1e-9); i * step <= hi + 1e-9 && out.length < 20; i++) out.push(Math.round(i * step * 1e10) / 1e10);
  return out;
}

export function tickLabel(v: number): string {
  return v === 0 ? "0" : String(Number(v.toPrecision(6)));
}

/** The part of the infinite line through p and q inside the box, or null (Liang-Barsky). */
export function clipLine(p: Pt, q: Pt, box: Box): [Pt, Pt] | null {
  const [x, y] = p;
  const dx = q[0] - x;
  const dy = q[1] - y;
  if (dx === 0 && dy === 0) return null;
  let t0 = -Infinity;
  let t1 = Infinity;
  for (const [d, lo, hi, v] of [
    [dx, box.left, box.right, x],
    [dy, box.top, box.bottom, y],
  ] as const) {
    if (d === 0) {
      if (v < lo || v > hi) return null;
      continue;
    }
    const a = (lo - v) / d;
    const b = (hi - v) / d;
    t0 = Math.max(t0, Math.min(a, b));
    t1 = Math.min(t1, Math.max(a, b));
  }
  if (t0 > t1) return null;
  return [
    [x + t0 * dx, y + t0 * dy],
    [x + t1 * dx, y + t1 * dy],
  ];
}

export function layoutChart(spec: ChartSpec): ChartLayout {
  const [x0, x1] = spec.x_range as [number, number];
  const [y0, y1] = spec.y_range as [number, number];
  const plot: Box = { left: PAD_LEFT, top: PAD_TOP + (spec.title ? TITLE_SPACE : 0), right: WIDTH - PAD_RIGHT, bottom: HEIGHT - PAD_BOTTOM };
  const sx = (x: number) => plot.left + ((x - x0) / (x1 - x0)) * (plot.right - plot.left);
  const sy = (y: number) => plot.bottom - ((y - y0) / (y1 - y0)) * (plot.bottom - plot.top);
  const px = (p: number[]): Pt => [sx(p[0] ?? 0), sy(p[1] ?? 0)];

  const xTicks = ticks(x0, x1);
  const yTicks = ticks(y0, y1);
  const tickLabels: Label[] = [
    ...xTicks.map((v) => ({ x: sx(v), y: plot.bottom + 14, text: tickLabel(v), anchor: "middle" as const, series: null })),
    ...yTicks.map((v) => ({ x: plot.left - 6, y: sy(v) + 3.5, text: tickLabel(v), anchor: "end" as const, series: null })),
  ];
  const axisLabels: Label[] = [];
  if (spec.x_label) axisLabels.push({ x: plot.right, y: plot.bottom + 30, text: spec.x_label, anchor: "end", series: null });
  if (spec.y_label) axisLabels.push({ x: 4, y: plot.top - 4, text: spec.y_label, anchor: "start", series: null });

  const barXs = [...new Set(spec.elements.filter((e) => e.type === "bar" && e.points[0]).map((e) => sx(e.points[0]![0] ?? 0)))].sort((a, b) => a - b);
  const gaps = barXs.slice(1).map((v, i) => v - barXs[i]!).filter((g) => g > 0);
  const barWidth = Math.max(2, Math.min(gaps.length ? 0.6 * Math.min(...gaps) : 0.08 * (plot.right - plot.left), 0.25 * (plot.right - plot.left)));

  const shapes: Shape[] = [];
  const labels: Label[] = [];
  spec.elements.forEach((el: ChartElement, i) => {
    const series = i % SERIES;
    const pts = el.points.map(px);
    let anchor: Pt | null = null;
    if (el.type === "line") {
      const clipped = pts.length === 2 ? clipLine(pts[0]!, pts[1]!, plot) : null;
      if (!clipped) return;
      const [[ax, ay], [bx, by]] = clipped;
      shapes.push({ kind: "line", x1: ax, y1: ay, x2: bx, y2: by, series, arrow: false });
      anchor = bx >= ax ? [bx, by] : [ax, ay];
    } else if ((el.type === "segment" || el.type === "vector") && pts.length === 2) {
      const [[ax, ay], [bx, by]] = pts as [Pt, Pt];
      shapes.push({ kind: "line", x1: ax, y1: ay, x2: bx, y2: by, series, arrow: el.type === "vector" });
      anchor = [bx, by];
    } else if (el.type === "polyline" && pts.length >= 2) {
      shapes.push({ kind: "polyline", points: pts, series });
      anchor = pts[pts.length - 1]!;
    } else if (el.type === "point" && pts[0]) {
      const [x, y] = pts[0];
      shapes.push({ kind: "dot", cx: x, cy: y, series });
      anchor = [x + 5, y - 6];
    } else if (el.type === "bar" && pts[0]) {
      const [x, top] = pts[0];
      const base = sy(Math.min(Math.max(0, y0), y1));
      shapes.push({ kind: "bar", x: x - barWidth / 2, y: Math.min(top, base), width: barWidth, height: Math.abs(base - top), series });
      anchor = [x, Math.min(top, base) - 4];
    } else if (el.type === "label" && pts[0]) {
      labels.push({ x: pts[0][0], y: pts[0][1], text: el.label ?? "", anchor: "middle", series: null });
      return;
    }
    if (el.label && anchor) {
      const [ax, ay] = anchor;
      const end = ax > plot.right - 60;
      labels.push({
        x: ax + (end ? -4 : 4),
        y: Math.max(plot.top + 10, Math.min(plot.bottom - 4, ay - 4)),
        text: el.label,
        anchor: end ? "end" : "start",
        series,
      });
    }
  });

  let axes: ChartLayout["axes"] = null;
  if (spec.show_axes) axes = { x: x0 <= 0 && 0 <= x1 ? sx(0) : plot.left, y: y0 <= 0 && 0 <= y1 ? sy(0) : plot.bottom };

  return {
    plot,
    title: spec.title ? { x: WIDTH / 2, y: PAD_TOP + 4, text: spec.title, anchor: "middle", series: null } : null,
    grid: { x: xTicks.map(sx), y: yTicks.map(sy) },
    ticks: tickLabels,
    axes,
    axisLabels,
    shapes,
    labels,
  };
}
