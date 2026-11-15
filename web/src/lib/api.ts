/**
 * Typed client for the BoardNotes API.
 *
 * - Types come from the generated contracts (web/src/contracts), never hand-written copies.
 * - Base URL: NEXT_PUBLIC_API_URL. Cookies are sent with every request (demo session cookie).
 * - Mock mode (NEXT_PUBLIC_API_MODE=mock, or no API URL set) serves in-memory data from src/mocks,
 *   so every page works without the server.
 */
import type { AskOut } from "@/contracts/AskOut";
import type { AskTurn } from "@/contracts/AskTurn";
import type { JobProgress } from "@/contracts/JobProgress";
import type { LectureDetail } from "@/contracts/LectureDetail";
import type { LectureSummary } from "@/contracts/LectureSummary";
import type { Me } from "@/contracts/Me";
import type { PdfInfo } from "@/contracts/PdfInfo";
import type { ReviewDecisionIn } from "@/contracts/ReviewDecisionIn";
import type { ReviewItem } from "@/contracts/ReviewItem";
import type { SourceView } from "@/contracts/SourceView";
import type { Suggestion } from "@/contracts/Suggestion";
import type { SuggestionCreate } from "@/contracts/SuggestionCreate";
import type { UploadInit } from "@/contracts/UploadInit";
import type { UploadSession } from "@/contracts/UploadSession";
import type { VoteResult } from "@/contracts/VoteResult";

export type {
  AskOut,
  JobProgress,
  LectureDetail,
  LectureSummary,
  Me,
  PdfInfo,
  ReviewDecisionIn,
  ReviewItem,
  SourceView,
  Suggestion,
  SuggestionCreate,
  UploadInit,
  UploadSession,
  VoteResult,
};

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
export const API_MODE: "mock" | "live" =
  process.env.NEXT_PUBLIC_API_MODE === "mock" || (!API_URL && process.env.NEXT_PUBLIC_API_MODE !== "live")
    ? "mock"
    : "live";

/**
 * Every route the web app calls, in one place so it is easy to line up with the server (task/D-backend-api).
 *
 *   GET    /auth/me · POST /auth/demo-login · POST /auth/logout
 *   GET    /lectures · GET /lectures/{id} · GET /bullets/{id}/source
 *   GET    /bullets/{id}/suggestions · POST /suggestions
 *   POST   /suggestions/{id}/vote (add my vote) · DELETE /suggestions/{id}/vote (remove it)
 *   GET    /review[?lecture_id=] · POST /review/{item_id}/decision   (item id: suggestion id or "bullet:<id>")
 *   POST   /lectures/{id}/ask        → SSE: event "answer" (AskOut JSON), "error", "done"
 *   GET    /pdfs
 *   POST   /uploads · GET|PUT /uploads/{id} · POST /uploads/{id}/complete → JobProgress
 *   GET    /lectures/{id}/progress   → SSE: event "progress" (JobProgress JSON); the stream ends when the job does
 *
 * The server has no verify or .tex routes yet: "approve section/lecture" is built from review decisions
 * (see verifyByReview) and the .tex link is hidden in live mode. `verifySection`, `verifyLecture` and `tex` stay
 * here as the proposed routes.
 */
export const paths = {
  me: "/auth/me",
  login: "/auth/demo-login",
  logout: "/auth/logout",
  lectures: "/lectures",
  lecture: (id: string) => `/lectures/${enc(id)}`,
  source: (bulletId: string) => `/bullets/${enc(bulletId)}/source`,
  suggestionsFor: (bulletId: string) => `/bullets/${enc(bulletId)}/suggestions`,
  suggestions: "/suggestions",
  vote: (suggestionId: string) => `/suggestions/${enc(suggestionId)}/vote`,
  review: "/review",
  decision: (itemId: string) => `/review/${enc(itemId)}/decision`,
  verifySection: (sectionId: string) => `/sections/${enc(sectionId)}/verify`,
  verifyLecture: (lectureId: string) => `/lectures/${enc(lectureId)}/verify`,
  ask: (lectureId: string) => `/lectures/${enc(lectureId)}/ask`,
  pdfs: "/pdfs",
  tex: (lectureId: string | null) => (lectureId ? `/lectures/${enc(lectureId)}/notes.tex` : "/module/notes.tex"),
  uploads: "/uploads",
  upload: (uploadId: string) => `/uploads/${enc(uploadId)}`,
  uploadComplete: (uploadId: string) => `/uploads/${enc(uploadId)}/complete`,
  progress: (lectureId: string) => `/lectures/${enc(lectureId)}/progress`,
} as const;

function enc(s: string): string {
  return encodeURIComponent(s);
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type Unsubscribe = () => void;

/** Outcome of approving a section or lecture: readings confirmed, student fixes still waiting, and failures. */
export interface VerifyResult {
  approved: number;
  waiting: number;
  failed: number;
}

export interface UploadProgress {
  sentBytes: number;
  totalBytes: number;
}

/** What the pages need from the server. Implemented over HTTP below and in memory in src/mocks. */
export interface BoardNotesApi {
  readonly mode: "mock" | "live";
  me(): Promise<Me | null>;
  login(userId: string): Promise<Me>;
  logout(): Promise<void>;
  listLectures(): Promise<LectureSummary[]>;
  getLecture(id: string): Promise<LectureDetail>;
  getSource(lectureId: string, bulletId: string): Promise<SourceView>;
  listSuggestions(bulletId: string): Promise<Suggestion[]>;
  createSuggestion(body: SuggestionCreate): Promise<Suggestion>;
  /** Set my vote on a suggestion (`on` = add, false = remove). With `on` omitted the mock toggles it. */
  vote(suggestionId: string, on?: boolean): Promise<VoteResult>;
  listReview(lectureId?: string): Promise<ReviewItem[]>;
  decide(itemId: string, body: ReviewDecisionIn): Promise<void>;
  /** Confirm the uncertain readings of one section. Student fixes are left for the lecturer to decide. */
  verifySection(lectureId: string, sectionId: string): Promise<VerifyResult>;
  /** Confirm the uncertain readings of the whole lecture. */
  verifyLecture(lectureId: string): Promise<VerifyResult>;
  ask(lectureId: string, question: string, history?: AskTurn[]): Promise<AskOut>;
  listPdfs(): Promise<PdfInfo[]>;
  /** Link to the LaTeX source, or null when the server does not offer one. */
  texUrl(lectureId: string | null): string | null;
  startUpload(init: UploadInit): Promise<UploadSession>;
  getUpload(uploadId: string): Promise<UploadSession>;
  putChunk(uploadId: string, offset: number, chunk: Blob, totalBytes: number): Promise<UploadSession>;
  completeUpload(uploadId: string): Promise<LectureSummary>;
  subscribeProgress(lectureId: string, onEvent: (p: JobProgress) => void, onError?: (e: Event) => void): Unsubscribe;
}

// ---------------------------------------------------------------- HTTP

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof Blob) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${API_URL}${path}`, { ...init, headers, credentials: "include" });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body: unknown = await res.json();
      if (body && typeof body === "object" && "detail" in body) message = String(body.detail);
    } catch {
      /* no JSON body */
    }
    throw new ApiError(res.status, message);
  }
  return res;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await send(path, init);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface SseEvent {
  event: string;
  data: string;
}

/** Parse a complete text/event-stream body into events (unnamed events are called "message"). */
export function parseSse(body: string): SseEvent[] {
  const out: SseEvent[] = [];
  for (const block of body.replace(/\r\n?/g, "\n").split(/\n\n+/)) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const i = line.indexOf(":");
      const field = i < 0 ? line : line.slice(0, i);
      const value = i < 0 ? "" : line.slice(i + 1).replace(/^ /, "");
      if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (data.length) out.push({ event, data: data.join("\n") });
  }
  return out;
}

/** The ask route streams SSE ("answer", "error", "done"); a plain JSON reply is accepted too. */
export async function readAskResponse(res: Response): Promise<AskOut> {
  if (!(res.headers.get("Content-Type") ?? "").includes("text/event-stream")) return (await res.json()) as AskOut;
  for (const e of parseSse(await res.text())) {
    if (e.event === "answer") return JSON.parse(e.data) as AskOut;
    if (e.event === "error") throw new ApiError(502, e.data || "The question could not be answered");
  }
  throw new ApiError(502, "The question could not be answered");
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export interface SseOptions<T> {
  /** Named SSE event to listen for, besides unnamed messages. */
  event?: string;
  /** True for the last message: the source is closed so it does not reconnect. */
  isFinal?: (data: T) => boolean;
  /** Called when the stream fails for good (not on the automatic reconnects EventSource makes). */
  onError?: (e: Event) => void;
}

/** Subscribe to a server-sent event stream of JSON messages. Returns a function that closes it. */
export function subscribeSse<T>(url: string, onMessage: (data: T) => void, opts: SseOptions<T> = {}): Unsubscribe {
  const source = new EventSource(url, { withCredentials: true });
  let finished = false;
  const handle = (e: MessageEvent<string>) => {
    if (finished) return;
    let data: T;
    try {
      data = JSON.parse(e.data) as T;
    } catch {
      return; // ignore malformed messages
    }
    if (opts.isFinal?.(data)) {
      finished = true;
      source.close();
    }
    onMessage(data);
  };
  source.onmessage = handle;
  if (opts.event) source.addEventListener(opts.event, handle as EventListener);
  source.onerror = (e) => {
    // While CONNECTING, EventSource is retrying by itself (for example after the server ends a long stream).
    if (finished || source.readyState !== EventSource.CLOSED) return;
    opts.onError?.(e);
  };
  return () => {
    finished = true;
    source.close();
  };
}

/** A job has stopped changing once it is done or has failed. */
export const jobFinished = (p: JobProgress): boolean => p.stage === "done" || p.error != null;

/**
 * Approve a section or lecture through the review queue: every uncertain reading ("bullet:<id>" item) in it is
 * confirmed. Student fixes are not decided here; they are counted as waiting. Keeps going past failures.
 */
export async function verifyByReview(client: BoardNotesApi, lectureId: string, sectionId: string | null): Promise<VerifyResult> {
  const items = (await client.listReview(lectureId)).filter((i) => sectionId === null || i.section_id === sectionId);
  const result: VerifyResult = { approved: 0, waiting: 0, failed: 0 };
  for (const item of items) {
    if (item.suggestion) {
      result.waiting += 1;
      continue;
    }
    try {
      await client.decide(item.id, { decision: "approve" });
      result.approved += 1;
    } catch {
      result.failed += 1;
    }
  }
  return result;
}

export const httpApi: BoardNotesApi = {
  mode: "live",
  async me() {
    try {
      return await request<Me>(paths.me);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return null;
      throw e;
    }
  },
  login: (userId) => request<Me>(paths.login, json({ user_id: userId })),
  logout: () => request<void>(paths.logout, { method: "POST" }),
  listLectures: () => request<LectureSummary[]>(paths.lectures),
  getLecture: (id) => request<LectureDetail>(paths.lecture(id)),
  getSource: (_lectureId, bulletId) => request<SourceView>(paths.source(bulletId)),
  listSuggestions: (bulletId) => request<Suggestion[]>(paths.suggestionsFor(bulletId)),
  createSuggestion: (body) => request<Suggestion>(paths.suggestions, json(body)),
  vote: (suggestionId, on = true) => request<VoteResult>(paths.vote(suggestionId), { method: on ? "POST" : "DELETE" }),
  listReview: (lectureId) =>
    request<ReviewItem[]>(lectureId ? `${paths.review}?lecture_id=${enc(lectureId)}` : paths.review),
  decide: (itemId, body) => request<void>(paths.decision(itemId), json(body)),
  verifySection: (lectureId, sectionId) => verifyByReview(httpApi, lectureId, sectionId),
  verifyLecture: (lectureId) => verifyByReview(httpApi, lectureId, null),
  ask: async (lectureId, question, history = []) => readAskResponse(await send(paths.ask(lectureId), json({ question, history }))),
  listPdfs: () => request<PdfInfo[]>(paths.pdfs),
  texUrl: () => null, // no .tex route on the server yet
  startUpload: (init) => request<UploadSession>(paths.uploads, json(init)),
  getUpload: (uploadId) => request<UploadSession>(paths.upload(uploadId)),
  putChunk: (uploadId, offset, chunk, totalBytes) =>
    request<UploadSession>(paths.upload(uploadId), {
      method: "PUT",
      body: chunk,
      headers: {
        "Content-Type": "application/octet-stream",
        "Content-Range": `bytes ${offset}-${offset + chunk.size - 1}/${totalBytes}`,
      },
    }),
  async completeUpload(uploadId) {
    // The server answers with the job's first progress; the pages need the lecture it created.
    const job = await request<JobProgress>(paths.uploadComplete(uploadId), { method: "POST" });
    const lectures = await request<LectureSummary[]>(paths.lectures).catch((): LectureSummary[] => []);
    return (
      lectures.find((l) => l.id === job.lecture_id) ?? {
        id: job.lecture_id,
        title: "",
        status: "processing",
        progress: job.progress,
        duration_s: null,
        section_count: 0,
        open_items: 0,
        uploaded_at: new Date().toISOString(),
      }
    );
  },
  subscribeProgress: (lectureId, onEvent, onError) =>
    subscribeSse<JobProgress>(`${API_URL}${paths.progress(lectureId)}`, onEvent, { event: "progress", isFinal: jobFinished, onError }),
};

/**
 * Absolute URL for a server-relative asset (video, snapshot, PDF). Absolute http(s) URLs (for example signed
 * storage links) are kept; every other scheme (javascript:, data:, ...) and protocol-relative URLs are dropped.
 */
export function assetUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (url.startsWith("#") || url.startsWith("blob:") || /^https?:\/\//i.test(url)) return url;
  // Backslashes are never needed and browsers treat "/\\host" like "//host": reject them anywhere.
  if (/^[a-z][a-z0-9+.-]*:/i.test(url) || url.startsWith("//") || url.includes("\\")) return null;
  return `${API_URL}${url.startsWith("/") ? "" : "/"}${url}`;
}

// ---------------------------------------------------------------- Resumable upload

const RESUME_KEY = (file: File) => `bn.upload:${file.name}:${file.size}:${file.lastModified}`;

function readResume(file: File): string | null {
  try {
    return localStorage.getItem(RESUME_KEY(file));
  } catch {
    return null;
  }
}

function writeResume(file: File, uploadId: string | null): void {
  try {
    if (uploadId) localStorage.setItem(RESUME_KEY(file), uploadId);
    else localStorage.removeItem(RESUME_KEY(file));
  } catch {
    /* storage unavailable: the upload just won't resume after a reload */
  }
}

/**
 * Upload a file in chunks. If the same file was partly uploaded before (same name, size and modified time),
 * it resumes from the byte the server already has.
 */
export async function uploadFile(
  client: BoardNotesApi,
  file: File,
  title: string,
  onProgress: (p: UploadProgress) => void,
  signal?: AbortSignal,
): Promise<LectureSummary> {
  const previous = readResume(file);
  if (previous) {
    let resumed: UploadSession | null = null;
    try {
      resumed = await client.getUpload(previous);
    } catch {
      writeResume(file, null);
    }
    if (resumed) {
      try {
        return await sendFrom(client, file, resumed, onProgress, signal);
      } catch (e) {
        // The stored session is gone or already finished (for example `complete` worked but its reply was lost):
        // forget it and upload again as a new session.
        if (!(e instanceof ApiError && (e.status === 404 || e.status === 409))) throw e;
        writeResume(file, null);
      }
    }
  }
  const session = await client.startUpload({ filename: file.name, size_bytes: file.size, title });
  writeResume(file, session.upload_id);
  return sendFrom(client, file, session, onProgress, signal);
}

async function sendFrom(
  client: BoardNotesApi,
  file: File,
  start: UploadSession,
  onProgress: (p: UploadProgress) => void,
  signal?: AbortSignal,
): Promise<LectureSummary> {
  let session = start;
  let offset = session.received_bytes;
  onProgress({ sentBytes: offset, totalBytes: file.size });
  let stalled = 0;
  while (offset < file.size) {
    if (signal?.aborted) throw new DOMException("Upload paused", "AbortError");
    const chunk = file.slice(offset, Math.min(file.size, offset + session.chunk_size));
    session = await client.putChunk(session.upload_id, offset, chunk, file.size);
    // Guard against a server that stops accepting data: give up instead of looping forever.
    stalled = session.received_bytes > offset ? 0 : stalled + 1;
    if (stalled >= 3) throw new Error("The upload stopped making progress. Check your connection and try again.");
    offset = session.received_bytes;
    onProgress({ sentBytes: offset, totalBytes: file.size });
  }
  const lecture = await client.completeUpload(session.upload_id);
  writeResume(file, null);
  return lecture;
}
