import type { ReactNode } from "react";
import { SourceChip } from "@/components/SourceChip";
import { formatClock } from "@/lib/format";
import { cx } from "@/lib/cx";

/** A finished (or still-being-written) section card on the processing page. */
export function SectionCard({
  title,
  summary,
  range,
  pending,
}: {
  title: string;
  summary?: ReactNode;
  range?: { start: number; end: number };
  pending?: boolean;
}) {
  return (
    <div className={cx("flex flex-col gap-1.5 rounded-lg border bg-surface p-4", pending ? "border-dashed border-strong opacity-60" : "border-default shadow-card")}>
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-display text-[15px] font-medium leading-6 text-primary">{title}</h3>
        {range && <SourceChip seconds={range.start} label={`${formatClock(range.start)} – ${formatClock(range.end)}`} />}
      </div>
      {pending ? <div className="h-2 w-3/4 rounded-full bg-muted" /> : <p className="text-[13px] leading-5 text-secondary">{summary}</p>}
    </div>
  );
}
