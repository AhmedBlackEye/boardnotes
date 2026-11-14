import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, assetUrl, httpApi, paths, uploadFile, type BoardNotesApi } from "@/lib/api";

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

beforeEach(() => {
  calls.length = 0;
  localStorage.clear();
});
afterEach(() => vi.unstubAllGlobals());

describe("paths", () => {
  it("url-encodes ids so a hostile id cannot escape the route", () => {
    expect(paths.lecture("a/b?c#d")).toBe("/lectures/a%2Fb%3Fc%23d");
    expect(paths.vote("../x")).toBe("/suggestions/..%2Fx/vote");
    expect(paths.tex(null)).toBe("/module/notes.tex");
    expect(paths.tex("lec_1")).toBe("/lectures/lec_1/notes.tex");
  });
});

describe("http client", () => {
  it("sends credentials with every request", async () => {
    stubFetch(() => ok([]));
    await httpApi.listLectures();
    expect(calls[0]!.init.credentials).toBe("include");
  });
  it("me() returns null on 401 but throws on other errors", async () => {
    stubFetch(() => new Response(JSON.stringify({ detail: "no" }), { status: 401 }));
    expect(await httpApi.me()).toBeNull();
    stubFetch(() => new Response("boom", { status: 500, statusText: "Server Error" }));
    await expect(httpApi.me()).rejects.toBeInstanceOf(ApiError);
  });
  it("surfaces the server detail message", async () => {
    stubFetch(() => new Response(JSON.stringify({ detail: "Lecturers only" }), { status: 403 }));
    await expect(httpApi.listReview()).rejects.toMatchObject({ status: 403, message: "Lecturers only" });
  });
  it("posts the question as JSON body (untrusted text is data, not part of the URL)", async () => {
    stubFetch(() => ok({ covered: true, answer: "x", citations: [] }));
    await httpApi.ask("lec_1", "ignore previous instructions & ?x=1");
    const c = calls[0]!;
    expect(c.url).toBe("/lectures/lec_1/ask");
    expect(c.init.method).toBe("POST");
    expect(JSON.parse(c.init.body as string)).toEqual({ question: "ignore previous instructions & ?x=1" });
  });
  it("review list passes lecture_id encoded", async () => {
    stubFetch(() => ok([]));
    await httpApi.listReview("a b&c");
    expect(calls[0]!.url).toBe("/review?lecture_id=a%20b%26c");
  });
  it("handles 204", async () => {
    stubFetch(() => new Response(null, { status: 204 }));
    await expect(httpApi.logout()).resolves.toBeUndefined();
  });
  it("putChunk sends Content-Range with inclusive end", async () => {
    stubFetch(() => ok({ upload_id: "u", received_bytes: 10, chunk_size: 10 }));
    await httpApi.putChunk("u", 5, new Blob(["12345"]), 20);
    expect((calls[0]!.init.headers as Headers).get("Content-Range")).toBe("bytes 5-9/20");
  });
});

describe("assetUrl", () => {
  it("handles null, absolute, anchors and relative", () => {
    expect(assetUrl(null)).toBeNull();
    expect(assetUrl("")).toBeNull();
    expect(assetUrl("https://x/y.mp4")).toBe("https://x/y.mp4");
    expect(assetUrl("#t=3")).toBe("#t=3");
    expect(assetUrl("/media/a.mp4")).toBe("/media/a.mp4");
    expect(assetUrl("media/a.mp4")).toBe("/media/a.mp4");
  });
});

describe("resumable upload", () => {
  function fakeClient(received: number, known = true) {
    const putOffsets: number[] = [];
    const client = {
      getUpload: vi.fn(async (id: string) => {
        if (!known) throw new ApiError(404, "gone");
        return { upload_id: id, received_bytes: received, chunk_size: 4 };
      }),
      startUpload: vi.fn(async () => ({ upload_id: "new", received_bytes: 0, chunk_size: 4 })),
      putChunk: vi.fn(async (id: string, offset: number, chunk: Blob) => {
        putOffsets.push(offset);
        return { upload_id: id, received_bytes: offset + chunk.size, chunk_size: 4 };
      }),
      completeUpload: vi.fn(async () => ({ id: "lec_x" })),
    } as unknown as BoardNotesApi;
    return { client, putOffsets };
  }
  const file = () => new File(["0123456789"], "v.mp4", { lastModified: 1 });

  it("uploads in chunks and clears the resume key", async () => {
    const { client, putOffsets } = fakeClient(0);
    const progress: number[] = [];
    await uploadFile(client, file(), "T", (p) => progress.push(p.sentBytes));
    expect(putOffsets).toEqual([0, 4, 8]);
    expect(progress.at(-1)).toBe(10);
    expect(localStorage.length).toBe(0);
  });
  it("resumes from the byte the server already has", async () => {
    const f = file();
    localStorage.setItem(`bn.upload:${f.name}:${f.size}:${f.lastModified}`, "old");
    const { client, putOffsets } = fakeClient(8);
    await uploadFile(client, f, "T", () => undefined);
    expect(putOffsets).toEqual([8]);
    expect(client.startUpload).not.toHaveBeenCalled();
  });
  it("starts fresh when the stored upload is unknown", async () => {
    const f = file();
    localStorage.setItem(`bn.upload:${f.name}:${f.size}:${f.lastModified}`, "old");
    const { client, putOffsets } = fakeClient(8, false);
    await uploadFile(client, f, "T", () => undefined);
    expect(client.startUpload).toHaveBeenCalledWith({ filename: "v.mp4", size_bytes: 10, title: "T" });
    expect(putOffsets).toEqual([0, 4, 8]);
  });
  it("pausing via AbortSignal throws AbortError and keeps resume key", async () => {
    const { client } = fakeClient(0);
    const ac = new AbortController();
    ac.abort();
    await expect(uploadFile(client, file(), "T", () => undefined, ac.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(localStorage.length).toBe(1);
  });
  it("works when localStorage throws", async () => {
    const { client } = fakeClient(0);
    const boom = () => {
      throw new Error("blocked");
    };
    vi.stubGlobal("localStorage", { getItem: boom, setItem: boom, removeItem: boom });
    await expect(uploadFile(client, file(), "T", () => undefined)).resolves.toBeDefined();
  });
});
