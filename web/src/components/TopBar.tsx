"use client";
import type { ReactNode } from "react";
import { Button } from "@/components/Button";
import { Icon } from "@/components/Icon";
import { useSession } from "@/lib/session";

/** Page header: breadcrumb, title and actions. Shows the preview banner while a lecturer views as a student. */
export function TopBar({ crumb, title, actions }: { crumb: string; title: string; actions?: ReactNode }) {
  const { viewAsStudent, setViewAsStudent } = useSession();
  return (
    <>
      <header className="flex min-h-[68px] flex-wrap items-center justify-between gap-3 border-b border-default bg-surface px-8 py-2">
        <div className="min-w-0">
          <p className="text-[12px] leading-4 text-tertiary">{crumb}</p>
          <h1 className="truncate font-display text-[19px] font-medium leading-6 text-primary">{title}</h1>
        </div>
        {actions && <div className="flex flex-wrap items-center gap-3">{actions}</div>}
      </header>
      {viewAsStudent && (
        <div className="flex items-center gap-3 bg-accent px-8 py-2.5 text-[13px] font-semibold text-on-accent" role="status" data-testid="preview-banner">
          <Icon name="eye" size={18} />
          <span className="flex-1">You&rsquo;re viewing this lecture as a student. Lecturer tools are hidden and nothing you do here is saved.</span>
          <Button variant="secondary" className="px-3 py-1" onClick={() => setViewAsStudent(false)}>
            Exit preview
          </Button>
        </div>
      )}
    </>
  );
}
