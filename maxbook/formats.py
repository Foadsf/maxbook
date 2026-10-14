# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Import and export: wxMaxima (.wxm/.wxmx), Maxima batch (.mac), Markdown, LaTeX."""

from __future__ import annotations

import base64
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .notebook import make_cell
from .splitter import SplitError, split_statements

# ======================================================================= import
_WXM_BLOCK = re.compile(
    r"/\* \[wxMaxima: (?P<kind>[a-z0-9]+)\s+start \]\s*(?:\*/)?\n(?P<body>.*?)\n?\s*"
    r"(?:/\* )?\[wxMaxima: (?P=kind)\s+end\s*\] \*/",
    re.DOTALL,
)
_WXM_HEADINGS = {"title": "#", "section": "##", "subsect": "###", "subsubsect": "####",
                 "heading5": "#####", "heading6": "######"}


def import_wxm(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    if "[wxMaxima batch file" not in text[:200]:
        raise ValueError("not a wxMaxima batch file (.wxm)")
    cells = []
    for m in _WXM_BLOCK.finditer(text):
        kind, body = m.group("kind"), m.group("body").strip("\n")
        if kind == "input":
            cells.append(make_cell("code", body.strip()))
        elif kind in _WXM_HEADINGS:
            cells.append(make_cell("markdown", f"{_WXM_HEADINGS[kind]} {body.strip()}"))
        elif kind in ("comment", "answer", "question"):
            cells.append(make_cell("markdown", body.strip()))
        # image, fold, page break: no equivalent yet
    title = next((c["source"][2:] for c in cells if c["source"].startswith("# ")), path.stem)
    return {"title": title, "cells": cells or [make_cell("code", "")]}


def _xml_lines(editor: ElementTree.Element | None) -> str:
    if editor is None:
        return ""
    return "\n".join("".join(line.itertext()) for line in editor.iter("line"))


def import_wxmx(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        try:
            content = zf.read("content.xml")
        except KeyError as exc:
            raise ValueError("not a wxMaxima document (content.xml missing)") from exc
    root = ElementTree.fromstring(content)
    heading = {"title": "#", "section": "##", "subsection": "###", "subsubsection": "####",
               "heading5": "#####", "heading6": "######"}
    cells = []
    for cell in root.iter("cell"):
        kind = cell.get("type", "")
        if kind == "code":
            src = _xml_lines(cell.find("input/editor"))
            cells.append(make_cell("code", src.strip()))
        elif kind in heading:
            cells.append(make_cell("markdown", f"{heading[kind]} {_xml_lines(cell.find('editor')).strip()}"))
        elif kind == "text":
            cells.append(make_cell("markdown", _xml_lines(cell.find("editor")).strip()))
    title = next((c["source"][2:] for c in cells if c["source"].startswith("# ")), path.stem)
    return {"title": title, "cells": cells or [make_cell("code", "")]}


def import_mac(path: Path) -> dict:
    """Standalone comments become text cells; code between them becomes code cells."""
    text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    cells = []
    code: list[str] = []

    def flush_code() -> None:
        src = "\n".join(code).strip()
        if src:
            cells.append(make_cell("code", src))
        code.clear()

    pos = 0
    for m in re.finditer(r"(?m)^[ \t]*/\*(.*?)\*/[ \t]*$", text, re.DOTALL):
        code.append(text[pos:m.start()])
        flush_code()
        comment = re.sub(r"(?m)^[ \t]*\*[ \t]?", "", m.group(1)).strip()
        if comment:
            cells.append(make_cell("markdown", comment))
        pos = m.end()
    code.append(text[pos:])
    flush_code()
    return {"title": path.stem, "cells": cells or [make_cell("code", "")]}


def import_markdown(path: Path) -> dict:
    """```maxima fences become code cells; everything else stays Markdown."""
    text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    cells = []
    pos = 0
    fence = re.compile(r"(?ms)^```(?:maxima|mac)\s*\n(.*?)^```\s*$")
    for m in fence.finditer(text):
        md = text[pos:m.start()].strip()
        if md:
            cells.append(make_cell("markdown", md))
        cells.append(make_cell("code", m.group(1).strip()))
        pos = m.end()
    md = text[pos:].strip()
    if md:
        cells.append(make_cell("markdown", md))
    title = path.stem
    first = cells[0]["source"] if cells else ""
    if first.startswith("# "):
        title = first.splitlines()[0][2:].strip()
    return {"title": title, "cells": cells or [make_cell("code", "")]}


IMPORTERS = {".wxm": import_wxm, ".wxmx": import_wxmx, ".mac": import_mac,
             ".md": import_markdown, ".markdown": import_markdown}


# ======================================================================= export
def cell_maxima_source(cell: dict) -> str:
    return cell.get("source", "").strip()


def export_mac(nb: dict) -> str:
    parts = [f"/* {nb.get('title', 'Untitled')} -- exported from Maxbook */"]
    for cell in nb["cells"]:
        if cell["type"] == "markdown":
            body = cell["source"].strip().replace("*/", "* /")
            if body:
                parts.append("/*\n" + body + "\n*/")
        else:
            src = cell_maxima_source(cell)
            if src:
                # batch() needs every statement terminated, as the notebook assumes
                try:
                    src = "\n".join(s.text for s in split_statements(src))
                except SplitError:
                    pass  # keep the user's text; Maxima will report the problem
                parts.append(src)
    return "\n\n".join(parts) + "\n"


def export_wxm(nb: dict) -> str:
    out = ["/* [wxMaxima batch file version 1] [ DO NOT EDIT BY HAND! ]*/",
           "/* [ Created with Maxbook ] */", ""]
    rev = {v: k for k, v in _WXM_HEADINGS.items()}
    for cell in nb["cells"]:
        if cell["type"] == "markdown":
            src = cell["source"].strip()
            m = re.match(r"^(#{1,6})\s+(.*)$", src)
            if m and "\n" not in src:
                kind = rev.get(m.group(1), "section")
                body = m.group(2)
            else:
                kind, body = "comment", src
            if not body:
                continue
            body = body.replace("*/", "* /")
            out += [f"/* [wxMaxima: {kind:<7} start ]", body, f"   [wxMaxima: {kind:<7} end   ] */", ""]
        else:
            src = cell_maxima_source(cell)
            if not src:
                continue
            out += ["/* [wxMaxima: input   start ] */", src, "/* [wxMaxima: input   end   ] */", ""]
    out += ["", "/* Old versions of Maxima abort on loading files that end in a comment. */",
            '"Created with Maxbook"$', ""]
    return "\n".join(out)


def _md_image(output: dict) -> str:
    mime, data = output.get("mime", ""), output.get("data", "")
    if mime == "image/svg+xml":
        data = base64.b64encode(data.encode("utf-8")).decode("ascii")
    return f"![plot](data:{mime};base64,{data})"


def export_markdown(nb: dict) -> str:
    parts = []
    for cell in nb["cells"]:
        if cell["type"] == "markdown":
            parts.append(cell["source"].strip())
            continue
        if cell["type"] == "math" and cell.get("latex"):
            parts.append("$$\n" + cell["latex"] + "\n$$")
        src = cell_maxima_source(cell)
        if src:
            parts.append("```maxima\n" + src + "\n```")
        for out in cell.get("outputs", []):
            kind = out.get("kind")
            if kind == "result" and out.get("latex"):
                label = out.get("label", "")
                tag = f"\\tag*{{({label.replace('%', chr(92) + '%')})}}" if label else ""
                parts.append("$$\n" + out["latex"] + tag + "\n$$")
            elif kind in ("text", "error"):
                parts.append("```text\n" + out.get("text", "") + "\n```")
            elif kind == "image":
                parts.append(_md_image(out))
    return "\n\n".join(p for p in parts if p) + "\n"


# --------------------------------------------------------------- markdown->tex
_TEX_SPECIAL = {"\\": r"\textbackslash{}", "#": r"\#", "$": r"\$", "%": r"\%", "&": r"\&",
                "~": r"\textasciitilde{}", "_": r"\_", "^": r"\textasciicircum{}",
                "{": r"\{", "}": r"\}"}


def tex_escape(text: str) -> str:
    return "".join(_TEX_SPECIAL.get(ch, ch) for ch in text)


def _inline_md_to_tex(text: str) -> str:
    """Inline Markdown (math, code, bold, italic, links) to LaTeX."""
    tokens: list[str] = []

    def stash(s: str) -> str:
        tokens.append(s)
        return f"\x00{len(tokens) - 1}\x00"

    text = re.sub(r"\$\$(.+?)\$\$", lambda m: stash(r"\[" + m.group(1) + r"\]"), text)
    text = re.sub(r"(?<!\\)\$(.+?)(?<!\\)\$", lambda m: stash("$" + m.group(1) + "$"), text)
    text = re.sub(r"`([^`]+)`", lambda m: stash(r"\texttt{" + tex_escape(m.group(1)) + "}"), text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: stash(r"\href{" + m.group(2).replace("%", r"\%").replace("#", r"\#") + "}{"
                                  + tex_escape(m.group(1)) + "}"), text)
    text = tex_escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\\emph{\1}", text)
    text = re.sub(r"(?<![\w\\])\\_(?!\s)(.+?)(?<!\s)\\_(?!\w)", r"\\emph{\1}", text)
    return re.sub("\x00(\\d+)\x00", lambda m: tokens[int(m.group(1))], text)


def markdown_to_latex(md: str) -> str:
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    list_env: str | None = None
    i = 0

    def flush_para() -> None:
        if para:
            out.append(_inline_md_to_tex(" ".join(p.strip() for p in para)))
            out.append("")
            para.clear()

    def close_list() -> None:
        nonlocal list_env
        if list_env:
            out.append(f"\\end{{{list_env}}}")
            out.append("")
            list_env = None

    sections = {1: "section*", 2: "section*", 3: "subsection*", 4: "subsubsection*",
                5: "paragraph*", 6: "subparagraph*"}
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_para()
            close_list()
            j = i + 1
            block = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                block.append(lines[j])
                j += 1
            out += [r"\begin{verbatim}", *block, r"\end{verbatim}", ""]
            i = j + 1
            continue
        if stripped.startswith("$$"):
            flush_para()
            close_list()
            body = stripped[2:]
            if body.endswith("$$") and len(body) >= 2:
                out += [r"\[", body[:-2], r"\]", ""]
                i += 1
                continue
            block = [body] if body else []
            j = i + 1
            while j < len(lines) and "$$" not in lines[j]:
                block.append(lines[j])
                j += 1
            if j < len(lines):
                block.append(lines[j].split("$$")[0])
            out += [r"\[", *[b for b in block if b.strip()], r"\]", ""]
            i = j + 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_para()
            close_list()
            level = len(m.group(1))
            if level == 1:
                out += [r"\begin{center}{\LARGE\bfseries " + _inline_md_to_tex(m.group(2)) + r"}\end{center}", ""]
            else:
                out += ["\\" + sections[level] + "{" + _inline_md_to_tex(m.group(2)) + "}", ""]
            i += 1
            continue
        m = re.match(r"^\s*([-*+]|\d+[.)])\s+(.*)$", line)
        if m:
            flush_para()
            env = "enumerate" if m.group(1)[0].isdigit() else "itemize"
            if list_env != env:
                close_list()
                out.append(f"\\begin{{{env}}}")
                list_env = env
            out.append(r"  \item " + _inline_md_to_tex(m.group(2)))
            i += 1
            continue
        if not stripped:
            flush_para()
            close_list()
        else:
            close_list()
            para.append(line)
        i += 1
    flush_para()
    close_list()
    return "\n".join(out).strip() + "\n"


LATEX_PREAMBLE = r"""\documentclass[11pt,a4paper]{article}
\usepackage{iftex}
\ifPDFTeX
  \usepackage[utf8]{inputenc}
  \usepackage[T1]{fontenc}
  \usepackage{lmodern}
\else
  \usepackage{fontspec}
\fi
\usepackage{amsmath,amssymb,mathtools}
% Macros used by the formula editor that are not part of standard LaTeX
\providecommand{\coloneq}{\mathrel{\vcentcolon=}}
\providecommand{\exponentialE}{\mathrm{e}}
\providecommand{\imaginaryI}{\mathrm{i}}
\providecommand{\differentialD}{\mathrm{d}}
\providecommand{\placeholder}[1][]{\square}
\usepackage{graphicx}
\usepackage[margin=2.5cm]{geometry}
\usepackage{xcolor}
\usepackage[hidelinks]{hyperref}
\setlength{\parindent}{0pt}
\setlength{\parskip}{0.6em}
\newcommand{\maxbookinput}[1]{\par\noindent{\color{gray}\small\texttt{#1}}\par}
"""


def export_latex(nb: dict, figure_names: dict[int, str] | None = None) -> str:
    """LaTeX document.  ``figure_names`` maps image ordinal -> graphics file."""
    title = nb.get("title", "Untitled")
    body: list[str] = []
    fig = 0
    figure_names = figure_names or {}
    for cell in nb["cells"]:
        if cell["type"] == "markdown":
            body.append(markdown_to_latex(cell["source"]))
            continue
        if cell["type"] == "math" and cell.get("latex"):
            body += [r"\[", cell["latex"], r"\]"]
        src = cell_maxima_source(cell)
        if src and cell["type"] == "code":
            body += [r"\begin{verbatim}", src, r"\end{verbatim}"]
        for out in cell.get("outputs", []):
            kind = out.get("kind")
            if kind == "result" and out.get("latex"):
                label = out.get("label", "")
                tag = rf"\tag*{{({tex_escape(label)})}}" if label else ""
                body += [r"\begin{equation*}", out["latex"] + tag, r"\end{equation*}"]
            elif kind in ("text", "error"):
                body += [r"\begin{verbatim}", out.get("text", ""), r"\end{verbatim}"]
            elif kind == "image":
                fig += 1
                name = figure_names.get(fig)
                if name:
                    body += [r"\begin{center}",
                             rf"\includegraphics[width=0.75\linewidth]{{{name}}}",
                             r"\end{center}"]
                else:
                    body.append(rf"\fbox{{Figure {fig} omitted: no raster version was provided}}")
        body.append("")
    first = next((c["source"].lstrip() for c in nb["cells"] if c["type"] == "markdown"), "")
    has_own_title = first.startswith("# ")
    head = [] if has_own_title else [rf"\title{{{tex_escape(title)}}}", r"\date{}"]
    doc = [LATEX_PREAMBLE, *head, r"\begin{document}",
           "" if has_own_title else r"\maketitle", "", *body, r"\end{document}", ""]
    return "\n".join(doc)


def write_latex_bundle(nb: dict, tex_path: Path, figures: list[str]) -> list[Path]:
    """Write ``name.tex`` plus PNG figures (data URLs from the front end)."""
    tex_path = Path(tex_path)
    written = []
    names: dict[int, str] = {}
    fig_dir = tex_path.with_name(tex_path.stem + "-figures")
    for i, data_url in enumerate(figures, start=1):
        m = re.match(r"data:image/png;base64,(.+)$", data_url or "", re.DOTALL)
        if not m:
            continue
        fig_dir.mkdir(parents=True, exist_ok=True)
        p = fig_dir / f"figure{i}.png"
        p.write_bytes(base64.b64decode(m.group(1)))
        written.append(p)
        names[i] = f"{fig_dir.name}/{p.name}"
    tex_path.write_text(export_latex(nb, names), encoding="utf-8")
    written.insert(0, tex_path)
    return written


EXPORTERS = {"mac": (".mac", export_mac), "wxm": (".wxm", export_wxm),
             "md": (".md", export_markdown), "tex": (".tex", export_latex)}

__all__ = ["EXPORTERS", "IMPORTERS", "export_latex", "markdown_to_latex", "write_latex_bundle"]
