/**
 * Typed client for the BoardNotes API.
 *
 * - Types come from the generated contracts (web/src/contracts), never hand-written copies.
 * - Base URL: NEXT_PUBLIC_API_URL. Cookies are sent with every request (demo session cookie).
 * - Mock mode (NEXT_PUBLIC_API_MODE=mock, or no API URL set) serves in-memory data from src/mocks,
 *   so every page works without the server.
 */
import type { AskOut } from "@/contracts/AskOut";
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

/** Every route the web app calls, in one place so it is easy to line up with the server. */
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
  vote(suggestionId: string): Promise<VoteResult>;
  listReview(lectureId?: string): Promise<ReviewItem[]>;
  decide(itemId: string, body: ReviewDecisionIn): Promise<void>;
  verifySection(sectionId: string): Promise<void>;
  verifyLecture(lectureId: string): Promise<void>;
  ask(lectureId: string, question: string): Promise<AskOut>;
  listPdfs(): Promise<PdfInfo[]>;
  texUrl(lectureId: string | null): string;
  startUpload(init: UploadInit): Promise<UploadSession>;
  getUpload(uploadId: string): Promise<UploadSession>;
  putChunk(uploadId: string, offset: number, chunk: Blob, totalBytes: number): Promise<UploadSession>;
  completeUpload(uploadId: string): Promise<LectureSummary>;
  subscribeProgress(lectureId: string, onEvent: (p: JobProgress) => void, onError?: (e: Event) => void): Unsubscribe;
}

// ---------------------------------------------------------------- HTTP

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
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
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

/** Subscribe to a server-sent event stream of JSON messages. Returns a function that closes it. */
export function subscribeSse<T>(url: string, onMessage: (data: T) => void, onError?: (e: Event) => void): Unsubscribe {
  const source = new EventSource(url, { withCredentials: true });
  source.onmessage = (e: MessageEvent<string>) => {
    try {
      onMessage(JSON.parse(e.data) as T);
    } catch {
      /* ignore malformed messages */
    }
  };
  if (onError) source.onerror = onError;
  return () => source.close();
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
  vote: (suggestionId) => request<VoteResult>(paths.vote(suggestionId), { method: "POST" }),
  listReview: (lectureId) =>
    request<ReviewItem[]>(lectureId ? `${paths.review}?lecture_id=${enc(lectureId)}` : paths.review),
  decide: (itemId, body) => request<void>(paths.decision(itemId), json(body)),
  verifySection: (sectionId) => request<void>(paths.verifySection(sectionId), { method: "POST" }),
  verifyLecture: (lectureId) => request<void>(paths.verifyLecture(lectureId), { method: "POST" }),
  ask: (lectureId, question) => request<AskOut>(paths.ask(lectureId), json({ question })),
  listPdfs: () => request<PdfInfo[]>(paths.pdfs),
  texUrl: (lectureId) => `${API_URL}${paths.tex(lectureId)}`,
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
  completeUpload: (uploadId) => request<LectureSummary>(paths.uploadComplete(uploadId), { method: "POST" }),
  subscribeProgress: (lectureId, onEvent, onError) =>
    subscribeSse<JobProgress>(`${API_URL}${paths.progress(lectureId)}`, onEvent, onError),
};

/** Absolute URL for a server-relative asset (video, snapshot, PDF). Leaves absolute URLs alone. */
export function assetUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (/^(https?:|blob:|data:)/.test(url) || url.startsWith("#")) return url;
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
  let session: UploadSession | null = null;
  const previous = readResume(file);
  if (previous) {
    try {
      session = await client.getUpload(previous);
    } catch {
      session = null;
    }
  }
  if (!session) {
    session = await client.startUpload({ filename: file.name, size_bytes: file.size, title });
    writeResume(file, session.upload_id);
  }
  let offset = session.received_bytes;
  onProgress({ sentBytes: offset, totalBytes: file.size });
  while (offset < file.size) {
    if (signal?.aborted) throw new DOMException("Upload paused", "AbortError");
    const chunk = file.slice(offset, Math.min(file.size, offset + session.chunk_size));
    session = await client.putChunk(session.upload_id, offset, chunk, file.size);
    offset = session.received_bytes;
    onProgress({ sentBytes: offset, totalBytes: file.size });
  }
  const lecture = await client.completeUpload(session.upload_id);
  writeResume(file, null);
  return lecture;
}
