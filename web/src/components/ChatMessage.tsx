import type { ReactNode } from "react";
import { cx } from "@/lib/cx";

/** A message in "Ask the lecture". `kind` is who speaks: the student, the answer with sources, or a not-covered notice. */
export function ChatMessage({ kind, children, sources }: { kind: "user" | "answer" | "notice"; children: ReactNode; sources?: ReactNode }) {
  if (kind === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-xl bg-accent px-4 py-2.5 text-[14px] font-semibold leading-[22px] text-on-accent">{children}</p>
      </div>
    );
  }
  return (
    <div className="flex items-start gap-2.5">
      <span className="mt-1 flex size-6 shrink-0 items-center justify-center rounded-md bg-sidebar font-chalk text-[13px] font-bold text-side-strong">B</span>
      <div
        className={cx(
          "flex max-w-[85%] flex-col gap-2 rounded-xl px-4 py-2.5 text-[14px] leading-[22px]",
          kind === "answer" ? "border border-default bg-surface text-primary" : "bg-muted text-secondary",
        )}
      >
        <p>{children}</p>
        {sources && <div className="flex flex-wrap gap-1.5">{sources}</div>}
      </div>
    </div>
  );
}
