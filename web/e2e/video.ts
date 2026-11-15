import { existsSync } from "node:fs";
import path from "node:path";

/** The demo clip the tests upload (git-ignored; share it separately, see fixtures/README.md). */
export const VIDEO_FIXTURE = path.resolve(__dirname, "../../fixtures/video/demo.mp4");
/** Made by global-setup.ts with ffmpeg when the demo clip is missing (for example in CI). */
export const VIDEO_FALLBACK = path.resolve(__dirname, "../.e2e-cache/demo.mp4");

/** E2E_VIDEO if set, else the demo clip, else the generated stand-in. */
export function videoPath(): string {
  return process.env.E2E_VIDEO ?? (existsSync(VIDEO_FIXTURE) ? VIDEO_FIXTURE : VIDEO_FALLBACK);
}
