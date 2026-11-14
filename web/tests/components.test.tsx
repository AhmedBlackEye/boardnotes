import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ usePathname: () => "/lectures", useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), useSearchParams: () => new URLSearchParams() }));
vi.mock("@/lib/session", () => ({ useSession: () => ({ logout: vi.fn() }) }));
vi.mock("@/lib/client", () => ({ api: { listReview: async () => [] } }));

import { AiVerdict } from "@/components/AiVerdict";
import { Button } from "@/components/Button";
import { Math as Tex } from "@/components/Math";
import { NoteBullet } from "@/components/NoteBullet";
import { Sidebar } from "@/components/Sidebar";
import { SourceChip } from "@/components/SourceChip";
import { StatusPill } from "@/components/StatusPill";
import { SuggestionCard } from "@/components/SuggestionCard";
import { Upvote } from "@/components/Upvote";
import { VideoPlayer } from "@/components/VideoPlayer";
import type { Suggestion } from "@/contracts/Suggestion";

const lecturer = { id: "u_lecturer", name: "Dr. Rivera", initials: "DR", role: "lecturer" as const };
const student = { id: "u_sam", name: "Sam Patel", initials: "SP", role: "student" as const };

describe("Sidebar roles", () => {
  it("students see no review queue or upload link", () => {
    render(<Sidebar me={student} reviewCount={5} />);
    expect(screen.getByText("Lectures")).toBeTruthy();
    expect(screen.getByText("Course notes")).toBeTruthy();
    expect(screen.queryByText("Review queue")).toBeNull();
    expect(screen.queryByText("Upload lecture")).toBeNull();
    expect(document.querySelector('a[href="/review"]')).toBeNull();
    expect(document.querySelector('a[href="/upload"]')).toBeNull();
  });
  it("lecturers see review queue with count and upload", () => {
    render(<Sidebar me={lecturer} reviewCount={7} />);
    expect(screen.getByText("Review queue")).toBeTruthy();
    expect(screen.getByText("Upload lecture")).toBeTruthy();
    expect(screen.getByText("7")).toBeTruthy();
  });
});

describe("SourceChip", () => {
  it("shows seconds as mm:ss and fires onClick", () => {
    const fn = vi.fn();
    render(<SourceChip seconds={2042.7} onClick={fn} />);
    fireEvent.click(screen.getByRole("button", { name: /34:02/ }));
    expect(fn).toHaveBeenCalledOnce();
  });
  it("seconds=0 still renders 0:00", () => {
    render(<SourceChip seconds={0} />);
    expect(screen.getByText("0:00")).toBeTruthy();
  });
  it("label overrides time; no onClick renders non-button", () => {
    render(<SourceChip type="reference" label="Board 3" />);
    expect(screen.getByText("Board 3").closest("button")).toBeNull();
  });
});

describe("NoteBullet", () => {
  it("selecting fires onSelect but clicking a chip does not", () => {
    const sel = vi.fn();
    const chip = vi.fn();
    render(
      <NoteBullet text="Hello" onSelect={sel}>
        <SourceChip seconds={5} onClick={chip} />
      </NoteBullet>,
    );
    fireEvent.click(screen.getByText("Hello"));
    expect(sel).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /0:05/ }));
    expect(chip).toHaveBeenCalledTimes(1);
    expect(sel).toHaveBeenCalledTimes(1);
  });
  it("renders KaTeX for latex and exposes state", () => {
    const { container } = render(<NoteBullet text="t" latex="x^2" state="uncertain" />);
    expect(container.querySelector(".katex")).not.toBeNull();
    expect(screen.getByTestId("note-bullet").getAttribute("data-state")).toBe("uncertain");
  });
  it("bullet text is plain text, never HTML", () => {
    const { container } = render(<NoteBullet text={'<img src=x onerror="alert(1)">'} />);
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("Math", () => {
  it("does not throw on invalid latex", () => {
    const { container } = render(<Tex latex={"\\frac{"} />);
    expect(container.textContent).toContain("\\frac");
  });
  it("does not produce live javascript: links", () => {
    const { container } = render(<Tex latex={"\\href{javascript:alert(1)}{x}"} />);
    expect(container.querySelector('a[href^="javascript"]')).toBeNull();
  });
});

describe("StatusPill", () => {
  it("always comes with a word", () => {
    for (const s of ["verified", "in_review", "uncertain", "processing", "draft", "flagged", "failed"] as const) {
      const { container, unmount } = render(<StatusPill status={s} />);
      expect((container.textContent ?? "").trim().length, s).toBeGreaterThan(0);
      unmount();
    }
  });
});

const sug = (over: Partial<Suggestion> = {}): Suggestion => ({
  id: "sg1",
  bullet_id: "b",
  author_name: "Riya Kapoor",
  author_initials: "RK",
  anonymous: false,
  proposed_text: "tr(A)",
  status: "open",
  upvotes: 3,
  voted_by_me: false,
  created_at: new Date().toISOString(),
  verdict: "agrees",
  verdict_reason: null,
  flagged: false,
  ...over,
});

describe("SuggestionCard", () => {
  it("hides the author name when anonymous", () => {
    render(<SuggestionCard suggestion={sug({ anonymous: true })} />);
    expect(screen.queryByText(/Riya Kapoor/)).toBeNull();
    expect(screen.getByText(/Anonymous/)).toBeTruthy();
  });
  it("flagged overrides verdict", () => {
    render(<SuggestionCard suggestion={sug({ flagged: true, verdict: "agrees" })} />);
    expect(screen.getByText(/Flagged/)).toBeTruthy();
    expect(screen.queryByText("AI agrees")).toBeNull();
  });
  it("null verdict (check running) shows unsure, not agrees", () => {
    render(<SuggestionCard suggestion={sug({ verdict: null })} />);
    expect(screen.getByText("AI unsure")).toBeTruthy();
  });
  it("student-written text is rendered as text", () => {
    const { container } = render(<SuggestionCard suggestion={sug({ proposed_text: "<script>x</script><b>bold</b>" })} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText(/<b>bold<\/b>/)).toBeTruthy();
  });
  it("voting calls onVote; disabled blocks it; read-only has no button", () => {
    const v = vi.fn();
    const { rerender } = render(<SuggestionCard suggestion={sug()} onVote={v} />);
    fireEvent.click(screen.getByRole("button"));
    expect(v).toHaveBeenCalledOnce();
    rerender(<SuggestionCard suggestion={sug()} onVote={v} voteDisabled />);
    fireEvent.click(screen.getByRole("button"));
    expect(v).toHaveBeenCalledOnce();
    rerender(<SuggestionCard suggestion={sug()} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("Upvote", () => {
  it("aria-pressed reflects voted", () => {
    render(<Upvote count={2} voted onToggle={() => undefined} />);
    expect(screen.getByRole("button").getAttribute("aria-pressed")).toBe("true");
  });
});

describe("AiVerdict + Button", () => {
  it("shows reason", () => {
    render(<AiVerdict verdict="disagrees" reason="Board says tr(A)" />);
    expect(screen.getByText("Board says tr(A)")).toBeTruthy();
    expect(screen.getByText(/disagrees/)).toBeTruthy();
  });
  it("Button defaults to type=button so it never submits forms", () => {
    render(<Button>Go</Button>);
    expect(screen.getByRole("button").getAttribute("type")).toBe("button");
  });
});

describe("VideoPlayer", () => {
  it("without src simulates a play head in seconds and obeys seek requests", () => {
    vi.useFakeTimers();
    const { rerender } = render(<VideoPlayer durationS={100} boardText="board" />);
    expect(screen.getByTestId("video-time").textContent).toBe("0:00");
    rerender(<VideoPlayer durationS={100} boardText="board" seek={{ t: 65.5, n: 1 }} />);
    expect(screen.getByTestId("video-time").textContent).toBe("1:05");
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByTestId("video-time").textContent).toBe("1:08");
    act(() => {
      vi.advanceTimersByTime(60000);
    });
    expect(screen.getByTestId("video-time").textContent).toBe("1:40");
    vi.useRealTimers();
  });
  it("same second twice still seeks (n changes)", () => {
    const { rerender } = render(<VideoPlayer durationS={100} seek={{ t: 10, n: 1 }} />);
    rerender(<VideoPlayer durationS={100} seek={{ t: 10, n: 2 }} />);
    expect(screen.getByTestId("video-time").textContent).toBe("0:10");
  });
  it("zero duration does not crash", () => {
    render(<VideoPlayer durationS={0} />);
    expect(screen.getByTestId("video-time")).toBeTruthy();
  });
});
