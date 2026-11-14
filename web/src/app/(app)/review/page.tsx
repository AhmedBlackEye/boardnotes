"use client";
import Link from "next/link";
import { redirect } from "next/navigation";
import { useState } from "react";
import { AiVerdict } from "@/components/AiVerdict";
import { BoardSnapshot } from "@/components/BoardSnapshot";
import { Button } from "@/components/Button";
import { Math as Tex } from "@/components/Math";
import { StatCard } from "@/components/StatCard";
import { StatusPill } from "@/components/StatusPill";
import { TextField } from "@/components/TextField";
import { TopBar } from "@/components/TopBar";
import { Upvote } from "@/components/Upvote";
import type { ReviewItem } from "@/contracts/ReviewItem";
import { api } from "@/lib/client";
import { cx } from "@/lib/cx";
import { formatClock, plural } from "@/lib/format";
import { useAsync } from "@/lib/hooks";
import { approveEach } from "@/lib/batch";
import { useSession } from "@/lib/session";

type Sort = "urgent" | "upvoted" | "section";

function sortItems(items: ReviewItem[], sort: Sort): ReviewItem[] {
  const copy = [...items];
  if (sort === "urgent") return copy.sort((a, b) => b.priority - a.priority);
  if (sort === "upvoted") return copy.sort((a, b) => (b.suggestion?.upvotes ?? 0) - (a.suggestion?.upvotes ?? 0));
  return copy.sort((a, b) => a.section_heading.localeCompare(b.section_heading, undefined, { numeric: true }));
}

/** Plain-text rendering of a board reading: prefer LaTeX through KaTeX, else the text. */
function Reading({ text, latex }: { text: string; latex?: string | null }) {
  return latex ? <Tex latex={latex} /> : <>{text}</>;
}

function ReviewCard({ item, onDone }: { item: ReviewItem; onDone: () => void }) {
  const s = item.suggestion;
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(s?.proposed_text ?? item.current_text);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function decide(decision: "approve" | "edit" | "reject") {
    setBusy(true);
    setError(null);
    try {
      await api.decide(item.id, decision === "edit" ? { decision, edited_text: text } : { decision });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
      setBusy(false);
    }
  }

  const block = item.board_block;
  const low = (block?.confidence ?? 1) < 0.8;
  return (
    <article className="flex flex-wrap gap-5 rounded-lg border border-default bg-surface p-5 shadow-card" data-testid="review-item">
      <div className="w-[190px] shrink-0">
        <BoardSnapshot
          caption={block ? `Board · ${formatClock(block.best_frame_s)}` : "Board"}
          text={block?.text ?? item.current_text}
          imageUrl={item.snapshot_url}
          className="justify-center"
        />
        <Link href={`/lectures/${item.lecture_id}?bullet=${item.bullet_id}&panel=source`} className="mt-2 block text-[12px] font-semibold text-accent">
          Open in notes
        </Link>
      </div>
      <div className="flex min-w-[260px] flex-1 flex-col gap-2.5">
        <div className="flex flex-wrap gap-2">
          {low && <StatusPill status="flagged">Low confidence</StatusPill>}
          {s ? <StatusPill status="info">Student fix</StatusPill> : <StatusPill status="uncertain">Uncertain reading</StatusPill>}
          {s?.flagged && <StatusPill status="flagged">Flagged · reads like instructions</StatusPill>}
          <span className="text-[12px] text-tertiary">{item.section_heading}</span>
        </div>
        <div className="grid grid-cols-[72px_1fr] items-baseline gap-x-3 gap-y-2 text-[14px]">
          <span className="text-[12px] text-tertiary">Current</span>
          <span className={cx(s && "text-danger line-through")}>{item.current_text}</span>
          {s && (
            <>
              <span className="text-[12px] text-tertiary">Suggested</span>
              <span className="font-semibold text-success">{s.proposed_text}</span>
            </>
          )}
          {!s && block && (
            <>
              <span className="text-[12px] text-tertiary">AI read</span>
              <span>
                <Reading text={block.text} latex={block.latex} />
              </span>
            </>
          )}
        </div>
        {s && (
          <div className="flex flex-wrap items-center gap-2">
            {s.verdict && <AiVerdictPill verdict={s.verdict} />}
            <Upvote count={s.upvotes} voted={s.voted_by_me} />
            <span className="text-[12px] text-tertiary">Suggested by {s.anonymous ? "Anonymous" : s.author_name}</span>
          </div>
        )}
        {s?.verdict_reason && <AiVerdict verdict={s.verdict ?? "unclear"} reason={s.verdict_reason} />}
        {!s && <p className="text-[12px] text-secondary">Low-confidence reading from the AI. No student fixes yet.</p>}
        {editing && <TextField multiline maxLength={1000} label="Edited text" value={text} onChange={(e) => setText(e.target.value)} />}
        {error && <p className="text-[13px] text-danger">{error}</p>}
      </div>
      <div className="flex w-[140px] shrink-0 flex-col gap-2">
        {editing ? (
          <>
            <Button variant="success" disabled={busy || !text.trim()} onClick={() => decide("edit")}>
              Save edit
            </Button>
            <Button variant="secondary" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </>
        ) : (
          <>
            <Button variant="success" disabled={busy} onClick={() => decide("approve")}>
              {s ? "Approve" : "Looks right"}
            </Button>
            <Button variant="secondary" disabled={busy} onClick={() => setEditing(true)}>
              Edit
            </Button>
            <Button variant="ghost" disabled={busy} onClick={() => decide("reject")} title={s ? undefined : "The reading is wrong: remove this line from the notes"}>
              {s ? "Reject" : "Remove line"}
            </Button>
          </>
        )}
      </div>
    </article>
  );
}

function AiVerdictPill({ verdict }: { verdict: NonNullable<ReviewItem["suggestion"]>["verdict"] }) {
  if (verdict === "agrees") return <StatusPill status="verified">AI agrees</StatusPill>;
  if (verdict === "disagrees") return <StatusPill status="flagged">AI disagrees</StatusPill>;
  return <StatusPill status="uncertain">AI unsure</StatusPill>;
}

export default function ReviewPage() {
  const { me } = useSession();
  const items = useAsync(() => api.listReview(), []);
  const lectures = useAsync(() => api.listLectures(), []);
  const [sort, setSort] = useState<Sort>("urgent");
  const [busy, setBusy] = useState(false);
  const [bulk, setBulk] = useState<{ error: boolean; text: string } | null>(null);
  if (me && me.role !== "lecturer") redirect("/lectures");

  const list = sortItems(items.data ?? [], sort);
  const agreed = list.filter((i) => i.suggestion?.verdict === "agrees" && !i.suggestion.flagged);
  const upvotes = list.reduce((n, i) => n + (i.suggestion?.upvotes ?? 0), 0);
  const ready = (lectures.data ?? []).filter((l) => l.status !== "processing" && l.status !== "uploading");
  const verified = ready.filter((l) => l.status === "verified").length;

  const bySection = new Map<string, number>();
  for (const i of list) bySection.set(i.section_heading, (bySection.get(i.section_heading) ?? 0) + 1);

  async function approveAll() {
    setBusy(true);
    setBulk(null);
    const r = await approveEach(agreed.map((i) => i.id), (id) => api.decide(id, { decision: "approve" }));
    setBulk(r.failed ? { error: true, text: `Approved ${r.done} of ${agreed.length}. ${plural(r.failed, "fix", "fixes")} could not be approved (${r.firstError}).` } : { error: false, text: `Approved ${plural(r.done, "fix", "fixes")}.` });
    items.reload();
    lectures.reload();
    setBusy(false);
  }

  return (
    <>
      <TopBar
        crumb="Review queue"
        title="Student fixes and uncertain readings"
        actions={
          <Button variant="success" disabled={busy || agreed.length === 0} onClick={approveAll}>
            Approve all AI-agreed ({agreed.length})
          </Button>
        }
      />
      <div className="grid gap-6 p-8 xl:grid-cols-[1fr_300px]">
        <div className="flex flex-col gap-5">
          <div className="flex flex-wrap gap-4">
            <StatCard value={String(list.length)} label="Items to review" />
            <StatCard value={`~${Math.ceil(list.length * 0.8)} min`} label="Estimated time left" />
            <StatCard value={`${verified} / ${ready.length}`} label="Lectures verified" />
            <StatCard value={String(upvotes)} label="Student upvotes" />
          </div>
          <div className="flex items-center justify-between">
            <div className="flex gap-2" role="tablist" aria-label="Sort review items">
              {(
                [
                  ["urgent", "Most urgent first"],
                  ["upvoted", "Most upvoted"],
                  ["section", "By section"],
                ] as const
              ).map(([k, label]) => (
                <button
                  key={k}
                  role="tab"
                  aria-selected={sort === k}
                  onClick={() => setSort(k)}
                  className={cx("rounded-md border px-3 py-1.5 text-[12px] font-semibold", sort === k ? "border-default bg-surface text-primary" : "border-transparent text-secondary hover:text-primary")}
                >
                  {label}
                </button>
              ))}
            </div>
            <p className="text-[12px] text-tertiary">Ranked by confidence, upvotes and AI check</p>
          </div>
          {bulk && (
            <p role="status" className={cx("text-[13px]", bulk.error ? "text-danger" : "text-secondary")}>
              {bulk.text}
            </p>
          )}
          {items.error && <p className="text-[13px] text-danger">{items.error}</p>}
          {list.map((item) => (
            <ReviewCard key={item.id} item={item} onDone={items.reload} />
          ))}
          {!items.loading && list.length === 0 && (
            <p className="rounded-lg border border-default bg-surface p-6 text-[14px] text-secondary">Nothing to review. Every fix has been decided.</p>
          )}
        </div>
        <div className="flex flex-col gap-4">
          <div className="rounded-lg border border-default bg-surface p-4 shadow-card">
            <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.08em] text-tertiary">Sections</p>
            <ul className="flex flex-col gap-2 text-[13px] text-primary">
              {[...bySection].map(([name, n]) => (
                <li key={name} className="flex items-center justify-between gap-2">
                  <span>{name}</span>
                  <StatusPill status="uncertain" showDot={false}>{plural(n, "item")}</StatusPill>
                </li>
              ))}
              {bySection.size === 0 && <li className="text-secondary">All clear.</li>}
            </ul>
          </div>
          <div className="rounded-lg border border-default bg-surface p-4 shadow-card">
            <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.08em] text-tertiary">How this works</p>
            <p className="text-[13px] leading-5 text-secondary">
              Students suggest fixes and upvote ones they agree with. The AI checks each fix against the board and the recording. Nothing in the notes or the PDF changes until you approve it.
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
