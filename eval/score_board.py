"""Measure board-reading accuracy on the labelled frames in fixtures/frames.

Each run reads every labelled frame with the current pipeline code, saves the model's responses, and scores them.
Saved responses can be re-scored for free, so live API calls happen only when a prompt or model actually changes.

  Replay (free):  uv run --project server python eval/score_board.py --run baseline
  Live (costs):   uv run --project server python eval/score_board.py --run baseline --live --yes
                  (about 15 Sonnet image calls: roughly $0.05-0.15)
  Compare runs:   uv run --project server python eval/score_board.py --compare baseline transcript_context

Metrics (higher is better unless noted):
  coverage        share of labelled lines (fully visible) matched by some block (fuzzy match >= 85)
  text_cer        character error rate of matched lines, lower is better
  formula_exact   share of labelled formulas matched exactly after normalising whitespace and LaTeX spacing
  diagram_recall  share of frames with a labelled diagram where a diagram block was returned
  invented        blocks that match nothing visible or partial in the label (possible hallucinations), lower is better
  calibration     mean confidence of correct blocks minus mean confidence of wrong ones (bigger gap = more useful)
"""

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from rapidfuzz import fuzz  # noqa: E402
from rapidfuzz.distance import Levenshtein  # noqa: E402

from app.contracts.ai import BoardRead  # noqa: E402
from app.llm.client import LLMRequest, T, Usage  # noqa: E402
from app.pipeline.board import read_board  # noqa: E402
from app.pipeline.interfaces import Keyframe  # noqa: E402

FRAMES = ROOT / "fixtures" / "frames"
RUNS = ROOT / "eval" / "runs"
MATCH = 85


# ---------- recording / replaying model responses ----------
class RecordingLLM:
    """Wraps a live LLM and saves each structured response, so the run can be re-scored for free later."""

    def __init__(self, inner, out: Path) -> None:
        self.inner, self.out, self.usage = inner, out, inner.usage
        self.current = ""

    async def structured(self, req: LLMRequest, schema: type[T]) -> T:
        result = await self.inner.structured(req, schema)
        (self.out / f"{self.current}.json").write_text(result.model_dump_json(indent=1))
        return result


class ReplayLLM:
    def __init__(self, src: Path) -> None:
        self.src, self.usage, self.current = src, Usage(), ""

    async def structured(self, req: LLMRequest, schema: type[T]) -> T:
        path = self.src / f"{self.current}.json"
        if not path.exists():
            raise FileNotFoundError(f"No saved response {path}; run once with --live --yes")
        return schema.model_validate_json(path.read_text())


# ---------- scoring ----------
def norm_text(s: str) -> str:
    s = s.replace("−", "-").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def norm_latex(s: str) -> str:
    s = re.sub(r"\\[,;:! ]|~", "", s)
    s = re.sub(r"\\left|\\right", "", s)
    return re.sub(r"\s+", "", s)


@dataclass
class FrameScore:
    frame: str
    lines: int = 0
    matched: int = 0
    char_errors: int = 0
    chars: int = 0
    formulas: int = 0
    formulas_exact: int = 0
    has_diagram: bool = False
    diagram_found: bool = False
    invented: int = 0
    conf_right: list[float] = field(default_factory=list)
    conf_wrong: list[float] = field(default_factory=list)


def score_frame(name: str, label: dict, read: BoardRead) -> FrameScore:
    s = FrameScore(frame=name)
    texts = [norm_text(b.text) for b in read.blocks]
    for line in label["lines"]:
        s.lines += 1
        target = norm_text(line)
        best = max(texts, key=lambda t: fuzz.partial_ratio(target, t), default="")
        if best and fuzz.partial_ratio(target, best) >= MATCH:
            s.matched += 1
            # Compare against the aligned part of the block only: blocks often hold several lines.
            al = fuzz.partial_ratio_alignment(target, best)
            aligned = best[al.dest_start : al.dest_end] if al else best
            s.char_errors += Levenshtein.distance(target, aligned)
            s.chars += len(target)
    got = [norm_latex(b.latex) for b in read.blocks if b.latex]
    for f in label["latex"]:
        s.formulas += 1
        if any(norm_latex(f) == g or norm_latex(f) in g for g in got):
            s.formulas_exact += 1
    s.has_diagram = bool(label["diagrams"])
    s.diagram_found = any(b.type == "diagram" for b in read.blocks)
    visible = [norm_text(x) for x in label["lines"] + label["partial"]]
    for b in read.blocks:
        if b.type == "diagram":
            (s.conf_right if s.has_diagram else s.conf_wrong).append(b.confidence)
            continue
        t = norm_text(b.text)
        best = max((fuzz.partial_ratio(t, v) for v in visible), default=0)
        if best >= MATCH:
            s.conf_right.append(b.confidence)
        else:
            s.invented += 1
            s.conf_wrong.append(b.confidence)
    return s


def summarise(scores: list[FrameScore]) -> dict:
    lines = sum(s.lines for s in scores) or 1
    chars = sum(s.chars for s in scores) or 1
    formulas = sum(s.formulas for s in scores) or 1
    diag = [s for s in scores if s.has_diagram] or [FrameScore("none")]
    right = [c for s in scores for c in s.conf_right]
    wrong = [c for s in scores for c in s.conf_wrong]
    mean = lambda xs: sum(xs) / len(xs) if xs else 0.0  # noqa: E731
    return {
        "frames": len(scores),
        "coverage": round(sum(s.matched for s in scores) / lines, 3),
        "text_cer": round(sum(s.char_errors for s in scores) / chars, 3),
        "formula_exact": round(sum(s.formulas_exact for s in scores) / formulas, 3),
        "diagram_recall": round(sum(s.diagram_found for s in diag) / len(diag), 3),
        "invented": sum(s.invented for s in scores),
        "calibration": round(mean(right) - mean(wrong), 3),
    }


# ---------- running ----------
async def run(name: str, live: bool) -> dict:
    out = RUNS / name
    out.mkdir(parents=True, exist_ok=True)
    if live:
        from app.llm.anthropic_llm import AnthropicLLM

        llm = RecordingLLM(AnthropicLLM(), out)
    else:
        llm = ReplayLLM(out)
    scores, per_frame = [], {}
    for label_path in sorted(FRAMES.glob("[0-9][0-9].json")):
        n = label_path.stem
        label = json.loads(label_path.read_text())
        kf = Keyframe(time_s=float(label["time_s"]), path=FRAMES / f"{n}.jpg", lines=[], readable=1.0)
        llm.current = n
        readings = await read_board([kf], llm)  # type: ignore[arg-type]
        read = readings[0].read if readings else BoardRead(blocks=[], frame_quality="poor")
        s = score_frame(n, label, read)
        scores.append(s)
        per_frame[n] = {"lines": s.lines, "matched": s.matched, "formulas": f"{s.formulas_exact}/{s.formulas}", "invented": s.invented}
    summary = summarise(scores)
    (out / "score.json").write_text(json.dumps({"summary": summary, "frames": per_frame}, indent=1))
    if live:
        u = llm.usage
        cost = u.input_tokens / 1e6 * 2 + u.output_tokens / 1e6 * 10  # Sonnet 5.5 list price
        print(f"live calls: {u.calls}, input {u.input_tokens} / output {u.output_tokens} tokens, about ${cost:.3f}")
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", help="name of the run (folder under eval/runs)")
    p.add_argument("--live", action="store_true", help="call the real model and save responses (costs credits)")
    p.add_argument("--yes", action="store_true", help="confirm a live run")
    p.add_argument("--compare", nargs="+", metavar="RUN", help="print saved scores side by side")
    a = p.parse_args()
    if a.compare:
        rows = {r: json.loads((RUNS / r / "score.json").read_text())["summary"] for r in a.compare}
        keys = list(next(iter(rows.values())))
        print("metric".ljust(16) + "".join(r[:18].ljust(20) for r in rows))
        for k in keys:
            print(k.ljust(16) + "".join(str(rows[r][k]).ljust(20) for r in rows))
        return
    if not a.run:
        p.error("--run is required")
    if a.live and not a.yes:
        p.error("live runs spend API credits: add --yes to confirm")
    print(json.dumps(asyncio.run(run(a.run, a.live)), indent=1))


if __name__ == "__main__":
    main()
