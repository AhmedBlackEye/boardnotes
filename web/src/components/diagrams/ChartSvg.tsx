import { useId } from "react";
import type { ChartSpec } from "@/contracts/ChartSpec";
import { cx } from "@/lib/cx";
import { HEIGHT, WIDTH, layoutChart, type Label } from "./chartGeometry";

const STROKE = ["stroke-accent", "stroke-success", "stroke-warning", "stroke-danger"];
const FILL = ["fill-accent", "fill-success", "fill-warning", "fill-danger"];

/** True when the spec can be laid out (finite, non-empty ranges). The server validates fully; this guards the renderer. */
export function isDrawable(spec: ChartSpec | null | undefined): spec is ChartSpec {
  if (!spec || !Array.isArray(spec.elements)) return false;
  const [x0, x1] = spec.x_range ?? [];
  const [y0, y1] = spec.y_range ?? [];
  return [x0, x1, y0, y1].every((v) => typeof v === "number" && Number.isFinite(v)) && x1! > x0! && y1! > y0!;
}

function Text({ label, className }: { label: Label; className: string }) {
  return (
    <text x={label.x} y={label.y} textAnchor={label.anchor} className={cx(className, label.series !== null && FILL[label.series])}>
      {label.text}
    </text>
  );
}

/** A chart drawn from a ChartSpec by our own code (no chart library, nothing executed). All text renders as text. */
export function ChartSvg({ spec, className }: { spec: ChartSpec; className?: string }) {
  const uid = useId().replace(/[^A-Za-z0-9_-]/g, "");
  const layout = layoutChart(spec);
  const { plot } = layout;
  const arrow = `${uid}-arrow`;
  const clip = `${uid}-plot`;
  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={spec.title ?? "Chart"} className={cx("h-auto w-full", className)} data-testid="chart-svg">
      <defs>
        <marker id={arrow} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" className="fill-primary" />
        </marker>
        <clipPath id={clip}>
          <rect x={plot.left} y={plot.top} width={plot.right - plot.left} height={plot.bottom - plot.top} />
        </clipPath>
      </defs>
      {layout.title && <Text label={layout.title} className="fill-primary text-[12px] font-semibold" />}
      {layout.grid.x.map((x, i) => (
        <line key={`gx${i}`} x1={x} y1={plot.top} x2={x} y2={plot.bottom} className="stroke-default" />
      ))}
      {layout.grid.y.map((y, i) => (
        <line key={`gy${i}`} x1={plot.left} y1={y} x2={plot.right} y2={y} className="stroke-default" />
      ))}
      {layout.ticks.map((t, i) => (
        <Text key={`t${i}`} label={t} className="fill-tertiary text-[10px]" />
      ))}
      {layout.axes && (
        <g className="stroke-secondary" strokeWidth={1.25}>
          <line x1={plot.left} y1={layout.axes.y} x2={plot.right} y2={layout.axes.y} />
          <line x1={layout.axes.x} y1={plot.top} x2={layout.axes.x} y2={plot.bottom} />
        </g>
      )}
      {layout.axisLabels.map((l, i) => (
        <Text key={`a${i}`} label={l} className="fill-primary text-[11px]" />
      ))}
      <g clipPath={`url(#${clip})`} fill="none" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        {layout.shapes.map((s, i) => {
          switch (s.kind) {
            case "line":
              return <line key={i} x1={s.x1} y1={s.y1} x2={s.x2} y2={s.y2} className={STROKE[s.series]} markerEnd={s.arrow ? `url(#${arrow})` : undefined} />;
            case "polyline":
              return <polyline key={i} points={s.points.map((p) => p.join(",")).join(" ")} className={STROKE[s.series]} />;
            case "dot":
              return <circle key={i} cx={s.cx} cy={s.cy} r={3.5} stroke="none" className={FILL[s.series]} />;
            case "bar":
              return <rect key={i} x={s.x} y={s.y} width={s.width} height={s.height} stroke="none" className={FILL[s.series]} />;
          }
        })}
      </g>
      {layout.labels.map((l, i) => (
        <Text key={`l${i}`} label={l} className={cx("text-[11px]", l.series === null && "fill-primary")} />
      ))}
    </svg>
  );
}
