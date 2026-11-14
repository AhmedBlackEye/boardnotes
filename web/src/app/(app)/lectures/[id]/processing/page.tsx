"use client";
import Link from "next/link";
import { redirect, useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Button } from "@/components/Button";
import { Icon } from "@/components/Icon";
import { SectionCard } from "@/components/SectionCard";
import { StatusPill } from "@/components/StatusPill";
import { TopBar } from "@/components/TopBar";
import { VideoPlayer } from "@/components/VideoPlayer";
import { ViewSwitch } from "@/components/ViewSwitch";
import type { JobProgress } from "@/contracts/JobProgress";
import { api } from "@/lib/client";
import { cx } from "@/lib/cx";
import { useAsync } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { STEPS, stepState } from "@/lib/steps";

/** Board text shown on the simulated player in mock mode (the mock processing lecture is L24). */
const MOCK_BOARD = "f(x) = xᵀAx\nxᵀAx > 0 for all x ≠ 0\n⇒ A positive definite";

export default function ProcessingPage() {
  const { id } = useParams<{ id: string }>();
  const { me, viewAsStudent, setViewAsStudent } = useSession();
  const [job, setJob] = useState<JobProgress | null>(null);
  const [lost, setLost] = useState(false);
  const lecture = useAsync(() => api.getLecture(id), [id]);

  useEffect(() => {
    return api.subscribeProgress(id, setJob, () => setLost(true));
  }, [id]);

  // Section text arrives as the job writes it: reload the lecture whenever another section is ready.
  // The progress stream closes itself once the job is done or failed; reload then too for the final title and PDF.
  const ready = job?.sections_ready ?? 0;
  const stage = job?.stage ?? "check_video";
  const done = stage === "done";
  const reload = lecture.reload;
  useEffect(() => {
    if (ready > 0 || done) reload();
  }, [ready, done, reload]);

  if (me && me.role !== "lecturer") redirect("/lectures");

  const d = lecture.data;
  const pct = Math.round((job?.progress ?? 0) * 100);
  const sections = d?.sections ?? [];
  const shown = sections.slice(0, ready);

  return (
    <>
      <TopBar
        crumb="Lectures"
        title={d?.summary.title ?? "Processing"}
        actions={
          <>
            <StatusPill status={job?.error ? "failed" : done ? "verified" : "processing"}>
              {job?.error ? "Failed" : done ? "Ready for review" : `Processing · ${pct}%`}
            </StatusPill>
            <ViewSwitch asStudent={viewAsStudent} onChange={setViewAsStudent} />
          </>
        }
      />
      <div className="grid gap-6 p-8 lg:grid-cols-2">
        <div className="flex flex-col gap-4">
          <VideoPlayer src={d?.video_url || null} boardText={api.mode === "mock" ? MOCK_BOARD : (d?.board_blocks[0]?.text ?? "")} durationS={d?.summary.duration_s ?? 0} />
          <div className="flex flex-col gap-4 rounded-lg border border-default bg-surface p-4 shadow-card" data-testid="steps">
            {STEPS.map((s, i) => {
              const st = job ? stepState(i, stage) : "waiting";
              return (
                <div key={s.title} className="flex items-start gap-3">
                  <span
                    className={cx(
                      "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold",
                      st === "done" && "bg-success text-on-accent",
                      st === "active" && "border-2 border-accent text-accent",
                      st === "waiting" && "border border-strong text-tertiary",
                    )}
                  >
                    {st === "done" ? <Icon name="check" size={14} /> : i + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[13px] font-semibold leading-[18px] text-primary">{s.title}</p>
                    {st === "active" && <p className="text-[12px] text-tertiary">{job?.detail}</p>}
                    {st === "active" && (
                      <div className="mt-1.5 h-1.5 max-w-[260px] overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={pct}>
                        <div className="h-1.5 rounded-full bg-accent transition-all" style={{ width: `${pct}%` }} />
                      </div>
                    )}
                  </div>
                  <span className={cx("text-[12px]", st === "done" ? "font-semibold text-success" : "text-tertiary")}>
                    {st === "done" ? "Done" : st === "active" ? (i === 3 ? "In progress" : `${pct}%`) : ""}
                  </span>
                </div>
              );
            })}
            {(job?.error || (lost && !done)) && <p className="text-[13px] text-danger">{job?.error ?? "Lost connection to the progress feed. Reload to reconnect."}</p>}
          </div>
        </div>
        <div className="flex flex-col gap-3">
          <div className="flex items-baseline justify-between">
            <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-tertiary">Ready to review</p>
            <p className="text-[12px] text-tertiary">Sections appear as soon as they are written</p>
          </div>
          {shown.map((s) => (
            <SectionCard key={s.id} title={`${s.order} · ${s.heading}`} summary={s.bullets[0]?.text} range={{ start: s.start_s, end: s.end_s }} />
          ))}
          {!done && <SectionCard pending title={ready > 0 ? `${ready + 1} · writing…` : "Writing the first section…"} />}
          {done && (
            <Link href={`/lectures/${id}`}>
              <Button variant="success">Open notes to review</Button>
            </Link>
          )}
        </div>
      </div>
    </>
  );
}
