/** Tests for the V1/V3 review fixes: live routes, SSE handling, resumable upload recovery, approve flows. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { errorText, verifyMessage } from "@/components/notes/helpers";
import type { ReviewItem } from "@/contracts/ReviewItem";
import { ApiError, assetUrl, httpApi, jobFinished, parseSse, subscribeSse, uploadFile, verifyByReview, type BoardNotesApi } from "@/lib/api";
import { approveEach } from "@/lib/batch";
import { stepState } from "@/lib/steps";
import { mockApi } from "@/mocks/api";
import { DETAILS, REVIEW_SEED } from "@/mocks/data";

const calls: { url: string; init: RequestInit }[] = [];
function stubFetch(responder: (url: string, init: RequestInit) => Response) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return responder(url, init);
    }),
  );
}
const ok = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const sse = (body: string) => new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream; charset=utf-8" } });

beforeEach(() => {
  calls.length = 0;
  localStorage.clear();
});
afterEach(() => vi.unstubAllGlobals());

describe("server-sent events", () => {
  it("parses named events, multi-line data, comments and CRLF", () => {
    const events = parseSse(': ping\r\n\r\nevent: answer\r\ndata: {"a":\r\ndata: 1}\r\n\r\nevent: done\ndata: {}\n\n');
    expect(events).toEqual([
      { event: "answer", data: '{"a":\n1}' },
      { event: "done", data: "{}" },
    ]);
    expect(parseSse("data: x\n\n")).toEqual([{ event: "message", data: "x" }]);
  });

  it("ask reads the streamed answer event", async () => {
    const out = { covered: true, answer: "Because det = 0", citations: [] };
    stubFetch(() => sse(`event: answer\ndata: ${JSON.stringify(out)}\n\nevent: done\ndata: {}\n\n`));
    await expect(httpApi.ask("lec_1", "why?")).resolves.toEqual(out);
  });

  it("ask turns an error event into an ApiError", async () => {
    stubFetch(() => sse("event: error\ndata: The question could not be answered\n\n"));
    await expect(httpApi.ask("lec_1", "why?")).rejects.toMatchObject({ name: "ApiError", message: "The question could not be answered" });
  });

  it("ask surfaces rate limits from the server", async () => {
    stubFetch(() => new Response(JSON.stringify({ detail: "Please wait" }), { status: 429 }));
    await expect(httpApi.ask("lec_1", "why?")).rejects.toMatchObject({ status: 429, message: "Please wait" });
  });
});

class FakeEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static last: FakeEventSource;
  readyState = FakeEventSource.OPEN;
  onmessage: ((e: MessageEvent<string>) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  listeners = new Map<string, (e: MessageEvent<string>) => void>();
  closed = false;
  constructor(readonly url: string) {
    FakeEventSource.last = this;
  }
  addEventListener(name: string, fn: (e: MessageEvent<string>) => void) {
    this.listeners.set(name, fn);
  }
  close() {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }
  emit(name: string, data: unknown) {
    const e = { data: JSON.stringify(data) } as MessageEvent<string>;
    if (name === "message") this.onmessage?.(e);
    else this.listeners.get(name)?.(e);
  }
  fail(state: number) {
    this.readyState = state;
    this.onerror?.(new Event("error"));
  }
}

describe("progress stream", () => {
  const job = (stage: string, error: string | null = null) => ({ lecture_id: "l", stage, progress: 0.5, detail: "", sections_ready: 0, error });

  it("receives the named progress event and closes once the job is done", () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const seen: string[] = [];
    const onError = vi.fn();
    httpApi.subscribeProgress("lec_1", (p) => seen.push(p.stage), onError);
    const es = FakeEventSource.last;
    expect(es.url).toBe("/lectures/lec_1/progress");
    es.emit("progress", job("transcribe"));
    expect(es.closed).toBe(false);
    es.emit("progress", job("done"));
    expect(seen).toEqual(["transcribe", "done"]);
    expect(es.closed).toBe(true);
    es.fail(FakeEventSource.CLOSED); // the server ending the stream must not show "lost connection"
    expect(onError).not.toHaveBeenCalled();
  });

  it("ignores automatic reconnects but reports a stream that fails for good", () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const onError = vi.fn();
    subscribeSse("/x", () => undefined, { onError });
    FakeEventSource.last.fail(FakeEventSource.CONNECTING);
    expect(onError).not.toHaveBeenCalled();
    FakeEventSource.last.fail(FakeEventSource.CLOSED);
    expect(onError).toHaveBeenCalledOnce();
  });

  it("a failed job also ends the stream", () => {
    expect(jobFinished(job("read_board", "Video unreadable") as never)).toBe(true);
    expect(jobFinished(job("read_board") as never)).toBe(false);
  });
});

describe("live routes match the server", () => {
  it("votes with POST and removes a vote with DELETE", async () => {
    stubFetch(() => ok({ suggestion_id: "s", upvotes: 1, voted_by_me: true }));
    await httpApi.vote("s", true);
    await httpApi.vote("s", false);
    expect(calls.map((c) => [c.url, c.init.method])).toEqual([
      ["/suggestions/s/vote", "POST"],
      ["/suggestions/s/vote", "DELETE"],
    ]);
  });

  it("completeUpload maps the server's JobProgress to the new lecture", async () => {
    const lecture = { id: "lec_9", title: "L9", status: "processing" };
    stubFetch((url) => (url.endsWith("/complete") ? ok({ lecture_id: "lec_9", stage: "check_video", progress: 0, detail: "", sections_ready: 0, error: null }) : ok([lecture])));
    await expect(httpApi.completeUpload("u1")).resolves.toEqual(lecture);
    expect(calls[0]!.init.method).toBe("POST");
  });

  it("completeUpload still returns the lecture id if the list fails", async () => {
    stubFetch((url) => (url.endsWith("/complete") ? ok({ lecture_id: "lec_9", stage: "check_video", progress: 0, detail: "", sections_ready: 0, error: null }) : new Response("", { status: 500 })));
    await expect(httpApi.completeUpload("u1")).resolves.toMatchObject({ id: "lec_9", status: "processing" });
  });

  it("has no .tex link in live mode (no server route)", () => {
    expect(httpApi.texUrl("lec_1")).toBeNull();
  });
});

describe("assetUrl drops unsafe schemes", () => {
  it.each(["javascript:alert(1)", "data:text/html,x", "//evil.example/x", "JAVASCRIPT:alert(1)"])("%s", (u) => {
    expect(assetUrl(u)).toBeNull();
  });
  it("keeps blob: and http(s)", () => {
    expect(assetUrl("blob:http://localhost/1")).toBe("blob:http://localhost/1");
    expect(assetUrl("http://localhost:8000/a.pdf")).toBe("http://localhost:8000/a.pdf");
  });
});

describe("resumable upload recovery", () => {
  const file = () => new File(["0123456789"], "v.mp4", { lastModified: 1 });
  const key = (f: File) => `bn.upload:${f.name}:${f.size}:${f.lastModified}`;

  it("starts again when the stored session was already completed (409)", async () => {
    const f = file();
    localStorage.setItem(key(f), "old");
    const client = {
      getUpload: vi.fn(async (id: string) => ({ upload_id: id, received_bytes: 10, chunk_size: 4 })),
      startUpload: vi.fn(async () => ({ upload_id: "new", received_bytes: 0, chunk_size: 4 })),
      putChunk: vi.fn(async (id: string, offset: number, chunk: Blob) => ({ upload_id: id, received_bytes: offset + chunk.size, chunk_size: 4 })),
      completeUpload: vi.fn(async (id: string) => {
        if (id === "old") throw new ApiError(409, "This upload is already finished");
        return { id: "lec_new" };
      }),
    } as unknown as BoardNotesApi;
    await expect(uploadFile(client, f, "T", () => undefined)).resolves.toEqual({ id: "lec_new" });
    expect(client.startUpload).toHaveBeenCalledOnce();
    expect(localStorage.getItem(key(f))).toBeNull();
  });

  it("forgets an unknown stored session", async () => {
    const f = file();
    localStorage.setItem(key(f), "gone");
    const client = {
      getUpload: vi.fn(async () => {
        throw new ApiError(404, "gone");
      }),
      startUpload: vi.fn(async () => {
        throw new ApiError(500, "down");
      }),
    } as unknown as BoardNotesApi;
    await expect(uploadFile(client, f, "T", () => undefined)).rejects.toMatchObject({ status: 500 });
    expect(localStorage.getItem(key(f))).toBeNull();
  });

  it("other errors keep the resume key so the upload can resume later", async () => {
    const f = file();
    localStorage.setItem(key(f), "old");
    const client = {
      getUpload: vi.fn(async (id: string) => ({ upload_id: id, received_bytes: 4, chunk_size: 4 })),
      putChunk: vi.fn(async () => {
        throw new ApiError(503, "busy");
      }),
      startUpload: vi.fn(),
    } as unknown as BoardNotesApi;
    await expect(uploadFile(client, f, "T", () => undefined)).rejects.toMatchObject({ status: 503 });
    expect(client.startUpload).not.toHaveBeenCalled();
    expect(localStorage.getItem(key(f))).toBe("old");
  });
});

describe("approve section / lecture through the review queue", () => {
  const item = (id: string, section: string, suggestion: boolean): ReviewItem =>
    ({ id, section_id: section, suggestion: suggestion ? { id } : null }) as unknown as ReviewItem;

  it("confirms uncertain readings, leaves student fixes waiting and keeps going past failures", async () => {
    const decided: string[] = [];
    const client = {
      listReview: vi.fn(async () => [item("bullet:a", "s1", false), item("sg_1", "s1", true), item("bullet:b", "s1", false), item("bullet:c", "s2", false)]),
      decide: vi.fn(async (id: string) => {
        if (id === "bullet:a") throw new ApiError(409, "already decided");
        decided.push(id);
      }),
    } as unknown as BoardNotesApi;
    await expect(verifyByReview(client, "lec", "s1")).resolves.toEqual({ approved: 1, waiting: 1, failed: 1 });
    expect(decided).toEqual(["bullet:b"]);
    expect(client.listReview).toHaveBeenCalledWith("lec");
    await verifyByReview(client, "lec", null);
    expect(decided).toContain("bullet:c");
  });

  it("explains the outcome", () => {
    expect(verifyMessage({ approved: 2, waiting: 1, failed: 0 })).toBe("Confirmed 2 uncertain readings. 1 student fix still needs a decision in the review queue.");
    expect(verifyMessage({ approved: 0, waiting: 0, failed: 0 })).toBe("Nothing was waiting here.");
    expect(verifyMessage({ approved: 0, waiting: 0, failed: 2 })).toMatch(/2 items could not be saved/);
    expect(errorText(new ApiError(403, "Lecturers only"), "x")).toBe("Lecturers only");
    expect(errorText("boom", "fallback")).toBe("fallback");
  });

  it("approve-all keeps going past failures and counts them", async () => {
    const r = await approveEach(["a", "b", "c"], async (id) => {
      if (id === "b") throw new ApiError(409, "already decided");
    });
    expect(r).toEqual({ done: 2, failed: 1, firstError: "already decided" });
  });
});

describe("mock mode matches the server's review item ids", () => {
  it("uses the suggestion id or bullet:<id>", async () => {
    for (const i of await mockApi.listReview()) {
      expect(i.id).toBe(i.suggestion ? i.suggestion.id : `bullet:${i.bullet_id}`);
    }
    expect(REVIEW_SEED.length).toBeGreaterThan(0);
  });

  it("rejecting an uncertain reading removes the line; approving a section verifies it", async () => {
    const lec22 = DETAILS.lec_22!;
    expect(lec22.sections.some((s) => s.bullets.some((b) => b.id === "bl_22_8a"))).toBe(true);
    await mockApi.decide("bullet:bl_22_8a", { decision: "reject" });
    const after = await mockApi.getLecture("lec_22");
    expect(after.sections.flatMap((s) => s.bullets).some((b) => b.id === "bl_22_8a")).toBe(false);
    const r = await mockApi.verifySection("lec_22", "sec_22_8");
    expect(r).toEqual({ approved: 0, waiting: 0, failed: 0 });
    expect((await mockApi.getLecture("lec_22")).sections.find((s) => s.id === "sec_22_8")!.status).toBe("verified");
  });

  it("a section with a waiting student fix is not marked verified", async () => {
    const r = await mockApi.verifySection("lec_22", "sec_22_3");
    expect(r.waiting).toBe(1);
    expect((await mockApi.getLecture("lec_22")).sections.find((s) => s.id === "sec_22_3")!.status).not.toBe("verified");
  });

  it("vote sets the requested state and refuses your own suggestion", async () => {
    const s = (await mockApi.listSuggestions("bl_21_4a"))[0]!;
    expect((await mockApi.vote(s.id, true)).voted_by_me).toBe(true);
    expect((await mockApi.vote(s.id, true)).upvotes).toBe(s.upvotes + 1);
    expect((await mockApi.vote(s.id, false)).upvotes).toBe(s.upvotes);
    await mockApi.login("u_riya");
    await expect(mockApi.vote(s.id, true)).rejects.toMatchObject({ status: 403 });
    await mockApi.logout();
  });
});

describe("processing steps", () => {
  it("marks earlier steps done, the current one active and later ones waiting", () => {
    expect([0, 1, 2, 3].map((i) => stepState(i, "read_board"))).toEqual(["done", "done", "active", "waiting"]);
    expect([0, 1, 2, 3].map((i) => stepState(i, "done"))).toEqual(["done", "done", "done", "done"]);
    expect(stepState(0, "check_video")).toBe("active");
    expect(stepState(9, "check_video")).toBe("waiting");
  });
});
