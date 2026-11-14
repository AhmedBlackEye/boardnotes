/** In-memory implementation of BoardNotesApi so every page works without the server (NEXT_PUBLIC_API_MODE=mock). */
import { ApiError, type BoardNotesApi, type Unsubscribe } from "@/lib/api";
import type { AskOut } from "@/contracts/AskOut";
import type { JobProgress, JobStage } from "@/contracts/JobProgress";
import type { LectureDetail } from "@/contracts/LectureDetail";
import type { LectureSummary } from "@/contracts/LectureSummary";
import type { ReviewItem } from "@/contracts/ReviewItem";
import type { Suggestion } from "@/contracts/Suggestion";
import type { UploadSession } from "@/contracts/UploadSession";
import { DETAILS, LECTURES, PDFS, QUOTES, REVIEW_SEED, SUGGESTIONS, USERS } from "@/mocks/data";

const USER_KEY = "bn.mock.user";
const delay = <T>(value: T, ms = 120): Promise<T> => new Promise((r) => setTimeout(() => r(structuredClone(value)), ms));

const state = {
  lectures: structuredClone(LECTURES),
  details: structuredClone(DETAILS),
  suggestions: structuredClone(SUGGESTIONS),
  review: structuredClone(REVIEW_SEED),
  uploads: new Map<string, { size: number; received: number; title: string }>(),
  /** Overall progress (0..1) per processing lecture. */
  jobs: new Map<string, number>([["lec_24", 0.64]]),
  me: null as string | null,
};

function storedUser(): string | null {
  try {
    return localStorage.getItem(USER_KEY);
  } catch {
    return state.me;
  }
}

function lecture(id: string): LectureDetail {
  const d = state.details[id];
  if (!d) throw new ApiError(404, "Lecture not found");
  return d;
}

function bulletLocation(bulletId: string) {
  for (const d of Object.values(state.details)) {
    for (const s of d.sections) {
      const b = s.bullets.find((x) => x.id === bulletId);
      if (b) return { detail: d, section: s, bullet: b };
    }
  }
  return null;
}

function refreshCounts(detail: LectureDetail) {
  const open = state.suggestions.filter(
    (s) => s.status === "open" && detail.sections.some((sec) => sec.bullets.some((b) => b.id === s.bullet_id)),
  ).length;
  for (const sec of detail.sections) {
    for (const b of sec.bullets) b.open_suggestions = state.suggestions.filter((s) => s.bullet_id === b.id && s.status === "open").length;
  }
  detail.summary.open_items = open + detail.sections.filter((s) => s.status === "uncertain").length;
  const l = state.lectures.find((x) => x.id === detail.summary.id);
  if (l) l.open_items = detail.summary.open_items;
}

function suggestionItems(): ReviewItem[] {
  const out: ReviewItem[] = [];
  for (const s of state.suggestions) {
    if (s.status !== "open") continue;
    const loc = bulletLocation(s.bullet_id);
    if (!loc) continue;
    const block = loc.detail.board_blocks.find((b) => loc.bullet.board_block_ids.includes(b.id)) ?? null;
    out.push({
      id: `ri_${s.id}`,
      lecture_id: loc.detail.summary.id,
      section_id: loc.section.id,
      section_heading: `${loc.section.order} · ${loc.section.heading}`,
      bullet_id: loc.bullet.id,
      current_text: loc.bullet.text,
      board_block: block,
      snapshot_url: null,
      suggestion: s,
      priority: 2 * (1 - loc.bullet.confidence) + Math.log2(1 + s.upvotes) + (s.verdict === "agrees" ? 1 : 0) - (s.flagged ? 2 : 0),
    });
  }
  return out;
}

function checkFix(text: string): Pick<Suggestion, "verdict" | "verdict_reason" | "flagged"> {
  if (/ignore|instruction|system prompt|disregard/i.test(text)) {
    return { verdict: "unclear", verdict_reason: "Reads like instructions, not a correction of the notes.", flagged: true };
  }
  return { verdict: "agrees", verdict_reason: "The board and the recording are consistent with this wording.", flagged: false };
}

function answerFor(lectureId: string, question: string): AskOut {
  const d = lecture(lectureId);
  const q = question.toLowerCase();
  if (/non-square|rectangular|not covered|weather|football/.test(q)) {
    return {
      covered: false,
      answer: "This lecture only covers square matrices, so I can't answer that from it. Try asking your lecturer.",
      citations: [],
    };
  }
  const sec = d.sections.find((s) => /trace/.test(q) && /trace/i.test(s.heading)) ?? d.sections.find((s) => /2x2|example/.test(q) && /example/i.test(s.heading)) ?? d.sections[Math.min(2, d.sections.length - 1)]!;
  const b = sec.bullets[0]!;
  return {
    covered: true,
    answer:
      /det|why/.test(q) && lectureId === "lec_21"
        ? "We want a non-zero x with (A − λI)x = 0. That only happens when A − λI has no inverse, which is exactly when its determinant is zero."
        : `${b.text} (See section ${sec.order}, “${sec.heading}”.)`,
    citations: [
      { kind: "transcript", ref: `${b.transcript_ranges[0]?.start_s ?? 0}`, at_s: b.transcript_ranges[0]?.start_s ?? null },
      ...(b.board_block_ids[0] ? [{ kind: "board" as const, ref: b.board_block_ids[0], at_s: null }] : []),
    ],
  };
}

// ---------------------------------------------------------------- Processing simulation

const STAGES: { stage: JobStage; upTo: number; detail: string }[] = [
  { stage: "check_video", upTo: 0.1, detail: "1080p · picture and sound found · 1 h 55 min" },
  { stage: "transcribe", upTo: 0.3, detail: "Transcript ready · lecturer and 2 students" },
  { stage: "select_frames", upTo: 0.45, detail: "Choosing the clearest board frames" },
  { stage: "read_board", upTo: 0.65, detail: "Board 9 of 14 · matching writing across camera moves" },
  { stage: "merge_blocks", upTo: 0.72, detail: "Merging repeated board readings" },
  { stage: "section", upTo: 0.78, detail: "Splitting the lecture into sections" },
  { stage: "write_notes", upTo: 0.95, detail: "Writing notes with sources" },
  { stage: "render_pdf", upTo: 0.99, detail: "Rendering the PDF" },
];

function jobEvent(lectureId: string, progress: number): JobProgress {
  const d = state.details[lectureId];
  const total = d?.sections.length ?? 0;
  const step = STAGES.find((s) => progress < s.upTo);
  const sectionsReady = progress < 0.78 ? 0 : Math.min(total, Math.round(((progress - 0.78) / 0.2) * total));
  return {
    lecture_id: lectureId,
    stage: step?.stage ?? "done",
    progress: Math.min(1, progress),
    detail: step?.detail ?? "Ready for review",
    sections_ready: progress >= 1 ? total : sectionsReady,
    error: null,
  };
}

// ---------------------------------------------------------------- The API

export const mockApi: BoardNotesApi = {
  mode: "mock",
  async me() {
    const id = storedUser();
    return delay(id ? (USERS[id] ?? null) : null, 20);
  },
  async login(userId) {
    const u = USERS[userId];
    if (!u) throw new ApiError(404, "Unknown demo user");
    state.me = userId;
    try {
      localStorage.setItem(USER_KEY, userId);
    } catch {
      /* private mode: stays in memory only */
    }
    return delay(u, 20);
  },
  async logout() {
    state.me = null;
    try {
      localStorage.removeItem(USER_KEY);
    } catch {
      /* ignore */
    }
  },
  listLectures: () => delay(state.lectures),
  async getLecture(id) {
    const d = lecture(id);
    const summary = state.lectures.find((l) => l.id === id);
    if (summary) d.summary = summary;
    refreshCounts(d);
    return delay(d);
  },
  async getSource(lectureId, bulletId) {
    const loc = bulletLocation(bulletId);
    if (!loc) throw new ApiError(404, "Bullet not found");
    const quote = QUOTES[bulletId] ?? loc.bullet.text;
    const range = loc.bullet.transcript_ranges[0] ?? { start_s: 0, end_s: 0 };
    void lectureId;
    return delay({
      bullet_id: bulletId,
      snapshot_urls: [],
      board_blocks: loc.detail.board_blocks.filter((b) => loc.bullet.board_block_ids.includes(b.id)),
      transcript: [{ start_s: range.start_s, end_s: range.end_s, speaker: "lecturer", text: quote }],
    });
  },
  listSuggestions: (bulletId) =>
    delay(state.suggestions.filter((s) => s.bullet_id === bulletId).sort((a, b) => b.upvotes - a.upvotes)),
  async createSuggestion(body) {
    const me = USERS[storedUser() ?? "u_sam"] ?? USERS.u_sam!;
    const s: Suggestion = {
      id: `sg_${Date.now()}`,
      bullet_id: body.bullet_id,
      author_name: me.name,
      author_initials: me.initials,
      anonymous: false,
      proposed_text: body.proposed_text,
      status: "open",
      upvotes: 0,
      voted_by_me: false,
      created_at: new Date().toISOString(),
      ...checkFix(body.proposed_text),
    };
    state.suggestions.push(s);
    const loc = bulletLocation(body.bullet_id);
    if (loc) refreshCounts(loc.detail);
    return delay(s, 500);
  },
  async vote(suggestionId) {
    const s = state.suggestions.find((x) => x.id === suggestionId);
    if (!s) throw new ApiError(404, "Suggestion not found");
    s.voted_by_me = !s.voted_by_me;
    s.upvotes += s.voted_by_me ? 1 : -1;
    return delay({ suggestion_id: s.id, upvotes: s.upvotes, voted_by_me: s.voted_by_me }, 40);
  },
  async listReview(lectureId) {
    const items = [...state.review, ...suggestionItems()].filter((i) => !lectureId || i.lecture_id === lectureId);
    return delay(items.sort((a, b) => b.priority - a.priority));
  },
  async decide(itemId, body) {
    const dynamic = suggestionItems().find((i) => i.id === itemId);
    const item = dynamic ?? state.review.find((i) => i.id === itemId);
    if (!item) throw new ApiError(404, "Review item not found");
    const loc = bulletLocation(item.bullet_id);
    if (loc && body.decision !== "reject") {
      const text = body.decision === "edit" ? (body.edited_text ?? item.current_text) : (item.suggestion?.proposed_text ?? item.current_text);
      loc.bullet.text = text;
      loc.bullet.latex = null;
      loc.bullet.uncertain = false;
      loc.bullet.confidence = 1;
      if (loc.section.bullets.every((b) => !b.uncertain)) loc.section.status = "verified";
    }
    if (dynamic && item.suggestion) {
      const s = state.suggestions.find((x) => x.id === item.suggestion?.id);
      if (s) s.status = body.decision === "reject" ? "rejected" : "approved";
    } else {
      state.review = state.review.filter((i) => i.id !== itemId);
    }
    if (loc) refreshCounts(loc.detail);
    return delay(undefined, 80);
  },
  async verifySection(sectionId) {
    for (const d of Object.values(state.details)) {
      const s = d.sections.find((x) => x.id === sectionId);
      if (s) {
        s.status = "verified";
        refreshCounts(d);
      }
    }
    return delay(undefined, 60);
  },
  async verifyLecture(lectureId) {
    const d = lecture(lectureId);
    for (const s of d.sections) s.status = "verified";
    d.summary.status = "verified";
    const l = state.lectures.find((x) => x.id === lectureId);
    if (l) l.status = "verified";
    return delay(undefined, 60);
  },
  ask: (lectureId, question) => delay(answerFor(lectureId, question), 700),
  listPdfs: () => delay(PDFS),
  texUrl: () => "/mock/notes.tex",
  async startUpload(init) {
    const id = `up_${Date.now()}`;
    state.uploads.set(id, { size: init.size_bytes, received: 0, title: init.title });
    return delay<UploadSession>({ upload_id: id, received_bytes: 0, chunk_size: 8 * 1024 * 1024 }, 40);
  },
  async getUpload(uploadId) {
    const u = state.uploads.get(uploadId);
    if (!u) throw new ApiError(404, "Upload not found");
    return delay({ upload_id: uploadId, received_bytes: u.received, chunk_size: 8 * 1024 * 1024 }, 20);
  },
  async putChunk(uploadId, offset, chunk) {
    const u = state.uploads.get(uploadId);
    if (!u) throw new ApiError(404, "Upload not found");
    u.received = offset + chunk.size;
    return delay({ upload_id: uploadId, received_bytes: u.received, chunk_size: 8 * 1024 * 1024 }, 250);
  },
  async completeUpload(uploadId) {
    const u = state.uploads.get(uploadId);
    if (!u) throw new ApiError(404, "Upload not found");
    const summary: LectureSummary = {
      id: `lec_${uploadId.slice(3)}`,
      title: u.title,
      status: "processing",
      progress: 0.02,
      duration_s: null,
      section_count: 0,
      open_items: 0,
      uploaded_at: new Date().toISOString(),
    };
    state.lectures.unshift(summary);
    state.details[summary.id] = { summary, video_url: "", pdf_url: null, board_blocks: [], sections: structuredClone(DETAILS.lec_24!.sections) };
    state.jobs.set(summary.id, 0.02);
    return delay(summary, 100);
  },
  subscribeProgress(lectureId, onEvent): Unsubscribe {
    const start = state.jobs.get(lectureId);
    const emit = (p: number) => onEvent(jobEvent(lectureId, p));
    if (start === undefined) {
      const d = state.details[lectureId];
      if (d) onEvent({ ...jobEvent(lectureId, 1), sections_ready: d.sections.length });
      return () => undefined;
    }
    emit(start);
    const timer = setInterval(() => {
      const next = Math.min(1, (state.jobs.get(lectureId) ?? 0) + 0.04);
      state.jobs.set(lectureId, next);
      const l = state.lectures.find((x) => x.id === lectureId);
      if (l) l.progress = next;
      if (next >= 1) {
        clearInterval(timer);
        state.jobs.delete(lectureId);
        if (l) {
          l.status = "draft";
          l.progress = null;
          l.section_count = state.details[lectureId]?.sections.length ?? 0;
        }
        const d = state.details[lectureId];
        if (d) {
          d.summary = { ...d.summary, status: "draft", progress: null, section_count: d.sections.length };
          d.pdf_url = "/mock/notes.pdf";
        }
      }
      emit(next);
    }, 1500);
    return () => clearInterval(timer);
  },
};
