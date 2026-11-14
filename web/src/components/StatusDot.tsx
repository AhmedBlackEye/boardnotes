import { cx } from "@/lib/cx";

export type DotStatus = "verified" | "uncertain" | "draft";

/** Compact section status for outlines and lists. Pair with a legend. */
export function StatusDot({ status, className }: { status: DotStatus; className?: string }) {
  const tone = status === "verified" ? "bg-success" : status === "uncertain" ? "bg-warning" : "bg-strong";
  return <span className={cx("inline-block size-2 shrink-0 rounded-full", tone, className)} aria-label={status} />;
}
