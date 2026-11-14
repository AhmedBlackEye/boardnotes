import type { Bullet } from "@/contracts/Bullet";
import type { LectureDetail } from "@/contracts/LectureDetail";
import type { Section } from "@/contracts/Section";

/** "Board 6": the 1-based position of a board block in the lecture. */
export function boardLabel(lecture: LectureDetail, blockId: string): string {
  const i = lecture.board_blocks.findIndex((b) => b.id === blockId);
  return i >= 0 ? `Board ${i + 1}` : "Board";
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
