/** V2 round 2: written from the spec (CLAUDE.md rules, JobProgress contract), not from the builder's tests. */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { approveEach } from "@/lib/batch";
import { STEPS, stepState } from "@/lib/steps";
import { formatTime } from "@/lib/format";

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}
const uiFiles = walk(join(__dirname, "../src/components"))
  .concat(walk(join(__dirname, "../src/app")))
  .filter((f) => /\.tsx$/.test(f));

describe("CLAUDE.md rule 6: design tokens, no raw hex in UI", () => {
  it("no raw hex colours in components or pages", () => {
    const bad = uiFiles.filter((f) => /["'`\s:]#[0-9a-fA-F]{3,8}\b/.test(readFileSync(f, "utf8")));
    expect(bad).toEqual([]);
  });
});

describe("processing steps", () => {
  it("every stage belongs to exactly one step", () => {
    const all = STEPS.flatMap((s) => s.stages);
    expect(new Set(all).size).toBe(all.length);
  });
  it("progresses through done/active/waiting", () => {
    expect(stepState(0, "check_video")).toBe("active");
    expect(stepState(1, "check_video")).toBe("waiting");
    expect(stepState(0, "transcribe")).toBe("done");
    expect(stepState(2, "read_board")).toBe("active");
    expect(stepState(3, "render_pdf")).toBe("active");
    for (let i = 0; i < STEPS.length; i++) expect(stepState(i, "done")).toBe("done");
    expect(stepState(99, "done")).toBe("waiting");
  });
});

describe("approveEach", () => {
  it("empty list does nothing", async () => {
    expect(await approveEach([], async () => {})).toEqual({ done: 0, failed: 0, firstError: null });
  });
  it("continues past failures, keeps the first error, processes in order", async () => {
    const seen: string[] = [];
    const r = await approveEach(["a", "b", "c", "d"], async (id) => {
      seen.push(id);
      if (id === "b") throw new Error("409 conflict");
      if (id === "c") throw new Error("later");
    });
    expect(seen).toEqual(["a", "b", "c", "d"]);
    expect(r).toEqual({ done: 2, failed: 2, firstError: "409 conflict" });
  });
  it("non-Error rejections still give a message", async () => {
    const r = await approveEach(["a"], () => Promise.reject("boom"));
    expect(r.failed).toBe(1);
    expect(r.firstError).toBeTruthy();
  });
});

describe("rule 5: seconds in data, mm:ss in UI", () => {
  it("formats seconds as mm:ss", () => {
    expect(formatTime(65)).toMatch(/^0?1:05$/);
    expect(formatTime(0)).toMatch(/^0?0:00$/);
  });
});
