import json

import pytest

from app.config import REPO_ROOT
from app.contracts.ai import LOW_CONFIDENCE, BoardBlock, NoteBullet, SaidNotWritten, SectionNotes, TimeRange, TranscriptSegment
from app.contracts.enums import BlockType
from app.pipeline import citations
from app.pipeline.citations import LatexError, check_latex, validate_citations


def transcript() -> list[TranscriptSegment]:
    raw = json.loads((REPO_ROOT / "fixtures" / "transcript.json").read_text())
    return [TranscriptSegment.model_validate(s) for s in raw]


def block(id: str, conf: float) -> BoardBlock:
    return BoardBlock(id=id, type=BlockType.MATH, text="x", latex="x", confidence=conf, first_seen_s=5, best_frame_s=5, bbox=[0, 0, 1, 1])


BLOCKS = [block("b_0001", 0.95), block("b_0002", 0.6)]


def bullet(ids: list[str] = [], ranges: list[tuple[float, float]] = [], conf: float = 0.9, latex: str | None = None) -> NoteBullet:  # noqa: B006
    return NoteBullet(
        text="A bullet",
        latex=latex,
        board_block_ids=ids,
        transcript_ranges=[TimeRange(start_s=a, end_s=b) for a, b in ranges],
        confidence=conf,
    )


def section(*bullets: NoteBullet, said: list[SaidNotWritten] | None = None) -> SectionNotes:
    return SectionNotes(heading="Intro", start_s=0, end_s=95, bullets=list(bullets), said_not_written=said or [])


def run(*bullets: NoteBullet, said: list[SaidNotWritten] | None = None):
    return validate_citations([section(*bullets, said=said)], BLOCKS, transcript())


def test_well_cited_bullet_is_kept_unchanged() -> None:
    b = bullet(["b_0001"], [(4.0, 18.5)], conf=0.9)
    report = run(b)
    assert report.valid[0].bullets == [b]
    assert report.dropped == []
    assert report.flagged_bullets == 0


def test_bullet_without_citations_is_dropped() -> None:
    report = run(bullet())
    assert report.valid[0].bullets == []
    assert "no citations" in report.dropped[0]


def test_bullet_citing_only_unknown_block_is_dropped() -> None:
    report = run(bullet(["b_9999"]))
    assert report.valid[0].bullets == []
    assert "unknown board block 'b_9999'" in report.dropped[0]


def test_range_outside_section_is_invalid() -> None:
    report = run(bullet(ranges=[(110.0, 128.0)]))  # real segment, but in the next section
    assert report.valid[0].bullets == []
    assert "outside the section" in report.dropped[0]


def test_range_matching_no_transcript_segment_is_invalid() -> None:
    report = run(bullet(ranges=[(45.0, 55.0)]))  # inside the section, but nobody spoke then
    assert report.valid[0].bullets == []
    assert "matches no transcript segment" in report.dropped[0]


def test_reversed_range_is_invalid() -> None:
    report = run(bullet(ranges=[(18.0, 5.0)]))
    assert "ends before it starts" in report.dropped[0]


def test_small_rounding_differences_are_tolerated() -> None:
    report = run(bullet(ranges=[(19.5, 25.0)]))  # segment ends at 18.5
    assert len(report.valid[0].bullets) == 1


def test_partly_invalid_citations_are_removed_and_bullet_flagged() -> None:
    report = run(bullet(["b_0001", "b_9999"], [(4.0, 18.5)], conf=0.9))
    (kept,) = report.valid[0].bullets
    assert kept.board_block_ids == ["b_0001"]
    assert kept.confidence < LOW_CONFIDENCE
    assert report.flagged_bullets == 1
    assert report.dropped[0].startswith("Removed citations")


def test_confidence_capped_by_best_cited_block() -> None:
    # One clear board source is enough: a blurry second reading doesn't drag the bullet down.
    report = run(bullet(["b_0001", "b_0002"], conf=0.9))
    (kept,) = report.valid[0].bullets
    assert kept.confidence == 0.9
    # Only unsure sources: the bullet is capped at the best of them.
    report = run(bullet(["b_0002"], conf=0.9))
    (kept,) = report.valid[0].bullets
    assert kept.confidence == 0.6
    assert report.flagged_bullets == 1
    assert report.dropped == []


def test_maths_cited_only_from_speech_is_uncertain() -> None:
    report = run(bullet(ranges=[(60.0, 72.0)], conf=0.95, latex="x = 2y - 1"))
    (kept,) = report.valid[0].bullets
    assert kept.confidence < LOW_CONFIDENCE
    assert report.flagged_bullets == 1


def test_said_not_written_outside_transcript_is_dropped() -> None:
    said = [SaidNotWritten(text="ok", at_s=35.0), SaidNotWritten(text="made up", at_s=50.0)]
    report = run(bullet(["b_0001"]), said=said)
    assert [s.text for s in report.valid[0].said_not_written] == ["ok"]
    assert "made up" in report.dropped[0]


def test_fixture_notes_pass_against_fixture_transcript() -> None:
    notes = SectionNotes.model_validate(json.loads((REPO_ROOT / "fixtures/llm/write_notes/default.json").read_text()))
    blocks = [block("b_0001", 0.95), block("b_0003", 0.97)]
    report = validate_citations([notes], blocks, transcript())
    assert report.valid[0].bullets == notes.bullets
    assert [d for d in report.dropped if not d.startswith("LaTeX not checked")] == []


# ---------- check_latex ----------

needs_katex = pytest.mark.skipif(
    not (REPO_ROOT / "web" / "node_modules" / "katex").exists() or citations.shutil.which("node") is None,
    reason="node or web/node_modules/katex not installed",
)


@needs_katex
def test_check_latex_validates_in_one_batch() -> None:
    out = check_latex(["x^2", "\\frac{1}{", "\\begin{cases} 2x + y = 3 \\\\ x - 2y = -1 \\end{cases}"])
    assert out[0] is True
    assert isinstance(out[1], LatexError) and "KaTeX parse error" in out[1].message
    assert out[2] is True


def test_check_latex_empty_list() -> None:
    assert check_latex([]) == []


def test_check_latex_unknown_without_node(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(citations.shutil, "which", lambda _: None)
    assert check_latex(["x", "y"]) == ["unknown", "unknown"]


def test_check_latex_unknown_when_script_fails(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    broken = tmp_path / "broken.mjs"
    broken.write_text("process.exit(1)\n")
    monkeypatch.setattr(citations, "KATEX_SCRIPT", broken)
    if citations.shutil.which("node") is None:
        pytest.skip("node not installed")
    assert check_latex(["x"]) == ["unknown"]


def test_check_latex_rejects_overlong_expressions_without_running_katex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(citations.shutil, "which", lambda _: None)
    out = check_latex(["x" * (citations.MAX_LATEX_CHARS + 1), "x"])
    assert isinstance(out[0], LatexError) and "longer than" in out[0].message
    assert out[1] == "unknown"


def test_check_latex_splits_large_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    batches: list[int] = []

    def fake_batch(latex_list: list[str]) -> list[citations.LatexResult]:
        batches.append(len(latex_list))
        return [True] * len(latex_list)

    monkeypatch.setattr(citations, "_katex_batch", fake_batch)
    monkeypatch.setattr(citations, "MAX_LATEX_BATCH", 3)
    assert check_latex(["x"] * 7) == [True] * 7
    assert batches == [3, 3, 1]


def test_validate_citations_removes_latex_that_does_not_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(citations, "_katex_batch", lambda xs: [True if x == "ok" else LatexError("KaTeX parse error") for x in xs])
    good, bad = bullet(["b_0001"], latex="ok"), bullet(["b_0001"], latex="\\frac{1}{")
    report = validate_citations([section(good, bad)], [block("b_0001", 0.95)], transcript())
    kept_good, kept_bad = report.valid[0].bullets
    assert kept_good.latex == "ok"
    assert kept_bad.latex is None and kept_bad.confidence < LOW_CONFIDENCE
    assert report.flagged_bullets == 1
    assert any("Removed LaTeX" in d for d in report.dropped)


def test_validate_citations_reports_when_latex_cannot_be_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(citations.shutil, "which", lambda _: None)
    report = run(bullet(["b_0001"], latex="x"))
    assert report.valid[0].bullets[0].latex == "x"
    assert "LaTeX not checked: KaTeX is not available on this server" in report.dropped
