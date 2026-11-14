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

_GREEK = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "varepsilon", "ζ": "zeta", "η": "eta",
    "θ": "theta", "ι": "iota", "κ": "kappa", "μ": "mu", "ν": "nu", "ξ": "xi", "π": "pi", "ρ": "rho",
    "σ": "sigma", "τ": "tau", "υ": "upsilon", "φ": "varphi", "χ": "chi", "ψ": "psi", "ω": "omega",
    "Γ": "Gamma", "Δ": "Delta", "Θ": "Theta", "Λ": "Lambda", "Ξ": "Xi", "Π": "Pi", "Σ": "Sigma",
    "Φ": "Phi", "Ψ": "Psi", "Ω": "Omega",
    "≈": "approx", "∞": "infty", "∂": "partial", "∇": "nabla", "∑": "sum", "∫": "int", "√": "surd",
    "±": "pm", "∈": "in", "∀": "forall", "∃": "exists", "∝": "propto", "≡": "equiv", "←": "leftarrow",
    "⇒": "Rightarrow", "⇔": "Leftrightarrow",
}  # fmt: skip
_UNICODE.update({ch: "$\\" + name + "$" for ch, name in _GREEK.items()})

# Formulas are untrusted. Only these control words may appear in a formula; anything else (\input, \write18, ...)
# makes the whole formula fall back to an escaped monospace line.
_MATH_COMMANDS = frozenset(
    """alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi varpi rho
    sigma varsigma tau upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega
    frac dfrac tfrac sqrt sum prod int oint lim limsup liminf sup inf max min log ln exp sin cos tan cot sec csc
    arcsin arccos arctan sinh cosh tanh det dim ker deg gcd arg mod bmod pmod Pr
    cdot cdots ldots dots vdots ddots times div pm mp ast star circ bullet oplus otimes
    leq geq neq approx sim simeq cong equiv propto ll gg le ge ne
    in notin subset supset subseteq supseteq cup cap setminus emptyset varnothing forall exists nexists neg land lor
    to rightarrow leftarrow leftrightarrow Rightarrow Leftarrow Leftrightarrow mapsto implies iff
    infty partial nabla prime hbar ell angle perp parallel mid
    left right big Big bigg Bigg langle rangle lceil rceil lfloor rfloor
    hat bar vec tilde dot ddot overline underline widehat widetilde overbrace underbrace
    mathbf mathrm mathcal mathbb mathit mathsf mathtt boldsymbol text textbf textit operatorname
    binom choose quad qquad begin end""".split()
)
_MATH_ENVS = frozenset({"matrix", "pmatrix", "bmatrix", "vmatrix", "Vmatrix", "cases", "aligned", "array"})
_CONTROL = re.compile(r"\\([A-Za-z]+|.)", re.DOTALL)
_BEGIN_END = re.compile(r"\\(?:begin|end)(?![A-Za-z])")
_BEGIN_END_ENV = re.compile(r"\\(?:begin|end)(?![A-Za-z])\s*\{([^{}]*)\}")
_SAFE_SYMBOLS = frozenset(" ,;:!{}|\\")  # \, \; \: \! \{ \} \| \\ and "\ " (control space)


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
        elif ord(ch) > 0x17F:
            out.append("?")  # outside what pdflatex (T1 + utf8) can print without extra setup
        else:
            out.append(ch)
    return "".join(out)


def safe_math(latex: str) -> str | None:
    r"""Return the formula if it is safe to embed in display maths, else None.

    Allowlist: printable ASCII only, no `$ % # @ ^^`, every control word in _MATH_COMMANDS, only maths
    environments, and no \[ \] \( \) (which could close or open maths mode).
    """
    latex = latex.strip()
    if not latex or not all(" " <= ch < "\x7f" for ch in latex):
        return None
    if any(bad in latex for bad in ("$", "%", "#", "@", "^^")):
        return None
    for m in _CONTROL.finditer(latex):
        name = m.group(1)
        if name.isalpha():
            if name not in _MATH_COMMANDS:
                return None
        elif name not in _SAFE_SYMBOLS:
            return None
    envs = [m.group(1) for m in _BEGIN_END_ENV.finditer(latex)]
    if any(e not in _MATH_ENVS for e in envs) or len(envs) != len(_BEGIN_END.findall(latex)):
        return None  # unknown environment, or \begin / \end without a plain {env} argument
    depth = 0
    for m in re.finditer(r"\\.|[{}]", latex):
        tok = m.group(0)
        depth += (tok == "{") - (tok == "}")
        if depth < 0:
            return None
    return latex if depth == 0 else None


def _href(url: str) -> str:
    """URL for \\href: drop or escape the characters that are special inside its argument."""
    return url.replace("\\", "").replace("{", "").replace("}", "").replace("%", r"\%").replace("#", r"\#")


def _stamp(link: str | None, seconds: float) -> str:
    return f" \\href{{{_href(link)}}}{{[{format_time(seconds)}]}}" if link else ""


def export_tex(lecture: LectureDetail, include_drafts: bool = True) -> str:
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
        if not include_drafts and section.status != SectionStatus.VERIFIED:
            continue
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
