"""V2 round 2: hostile formula / URL / transcript edge cases, from the spec (untrusted text must be inert)."""

import asyncio
import re

import pytest

from app.pipeline import pdf as P
from app.pipeline import tex as X
from tests.factories import bullet, sample_lecture


def tex_with_latex(latex: str) -> str:
    l = sample_lecture()
    s = l.sections[0].model_copy(update={"bullets": [bullet("e", 1, "t", latex=latex, ranges=[(1.0, 2.0)])]})
    return X.export_tex(l.model_copy(update={"sections": [s]})).split("\\begin{document}")[1]


def raw_commands(body: str) -> set[str]:
    """Control words that remain live (not preceded by an escaping backslash)."""
    return set(re.findall(r"(?<!\\)\\([A-Za-z]+)", body))


FORBIDDEN = {"input", "include", "write", "immediate", "openin", "openout", "read", "catcode", "def", "edef", "gdef",
             "xdef", "let", "csname", "usepackage", "newcommand", "renewcommand", "verbatiminput", "lstinputlisting",
             "directlua", "scantokens", "expandafter", "newwrite", "closeout", "special", "jobname",
             "verb", "makeatletter", "endinput", "everyeof", "IfFileExists"}


@pytest.mark.parametrize(
    "evil",
    [
        r"^^5cinput{/etc/passwd}",
        r"\^^5cinput{/etc/passwd}",
        r"x^^M\input{x}",
        r"\makeatletter\@input{/etc/passwd}",
        r"\@@input{x}",
        r"\[ \input{x} \]",
        r"\( \write18{id} \)",
        r"$$ \input{x} $$",
        r"\end{document}\input{/etc/passwd}",
        r"\begin{verbatim}\end{verbatim}",
        r"\begin{document}",
        r"\text{\input{/etc/passwd}}",
        r"\textbf{\write18{id}}",
        r"\operatorname{\input{x}}",
        r"\csname input\endcsname{x}",
        r"\expandafter\input\csname x\endcsname",
        r"\verb|x|",
        r"\newcommand{\x}{\input{x}}",
        r"x % comment \end{equation*}",
        r"\begin{matrix}\input{x}\end{matrix}",
        r"\begin{lstlisting}",
        r"\begin{aligned}\write18{id}\end{aligned}",
        "\\in\x00put{x}",
        "\\input\n{x}",
        "\\ input{x}",
        r"\input {x}",
        r"\IfFileExists{/etc/passwd}{\input{/etc/passwd}}{}",
        r"\directlua{os.execute('id')}",
        r"\catcode`\\=12 \input x",
        r"\scantokens{\input x}",
    ],
)
def test_hostile_formula_leaves_no_live_dangerous_command(evil):
    body = tex_with_latex(evil)
    live = raw_commands(body)
    assert not (live & FORBIDDEN), (live & FORBIDDEN, body)
    assert body.count("\\end{document}") == 1


def test_formula_cannot_close_document_early():
    body = tex_with_latex(r"\end{document}")
    assert body.count("\\end{document}") == 1
    assert body.rstrip().endswith("\\end{document}")


def test_benign_formulas_are_kept_as_math():
    for f in [r"\frac{a}{b}", r"\lambda_1 + \cdots + \lambda_n = \operatorname{tr}(A)", r"x^2 + y^2 = r^2",
              r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}", r"\sum_{i=1}^{n} i"]:
        body = tex_with_latex(f)
        assert f in body, (f, body)


def test_href_url_cannot_break_out():
    l = sample_lecture().model_copy(update={"video_url": "https://example.com/v?a=1&b=%25}{\\input{x}#frag"})
    out = X.export_tex(l)
    assert not (raw_commands(out.split("\\begin{document}")[1]) & {"input", "write", "immediate"})
    for m in re.finditer(r"\\href\{([^}]*)\}", out):
        assert " " not in m.group(1)


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "data:text/html,x", "file:///etc/passwd", "vbscript:x", "JaVaScRiPt:x", ""]
)
def test_unsafe_video_urls_never_linked(url):
    l = sample_lecture().model_copy(update={"video_url": url})
    out = X.export_tex(l)
    assert url.lower() not in out.lower() or url == ""
    html = P.build_lecture_html(l)
    assert not re.search(r'<a [^>]*href="\s*(javascript|data|file|vbscript):', html, re.I)


def test_timestamps_in_links_are_seconds_not_mmss():
    html = P.build_lecture_html(sample_lecture().model_copy(update={"video_url": "https://v.example/x.mp4"}))
    assert "#t=2512" in html
    assert "#t=41:52" not in html


def test_format_time_mmss():
    assert P.format_time(2512.0) == "41:52"


def test_title_with_tex_specials_is_inert():
    l = sample_lecture(title=r"A\input{x} & B_1 ^ 2 % c {")
    out = X.export_tex(l)
    assert not (raw_commands(out.split("\\begin{document}")[1]) & FORBIDDEN)
    assert not (raw_commands(out.split("\\begin{document}")[0].split("\\title")[-1]) & FORBIDDEN)


def test_pdf_html_escapes_formula_and_heading():
    l = sample_lecture()
    s = l.sections[0].model_copy(
        update={
            "heading": "<img src=x onerror=alert(1)>",
            "bullets": [bullet("e", 1, "<b>t</b>", latex="</script><script>alert(1)</script>", ranges=[(1.0, 2.0)])],
        }
    )
    html = P.build_lecture_html(l.model_copy(update={"sections": [s]}))
    assert "<img src=x" not in html
    assert "<script>alert(1)" not in html


def test_module_pdf_is_pdf_with_many_lectures():
    ls = [sample_lecture(title=f"Lecture {i}") for i in range(3)]
    data = asyncio.run(P.render_module_pdf(ls, "Module X"))
    assert data.startswith(b"%PDF")
