/** Formatting helpers. Times are seconds (float) everywhere; they become mm:ss only here, for display. */

/** 125.4 -> "2:05"; 6740 -> "1:52:20". */
export function formatTime(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${ss}`;
  return `${m}:${ss}`;
}

/** Same as formatTime but always at least mm:ss with two-digit minutes ("00:00 – 12:40" style ranges). */
export function formatClock(seconds: number): string {
  const t = formatTime(seconds);
  return t.length === 4 ? `0${t}` : t;
}

export function formatRange(start: number, end: number): string {
  return `${formatTime(start)} – ${formatTime(end)}`;
}

/** 6740 -> "1 h 52 min"; 2700 -> "45 min"; null -> "–". */
export function formatDuration(seconds: number | null): string {
  if (seconds == null) return "–";
  const mins = Math.round(seconds / 60);
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h > 0 ? `${h} h ${m} min` : `${m} min`;
}

/** Relative day wording used in lists: "today", "yesterday", "3 days ago", "last week", "2 weeks ago". */
export function formatRelativeDay(iso: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOf(now) - startOf(then)) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 14) return "last week";
  if (days < 60) return `${Math.floor(days / 7)} weeks ago`;
  return then.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/** "2 h ago", "5 min ago", "just now". */
export function formatAgo(iso: string, now: Date = new Date()): string {
  const secs = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)} min ago`;
  if (secs < 86_400) return `${Math.floor(secs / 3600)} h ago`;
  return formatRelativeDay(iso, now);
}

export function formatBytes(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(0)} MB`;
  return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n} ${n === 1 ? word : many}`;
}

/** Lecture titles look like "L21 · Eigenvalues"; the short code is used on board thumbnails and PDFs. */
export function lectureCode(title: string): string {
  return title.split(" · ")[0] ?? title;
}
