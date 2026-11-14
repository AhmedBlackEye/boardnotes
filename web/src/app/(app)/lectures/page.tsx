"use client";
import Link from "next/link";
import { useState } from "react";
import { BoardSnapshot } from "@/components/BoardSnapshot";
import { Button } from "@/components/Button";
import { Icon } from "@/components/Icon";
import { LectureHeader, LectureRow } from "@/components/LectureRow";
import { TopBar } from "@/components/TopBar";
import { UploadPanel } from "@/components/UploadPanel";
import { ViewSwitch } from "@/components/ViewSwitch";
import type { LectureSummary } from "@/contracts/LectureSummary";
import { api } from "@/lib/client";
import { formatRelativeDay, lectureCode } from "@/lib/format";
import { useAsync } from "@/lib/hooks";
import { cx } from "@/lib/cx";
import { useSession } from "@/lib/session";

type Filter = "all" | "verified" | "in_review" | "draft";

function subtitle(l: LectureSummary, lecturer: boolean): string {
  if (lecturer) {
    if (l.status === "draft") return `Draft notes ready · ${l.open_items} uncertain points`;
    if (l.status === "in_review") return `${l.open_items} student fixes waiting`;
    if (l.status === "verified") return `Verified ${formatRelativeDay(l.uploaded_at)}`;
  }
  return `Uploaded ${formatRelativeDay(l.uploaded_at)}`;
}

export default function LecturesPage() {
  const { me, role, viewAsStudent, setViewAsStudent } = useSession();
  const lectures = useAsync(() => api.listLectures(), []);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const lecturer = role === "lecturer";
  const all = lectures.data ?? [];
  const count = (f: Filter) => (f === "all" ? all.length : all.filter((l) => l.status === f).length);
  const shown = all.filter((l) => (filter === "all" || l.status === filter) && l.title.toLowerCase().includes(query.toLowerCase()));
  const latest = all.find((l) => l.status === "verified" || l.status === "in_review" || l.status === "draft");

  const actions = lecturer ? (
    <>
      <ViewSwitch asStudent={viewAsStudent} onChange={setViewAsStudent} />
      <Link href="/upload">
        <Button>Upload lecture</Button>
      </Link>
    </>
  ) : (
    <>
      {me?.role === "lecturer" && <ViewSwitch asStudent={viewAsStudent} onChange={setViewAsStudent} />}
      <label className="flex w-[260px] items-center gap-2 rounded-md border border-default bg-subtle px-3 py-2 text-tertiary">
        <Icon name="search" size={16} />
        <input
          className="w-full bg-transparent text-[13px] text-primary placeholder:text-tertiary focus:outline-none"
          placeholder="Search lectures and notes…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search lectures"
        />
      </label>
      <Link href="/course-notes">
        <Button variant="secondary">Course notes PDF</Button>
      </Link>
    </>
  );

  const action = (l: LectureSummary) => {
    if (l.status === "processing" || l.status === "uploading") {
      return lecturer ? (
        <Link href={`/lectures/${l.id}/processing`}>
          <Button variant="secondary" className="px-3 py-1.5">View progress</Button>
        </Link>
      ) : (
        <span className="text-[12px] font-semibold text-secondary">Notes soon</span>
      );
    }
    if (lecturer && (l.status === "draft" || l.status === "in_review")) {
      return (
        <Link href={`/lectures/${l.id}`}>
          <Button className="px-3 py-1.5">Review</Button>
        </Link>
      );
    }
    return (
      <Link href={`/lectures/${l.id}`}>
        <Button variant="secondary" className="px-3 py-1.5">Open notes</Button>
      </Link>
    );
  };

  return (
    <>
      <TopBar crumb="Linear Algebra" title="Lectures" actions={actions} />
      <div className="flex flex-col gap-6 p-8">
        {lecturer ? (
          <UploadPanel />
        ) : (
          latest && (
            <div className="flex flex-wrap items-center gap-6 rounded-xl border border-default bg-surface p-4 shadow-card">
              <BoardSnapshot size="large" text={api.mode === "mock" ? "A = Aᵀ ⇒ real λ" : lectureCode(latest.title)} className="h-[100px] w-[200px] justify-center" />
              <div className="min-w-[200px] flex-1">
                <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-accent">Continue where you left off</p>
                <p className="font-display text-[19px] font-medium text-primary">{latest.title}</p>
                <p className="text-[13px] text-secondary">Pick up with the notes and the video side by side.</p>
              </div>
              <Link href={`/lectures/${latest.id}`}>
                <Button>Resume</Button>
              </Link>
            </div>
          )
        )}
        {!lecturer && (
          <div className="flex gap-2" role="tablist" aria-label="Filter lectures">
            {(
              [
                ["all", "All"],
                ["verified", "Verified"],
                ["in_review", "In review"],
                ["draft", "Draft"],
              ] as const
            ).map(([f, label]) => (
              <button
                key={f}
                role="tab"
                aria-selected={filter === f}
                onClick={() => setFilter(f)}
                className={cx("rounded-md border px-3 py-1.5 text-[12px] font-semibold", filter === f ? "border-default bg-surface text-primary" : "border-transparent text-secondary hover:text-primary")}
              >
                {label} · {count(f)}
              </button>
            ))}
          </div>
        )}
        <div className="rounded-lg border border-default bg-surface shadow-card">
          <LectureHeader />
          {lectures.error && <p className="p-4 text-[13px] text-danger">{lectures.error}</p>}
          {lectures.loading && !lectures.data && <p className="p-4 text-[13px] text-secondary">Loading lectures…</p>}
          {shown.map((l) => (
            <LectureRow key={l.id} lecture={l} lecturer={lecturer} subtitle={subtitle(l, lecturer)} action={action(l)} />
          ))}
          {!lectures.loading && shown.length === 0 && <p className="p-4 text-[13px] text-secondary">No lectures match.</p>}
        </div>
      </div>
    </>
  );
}
