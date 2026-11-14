"use client";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Button } from "@/components/Button";
import { Icon } from "@/components/Icon";
import { uploadFile, type UploadProgress } from "@/lib/api";
import { api } from "@/lib/client";
import { formatBytes } from "@/lib/format";
import { cx } from "@/lib/cx";

/** "L25_quadratic_forms.mp4" -> "L25 quadratic forms". */
export function titleFromFilename(name: string): string {
  return name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim() || name;
}

/** Drop zone plus chunked, resumable upload with progress. On success it opens the processing page. */
export function UploadPanel() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [paused, setPaused] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);

  async function start(f: File) {
    setFile(f);
    setError(null);
    setPaused(false);
    abort.current = new AbortController();
    try {
      const lecture = await uploadFile(api, f, titleFromFilename(f.name), setProgress, abort.current.signal);
      router.push(`/lectures/${lecture.id}/processing`);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") setPaused(true);
      else setError(e instanceof Error ? e.message : "Upload failed");
    }
  }

  const pct = progress ? Math.round((progress.sentBytes / Math.max(1, progress.totalBytes)) * 100) : 0;
  const uploading = file !== null && !error && !paused;

  return (
    <div
      className={cx("flex flex-wrap items-center gap-6 rounded-xl border-2 border-dashed bg-surface p-6", over ? "border-accent bg-accent-subtle" : "border-accent-border")}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const f = e.dataTransfer.files[0];
        if (f) void start(f);
      }}
    >
      <span className="flex size-12 items-center justify-center rounded-lg bg-accent-subtle text-accent">
        <Icon name="upload" size={24} />
      </span>
      <div className="min-w-[240px] flex-1">
        <p className="font-display text-[15px] font-medium text-primary">Drop a lecture video here</p>
        <p className="text-[13px] text-secondary">MP4, MOV or MKV · up to 3 hours. We check it has both picture and sound before processing.</p>
        <input
          ref={input}
          type="file"
          accept="video/*,.mkv"
          className="sr-only"
          aria-label="Choose a lecture video"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void start(f);
          }}
        />
        {!file && (
          <Button variant="secondary" className="mt-3" onClick={() => input.current?.click()}>
            Choose file
          </Button>
        )}
      </div>
      {file && (
        <div className="w-[320px] max-w-full rounded-lg border border-default bg-surface p-3 shadow-card" data-testid="upload-card">
          <div className="flex items-center justify-between gap-2 text-[13px]">
            <span className="truncate font-semibold text-primary">{file.name}</span>
            <span className="shrink-0 text-tertiary">
              {formatBytes(progress?.sentBytes ?? 0)} / {formatBytes(file.size)}
            </span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-1.5 rounded-full bg-accent transition-all" style={{ width: `${pct}%` }} />
          </div>
          <div className="mt-2 flex items-center justify-between text-[12px]">
            <span className={error ? "text-danger" : "text-tertiary"}>{error ?? (paused ? "Paused" : `Uploading · ${pct}%`)}</span>
            {uploading ? (
              <button type="button" className="font-semibold text-accent" onClick={() => abort.current?.abort()}>
                Pause
              </button>
            ) : (
              <button type="button" className="font-semibold text-accent" onClick={() => void start(file)}>
                {paused ? "Resume" : "Retry"}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
