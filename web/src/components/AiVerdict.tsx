import { Icon } from "@/components/Icon";
import type { Suggestion } from "@/contracts/Suggestion";
import { cx } from "@/lib/cx";

type Verdict = NonNullable<Suggestion["verdict"]>;

const COPY: Record<Verdict, { title: string; box: string }> = {
  agrees: { title: "AI agrees with this fix", box: "bg-success-subtle text-success" },
  disagrees: { title: "AI disagrees with this fix", box: "bg-danger-subtle text-danger" },
  unclear: { title: "AI is not sure about this fix", box: "bg-warning-subtle text-warning" },
};

/** The AI check of a student fix against the board and recording, with its reason. */
export function AiVerdict({ verdict, reason }: { verdict: Verdict; reason?: string | null }) {
  const c = COPY[verdict];
  return (
    <div className={cx("flex gap-3 rounded-lg p-3", c.box)} role="status">
      <Icon name="check" size={18} />
      <div className="flex flex-col gap-0.5">
        <p className="text-[13px] font-semibold leading-[18px]">{c.title}</p>
        {reason && <p className="text-[12px] leading-4 text-secondary">{reason}</p>}
      </div>
    </div>
  );
}
