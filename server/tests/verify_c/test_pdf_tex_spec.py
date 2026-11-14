"""V2 spec tests for C-2 (PDF) and C-3 (.tex). From contracts + acceptance criteria only."""

import asyncio
import io
import re
import shutil
import subprocess

import pytest
from pypdf import PdfReader

from app.contracts.api import LectureDetail
from app.contracts.enums import LectureStatus, SectionStatus
from app.pipeline import pdf as P
from app.pipeline import tex as X
from tests.factories import bullet, sample_lecture


def run(c):
    return asyncio.run(c)


def text_of(data: bytes) -> str:
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)


def links_of(data: bytes) -> list[str]:
    out = []
    for p in PdfReader(io.BytesIO(data)).pages:
        for a in p.get("/Annots") or []:
            act = a.get_object().get("/A")
            if act and "/URI" in act:
                out.append(str(act["/URI"]))
    return out


def lec(**kw) -> LectureDetail:
    return sample_lecture(**kw)


def with_video(l: LectureDetail, url: str) -> LectureDetail:
    return l.model_copy(update={"video_url": url})


def verified(l: LectureDetail) -> LectureDetail:
    return l.model_copy(update={"sections": [s.model_copy(update={"status": SectionStatus.VERIFIED}) for s in l.sections]})


# ---------------- PDF ----------------
def test_render_pdf_returns_real_pdf():
    data = run(P.render_pdf(lec()))
    assert data.startswith(b"%PDF")
    assert len(PdfReader(io.BytesIO(data)).pages) >= 1
    t = text_of(data)
    assert "Linear Algebra" in t
    assert "characteristic equation" in t
    assert "Trace" in t


def test_pdf_has_clickable_timestamp_links_in_seconds():
    links = links_of(run(P.render_pdf(lec())))
    assert any("#t=2010" in x for x in links), links


def test_pdf_draft_marks_present_when_unverified_and_absent_when_verified():
    assert "draft" in text_of(run(P.render_pdf(lec()))).lower()
    l = verified(lec(status=LectureStatus.VERIFIED))
    assert "draft" not in text_of(run(P.render_pdf(l))).lower()


def test_include_drafts_false_hides_draft_sections():
    full = text_of(run(P.render_pdf(lec(), include_drafts=True)))
    only = text_of(run(P.render_pdf(lec(), include_drafts=False)))
    assert "Trace" in full
    assert "Trace & determinant" not in only
    assert "characteristic equation" in only


def test_pdf_script_injection_is_inert():
    html = P.build_lecture_html(lec())
    assert "<script>alert" not in html


def test_title_html_escaped():
    html = P.build_lecture_html(lec(title="<img src=x onerror=alert(1)>"))
    assert "<img src=x" not in html


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "file:///etc/passwd", "data:text/html,x", "//evil.org/x"])
def test_unsafe_video_url_produces_no_link(bad):
    l = with_video(lec(), bad)
    assert bad not in P.build_lecture_html(l)
    assert not any(bad in x for x in links_of(run(P.render_pdf(l))))


def test_empty_lecture_renders():
    l = lec().model_copy(update={"sections": [], "board_blocks": []})
    assert run(P.render_pdf(l)).startswith(b"%PDF")


def test_bullet_without_citations_renders_without_crash():
    l = lec()
    s = l.sections[0].model_copy(update={"bullets": [bullet("x", 1, "Uncited claim")]})
    l = l.model_copy(update={"sections": [s]})
    assert "Uncited claim" in text_of(run(P.render_pdf(l)))


def test_sections_ordered_by_order_field():
    t = text_of(run(P.render_pdf(lec())))
    assert t.index("characteristic equation") < t.index("Trace")


def test_module_pdf_contains_all_lectures_and_title():
    data = run(P.render_module_pdf([lec(title="Lecture A unique"), lec(title="Lecture B unique")], "Module Foo 101"))
    t = text_of(data)
    assert data.startswith(b"%PDF")
    assert "Module Foo 101" in t and "Lecture A unique" in t and "Lecture B unique" in t


def test_module_pdf_empty_list_does_not_crash():
    assert run(P.render_module_pdf([], "Empty")).startswith(b"%PDF")


def test_no_remote_assets_in_html():
    html = P.build_lecture_html(lec())
    external = re.findall(r'(?:src|href)="(https?://[^"]+)"', html)
    assert all("lec_21.mp4" in u for u in external), external


# ---------------- TeX ----------------
def test_tex_basic_structure():
    s = X.export_tex(lec())
    assert s.startswith("\\documentclass")
    assert "\\begin{document}" in s and s.rstrip().endswith("\\end{document}")
    assert "characteristic equation" in s
    assert "\\det(A - \\lambda I) = 0" in s


def test_tex_escapes_specials():
    s = X.export_tex(lec())
    assert "50\\%" in s
    assert "\\&" in s
    assert "\\#" in s


def test_tex_draft_marks():
    assert "DRAFT" in X.export_tex(lec())
    body = X.export_tex(verified(lec(status=LectureStatus.VERIFIED))).split("\\begin{document}")[1]
    assert "DRAFT" not in body


@pytest.mark.parametrize(
    "evil",
    [r"\write18{rm -rf /}", r"\input{/etc/passwd}", r"\immediate\write18{id}", r"\openin1=/etc/passwd", r"\catcode`\%=12", r"\def\x{y}", r"\usepackage{shellesc}"],
)
def test_tex_dangerous_latex_neutralised(evil):
    l = lec()
    s = l.sections[0].model_copy(update={"bullets": [bullet("e", 1, "t", latex=evil, ranges=[(1.0, 2.0)])]})
    body = X.export_tex(l.model_copy(update={"sections": [s]})).split("\\begin{document}")[1]
    stripped = body.replace("\\textbackslash{}", "")
    for cmd in ("\\write18", "\\input{", "\\openin", "\\catcode", "\\def", "\\usepackage"):
        assert cmd not in stripped.replace("\\detokenize", ""), (cmd, body)
        assert cmd not in body or "\\texttt" in body or "\\textbackslash" in body


def test_tex_evil_text_escaped():
    l = lec()
    s = l.sections[0].model_copy(update={"heading": r"\input{/etc/passwd} $x$ ~ ^ _", "bullets": [bullet("e", 1, r"\write18{x} {}", ranges=[(1.0, 2.0)])]})
    out = X.export_tex(l.model_copy(update={"sections": [s]}))
    body = out.split("\\begin{document}")[1]
    assert "\\input{/etc" not in body
    assert "\\write18" not in body


def test_tex_unsafe_url_not_linked():
    assert "javascript:" not in X.export_tex(with_video(lec(), "javascript:alert(1)"))


def test_tex_unbalanced_math_does_not_break_doc():
    l = lec()
    s = l.sections[0].model_copy(update={"bullets": [bullet("e", 1, "t", latex=r"\frac{a}{", ranges=[(1.0, 2.0)])]})
    out = X.export_tex(l.model_copy(update={"sections": [s]}))
    assert out.count("\\begin{document}") == 1 and out.count("\\end{document}") == 1


def test_tex_empty_lecture():
    assert "\\end{document}" in X.export_tex(lec().model_copy(update={"sections": []}))


def _compile(tmp_path, source: str):
    (tmp_path / "n.tex").write_text(source)
    return subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "n.tex"],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )


needs_latex = pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")


@needs_latex
def test_tex_compiles(tmp_path):
    r = _compile(tmp_path, X.export_tex(lec()))
    assert r.returncode == 0, r.stdout[-1500:]
    assert (tmp_path / "n.pdf").exists()


@needs_latex
def test_tex_with_hostile_content_compiles(tmp_path):
    l = lec(title="A_B & C% #D {E} ~ ^ \\ $")
    s = l.sections[0].model_copy(
        update={
            "bullets": [
                bullet("e", 1, "α β ≤ — “quoted” _x_ ^y", latex=r"\frac{a}{", ranges=[(1.0, 2.0)]),
                bullet("f", 2, "t", latex=r"\write18{id}", ranges=[(1.0, 2.0)]),
            ]
        }
    )
    r = _compile(tmp_path, X.export_tex(l.model_copy(update={"sections": [s]})))
    assert r.returncode == 0, r.stdout[-1500:]
