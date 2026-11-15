import Link from "next/link";
import type { ReactNode } from "react";
import { BoardSnapshot } from "@/components/BoardSnapshot";
import { StatusPill } from "@/components/StatusPill";
import type { LectureSummary } from "@/contracts/LectureSummary";
import { formatDuration } from "@/lib/format";

/** Shared grid so the header row and the lecture rows line up. */
export const LECTURE_GRID = "grid grid-cols-[72px_minmax(0,1fr)_90px_90px_150px_120px] items-center gap-4";

export function lecturePill(l: LectureSummary, lecturer: boolean): ReactNode {
  switch (l.status) {
    case "processing":
    case "uploading":
      return <StatusPill status="processing">Processing{l.progress != null ? ` · ${Math.round(l.progress * 100)}%` : ""}</StatusPill>;
    case "draft":
      return <StatusPill status="draft">{lecturer ? "Draft · needs review" : "Draft"}</StatusPill>;
    case "in_review":
      return <StatusPill status="in_review">In review{l.open_items ? ` · ${l.open_items} ${lecturer ? "fixes" : ""}`.trimEnd() : ""}</StatusPill>;
    case "verified":
      return <StatusPill status="verified" />;
    case "failed":
      return <StatusPill status="failed" />;
  }
}

/** One lecture in the list: board thumbnail, title, length, sections, status and an action button. */
export function LectureRow({
  lecture,
  subtitle,
  action,
  lecturer = false,
  href,
}: {
  lecture: LectureSummary;
  subtitle: string;
  action: ReactNode;
  lecturer?: boolean;
  href?: string;
}) {
  return (
    <div className={`${LECTURE_GRID} border-t border-default px-4 py-3`} data-testid="lecture-row">
      <BoardSnapshot size="small" text="Ax = b" className="h-10 justify-center" />
      <div className="min-w-0">
        {href ? (
          <Link href={href} className="block truncate text-[14px] font-semibold leading-[22px] text-primary hover:text-accent hover:underline">
            {lecture.title}
          </Link>
        ) : (
          <p className="truncate text-[14px] font-semibold leading-[22px] text-primary">{lecture.title}</p>
        )}
        <p className="text-[12px] text-tertiary">{subtitle}</p>
      </div>
      <p className="text-[13px] text-secondary">{formatDuration(lecture.duration_s)}</p>
      <p className="text-[13px] text-secondary">{lecture.section_count ? `${lecture.section_count} sections` : "–"}</p>
      <div>{lecturePill(lecture, lecturer)}</div>
      <div className="text-right">{action}</div>
    </div>
  );
}

export function LectureHeader() {
  return (
    <div className={`${LECTURE_GRID} rounded-t-lg bg-subtle px-4 py-3 text-[12px] font-semibold text-tertiary`}>
      <span />
      <span>Lecture</span>
      <span>Length</span>
      <span>Sections</span>
      <span>Status</span>
      <span />
    </div>
  );
}
