"use client";
import { usePathname, useRouter } from "next/navigation";
import { Avatar } from "@/components/Avatar";
import { NavItem } from "@/components/NavItem";
import type { Me } from "@/contracts/Me";
import { useAsync } from "@/lib/hooks";
import { api } from "@/lib/client";
import { useSession } from "@/lib/session";

/** App navigation. Students get Lectures and Course notes; lecturers also get Review queue (with count) and Upload lecture. */
export function Sidebar({ me, reviewCount }: { me: Me; reviewCount?: number }) {
  const pathname = usePathname();
  const router = useRouter();
  const { logout } = useSession();
  const is = (p: string) => pathname === p || pathname.startsWith(`${p}/`);
  return (
    <aside className="flex w-[240px] shrink-0 flex-col gap-7 bg-sidebar px-4 py-6">
      <div className="flex items-center gap-2.5 pl-2">
        <span className="flex size-[30px] items-center justify-center rounded-md bg-accent font-chalk text-[18px] font-bold text-on-accent">B</span>
        <span className="font-display text-[20px] font-bold leading-6 text-side-strong">BoardNotes</span>
      </div>
      <div className="flex flex-col gap-0.5 rounded-lg bg-sidebar-raised p-3">
        <p className="text-[11px] font-bold uppercase leading-4 tracking-[0.08em] text-side-muted">Module</p>
        <p className="text-[14px] font-semibold leading-[22px] text-side-strong">Linear Algebra</p>
        <p className="text-[12px] leading-4 text-side-muted">Autumn term · 24 lectures</p>
      </div>
      <nav className="flex flex-col gap-1" aria-label="Main">
        <NavItem href="/lectures" icon="lectures" label="Lectures" active={is("/lectures")} />
        <NavItem href="/course-notes" icon="notes" label="Course notes" active={is("/course-notes")} />
        {me.role === "lecturer" && (
          <>
            <NavItem href="/review" icon="review" label="Review queue" active={is("/review")} count={reviewCount} />
            <NavItem href="/upload" icon="upload" label="Upload lecture" active={is("/upload")} />
          </>
        )}
      </nav>
      <div className="flex-1" />
      <div className="flex items-center gap-2.5 pl-1">
        <Avatar initials={me.initials} tone={me.role} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-semibold leading-[18px] text-side-strong">{me.name}</p>
          <p className="text-[12px] capitalize leading-4 text-side-muted">{me.role}</p>
        </div>
        <button
          type="button"
          className="text-[12px] text-side-muted hover:text-side-strong"
          onClick={async () => {
            await logout();
            router.replace("/login");
          }}
        >
          Switch
        </button>
      </div>
    </aside>
  );
}

/** Sidebar wired to the session and the review count. */
export function ConnectedSidebar() {
  const { me } = useSession();
  const pathname = usePathname();
  // Refresh the count when moving between pages so approvals show up in the badge.
  const review = useAsync(() => (me?.role === "lecturer" ? api.listReview() : Promise.resolve([])), [me?.id, pathname]);
  if (!me) return null;
  return <Sidebar me={me} reviewCount={review.data?.length || undefined} />;
}
