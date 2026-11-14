"use client";
import Link from "next/link";
import { Button } from "@/components/Button";
import { Icon } from "@/components/Icon";
import { PdfRow } from "@/components/PdfRow";
import { StatusPill, type PillStatus } from "@/components/StatusPill";
import { TopBar } from "@/components/TopBar";
import type { PdfInfo } from "@/contracts/PdfInfo";
import { assetUrl, API_MODE } from "@/lib/api";
import { api } from "@/lib/client";
import { formatAgo } from "@/lib/format";
import { useAsync } from "@/lib/hooks";

const PILL: Record<PdfInfo["status"], PillStatus> = {
  uploading: "processing",
  processing: "processing",
  draft: "draft",
  in_review: "in_review",
  verified: "verified",
  failed: "failed",
};

function rowMeta(p: PdfInfo): string {
  if (p.status === "processing" || p.status === "uploading") return "Available after processing";
  if (p.status === "draft") return `${p.pages} pages · draft, generated ${formatAgo(p.generated_at)}`;
  if (p.status === "in_review") return `${p.pages} pages · generated ${formatAgo(p.generated_at)}, some fixes waiting`;
  return `${p.pages} pages · verified ${formatAgo(p.generated_at)}`;
}

export default function CourseNotesPage() {
  const pdfs = useAsync(() => api.listPdfs(), []);
  const lectures = useAsync(() => api.listLectures(), []);
  const all = pdfs.data ?? [];
  const whole = all.find((p) => p.lecture_id === null);
  const rows = all.filter((p) => p.lecture_id !== null);
  const done = (lectures.data ?? []).filter((l) => l.status !== "processing" && l.status !== "uploading");
  const verified = done.filter((l) => l.status === "verified").length;
  const pct = done.length ? (verified / done.length) * 100 : 0;
  const texHref = (id: string | null) => assetUrl(api.texUrl(id)) ?? "#";

  return (
    <>
      <TopBar
        crumb="Linear Algebra"
        title="Course notes"
        actions={
          <>
            <a href={texHref(null)} download>
              <Button variant="secondary">Download LaTeX</Button>
            </a>
            {whole && (
              <a href={assetUrl(whole.url) ?? "#"} download>
                <Button>Download module PDF</Button>
              </a>
            )}
          </>
        }
      />
      <div className="flex flex-col gap-6 p-8">
        {whole && (
          <div className="flex flex-wrap gap-6 rounded-xl border border-default bg-surface p-6 shadow-card">
            <div className="flex h-[140px] w-[107px] flex-col gap-1.5 rounded-sm border border-default bg-surface p-3 shadow-card">
              <p className="text-[8px] font-bold uppercase tracking-[0.08em] text-accent">Linear Algebra</p>
              <p className="font-display text-[11px] font-medium leading-3 text-primary">Complete course notes</p>
              {[80, 100, 70, 90, 60].map((w, i) => (
                <div key={i} className="h-1 rounded-full bg-muted" style={{ width: `${w}%` }} />
              ))}
            </div>
            <div className="flex min-w-[260px] flex-1 flex-col gap-2">
              <p className="text-[11px] font-bold uppercase tracking-[0.08em] text-tertiary">Whole module</p>
              <h2 className="font-display text-[22px] font-medium leading-7 text-primary">{whole.title}</h2>
              <p className="text-[13px] text-secondary">
                {done.length} lectures · {whole.pages} pages · updated {formatAgo(whole.generated_at)}
              </p>
              <p className="text-[12px] text-secondary">
                {verified} of {done.length} lectures verified by the lecturer
              </p>
              <div className="h-1.5 max-w-[300px] overflow-hidden rounded-full bg-muted">
                <div className="h-1.5 rounded-full bg-success" style={{ width: `${pct}%` }} />
              </div>
              <div className="mt-1 flex gap-3">
                <a href={assetUrl(whole.url) ?? "#"} download>
                  <Button>Download module PDF</Button>
                </a>
                <Link href="/course-notes/module">
                  <Button variant="secondary">Preview</Button>
                </Link>
              </div>
            </div>
          </div>
        )}
        <div className="flex items-center gap-3 rounded-lg bg-accent-subtle px-4 py-3 text-[13px] text-secondary">
          <Icon name="check" size={16} className="shrink-0 text-accent" />
          <span>PDFs update automatically when the lecturer approves changes. Unverified sections are marked &ldquo;Draft&rdquo; in the margin, and every formula links to its moment in the video.</span>
        </div>
        <h2 className="font-display text-[17px] font-medium text-primary">By lecture</h2>
        <div className="overflow-hidden rounded-lg border border-default bg-surface shadow-card">
          {pdfs.error && <p className="p-4 text-[13px] text-danger">{pdfs.error}</p>}
          {rows.map((p) => {
            const ready = p.status !== "processing" && p.status !== "uploading";
            return (
              <PdfRow
                key={p.lecture_id}
                title={p.title}
                meta={rowMeta(p)}
                status={<StatusPill status={PILL[p.status]} />}
                action={
                  ready ? (
                    <div className="flex justify-end gap-2">
                      <Link href={`/course-notes/${p.lecture_id}`}>
                        <Button variant="secondary" className="px-3 py-1.5">Preview</Button>
                      </Link>
                      <a href={assetUrl(p.url) ?? "#"} download>
                        <Button variant="secondary" className="px-3 py-1.5">Download</Button>
                      </a>
                    </div>
                  ) : (
                    <span className="text-[12px] font-semibold text-secondary">Not ready</span>
                  )
                }
              />
            );
          })}
        </div>
        {API_MODE === "mock" && <p className="text-[12px] text-tertiary">Mock mode: downloads are a placeholder PDF.</p>}
      </div>
    </>
  );
}
