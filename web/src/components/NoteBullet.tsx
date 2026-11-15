import type { ReactNode } from "react";
import { Math } from "@/components/Math";
import { cx } from "@/lib/cx";

export type NoteBulletState = "default" | "selected" | "uncertain";
export type NoteKind = "point" | "definition" | "example" | "result" | "remark";

/** Box styles for the kinds the AI marks as worth highlighting (textbook-style callouts). */
const BOXES: Record<Exclude<NoteKind, "point">, { name: string; bar: string; body: string; border: string }> = {
  definition: { name: "Definition", bar: "bg-accent text-on-accent", body: "bg-accent-subtle", border: "border-accent" },
  example: { name: "Example", bar: "bg-warning text-on-accent", body: "bg-warning-subtle", border: "border-warning" },
  result: { name: "Key result", bar: "bg-success text-on-accent", body: "bg-success-subtle", border: "border-success" },
  remark: { name: "Remark", bar: "bg-sidebar text-side-strong", body: "bg-muted", border: "border-sidebar" },
};

export function boxName(kind: NoteKind): string | null {
  return kind === "point" ? null : BOXES[kind].name;
}

/** One point in the notes. Children are the source chips (and any status pill). Every bullet cites at least one source. */
export function NoteBullet({
  text,
  latex,
  state = "default",
  onSelect,
  figures,
  children,
  kind = "point",
  title,
  number,
}: {
  kind?: NoteKind;
  /** Box title (e.g. the term defined); boxes are used for every kind except "point". */
  title?: string | null;
  /** Box number shown in the title bar, e.g. "2.1". */
  number?: string;
  text: string;
  latex?: string | null;
  state?: NoteBulletState;
  onSelect?: () => void;
  /** Diagrams from the board that this point cites (shown under the text; clicks on them don't select the bullet). */
  figures?: ReactNode;
  children?: ReactNode;
}) {
  const box = {
    default: "border border-transparent",
    selected: "border border-accent-border bg-accent-subtle",
    uncertain: "border border-transparent bg-warning-subtle",
  }[state];
  const dot = state === "uncertain" ? "bg-warning" : "bg-accent";
  if (kind !== "point") {
    const style = BOXES[kind];
    const ring = state === "selected" ? "ring-2 ring-accent-border" : "";
    return (
      <div
        className={cx("overflow-hidden rounded-md border-[1.5px]", style.border, ring, onSelect && "cursor-pointer")}
        onClick={onSelect}
        data-state={state}
        data-kind={kind}
        data-testid="note-bullet"
      >
        <div className={cx("flex items-center justify-between gap-3 px-4 py-1.5 text-[13px] font-bold", style.bar)}>
          <span>{title}</span>
          <span className="shrink-0">
            {style.name}
            {number ? ` ${number}` : ""}
          </span>
        </div>
        <div className={cx("flex flex-col gap-2 px-4 py-3", style.body, state === "uncertain" && "border-l-4 border-warning")}>
          <p className="text-[14px] leading-[22px] text-primary">{text}</p>
          {latex && (
            <div className="flex justify-center overflow-x-auto py-1 text-[19px]">
              <Math latex={latex} display />
            </div>
          )}
          {figures && (
            <div className="flex flex-col gap-2" onClick={(e) => e.stopPropagation()}>
              {figures}
            </div>
          )}
          {children && (
            <div className="flex flex-wrap items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
              {children}
            </div>
          )}
        </div>
      </div>
    );
  }
  return (
    <div
      className={cx("flex items-start gap-3 rounded-lg p-3", box, onSelect && "cursor-pointer")}
      onClick={onSelect}
      data-state={state}
      data-testid="note-bullet"
    >
      <span className={cx("mt-2 size-1.5 shrink-0 rounded-full", dot)} />
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <p className="text-[14px] leading-[22px] text-primary">{text}</p>
        {latex && (
          <div
            className={cx(
              "flex justify-center overflow-x-auto rounded-md border bg-subtle px-4 py-3 text-[19px]",
              state === "uncertain" ? "border-dashed border-warning" : "border-default",
            )}
          >
            <Math latex={latex} display />
          </div>
        )}
        {figures && (
          <div className="flex flex-col gap-2" onClick={(e) => e.stopPropagation()}>
            {figures}
          </div>
        )}
        {children && (
          <div className="flex flex-wrap items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
            {children}
          </div>
        )}
      </div>
    </div>
  );
}
