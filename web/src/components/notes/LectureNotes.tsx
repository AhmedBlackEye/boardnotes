"use client";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useRef, useState } from "react";
import { Button } from "@/components/Button";
import { Icon } from "@/components/Icon";
import { NoteBullet } from "@/components/NoteBullet";
import { SourceChip } from "@/components/SourceChip";
import { StatusDot } from "@/components/StatusDot";
import { StatusPill } from "@/components/StatusPill";
import { TopBar } from "@/components/TopBar";
import { ViewSwitch } from "@/components/ViewSwitch";
import type { SeekRequest } from "@/components/VideoPlayer";
import type { LectureDetail } from "@/contracts/LectureDetail";
import type { Section } from "@/contracts/Section";
import { assetUrl, type VerifyResult } from "@/lib/api";
import { api } from "@/lib/client";
import { cx } from "@/lib/cx";
import { plural } from "@/lib/format";
import { useSession } from "@/lib/session";
import { AskPanel } from "@/components/notes/AskPanel";
import { FixPanel } from "@/components/notes/FixPanel";
import { SourcePanel } from "@/components/notes/SourcePanel";
import { DiagramFigure } from "@/components/diagrams/DiagramFigure";
import { boardLabel, bulletAt, errorText, figuresByBullet, findBullet, firstStart, snapshotUrl, uncertainCount, verifyMessage } from "@/components/notes/helpers";

type PanelName = "source" | "fix" | "ask";

function sectionPill(s: Section) {
  const u = uncertainCount(s);
  if (s.status === "verified") return <StatusPill status="verified">Verified by lecturer</StatusPill>;
  if (s.status === "draft" && !u) return <StatusPill status="draft">Draft</StatusPill>;
  return <StatusPill status="uncertain">{plural(u || 1, "uncertain point")}</StatusPill>;
}

/**
 * Lecture notes with the source/fix/ask panel. One component for the student view (S2-S4), the lecturer view (L4)
 * and the lecturer previewing as a student (L5). The panel state lives in the URL: ?bullet=..&panel=source|fix|ask.
 */
export function LectureNotes({ lecture, mode, preview, onChanged }: { lecture: LectureDetail; mode: "student" | "lecturer"; preview: boolean; onChanged: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { me, viewAsStudent, setViewAsStudent } = useSession();
  const notesRef = useRef<HTMLDivElement>(null);
  const seekN = useRef(0);
  const [seek, setSeek] = useState<SeekRequest | null>(() => {
    const t = Number(params.get("t"));
    return params.get("t") && Number.isFinite(t) ? { t, n: 0 } : null;
  });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ at: string; error: boolean; text: string } | null>(null);
  const [activeSection, setActiveSection] = useState<string | null>(null);

  const bulletId = params.get("bullet");
  const panel = (params.get("panel") as PanelName | null) ?? (bulletId ? "source" : null);
  const selected = findBullet(lecture, bulletId);
  const lecturer = mode === "lecturer";

  function go(next: { bullet?: string | null; panel?: PanelName | null; t?: number | null }) {
    const q = new URLSearchParams(params.toString());
    const set = (k: string, v: string | null | undefined) => (v ? q.set(k, v) : q.delete(k));
    if ("bullet" in next) set("bullet", next.bullet);
    if ("panel" in next) set("panel", next.panel);
    if ("t" in next) set("t", next.t == null ? null : String(next.t));
    const qs = q.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  function open(bulletId: string, name: PanelName, t?: number) {
    if (t !== undefined) {
      seekN.current += 1;
      setSeek({ t, n: seekN.current });
    }
    go({ bullet: bulletId, panel: name, t: t ?? null });
  }

  function seekTo(t: number) {
    const b = bulletAt(lecture, t) ?? selected?.bullet;
    if (b) open(b.id, "source", t);
  }

  const verified = lecture.sections.filter((s) => s.status === "verified").length;
  const waiting = lecture.sections.reduce((n, s) => n + s.bullets.reduce((m, b) => m + b.open_suggestions, 0), 0);
  const uncertainTotal = lecture.sections.reduce((n, s) => n + uncertainCount(s), 0);
  const pdf = assetUrl(lecture.pdf_url);
  const figures = figuresByBullet(lecture);
  const boxNumbers = new Map(
    lecture.sections.flatMap((s) => s.bullets.filter((b) => (b.kind ?? "point") !== "point").map((b, i) => [b.id, `${s.order}.${i + 1}`] as const)),
  );

  /** Approve a section (or "lecture") and say what happened next to the button. */
  async function verify(at: string, fn: () => Promise<VerifyResult>) {
    setBusy(true);
    setNotice(null);
    try {
      const r = await fn();
      setNotice({ at, error: r.failed > 0, text: verifyMessage(r) });
    } catch (e) {
      setNotice({ at, error: true, text: errorText(e, "Could not approve. Try again.") });
    } finally {
      setBusy(false);
      onChanged();
    }
  }
  const noticeFor = (at: string) =>
    notice?.at === at ? (
      <p role="status" className={cx("text-[13px]", notice.error ? "text-danger" : "text-secondary")}>
        {notice.text}
      </p>
    ) : null;

  const actions = (
    <>
      {lecturer || me?.role === "lecturer" ? <ViewSwitch asStudent={viewAsStudent} onChange={setViewAsStudent} /> : null}
      {!lecturer && (
        <StatusPill status={verified === lecture.sections.length ? "verified" : "in_review"}>
          {verified} of {lecture.sections.length} sections verified
        </StatusPill>
      )}
      {pdf ? (
        <a href={pdf} download>
          <Button variant="secondary">Download PDF</Button>
        </a>
      ) : (
        <Button variant="secondary" disabled>
          Download PDF
        </Button>
      )}
      {lecturer ? (
        <Button variant="success" disabled={busy || lecture.summary.status === "verified"} onClick={() => verify("lecture", () => api.verifyLecture(lecture.summary.id))}>
          {lecture.summary.status === "verified" ? "Lecture approved" : "Approve lecture"}
        </Button>
      ) : (
        <Button onClick={() => go({ panel: "ask" })}>Ask the lecture</Button>
      )}
    </>
  );

  const panelTitle = panel === "fix" ? "Suggest a fix" : panel === "ask" ? "Ask the lecture" : lecturer ? "Edit this point" : "Source";

  return (
    <>
      <TopBar crumb="Lectures" title={lecture.summary.title} actions={actions} />
      <div className="flex min-h-0 flex-1 gap-6 px-8 py-6">
        <nav className={cx("hidden w-[220px] shrink-0 flex-col gap-1 overflow-y-auto", panel ? "2xl:flex" : "lg:flex")} aria-label="Sections">
          <p className="text-[11px] font-bold uppercase leading-4 tracking-[0.08em] text-tertiary">Sections</p>
          {lecture.sections.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => {
                setActiveSection(s.id);
                document.getElementById(`section-${s.id}`)?.scrollIntoView?.({ behavior: "smooth", block: "start" });
              }}
              className={cx(
                "flex items-center justify-between gap-2 rounded-md px-3 py-2 text-left",
                activeSection === s.id ? "border border-default bg-surface text-[13px] font-semibold text-primary" : "border border-transparent text-[14px] text-secondary hover:bg-muted",
              )}
            >
              <span>
                {s.order} · {s.heading}
              </span>
              <StatusDot status={s.status} />
            </button>
          ))}
          <div className="flex flex-col gap-1.5 pl-3 pt-4 text-[12px] text-secondary">
            <span className="flex items-center gap-2"><StatusDot status="verified" /> Lecturer-verified</span>
            <span className="flex items-center gap-2"><StatusDot status="uncertain" /> Has uncertain points</span>
            <span className="flex items-center gap-2"><StatusDot status="draft" /> Draft</span>
          </div>
        </nav>

        <div ref={notesRef} className="min-w-[340px] flex-1 overflow-y-auto rounded-lg border border-default bg-surface px-8 py-6 shadow-card" data-testid="notes">
          {notice?.at === "lecture" && <div className="mb-4">{noticeFor("lecture")}</div>}
          {lecturer && (waiting > 0 || uncertainTotal > 0) && (
            <div className="mb-4 flex items-center justify-between gap-3 rounded-lg bg-warning-subtle px-4 py-3 text-[13px] font-semibold text-warning">
              <span>
                {[waiting > 0 && plural(waiting, "student fix", "student fixes"), uncertainTotal > 0 && plural(uncertainTotal, "uncertain reading")]
                  .filter(Boolean)
                  .join(" and ")}{" "}
                {waiting + uncertainTotal === 1 ? "is" : "are"} waiting in this lecture.
              </span>
              <Link href="/review">
                <Button variant="secondary" className="px-3 py-1">Open review queue</Button>
              </Link>
            </div>
          )}
          {lecture.sections.map((s, si) => (
            <section key={s.id} id={`section-${s.id}`} className={cx("flex flex-col gap-4", si > 0 && "mt-6 border-t border-default pt-6")}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="font-display text-[22px] font-medium leading-7 tracking-[-0.005em] text-primary">
                  {s.order} · {s.heading}
                </h2>
                <div className="flex items-center gap-2">
                  {sectionPill(s)}
                  {lecturer && s.status !== "verified" && (
                    <Button variant="success" className="px-3 py-1" disabled={busy} onClick={() => verify(s.id, () => api.verifySection(lecture.summary.id, s.id))}>
                      Approve section
                    </Button>
                  )}
                </div>
              </div>
              {noticeFor(s.id)}
              {s.bullets.map((b) => (
                <NoteBullet
                  key={b.id}
                  kind={b.kind}
                  title={b.title}
                  number={boxNumbers.get(b.id)}
                  text={b.text}
                  latex={b.latex}
                  state={b.id === bulletId ? "selected" : b.uncertain ? "uncertain" : "default"}
                  onSelect={() => open(b.id, "source", firstStart(b))}
                  figures={figures.get(b.id)?.map((block) =>
                    block.figure ? <DiagramFigure key={block.id} figure={block.figure} boardText={block.text} snapshotUrl={snapshotUrl(lecture.summary.id, block.id)} /> : null,
                  )}
                >
                  {b.transcript_ranges.map((r, i) => (
                    <SourceChip key={i} seconds={r.start_s} onClick={() => open(b.id, "source", r.start_s)} />
                  ))}
                  {b.board_block_ids.map((id) => (
                    <SourceChip key={id} type="reference" label={boardLabel(lecture, id)} onClick={() => open(b.id, "source", firstStart(b))} />
                  ))}
                  {(b.uncertain || b.open_suggestions > 0) && (
                    <StatusPill status="uncertain" showDot className="bg-transparent px-1">
                      {b.uncertain ? "AI unsure" : "Fix suggested"}
                      {b.open_suggestions > 0 ? ` · ${plural(b.open_suggestions, "fix", "fixes")} suggested` : ""}
                    </StatusPill>
                  )}
                </NoteBullet>
              ))}
              {s.said_not_written.map((w, i) => (
                <div key={i} className="flex flex-col gap-2 rounded-lg bg-accent-subtle p-3">
                  <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-accent">Said but not written</p>
                  <p className="text-[14px] leading-[22px] text-primary">“{w.text}”</p>
                  <div>
                    <SourceChip seconds={w.at_s} onClick={() => seekTo(w.at_s)} />
                  </div>
                </div>
              ))}
            </section>
          ))}
        </div>

        {panel && (
          <aside className="flex w-[400px] max-w-[42vw] shrink-0 flex-col overflow-hidden rounded-lg border border-default bg-surface shadow-card" aria-label={panelTitle}>
            <div className="flex items-center justify-between border-b border-default px-5 py-4">
              <div>
                <h2 className="font-display text-[17px] font-medium leading-6 text-primary">{panelTitle}</h2>
                {panel === "ask" && <p className="text-[12px] text-tertiary">Answers come only from this lecture, with sources</p>}
              </div>
              <button type="button" aria-label="Close panel" className="text-tertiary hover:text-primary" onClick={() => go({ panel: null, bullet: null, t: null })}>
                <Icon name="close" size={18} />
              </button>
            </div>
            {panel === "ask" ? (
              <AskPanel lecture={lecture} onSeek={seekTo} />
            ) : !selected ? (
              <p className="p-5 text-[13px] text-secondary">Select a point in the notes to see its source.</p>
            ) : panel === "fix" ? (
              <FixPanel lecture={lecture} bullet={selected.bullet} preview={preview} onChanged={onChanged} />
            ) : (
              <SourcePanel
                lecture={lecture}
                bullet={selected.bullet}
                seek={seek}
                mode={mode}
                onAsk={() => go({ panel: "ask" })}
                onFix={() => go({ panel: "fix" })}
                onChanged={onChanged}
              />
            )}
          </aside>
        )}
      </div>
    </>
  );
}
