import Link from "next/link";
import { Icon, type IconName } from "@/components/Icon";
import { cx } from "@/lib/cx";

/** Sidebar navigation row. `count` flags items needing attention (the review queue). */
export function NavItem({ href, icon, label, active, count }: { href: string; icon: IconName; label: string; active?: boolean; count?: number }) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cx(
        "flex h-[38px] items-center gap-3 rounded-md px-3 text-[13px] font-semibold leading-[18px]",
        active ? "bg-sidebar-active text-side-strong" : "text-side-text hover:bg-sidebar-raised",
      )}
    >
      <Icon name={icon} />
      <span className="flex-1">{label}</span>
      {count ? <span className="rounded-full bg-warning px-2 text-[11px] font-bold leading-4 text-on-accent">{count}</span> : null}
    </Link>
  );
}
