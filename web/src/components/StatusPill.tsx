import type { ReactNode } from "react";
import { cx } from "@/lib/cx";

export type PillStatus = "verified" | "in_review" | "uncertain" | "processing" | "draft" | "flagged" | "failed" | "info";

const TONE: Record<PillStatus, { box: string; dot: string }> = {
  verified: { box: "bg-success-subtle text-success", dot: "bg-success" },
  in_review: { box: "bg-warning-subtle text-warning", dot: "bg-warning" },
  uncertain: { box: "bg-warning-subtle text-warning", dot: "bg-warning" },
  processing: { box: "bg-accent-subtle text-accent", dot: "bg-accent" },
  draft: { box: "bg-muted text-secondary", dot: "bg-strong" },
  flagged: { box: "bg-danger-subtle text-danger", dot: "bg-danger" },
  failed: { box: "bg-danger-subtle text-danger", dot: "bg-danger" },
  info: { box: "bg-muted text-secondary", dot: "bg-tertiary" },
};

const DEFAULT_LABEL: Record<PillStatus, string> = {
  verified: "Verified",
  in_review: "In review",
  uncertain: "Uncertain",
  processing: "Processing",
  draft: "Draft",
  flagged: "Flagged",
  failed: "Failed",
  info: "",
};

/** State of a lecture, section, note or fix. Colour always comes with a word. */
export function StatusPill({
  status,
  children,
  showDot = true,
  className,
}: {
  status: PillStatus;
  children?: ReactNode;
  showDot?: boolean;
  className?: string;
}) {
  const t = TONE[status];
  return (
    <span className={cx("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1 text-[12px] font-semibold leading-4", t.box, className)}>
      {showDot && <span className={cx("size-1.5 rounded-full", t.dot)} />}
      {children ?? DEFAULT_LABEL[status]}
    </span>
  );
}
