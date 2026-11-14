import { PlayIcon } from "@/components/Icon";
import { formatTime } from "@/lib/format";
import { cx } from "@/lib/cx";

/**
 * Links a note back to its source. "timestamp" opens the video at that second; "reference" points at a board or section.
 * `seconds` are seconds (float); they become mm:ss here.
 */
export function SourceChip({
  type = "timestamp",
  seconds,
  label,
  onClick,
  active,
}: {
  type?: "timestamp" | "reference";
  seconds?: number;
  label?: string;
  onClick?: () => void;
  active?: boolean;
}) {
  const text = label ?? (seconds !== undefined ? formatTime(seconds) : "");
  const tone = type === "timestamp" ? "bg-accent-subtle text-accent" : "bg-muted text-secondary";
  const cls = cx(
    "inline-flex items-center gap-1 rounded-sm px-2 py-1 text-[12px] font-semibold leading-4",
    tone,
    active && "ring-2 ring-accent-border",
    onClick && "cursor-pointer hover:brightness-95",
  );
  const body = (
    <>
      {type === "timestamp" && <PlayIcon size={8} />}
      {text}
    </>
  );
  return onClick ? (
    <button type="button" className={cls} onClick={onClick}>
      {body}
    </button>
  ) : (
    <span className={cls}>{body}</span>
  );
}
