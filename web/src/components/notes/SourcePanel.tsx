"use client";
import { useState } from "react";
import { AiVerdict } from "@/components/AiVerdict";
import { BoardSnapshot } from "@/components/BoardSnapshot";
import { Button } from "@/components/Button";
import { TextField } from "@/components/TextField";
import { VideoPlayer, type SeekRequest } from "@/components/VideoPlayer";
import type { Bullet } from "@/contracts/Bullet";
import type { LectureDetail } from "@/contracts/LectureDetail";
import { api } from "@/lib/client";
import { formatRange, formatTime } from "@/lib/format";
import { useAsync } from "@/lib/hooks";
import { firstStart } from "@/components/notes/helpers";

/**
 * Where a bullet came from: video at that moment, the board crop and what the lecturer said.
 * Students get "Ask about this" / "Suggest a fix"; lecturers get the top fix with "Edit text" / "Accept fix".
 */
export function SourcePanel({
  lecture,
  bullet,
  seek,
  mode,
  onAsk,
  onFix,
  onChanged,
}: {
  lecture: LectureDetail;
  bullet: Bullet;
  seek: SeekRequest | null;
  mode: "student" | "lecturer";
  onAsk: () => void;
  onFix: () => void;
  onChanged: () => void;
}) {
  const source = useAsync(() => api.getSource(lecture.summary.id, bullet.id), [lecture.summary.id, bullet.id]);
  const review = useAsync(() => (mode === "lecturer" ? api.listReview(lecture.summary.id) : Promise.resolve([])), [lecture.summary.id, mode, bullet.id]);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(bullet.text);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const blocks = source.data?.board_blocks ?? [];
  const block = blocks[0];
  const first = source.data?.transcript[0];
  const start = seek?.t ?? firstStart(bullet);
  // The open review item for this point: the top student fix if there is one, else the uncertain reading itself.
  const forBullet = (review.data ?? []).filter((i) => i.bullet_id === bullet.id);
  const item = forBullet.find((i) => i.suggestion) ?? forBullet[0];
  const top = item?.suggestion ?? null;

  async function decide(decision: "approve" | "edit") {
    if (!item) return;
    setBusy(true);
    setError(null);
    try {
      await api.decide(item.id, decision === "edit" ? { decision, edited_text: text } : { decision });
      setEditing(false);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-5">
      <VideoPlayer
        src={lecture.video_url || null}
        boardText={block?.text ?? bullet.text}
        durationS={lecture.summary.duration_s ?? 0}
        seek={seek ?? { t: start, n: 0 }}
        compact
      />
      {block && <BoardSnapshot caption={`On the board · ${formatTime(block.best_frame_s)}`} text={block.text} imageUrl={source.data?.snapshot_urls[0]} />}
      {first && (
        <div className="flex flex-col gap-1.5">
          <p className="text-[12px] font-semibold text-secondary">The lecturer said · {formatRange(first.start_s, first.end_s)}</p>
          <blockquote className="border-l-[3px] border-accent-border pl-3 text-[14px] italic leading-[22px] text-secondary">“{first.text}”</blockquote>
        </div>
      )}
      {source.error && <p className="text-[13px] text-danger">{source.error}</p>}

      {mode === "lecturer" && top && (
        <AiVerdict verdict={top.verdict ?? "unclear"} reason={`Top student fix: “${top.proposed_text}” · ${top.upvotes} upvotes. ${top.verdict_reason ?? ""}`} />
      )}
      {mode === "lecturer" && editing && <TextField multiline maxLength={1000} label="Edited text" value={text} onChange={(e) => setText(e.target.value)} />}
      {error && <p className="text-[13px] text-danger">{error}</p>}

      <div className="flex-1" />
      <div className="flex gap-3">
        {mode === "student" ? (
          <>
            <Button variant="secondary" block onClick={onAsk}>
              Ask about this
            </Button>
            <Button block onClick={onFix}>
              Suggest a fix
            </Button>
          </>
        ) : editing ? (
          <>
            <Button variant="secondary" block onClick={() => setEditing(false)}>
              Cancel
            </Button>
            <Button variant="success" block disabled={busy || !item || !text.trim()} onClick={() => decide("edit")}>
              Save edit
            </Button>
          </>
        ) : (
          <>
            <Button variant="secondary" block disabled={!item} title={item ? undefined : "No open review item for this point"} onClick={() => setEditing(true)}>
              Edit text
            </Button>
            <Button variant="success" block disabled={busy || !item} onClick={() => decide("approve")}>
              {item && !top ? "Looks right" : "Accept fix"}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
