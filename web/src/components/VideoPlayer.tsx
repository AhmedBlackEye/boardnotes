"use client";
import { useEffect, useRef, useState } from "react";
import { PlayIcon } from "@/components/Icon";
import { assetUrl } from "@/lib/api";
import { formatTime } from "@/lib/format";
import { cx } from "@/lib/cx";

export interface SeekRequest {
  /** Seconds into the video. */
  t: number;
  /** Changes on every request so seeking to the same second twice still fires. */
  n: number;
}

/**
 * Lecture video in a chalkboard frame. With a `src` it is a real HTML5 video; without one (mock mode, or a lecture
 * whose video has not arrived) it shows the board text and a simulated play head so the page still behaves.
 */
export function VideoPlayer({
  src,
  boardText,
  durationS,
  seek,
  className,
  compact,
}: {
  src?: string | null;
  boardText?: string;
  durationS: number;
  seek?: SeekRequest | null;
  className?: string;
  compact?: boolean;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const url = assetUrl(src);

  useEffect(() => {
    if (!seek) return;
    setTime(seek.t);
    if (ref.current) {
      ref.current.currentTime = seek.t;
      void ref.current.play().catch(() => undefined);
    }
  }, [seek]);

  useEffect(() => {
    if (url || !playing) return;
    const id = setInterval(() => setTime((t) => Math.min(durationS, t + 1)), 1000);
    return () => clearInterval(id);
  }, [url, playing, durationS]);

  return (
    <div className={cx("flex flex-col overflow-hidden rounded-lg bg-board", className)} data-testid="video-player">
      {url ? (
        <video
          ref={ref}
          src={url}
          controls
          preload="metadata"
          className={cx("w-full bg-board", compact ? "max-h-[200px]" : "max-h-[360px]")}
          onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
        />
      ) : (
        <>
          <div className={cx("flex-1 whitespace-pre-wrap px-6 py-5 font-chalk text-[22px] leading-[30px] text-chalk", compact ? "min-h-[130px]" : "min-h-[200px]")}>
            {boardText}
          </div>
          <div className="flex items-center gap-3 bg-sidebar px-4 py-3 text-[12px] font-semibold text-on-accent">
            <button type="button" aria-label={playing ? "Pause" : "Play"} onClick={() => setPlaying((p) => !p)} className="flex w-3 justify-center">
              {playing ? <span className="text-[10px]">❚❚</span> : <PlayIcon size={12} />}
            </button>
            <span data-testid="video-time">{formatTime(time)}</span>
            <div className="h-1 flex-1 overflow-hidden rounded-full bg-sidebar-active">
              <div className="h-1 rounded-full bg-accent" style={{ width: `${Math.min(100, (time / Math.max(1, durationS)) * 100)}%` }} />
            </div>
            <span>{formatTime(durationS)}</span>
          </div>
        </>
      )}
    </div>
  );
}
