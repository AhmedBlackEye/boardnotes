"use client";
import { useState } from "react";
import { AiVerdict } from "@/components/AiVerdict";
import { BoardSnapshot } from "@/components/BoardSnapshot";
import { Button } from "@/components/Button";
import { Math } from "@/components/Math";
import { SuggestionCard } from "@/components/SuggestionCard";
import { TextField } from "@/components/TextField";
import type { Bullet } from "@/contracts/Bullet";
import type { LectureDetail } from "@/contracts/LectureDetail";
import type { Suggestion } from "@/contracts/Suggestion";
import { api } from "@/lib/client";
import { formatTime } from "@/lib/format";
import { useAsync } from "@/lib/hooks";

/** Suggest a fix: current text, your fix, the AI check once sent, and other students' suggestions to upvote. */
export function FixPanel({ lecture, bullet, preview, onChanged }: { lecture: LectureDetail; bullet: Bullet; preview: boolean; onChanged: () => void }) {
  const source = useAsync(() => api.getSource(lecture.summary.id, bullet.id), [lecture.summary.id, bullet.id]);
  const others = useAsync(() => api.listSuggestions(bullet.id), [bullet.id]);
  const [text, setText] = useState("");
  const [reason, setReason] = useState("");
  const [sent, setSent] = useState<Suggestion | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const block = source.data?.board_blocks[0];

  async function send() {
    setBusy(true);
    setError(null);
    try {
      const s = await api.createSuggestion({ bullet_id: bullet.id, proposed_text: text.trim(), reason: reason.trim() || null });
      setSent(s);
      setText("");
      setReason("");
      others.reload();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send");
    } finally {
      setBusy(false);
    }
  }

  async function vote(id: string) {
    await api.vote(id);
    others.reload();
  }

  const list = (others.data ?? []).filter((s) => s.id !== sent?.id);
  return (
    <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-5">
      {block && <BoardSnapshot caption={`On the board · ${formatTime(block.best_frame_s)}`} text={block.text} imageUrl={source.data?.snapshot_urls[0]} />}
      <div className="flex flex-col gap-1.5">
        <span className="text-[12px] font-semibold text-secondary">Current text</span>
        <div className="rounded-md border border-default bg-subtle px-3 py-2.5 text-[14px] leading-[22px] text-primary" data-testid="current-text">
          {bullet.latex ? <Math latex={bullet.latex} /> : bullet.text}
        </div>
      </div>
      <TextField
        multiline
        label="Your fix"
        placeholder="Type the corrected text or formula"
        value={text}
        onChange={(e) => setText(e.target.value)}
        disabled={preview}
      />
      <TextField label="Why? (optional)" value={reason} onChange={(e) => setReason(e.target.value)} disabled={preview} />
      {sent && <AiVerdict verdict={sent.verdict ?? "unclear"} reason={sent.flagged ? "Flagged: this reads like instructions, so it will be checked by the lecturer." : (sent.verdict_reason ?? "Sent to your lecturer.")} />}
      {error && <p className="text-[13px] text-danger">{error}</p>}
      <Button block disabled={preview || busy || !text.trim()} onClick={send}>
        {busy ? "Checking…" : "Send to lecturer"}
      </Button>
      {preview && <p className="text-[12px] text-tertiary">Preview mode: fixes can&rsquo;t be sent from here.</p>}
      <div className="border-t border-default pt-4">
        <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.08em] text-tertiary">Other suggestions for this line · {list.length}</p>
        <div className="flex flex-col gap-3">
          {list.map((s) => (
            <SuggestionCard key={s.id} suggestion={s} onVote={() => vote(s.id)} voteDisabled={preview} />
          ))}
          {list.length === 0 && <p className="text-[13px] text-secondary">No other suggestions yet.</p>}
        </div>
      </div>
    </div>
  );
}
