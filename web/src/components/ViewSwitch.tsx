import { Icon } from "@/components/Icon";
import { cx } from "@/lib/cx";

/** Lecturer view / View as student toggle. */
export function ViewSwitch({ asStudent, onChange }: { asStudent: boolean; onChange: (asStudent: boolean) => void }) {
  const seg = (on: boolean) =>
    cx("inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-semibold", on ? "bg-surface text-primary shadow-card" : "text-secondary hover:text-primary");
  return (
    <div role="group" aria-label="View mode" className="inline-flex gap-0.5 rounded-lg bg-muted p-1">
      <button type="button" className={seg(!asStudent)} aria-pressed={!asStudent} onClick={() => onChange(false)}>
        Lecturer view
      </button>
      <button type="button" className={seg(asStudent)} aria-pressed={asStudent} onClick={() => onChange(true)}>
        <Icon name="eye" size={14} />
        View as student
      </button>
    </div>
  );
}
