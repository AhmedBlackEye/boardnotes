import { Icon } from "@/components/Icon";
import { cx } from "@/lib/cx";

/** Upvote count. Interactive for students (onToggle); read-only for lecturers. */
export function Upvote({ count, voted, onToggle, disabled }: { count: number; voted?: boolean; onToggle?: () => void; disabled?: boolean }) {
  const cls = cx(
    "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[12px] font-semibold",
    voted ? "border-accent bg-accent-subtle text-accent" : "border-default bg-surface text-primary",
    onToggle && !disabled && "cursor-pointer hover:bg-subtle",
  );
  const body = (
    <>
      <Icon name="up" size={10} />
      {count}
    </>
  );
  return onToggle ? (
    <button type="button" className={cls} onClick={onToggle} disabled={disabled} aria-pressed={voted} aria-label={`Upvote, ${count} so far`}>
      {body}
    </button>
  ) : (
    <span className={cls} aria-label={`${count} upvotes`}>
      {body}
    </span>
  );
}
