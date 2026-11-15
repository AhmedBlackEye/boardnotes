"use client";
import { useCallback, useState } from "react";
import { BoardSnapshot } from "@/components/BoardSnapshot";
import type { DiagramFigure as Figure } from "@/contracts/DiagramFigure";
import { cx } from "@/lib/cx";
import { ChartSvg, isDrawable } from "./ChartSvg";
import { MermaidDiagram } from "./MermaidDiagram";

/**
 * A diagram from the board: the AI redraw (chart or flowchart) with a "Redrawn by AI" label and a "View original"
 * toggle, or just the board crop. Anything that can't be drawn falls back to the crop.
 */
export function DiagramFigure({
  figure,
  snapshotUrl,
  boardText,
  className,
}: {
  figure: Figure;
  snapshotUrl?: string | null;
  boardText: string;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const [showOriginal, setShowOriginal] = useState(false);
  const onError = useCallback(() => setFailed(true), []);

  const chart = figure.kind === "chart" && isDrawable(figure.chart) ? figure.chart : null;
  const mermaid = figure.kind === "mermaid" && figure.mermaid ? figure.mermaid : null;
  const redrawn = !failed && (chart !== null || mermaid !== null);
  const original = <BoardSnapshot caption="On the board" text={boardText} imageUrl={snapshotUrl} size="small" />;

  return (
    <figure className={cx("flex flex-col gap-2 rounded-md border border-default bg-surface p-3", className)} data-testid="diagram-figure" data-kind={redrawn ? figure.kind : "crop"}>
      {redrawn ? (
        <>
          {chart && <ChartSvg spec={chart} className="mx-auto max-w-[480px]" />}
          {mermaid && <MermaidDiagram source={mermaid} onError={onError} />}
          {showOriginal && original}
        </>
      ) : (
        original
      )}
      <figcaption className="flex flex-wrap items-center justify-between gap-2 text-[12px] leading-4 text-secondary">
        <span>{figure.caption}</span>
        {redrawn && (
          <span className="flex items-center gap-2">
            <span className="rounded-sm bg-accent-subtle px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-[0.08em] text-accent">Redrawn by AI</span>
            <button type="button" className="font-semibold text-accent hover:text-accent-hover" aria-pressed={showOriginal} onClick={() => setShowOriginal((v) => !v)}>
              {showOriginal ? "Hide original" : "View original"}
            </button>
          </span>
        )}
      </figcaption>
    </figure>
  );
}
