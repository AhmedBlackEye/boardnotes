import type { Bullet } from "@/contracts/Bullet";
import type { LectureDetail } from "@/contracts/LectureDetail";
import type { Section } from "@/contracts/Section";
import type { BoardBlock } from "@/contracts/BoardBlock";
import { API_MODE, type VerifyResult } from "@/lib/api";
import { plural } from "@/lib/format";

/** "Board 6": the 1-based position of a board block in the lecture. */
export function boardLabel(lecture: LectureDetail, blockId: string): string {
  const i = lecture.board_blocks.findIndex((b) => b.id === blockId);
  return i >= 0 ? `Board ${i + 1}` : "Board";
}

/** Server URL of a block's board crop (the snapshots route); null in mock mode, where there are no images. */
export function snapshotUrl(lectureId: string, blockId: string): string | null {
  return API_MODE === "mock" ? null : `/snapshots/${encodeURIComponent(lectureId)}/${encodeURIComponent(blockId)}.jpg`;
}

/** Diagram blocks to draw under each bullet: each figure appears once, under the first bullet that cites it. */
export function figuresByBullet(lecture: LectureDetail): Map<string, BoardBlock[]> {
  const blocks = new Map(lecture.board_blocks.filter((b) => b.figure).map((b) => [b.id, b]));
  const out = new Map<string, BoardBlock[]>();
  for (const s of lecture.sections) {
    for (const bullet of s.bullets) {
      for (const id of bullet.board_block_ids) {
        const block = blocks.get(id);
        if (!block) continue;
        blocks.delete(id);
        out.set(bullet.id, [...(out.get(bullet.id) ?? []), block]);
      }
    }
  }
  return out;
}

export function findBullet(lecture: LectureDetail, bulletId: string | null): { section: Section; bullet: Bullet } | null {
  if (!bulletId) return null;
  for (const section of lecture.sections) {
    const bullet = section.bullets.find((b) => b.id === bulletId);
    if (bullet) return { section, bullet };
  }
  return null;
}

/** The bullet whose transcript range covers `t` (seconds), else the first bullet of the section that does. */
export function bulletAt(lecture: LectureDetail, t: number): Bullet | null {
  for (const s of lecture.sections) {
    const hit = s.bullets.find((b) => b.transcript_ranges.some((r) => t >= r.start_s && t <= r.end_s));
    if (hit) return hit;
  }
  const sec = lecture.sections.find((s) => t >= s.start_s && t < s.end_s);
  return sec?.bullets[0] ?? null;
}

export function uncertainCount(section: Section): number {
  return section.bullets.filter((b) => b.uncertain).length;
}

export function firstStart(bullet: Bullet): number {
  return bullet.transcript_ranges[0]?.start_s ?? 0;
}

/** What happened when the lecturer approved a section or lecture, in one or two sentences for the UI. */
export function verifyMessage(r: VerifyResult): string {
  const parts: string[] = [];
  if (r.approved) parts.push(`Confirmed ${plural(r.approved, "uncertain reading")}.`);
  if (r.waiting) parts.push(`${plural(r.waiting, "student fix", "student fixes")} still ${r.waiting === 1 ? "needs" : "need"} a decision in the review queue.`);
  if (r.failed) parts.push(`${plural(r.failed, "item")} could not be saved. Try again.`);
  return parts.length ? parts.join(" ") : "Nothing was waiting here.";
}

/** Text for a failed request. */
export function errorText(e: unknown, fallback: string): string {
  return e instanceof Error && e.message ? e.message : fallback;
}
