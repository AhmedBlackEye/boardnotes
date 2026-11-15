import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, request, type APIRequestContext, type Page } from "@playwright/test";
import type { LectureDetail } from "@/contracts/LectureDetail";
import type { LectureSummary } from "@/contracts/LectureSummary";
import type { Suggestion } from "@/contracts/Suggestion";
import type { UploadSession } from "@/contracts/UploadSession";
import { API_URL } from "./ports";
import { videoPath } from "./video";

export type DemoUser = "Dr. Rivera" | "Sam Patel" | "Riya Kapoor" | "Tom Wells";

/**
 * Open a page and wait until React has hydrated it: the session check (GET /auth/me) runs from an effect, so once
 * it has answered, clicks reach the real handlers rather than the server-rendered HTML.
 */
export async function open(page: Page, path: string): Promise<void> {
  const me = page.waitForResponse((r) => new URL(r.url()).pathname === "/auth/me");
  await page.goto(path);
  await me;
}

/** Sign in through the demo login page and wait for the lectures list. */
export async function login(page: Page, name: DemoUser): Promise<void> {
  await open(page, "/login");
  await page.getByRole("button", { name: new RegExp(name) }).click();
  await expect(page).toHaveURL(/\/lectures$/);
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
}

/** An API client signed in as a demo user (for setting up data the test is not about). */
export async function apiAs(userId: "u_lecturer" | "u_sam" | "u_riya" | "u_tom"): Promise<APIRequestContext> {
  const ctx = await request.newContext({ baseURL: API_URL });
  const res = await ctx.post("/auth/demo-login", { data: { user_id: userId } });
  expect(res.ok(), await res.text()).toBeTruthy();
  return ctx;
}

/** Upload the test video as the lecturer over the API and wait until its notes are written. */
export async function uploadLectureViaApi(lecturer: APIRequestContext, title: string): Promise<LectureDetail> {
  const file = videoPath();
  const bytes = readFileSync(file);
  const start = await lecturer.post("/uploads", { data: { filename: path.basename(file), size_bytes: bytes.length, title } });
  expect(start.status(), await start.text()).toBe(201);
  let session = (await start.json()) as UploadSession;
  while (session.received_bytes < bytes.length) {
    const from = session.received_bytes;
    const to = Math.min(bytes.length, from + session.chunk_size);
    const res = await lecturer.put(`/uploads/${session.upload_id}`, {
      data: bytes.subarray(from, to),
      headers: { "Content-Type": "application/octet-stream", "Content-Range": `bytes ${from}-${to - 1}/${bytes.length}` },
    });
    expect(res.ok(), await res.text()).toBeTruthy();
    session = (await res.json()) as UploadSession;
  }
  const done = await lecturer.post(`/uploads/${session.upload_id}/complete`);
  expect(done.ok(), await done.text()).toBeTruthy();
  const { lecture_id } = (await done.json()) as { lecture_id: string };
  await expect
    .poll(
      async () => {
        const lectures = (await (await lecturer.get("/lectures")).json()) as LectureSummary[];
        return lectures.find((l) => l.id === lecture_id)?.status;
      },
      { timeout: 120_000, intervals: [500, 1000, 2000] },
    )
    .toMatch(/^(draft|in_review|verified)$/);
  return (await (await lecturer.get(`/lectures/${lecture_id}`)).json()) as LectureDetail;
}

/** A student fix created over the API (gets the AI check like one sent from the page). */
export async function suggestViaApi(student: APIRequestContext, bulletId: string, text: string): Promise<Suggestion> {
  const res = await student.post("/suggestions", { data: { bullet_id: bulletId, proposed_text: text, reason: null } });
  expect(res.status(), await res.text()).toBe(201);
  return (await res.json()) as Suggestion;
}

/** Fetch a link's target with the page's cookies and check it is a PDF. */
export async function expectPdf(page: Page, href: string | null): Promise<void> {
  expect(href, "the link has an address").toBeTruthy();
  const res = await page.request.get(new URL(href ?? "", page.url()).toString());
  expect(res.status()).toBe(200);
  expect(res.headers()["content-type"]).toContain("application/pdf");
  expect((await res.body()).subarray(0, 5).toString()).toBe("%PDF-");
}
