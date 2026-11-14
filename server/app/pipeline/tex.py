"""Stage: export lecture notes as a compilable LaTeX article.

Plain text is escaped for LaTeX (note text is untrusted). Formulas go in display maths verbatim, but only if they
pass a conservative check: anything that could run commands (\\input, \\write, ...) falls back to an escaped
monospace line instead.
"""

import re

from app.contracts.api import LectureDetail
from app.contracts.enums import LectureStatus, SectionStatus
from app.pipeline.pdf import bullet_time, format_time, safe_video_url, status_label, timestamp_link

_SPECIAL = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "%": r"\%",
    "_": r"\_",
    "^": r"\textasciicircum{}",
    "~": r"\textasciitilde{}",
}
# Characters pdflatex (T1 + utf8) cannot print by default: map the common ones used in maths-flavoured prose.
_UNICODE = {
    "−": "-",
    "–": "--",
    "—": "---",
    "‘": "`",
    "’": "'",
    "“": "``",
    "”": "''",
    "λ": r"$\lambda$",
    "≠": r"$\neq$",
    "≤": r"$\leq$",
    "≥": r"$\geq$",
    "×": r"$\times$",
    "→": r"$\to$",
    "·": r"$\cdot$",
}

_DANGEROUS = re.compile(
    r"\\(input|include|write|read|openin|openout|immediate|catcode|def|edef|gdef|csname|usepackage|"
    r"newcommand|renewcommand|special|href|url|verb)\b|%"
)


def escape_tex(text: str) -> str:
    """Escape LaTeX special characters in plain text."""
    out: list[str] = []
    for ch in text:
        if ch in _SPECIAL:
            out.append(_SPECIAL[ch])
        elif ch in _UNICODE:
            out.append(_UNICODE[ch])
        elif ord(ch) < 32:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def safe_math(latex: str) -> str | None:
    """Return the formula if it is safe to embed in display maths, else None."""
    latex = latex.strip()
    if not latex or _DANGEROUS.search(latex) or "$" in latex:
        return None
    depth = 0
    for ch in latex:
        depth += (ch == "{") - (ch == "}")
        if depth < 0:
            return None
    return latex if depth == 0 else None


def _href(url: str) -> str:
    """URL for \\href: drop or escape the characters that are special inside its argument."""
    return url.replace("\\", "").replace("{", "").replace("}", "").replace("%", r"\%").replace("#", r"\#")


def _stamp(link: str | None, seconds: float) -> str:
    return f" \\href{{{_href(link)}}}{{[{format_time(seconds)}]}}" if link else ""


def export_tex(lecture: LectureDetail) -> str:
    """Pipeline stage: one lecture's notes as a complete LaTeX document."""
    video_url = safe_video_url(lecture.video_url)
    first_seen = {b.id: b.first_seen_s for b in lecture.board_blocks}
    status = lecture.summary.status
    lines = [
        r"\documentclass[11pt,a4paper]{article}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage{lmodern,amsmath,amssymb,hyperref,xcolor}",
        r"\usepackage[margin=25mm]{geometry}",
        r"\hypersetup{colorlinks=true,linkcolor=blue,urlcolor=blue}",
        r"\newcommand{\draftmark}{\textcolor{orange}{\textbf{DRAFT $\cdot$ not yet verified}}}",
        f"\\title{{{escape_tex(lecture.summary.title)}}}",
        f"\\author{{{escape_tex(status_label(status))}}}",
        r"\date{}",
        r"\begin{document}",
        r"\maketitle",
    ]
    if status != LectureStatus.VERIFIED:
        lines.append(r"\noindent\draftmark" + "\n")
    for section in sorted(lecture.sections, key=lambda s: s.order):
        lines.append(f"\\section{{{escape_tex(section.heading)}}}")
        if section.status != SectionStatus.VERIFIED:
            lines.append(r"\noindent\draftmark")
        lines.append(r"\begin{itemize}")
        for b in sorted(section.bullets, key=lambda b: b.order):
            item = r"\item " + escape_tex(b.text)
            if b.uncertain:
                item += r" \textit{(uncertain)}"
            t = bullet_time(b, first_seen)
            if t is not None:
                item += _stamp(timestamp_link(video_url, t), t)
            lines.append(item)
            math = safe_math(b.latex) if b.latex else None
            if math:
                lines.append("\\[\n" + math + "\n\\]")
            elif b.latex and b.latex.strip():
                lines.append(r"\texttt{" + escape_tex(b.latex.strip()) + "}")
        lines.append(r"\end{itemize}")
        for n in section.said_not_written:
            lines.append(
                f"\\par\\noindent\\textit{{Said but not written:}} {escape_tex(n.text)}{_stamp(timestamp_link(video_url, n.at_s), n.at_s)}"
            )
        lines.append("")
    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"
