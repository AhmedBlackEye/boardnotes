import io
import re
import unicodedata

import pytest
from pypdf import PdfReader

from app.contracts.ai import BoardBlock, DiagramFigure
from app.contracts.api import LectureDetail
from app.contracts.enums import BlockType, LectureStatus
from app.pipeline import pdf
from tests.factories import bullet, sample_lecture


def pdf_text(data: bytes) -> str:
    # NFKC folds the serif font's ligatures ("ﬁ") back into plain letters.
    return unicodedata.normalize("NFKC", "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages))


def pdf_links(data: bytes) -> list[str]:
    links: list[str] = []
    for page in PdfReader(io.BytesIO(data)).pages:
        for annot in page.get("/Annots") or []:
            action = annot.get_object().get("/A")
            if action and "/URI" in action:
                links.append(str(action["/URI"]))
    return links


# ---------- pure helpers ----------
@pytest.mark.parametrize(("seconds", "expected"), [(0, "00:00"), (65.9, "01:05"), (2050.0, "34:10"), (3725, "1:02:05"), (-3, "00:00")])
def test_format_time(seconds: float, expected: str) -> None:
    assert pdf.format_time(seconds) == expected


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://x.org/v.mp4", True),
        ("/media/v.mp4", True),
        ("javascript:alert(1)", False),
        ("file:///etc/passwd", False),
        ("//evil.org/v.mp4", False),
        ("data:text/html,hi", False),
        ("/\\evil.org/v.mp4", False),
        ("/media/v.mp4\n", True),  # trailing whitespace is stripped
        ("/med ia/v.mp4", False),
        ("/media/\x00v.mp4", False),
        ("https://x.org/a\tb", False),
    ],
)
def test_safe_video_url(url: str, ok: bool) -> None:
    assert (pdf.safe_video_url(url) is not None) is ok


def test_site_relative_url_becomes_absolute_on_public_origin() -> None:
    assert pdf.safe_video_url("/lectures/l1/video") == "http://localhost:3000/lectures/l1/video"


def test_timestamp_link() -> None:
    assert pdf.timestamp_link("https://x.org/v.mp4#t=5", 2050.0) == "https://x.org/v.mp4#t=2050"
    assert pdf.timestamp_link("/v.mp4", 12.345) == "/v.mp4#t=12.3"
    assert pdf.timestamp_link(None, 1.0) is None


def test_bullet_time_prefers_earliest_transcript_then_board() -> None:
    lec = sample_lecture()
    first_seen = {b.id: b.first_seen_s for b in lec.board_blocks}
    s3 = next(s for s in lec.sections if s.id == "s_3")
    assert pdf.bullet_time(s3.bullets[0], first_seen) == 2010.5
    assert pdf.bullet_time(s3.bullets[1], first_seen) == 2142.0


# ---------- HTML ----------
def test_html_escapes_note_text() -> None:
    html = pdf.build_lecture_html(sample_lecture())
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert(&#39;x&#39;)&lt;/script&gt; &amp; 50% of #cases_{1}" in html
    # The only scripts are KaTeX and our renderer.
    assert len(re.findall(r"<script", html)) <= 2


def test_html_escapes_latex_and_title() -> None:
    lec = sample_lecture(title='Evil "title" <img src=x onerror=alert(1)>')
    lec.sections[0].bullets[0].latex = '"><img src=x onerror=alert(1)>'
    html = pdf.build_lecture_html(lec)
    assert "<img" not in html
    assert 'data-latex="&#34;&gt;&lt;img' in html
    assert "Evil &#34;title&#34; &lt;img" in html


def test_html_structure() -> None:
    html = pdf.build_lecture_html(sample_lecture())
    # Sections numbered by order, not list position.
    assert re.search(r'<span class="num">1</span>The characteristic equation', html)
    assert re.search(r'<span class="num">2</span>Trace &amp; determinant', html)
    assert html.index("The characteristic equation") < html.index("Trace &amp; determinant")
    assert html.count('class="draft-mark"') == 1
    # One link to the lecture video at the top; no per-point timestamp links.
    assert html.count('href="http://localhost:3000/lectures/lec_21"') == 1
    assert "#t=" not in html
    assert "Watch the lecture video" in html
    assert 'data-latex="\\det(A - \\lambda I) = 0"' in html
    assert "Said in lecture, not on the board" in html
    assert '<span class="uncertain">AI unsure</span>' in html
    # Plain points are a bulleted list; no boxes without a kind.
    assert '<ul class="bullets">' in html and 'class="box definition"' not in html


def test_html_excludes_drafts_when_asked() -> None:
    html = pdf.build_lecture_html(sample_lecture(), include_drafts=False)
    assert "The characteristic equation" in html
    assert "Trace &amp; determinant" not in html
    assert "draft-mark" not in html.split("<body>", 1)[1]


def test_unsafe_video_url_drops_links() -> None:
    lec = sample_lecture()
    lec.video_url = "javascript:alert(1)"
    html = pdf.build_lecture_html(lec)
    assert "javascript:" not in html
    assert 'class="chip"' not in html


def test_module_html_has_cover_and_contents() -> None:
    lectures = [sample_lecture(LectureStatus.VERIFIED, "Lecture 1"), sample_lecture(title="Lecture 2")]
    html = pdf.build_module_html(lectures, "Linear <Algebra>")
    assert 'class="cover"' in html and 'class="contents"' in html
    assert "<h1>Linear &lt;Algebra&gt;</h1>" in html and "Complete lecture notes" in html
    assert '<span class="num">2.1</span>' in html  # module sections are numbered lecture.section
    assert "1 of 2 verified by the lecturer" in html
    assert html.index("Contents") < html.index('<article class="lecture">')


def _with_kinds(lec: LectureDetail) -> LectureDetail:
    s3 = next(s for s in lec.sections if s.id == "s_3")
    b1, b2 = s3.bullets
    bullets = [
        b1.model_copy(update={"kind": "definition", "title": "Eigenvalue <i>"}),
        b2.model_copy(update={"kind": "example"}),
        bullet("b_3_3", 3, "A plain point."),
        bullet("b_3_4", 4, "Worth remembering.", None, [(2100.0, 2110.0)]).model_copy(update={"kind": "result"}),
    ]
    return lec.model_copy(update={"sections": [s.model_copy(update={"bullets": bullets}) if s.id == "s_3" else s for s in lec.sections]})


def test_boxes_have_type_label_and_section_number() -> None:
    html = pdf.build_lecture_html(_with_kinds(sample_lecture()))
    assert 'class="box definition"' in html and 'class="box example"' in html and 'class="box result"' in html
    assert '<span class="title">Eigenvalue &lt;i&gt;</span><span class="kind">Definition 1.1</span>' in html
    # No title: the bar shows only the type label; numbering counts boxes within the section.
    assert '<div class="box-bar"><span class="kind">Example 1.2</span></div>' in html
    assert '<span class="kind">Key result 1.3</span>' in html
    # Box text (and the formula) sit inside the box body; the plain point between boxes is a bulleted list.
    example = html.split('class="box example"', 1)[1].split('class="box result"', 1)[0]
    assert "Its roots are the eigenvalues." in example
    assert '<ul class="bullets">' in example and "A plain point." in example
    definition = html.split('class="box definition"', 1)[1].split('class="box example"', 1)[0]
    assert 'data-latex="\\det(A - \\lambda I) = 0"' in definition


def _figure(caption: str) -> DiagramFigure:
    return DiagramFigure(kind="crop", chart=None, mermaid=None, caption=caption, redrawn_by_ai=False)


def _lecture_with_diagrams(chosen: str | None) -> LectureDetail:
    lec = sample_lecture()
    blocks = [
        BoardBlock(
            id=i, type=BlockType.DIAGRAM, text="", latex=None, confidence=0.9, first_seen_s=2000.0, best_frame_s=2000.0,
            bbox=[0, 0, 1, 1], figure=_figure(f"Caption {i}") if i != "blk_none" else None,
        )
        for i in ("blk_a", "blk_b", "blk_c", "blk_none")
    ]  # fmt: skip
    sections = []
    for s in lec.sections:
        bullets = [
            b.model_copy(
                update={
                    "board_block_ids": ["blk_none", "blk_a", "blk_b"] if b.id == "b_3_1" else ["blk_a", "blk_c"],
                    "figure_block_id": chosen if b.id == "b_4_1" else None,
                }
            )
            for b in s.bullets
        ]
        sections.append(s.model_copy(update={"bullets": bullets}))
    return lec.model_copy(update={"board_blocks": blocks, "sections": sections})


def test_without_chosen_figures_each_bullet_shows_at_most_one() -> None:
    view = pdf.lecture_view(_lecture_with_diagrams(chosen=None))
    shown = [[f.caption for f in b.figures] for s in view.sections for b in s.bullets]
    # s_3: b_3_1 -> blk_a (blk_none has no figure; only the first is shown), b_3_2 -> blk_c (blk_a already used)
    assert shown == [["Caption blk_a"], ["Caption blk_c"], [], []]
    assert view.sections[0].bullets[0].figures[0].label == "Figure 1.1"


def test_chosen_figures_replace_cited_ones() -> None:
    view = pdf.lecture_view(_lecture_with_diagrams(chosen="blk_b"))
    shown = [[f.caption for f in b.figures] for s in view.sections for b in s.bullets]
    assert shown == [[], [], ["Caption blk_b"], []]
    assert view.sections[1].bullets[0].figures[0].label == "Figure 2.1"


def test_header_escapes_title() -> None:
    header = pdf.header_html("<b>x</b>", "Verified by the lecturer", verified=True)
    assert "<b>" not in header and "&lt;b&gt;" in header


# ---------- real rendering (headless Chromium) ----------
@pytest.fixture(scope="module")
def chromium_ok() -> None:
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            pw.chromium.launch().close()
    except Exception as e:  # pragma: no cover - depends on the machine
        pytest.skip(f"Chromium not available ({e}); run `uv run playwright install chromium`")


async def test_render_pdf(chromium_ok: None) -> None:
    data = await pdf.render_pdf(sample_lecture())
    assert data.startswith(b"%PDF")
    text = pdf_text(data)
    for expected in [
        "Linear Algebra · Lecture 21",
        "The characteristic equation",
        "Trace & determinant",
        "draft, not yet verified",
        "<script>alert('x')</script>",
        "In review · not yet verified",
        "Page 1 of",
        "Watch the lecture video",
    ]:
        assert expected in text, expected
    assert pdf_links(data) == ["http://localhost:3000/lectures/lec_21"]
    if (pdf.KATEX_DIR / "katex.min.js").exists():
        # KaTeX rendered the formula (its HTML output repeats glyphs; the raw source is gone).
        assert "\\det(A" not in text


async def test_render_module_pdf(chromium_ok: None) -> None:
    lectures = [sample_lecture(LectureStatus.VERIFIED, "Lecture 1 · Systems"), sample_lecture(title="Lecture 2 · Eigenvalues")]
    data = await pdf.render_module_pdf(lectures, "Linear Algebra")
    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) >= 4  # cover, contents, one page per lecture
    first = unicodedata.normalize("NFKC", reader.pages[0].extract_text())
    assert "Linear Algebra" in first and "Complete lecture notes" in first
    assert "Contents" in reader.pages[1].extract_text()
    text = pdf_text(data)
    assert "Lecture 2 · Eigenvalues" in text and "1 of 2 lectures verified" in text


async def test_render_module_pdf_caps_lecture_count() -> None:
    with pytest.raises(ValueError, match="at most"):
        await pdf.render_module_pdf([sample_lecture()] * (pdf.MAX_MODULE_LECTURES + 1), "Too big")


def test_missing_tokens_css_emits_no_link(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # noqa: ANN001
    monkeypatch.setattr(pdf, "TOKENS_CSS", tmp_path / "missing.css")
    pdf.design_tokens.cache_clear()
    html = pdf.build_lecture_html(sample_lecture())
    assert 'href="None"' not in html
    assert pdf.design_tokens() == {}
    pdf.design_tokens.cache_clear()
