import type { ReactNode } from "react";
import { Math } from "@/components/Math";
import { cx } from "@/lib/cx";

export type NoteBulletState = "default" | "selected" | "uncertain";

/** One point in the notes. Children are the source chips (and any status pill). Every bullet cites at least one source. */
export function NoteBullet({
  text,
  latex,
  state = "default",
  onSelect,
  children,
}: {
  text: string;
  latex?: string | null;
  state?: NoteBulletState;
  onSelect?: () => void;
  children?: ReactNode;
}) {
  const box = {
    default: "border border-transparent",
    selected: "border border-accent-border bg-accent-subtle",
    uncertain: "border border-transparent bg-warning-subtle",
  }[state];
  const dot = state === "uncertain" ? "bg-warning" : "bg-accent";
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
        {children && (
          <div className="flex flex-wrap items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
            {children}
          </div>
        )}
      </div>
    </div>
  );
}
