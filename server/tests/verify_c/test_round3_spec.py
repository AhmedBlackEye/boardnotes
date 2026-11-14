"""V2 round 2 (post-fix): C1 control characters, formula balance, module limits."""

import asyncio
import re

import pytest

from app.pipeline import pdf as P
from app.pipeline import tex as X
from tests.factories import bullet, sample_lecture


def _lecture_with(text: str, latex: str | None = None):
    l = sample_lecture()
    s = l.sections[0].model_copy(update={"bullets": [bullet("e", 1, text, latex=latex, ranges=[(1.0, 2.0)])]})
    return l.model_copy(update={"sections": [s]})


@pytest.mark.parametrize("ch", ["\x85", "\x9b", "\x00", "\x1b", "‮", " "])
def test_control_chars_do_not_crash_tex_or_html(ch):
    l = _lecture_with(f"a{ch}b <script>alert(1)</script>")
    body = X.export_tex(l).split("\\begin{document}")[1]
    assert not re.search(r"(?<!\\)\\input", body)
    html = P.build_lecture_html(l)
    assert "<script>alert(1)" not in html


@pytest.mark.parametrize("latex", ["x^{2", "}{x", "\\frac{a}{b", "a}b{", "\\left( x", "{{{{", "}}}}"])
def test_unbalanced_formula_keeps_document_balanced(latex):
    out = X.export_tex(_lecture_with("t", latex=latex))
    body = out.split("\\begin{document}")[1]
    assert body.count("\\end{document}") == 1
    stripped = re.sub(r"\\[{}]", "", body)
    assert stripped.count("{") == stripped.count("}")


def test_module_pdf_limit_rejects_huge_lists():
    ls = [sample_lecture()] * (P.MAX_MODULE_LECTURES + 1)
    with pytest.raises(ValueError):
        asyncio.run(P.render_module_pdf(ls, "M"))


def test_module_html_title_escaped():
    html = P.build_module_html([], "<img src=x onerror=alert(1)>")
    assert "<img src=x" not in html
