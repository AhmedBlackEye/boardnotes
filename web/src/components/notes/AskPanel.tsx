"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/Button";
import { ChatMessage } from "@/components/ChatMessage";
import { SourceChip } from "@/components/SourceChip";
import type { AskOut } from "@/contracts/AskOut";
import type { LectureDetail } from "@/contracts/LectureDetail";
import { api } from "@/lib/client";
import { boardLabel } from "@/components/notes/helpers";

type Msg = { role: "user"; text: string } | { role: "answer"; out: AskOut } | { role: "error"; text: string };

const SUGGESTED = ["What is the trace?", "Explain the 2×2 example", "Summarise section 3"];

/** Ask the lecture: answers come only from this lecture and carry their sources. */
export function AskPanel({ lecture, onSeek, initialQuestion }: { lecture: LectureDetail; onSeek: (t: number) => void; initialQuestion?: string }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState(initialQuestion ?? "");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => end.current?.scrollIntoView?.({ block: "end" }), [msgs, busy]);

  async function ask(question: string) {
    const text = question.trim();
    if (!text || busy) return;
    setMsgs((m) => [...m, { role: "user", text }]);
    setQ("");
    setBusy(true);
    try {
      const out = await api.ask(lecture.summary.id, text);
      setMsgs((m) => [...m, { role: "answer", out }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "error", text: e instanceof Error ? e.message : "Could not answer" }]);
    } finally {
      setBusy(false);
    }
  }

  function chips(out: AskOut) {
    return out.citations.map((c, i) => {
      if (c.kind === "transcript" && c.at_s !== null) return <SourceChip key={i} seconds={c.at_s} onClick={() => onSeek(c.at_s ?? 0)} />;
      if (c.kind === "board") return <SourceChip key={i} type="reference" label={boardLabel(lecture, c.ref)} />;
      const sec = lecture.sections.find((s) => s.id === c.ref);
      return <SourceChip key={i} type="reference" label={sec ? `Section ${sec.order}` : "Section"} />;
    });
  }

  return (
    <>
      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-5" aria-live="polite">
        {msgs.length === 0 && <p className="text-[13px] text-secondary">Ask anything about this lecture. If it isn&rsquo;t covered, we&rsquo;ll say so.</p>}
        {msgs.map((m, i) =>
          m.role === "user" ? (
            <ChatMessage key={i} kind="user">
              {m.text}
            </ChatMessage>
          ) : m.role === "answer" ? (
            <ChatMessage key={i} kind={m.out.covered ? "answer" : "notice"} sources={m.out.covered ? chips(m.out) : undefined}>
              {m.out.answer}
            </ChatMessage>
          ) : (
            <ChatMessage key={i} kind="notice">
              {m.text}
            </ChatMessage>
          ),
        )}
        {busy && (
          <ChatMessage kind="notice">Reading the lecture…</ChatMessage>
        )}
        <div ref={end} />
      </div>
      <div className="flex flex-col gap-3 border-t border-default p-4">
        <div className="flex flex-wrap gap-2">
          {SUGGESTED.map((s) => (
            <button key={s} type="button" onClick={() => ask(s)} className="rounded-full border border-default px-3 py-1 text-[12px] text-secondary hover:bg-subtle">
              {s}
            </button>
          ))}
        </div>
        <form
          className="flex items-center gap-2 rounded-lg border border-default bg-surface p-1.5 focus-within:border-accent"
          onSubmit={(e) => {
            e.preventDefault();
            void ask(q);
          }}
        >
          <input
            className="min-w-0 flex-1 bg-transparent px-2 text-[14px] text-primary placeholder:text-tertiary focus:outline-none"
            placeholder="Ask a question about this lecture…"
            aria-label="Your question"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <Button type="submit" className="px-3 py-1.5" disabled={busy || !q.trim()}>
            Ask
          </Button>
        </form>
      </div>
    </>
  );
}
