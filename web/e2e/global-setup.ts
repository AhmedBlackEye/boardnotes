import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import path from "node:path";
import { VIDEO_FALLBACK, VIDEO_FIXTURE } from "./video";

/**
 * The demo clip (fixtures/video/demo.mp4) is git-ignored, so CI does not have it. Without it, make a stand-in clip
 * with ffmpeg: 5 minutes of a plain picture and a tone. The fake models answer the same either way.
 */
export default function globalSetup(): void {
  if (process.env.E2E_VIDEO || existsSync(VIDEO_FIXTURE) || existsSync(VIDEO_FALLBACK)) return;
  mkdirSync(path.dirname(VIDEO_FALLBACK), { recursive: true });
  execFileSync(
    "ffmpeg",
    [
      "-loglevel", "error", "-y",
      "-f", "lavfi", "-i", "color=c=white:s=640x360:r=2:d=300",
      "-f", "lavfi", "-i", "sine=frequency=440:duration=300",
      "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
      "-c:a", "aac", "-shortest",
      VIDEO_FALLBACK,
    ],
    { stdio: "inherit" },
  );
}
