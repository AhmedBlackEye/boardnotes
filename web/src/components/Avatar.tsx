import { cx } from "@/lib/cx";

/** Initials avatar. Lecturers are green so staff are recognisable in fix threads. */
export function Avatar({
  initials,
  tone = "student",
  size = 32,
  anonymous,
}: {
  initials: string;
  tone?: "student" | "lecturer";
  size?: 20 | 24 | 32;
  anonymous?: boolean;
}) {
  return (
    <span
      style={{ width: size, height: size }}
      className={cx(
        "inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-on-accent",
        size === 32 ? "text-[12px]" : "text-[9px]",
        anonymous ? "bg-tertiary" : tone === "lecturer" ? "bg-success" : "bg-accent",
      )}
    >
      {anonymous ? "?" : initials}
    </span>
  );
}
