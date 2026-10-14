# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Rewrite Maxima's ``tex1`` output into LaTeX that browser math renderers accept.

Maxima still emits a few plain-TeX constructs (``{a}\\over{b}``, ``\\pmatrix``
behind an ``\\ifx`` guard, ``{\\it x}``, ``\\mbox``).  Renderers such as
MathLive and KaTeX implement the LaTeX/amsmath forms, so convert them here.
"""

from __future__ import annotations

import re

_PMATRIX_OPEN = r"\ifx\endpmatrix\undefined\pmatrix{\else\begin{pmatrix}\fi"
_PMATRIX_CLOSE = r"\ifx\endpmatrix\undefined}\else\end{pmatrix}\fi"


def _match_brace(s: str, i: int) -> int:
    """Index of the ``}`` matching the ``{`` at ``s[i]`` (or -1)."""
    depth = 0
    j = i
    while j < len(s):
        ch = s[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def _top_level_over(s: str) -> int:
    """Index of a ``\\over`` at brace depth 0 in ``s`` (or -1)."""
    depth, i = 0, 0
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            if depth == 0 and s.startswith(r"\over", i) and not s[i + 5:i + 6].isalpha():
                return i
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return -1


def _unwrap(s: str) -> str:
    s = s.strip()
    if s.startswith("{") and _match_brace(s, 0) == len(s) - 1:
        return s[1:-1]
    return s


def _rewrite_over(s: str) -> str:
    """``{{num}\\over{den}}`` -> ``\\frac{num}{den}``, working on brace groups
    recursively so nested fractions come out right."""
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            out.append(s[i:i + 2])
            i += 2
        elif ch == "{":
            j = _match_brace(s, i)
            if j < 0:
                out.append(s[i:])  # malformed; leave untouched rather than guess
                break
            inner = _rewrite_over(s[i + 1:j])
            k = _top_level_over(inner)
            if k >= 0:
                out.append(r"\frac{" + _unwrap(inner[:k]) + "}{" + _unwrap(inner[k + 5:]) + "}")
            else:
                out.append("{" + inner + "}")
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _rewrite_font_groups(s: str) -> str:
    """``{\\it name}`` -> ``\\mathit{name}`` and ``{\\rm x}`` -> ``\\mathrm{x}``."""
    for cmd, repl in ((r"\it ", r"\mathit"), (r"\rm ", r"\mathrm"), (r"\bf ", r"\mathbf")):
        pat = "{" + cmd
        while True:
            k = s.find(pat)
            if k < 0:
                break
            end = _match_brace(s, k)
            if end < 0:
                break
            inner = s[k + len(pat):end]
            s = s[:k] + repl + "{" + inner + "}" + s[end + 1:]
    return s


def _rewrite_mbox(s: str) -> str:
    r"""``\mbox{ text }`` -> ``\text{text}``; whitespace-only boxes become a space."""
    out = []
    i = 0
    while True:
        k = s.find(r"\mbox{", i)
        if k < 0:
            out.append(s[i:])
            return "".join(out)
        end = _match_brace(s, k + 5)
        if end < 0:
            out.append(s[i:])
            return "".join(out)
        inner = s[k + 6:end]
        out.append(s[i:k])
        if inner.strip():
            # keep word separation: Maxima pads text boxes with spaces
            out.append(r"\text{" + re.sub(r"\s+", " ", inner) + "}")
        else:
            out.append(r"\;")
        i = end + 1


def maxima_tex_to_latex(tex: str) -> str:
    s = tex.strip()
    if s.startswith("$$") and s.endswith("$$"):
        s = s[2:-2].strip()
    s = s.replace(_PMATRIX_OPEN, r"\begin{pmatrix}").replace(_PMATRIX_CLOSE, r"\end{pmatrix}")
    s = s.replace(r"\pmatrix{", r"\begin{pmatrix}")
    s = re.sub(r"\\cr\s*(?=\\end\{pmatrix\})", "", s)
    s = s.replace(r"\cr", r"\\")
    s = _rewrite_over(s)
    s = _rewrite_font_groups(s)
    s = _rewrite_mbox(s)
    return s.strip()
