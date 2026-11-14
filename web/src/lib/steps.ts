import type { JobStage } from "@/contracts/JobProgress";

/** The four steps shown to the lecturer while a lecture is processed, each covering one or more pipeline stages. */
export const STEPS: { title: string; stages: JobStage[] }[] = [
  { title: "Checked the video", stages: ["check_video"] },
  { title: "Listened to the lecture", stages: ["transcribe"] },
  { title: "Reading the board", stages: ["select_frames", "read_board", "merge_blocks"] },
  { title: "Writing notes and PDF", stages: ["section", "write_notes", "render_pdf"] },
];

const ORDER: JobStage[] = ["check_video", "transcribe", "select_frames", "read_board", "merge_blocks", "section", "write_notes", "render_pdf", "done"];

export type StepState = "done" | "active" | "waiting";

/** Whether step `step` (index into STEPS) is done, running or still waiting when the job is at `stage`. */
export function stepState(step: number, stage: JobStage): StepState {
  const s = STEPS[step];
  if (!s) return "waiting";
  if (stage === "done") return "done";
  const idx = ORDER.indexOf(stage);
  const first = ORDER.indexOf(s.stages[0]!);
  const last = ORDER.indexOf(s.stages[s.stages.length - 1]!);
  if (idx > last) return "done";
  return idx >= first ? "active" : "waiting";
}
