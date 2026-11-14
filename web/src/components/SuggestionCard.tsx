import { Avatar } from "@/components/Avatar";
import { StatusPill } from "@/components/StatusPill";
import { Upvote } from "@/components/Upvote";
import type { Suggestion } from "@/contracts/Suggestion";
import { formatAgo } from "@/lib/format";
import { cx } from "@/lib/cx";

/** A student's suggested fix with its author, AI check and upvote. `onVote` is omitted for read-only views. */
export function SuggestionCard({ suggestion: s, onVote, voteDisabled }: { suggestion: Suggestion; onVote?: () => void; voteDisabled?: boolean }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-default bg-surface p-3" data-testid="suggestion-card">
      <div className="flex items-center gap-2">
        <Avatar initials={s.author_initials} size={20} anonymous={s.anonymous} />
        <span className="flex-1 text-[12px] text-tertiary">
          {s.anonymous ? "Anonymous" : s.author_name} · {formatAgo(s.created_at)}
        </span>
        <Upvote count={s.upvotes} voted={s.voted_by_me} onToggle={onVote} disabled={voteDisabled} />
      </div>
      <p className={cx("text-[14px] leading-[22px] text-primary", s.flagged && "italic")}>{s.proposed_text}</p>
      <div>
        {s.flagged ? (
          <StatusPill status="flagged">Flagged · reads like instructions</StatusPill>
        ) : s.verdict === "agrees" ? (
          <StatusPill status="verified">AI agrees</StatusPill>
        ) : s.verdict === "disagrees" ? (
          <StatusPill status="flagged">AI disagrees</StatusPill>
        ) : (
          <StatusPill status="uncertain">AI unsure</StatusPill>
        )}
      </div>
    </div>
  );
}
