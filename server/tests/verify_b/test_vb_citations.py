"""V2 tests for B-4: validate_citations (pure code) and check_latex."""

from app.contracts.ai import LOW_CONFIDENCE, BoardBlock, NoteBullet, SaidNotWritten, SectionNotes, TimeRange, TranscriptSegment
from app.pipeline.citations import LatexError, check_latex, validate_citations

TR = [TranscriptSegment(start_s=0, end_s=30, speaker="lecturer", text="a"), TranscriptSegment(start_s=30, end_s=60, speaker="lecturer", text="b")]


def B(i, conf=0.9):
    return BoardBlock(id=i, type="text", text="t", latex=None, confidence=conf, first_seen_s=1.0, best_frame_s=1.0, bbox=[0, 0, 1, 1])


def bullet(text="x", ids=(), ranges=(), conf=0.9, latex=None):
    return NoteBullet(text=text, latex=latex, board_block_ids=list(ids), transcript_ranges=[TimeRange(start_s=a, end_s=b) for a, b in ranges], confidence=conf)


def sec(bullets, said=(), start=0.0, end=30.0, heading="H"):
    return SectionNotes(heading=heading, start_s=start, end_s=end, bullets=list(bullets), said_not_written=list(said))


def run(bullets, blocks=(B("b_0001"),), **kw):
    rep = validate_citations([sec(bullets, **kw)], list(blocks), TR)
    return rep, rep.valid[0].bullets


def test_good_bullet_kept_unchanged():
    rep, bs = run([bullet(ids=["b_0001"], ranges=[(2, 10)])])
    assert len(bs) == 1 and bs[0].confidence == 0.9 and rep.flagged_bullets == 0 and rep.dropped == []


def test_no_citations_dropped_with_reason():
    rep, bs = run([bullet()])
    assert bs == [] and len(rep.dropped) == 1 and rep.dropped[0]


def test_unknown_block_only_dropped():
    _, bs = run([bullet(ids=["b_9999"])])
    assert bs == []


def test_unknown_block_removed_but_valid_kept():
    rep, bs = run([bullet(ids=["b_9999", "b_0001"])])
    assert len(bs) == 1 and bs[0].board_block_ids == ["b_0001"]
    assert rep.dropped


def test_transcript_range_only_valid():
    _, bs = run([bullet(ranges=[(5, 12)])])
    assert len(bs) == 1


def test_transcript_range_beyond_transcript_dropped():
    _, bs = run([bullet(ranges=[(500, 520)])], start=0, end=600)
    assert bs == []


def test_range_outside_section_dropped():
    _, bs = run([bullet(ranges=[(40, 50)])], start=0, end=30)
    assert bs == []


def test_reversed_range_dropped():
    _, bs = run([bullet(ranges=[(20, 10)])])
    assert bs == []


def test_confidence_capped_by_cited_block():
    _, bs = run([bullet(ids=["b_0001"], conf=0.99)], blocks=[B("b_0001", 0.5)])
    assert bs[0].confidence <= 0.5


def test_low_confidence_counted_as_flagged():
    rep, bs = run([bullet(ids=["b_0001"], conf=0.99)], blocks=[B("b_0001", 0.5)])
    assert len(bs) == 1 and rep.flagged_bullets == 1 and bs[0].confidence < LOW_CONFIDENCE


def test_confidence_never_increased():
    _, bs = run([bullet(ids=["b_0001"], ranges=[(1, 5)], conf=0.4)])
    assert bs[0].confidence <= 0.4


def test_said_not_written_outside_transcript_dropped():
    rep = validate_citations([sec([bullet(ids=["b_0001"])], said=[SaidNotWritten(text="ok", at_s=5.0), SaidNotWritten(text="bad", at_s=400.0)])], [B("b_0001")], TR)
    assert [s.text for s in rep.valid[0].said_not_written] == ["ok"]


def test_section_metadata_preserved_and_order():
    s1 = sec([bullet(ids=["b_0001"])], heading="One", start=0, end=30)
    s2 = sec([bullet()], heading="Two", start=30, end=60)
    rep = validate_citations([s1, s2], [B("b_0001")], TR)
    assert [s.heading for s in rep.valid] == ["One", "Two"]
    assert (rep.valid[1].start_s, rep.valid[1].end_s) == (30, 60)
    assert rep.valid[1].bullets == []


def test_input_not_mutated():
    s = sec([bullet(ids=["b_9999", "b_0001"]), bullet()])
    before = s.model_dump()
    validate_citations([s], [B("b_0001")], TR)
    assert s.model_dump() == before


def test_empty_inputs():
    rep = validate_citations([], [], [])
    assert rep.valid == [] and rep.dropped == [] and rep.flagged_bullets == 0


def test_result_always_satisfies_citation_rule():
    bullets = [bullet(), bullet(ids=["nope"]), bullet(ranges=[(999, 1000)]), bullet(ids=["b_0001"]), bullet(ranges=[(1, 2)])]
    _, bs = run(bullets)
    assert bs and all(b.board_block_ids or b.transcript_ranges for b in bs)


# ---------- check_latex ----------
def test_latex_empty():
    assert check_latex([]) == []


def test_latex_valid_and_invalid_in_order():
    out = check_latex([r"\frac{a}{b}", r"\frac{a", r"E = mc^2", r"\notamacro{x}"])
    assert out[0] is True and out[2] is True
    assert isinstance(out[1], LatexError) and out[1].message
    assert isinstance(out[3], LatexError)


def test_latex_length_matches_input():
    xs = ["x"] * 7 + ["\\frac{"]
    assert len(check_latex(xs)) == 8


def test_latex_hostile_input_does_not_crash():
    out = check_latex(['"; process.exit(1); //', "\\href{javascript:alert(1)}{x}", "\x00"])
    assert len(out) == 3
