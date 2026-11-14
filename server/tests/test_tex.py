import shutil
import subprocess
from pathlib import Path

import pytest

from app.contracts.enums import LectureStatus
from app.pipeline.tex import escape_tex, export_tex, safe_math
from tests.factories import sample_lecture


def test_escape_specials() -> None:
    got = escape_tex(r"50% of $x_1 & #2 {a} ~ ^ \n")
    assert got == r"50\% of \$x\_1 \& \#2 \{a\} \textasciitilde{} \textasciicircum{} \textbackslash{}n"


def test_safe_math() -> None:
    assert safe_math(r"\det(A - \lambda I) = 0") is not None
    assert safe_math(r"\input{/etc/passwd}") is None
    assert safe_math(r"\frac{a}{b") is None
    assert safe_math("x $ y") is None


def test_structure() -> None:
    tex = export_tex(sample_lecture())
    assert tex.startswith(r"\documentclass")
    assert tex.rstrip().endswith(r"\end{document}")
    assert tex.count(r"\begin{itemize}") == tex.count(r"\end{itemize}") >= 2
    assert r"\section{" in tex
    assert r"\det(A - \lambda I) = 0" in tex and "\\[" in tex
    assert r"\href{https://example.org/media/lec_21.mp4\#t=2010.5}{[33:30]}" in tex
    assert r"\draftmark" in tex


def test_untrusted_title_escaped() -> None:
    tex = export_tex(sample_lecture(title=r"\input{x} & 100%"))
    assert r"\title{\textbackslash{}input\{x\} \& 100\%}" in tex


def test_verified_lecture_has_no_front_draft_mark() -> None:
    head = export_tex(sample_lecture(LectureStatus.VERIFIED)).split(r"\maketitle")[1].split(r"\section")[0]
    assert "draftmark" not in head


@pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not installed")
def test_compiles(tmp_path: Path) -> None:
    (tmp_path / "n.tex").write_text(export_tex(sample_lecture()), encoding="utf-8")
    cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "n.tex"]
    r = subprocess.run(cmd, cwd=tmp_path, capture_output=True, timeout=120)  # noqa: S603
    assert r.returncode == 0, r.stdout.decode()[-800:]


@pytest.mark.parametrize(
    "evil",
    [
        r"\write18{id}",
        r"\input1",
        r"\InputIfFileExists{x}{}{}",
        r"\scantokens{x}",
        r"\newread\x",
        r"x \] \input{/etc/passwd} \[",
        r"\(x\)",
        r"^^5cinput{/etc/passwd}",
        r"\let\a\b",
        r"\expandafter\x",
        r"\begin{verbatim}x\end{verbatim}",
        "é",
        r"a_@",
    ],
)
def test_safe_math_rejects(evil: str) -> None:
    assert safe_math(evil) is None


def test_safe_math_accepts_normal_formulas() -> None:
    for f in [r"\det(A - \lambda I) = 0", r"\frac{a}{b} \, x^2", r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}"]:
        assert safe_math(f) == f
