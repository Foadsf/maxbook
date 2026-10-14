# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Import and export.

Imports (.wxm, .wxmx, .mac, .md, .tex) produce the cell form of a notebook
(see :mod:`maxbook.notebook`); the editor turns that into a document.
Exports (.tex, .md, .mac, .wxm, .wxmx) read the version-2 document directly.
"""

from __future__ import annotations

import base64
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape as xml_escape

from . import document
from .document import inline_math_latex, plain_text
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


def _title_from(cells, fallback: str) -> str:
    return next((c["source"][2:].splitlines()[0] for c in cells if c["source"].startswith("# ")), fallback)


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
    return {"title": _title_from(cells, path.stem), "cells": cells or [make_cell("code", "")]}


def _xml_lines(editor: ElementTree.Element | None) -> str:
    if editor is None:
        return ""
    return "\n".join("".join(line.itertext()) for line in editor.iter("line"))


_WXMX_HEADINGS = {"title": "#", "section": "##", "subsection": "###", "subsubsection": "####",
                  "heading5": "#####", "heading6": "######"}


def import_wxmx(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        try:
            content = zf.read("content.xml")
        except KeyError as exc:
            raise ValueError("not a wxMaxima document (content.xml missing)") from exc
    root = ElementTree.fromstring(content)
    cells = []
    for cell in root.iter("cell"):
        kind = cell.get("type", "")
        if kind == "code":
            src = _xml_lines(cell.find("input/editor"))
            cells.append(make_cell("code", src.strip()))
        elif kind in _WXMX_HEADINGS:
            cells.append(make_cell("markdown", f"{_WXMX_HEADINGS[kind]} {_xml_lines(cell.find('editor')).strip()}"))
        elif kind == "text":
            cells.append(make_cell("markdown", _xml_lines(cell.find("editor")).strip()))
    return {"title": _title_from(cells, path.stem), "cells": cells or [make_cell("code", "")]}


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
    return markdown_to_cells(path.read_text(encoding="utf-8", errors="replace"), path.stem)


def markdown_to_cells(text: str, title: str = "Untitled") -> dict:
    text = text.replace("\r\n", "\n")
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
    return {"title": _title_from(cells, title), "cells": cells or [make_cell("code", "")]}


# ----------------------------------------------------------------- LaTeX import
_TEX_SECTIONS = {"part": "#", "chapter": "#", "section": "##", "subsection": "###",
                 "subsubsection": "####", "paragraph": "####"}
_TEX_DISPLAY_ENVS = ("equation", "equation*", "align", "align*", "gather", "gather*",
                     "multline", "multline*", "displaymath")


def _strip_tex_comments(text: str) -> str:
    return re.sub(r"(?m)(?<!\\)%.*$", "", text)


def _braced(text: str, i: int) -> tuple[str, int]:
    """Content of the brace group starting at text[i] == '{' and the index after it."""
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
        j += 1
    return text[i + 1:], len(text)


def _tex_inline_to_md(text: str) -> str:
    """Text-mode LaTeX to Markdown; math is kept as $...$."""
    out: list[str] = []
    i = 0
    simple = {"textbf": "**", "emph": "*", "textit": "*", "texttt": "`"}
    while i < len(text):
        c = text[i]
        if c == "$":
            j = text.find("$", i + 1)
            j = len(text) - 1 if j < 0 else j
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith(r"\(", i):
            j = text.find(r"\)", i)
            j = len(text) if j < 0 else j
            out.append("$" + text[i + 2:j] + "$")
            i = j + 2
        elif c == "\\":
            m = re.match(r"\\([A-Za-z]+)\*?\s*", text[i:])
            if not m:
                nxt = text[i + 1:i + 2]
                out.append({"\\": "\n", "%": "%", "&": "&", "_": "_", "#": "#", "$": r"\$",
                            "{": "{", "}": "}", " ": " "}.get(nxt, nxt))
                i += 2
                continue
            name = m.group(1)
            i += m.end()
            if i < len(text) and text[i] == "{":
                arg, i = _braced(text, i)
                inner = _tex_inline_to_md(arg)
                if name in simple:
                    out.append(simple[name] + inner + simple[name])
                elif name == "href" and i < len(text) and text[i] == "{":
                    label, i = _braced(text, i)
                    out.append(f"[{_tex_inline_to_md(label)}]({arg})")
                elif name in ("cite", "label", "ref", "eqref", "footnote", "index"):
                    out.append("" if name in ("label", "index") else f"[{name}: {arg}]")
                else:
                    out.append(inner)
            elif name in ("LaTeX", "TeX"):
                out.append(name)
            elif name in ("ldots", "dots"):
                out.append("…")
            # other argument-less commands (\noindent, \par, \maketitle, ...) are dropped
        elif c == "~":
            out.append(" ")
            i += 1
        elif c in "{}":
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def latex_to_cells(text: str, fallback_title: str = "Untitled") -> dict:
    """A practical subset of LaTeX: sections, paragraphs, lists, display math,
    verbatim and Maxima listings.  Unknown commands keep their text."""
    text = _strip_tex_comments(text.replace("\r\n", "\n"))
    title_m = re.search(r"\\title\s*\{", text)
    title = _tex_inline_to_md(_braced(text, title_m.end() - 1)[0]) if title_m else fallback_title
    body_m = re.search(r"\\begin\{document\}(.*?)(\\end\{document\}|\Z)", text, re.DOTALL)
    body = body_m.group(1) if body_m else text
    cells = []
    md: list[str] = []

    def flush() -> None:
        s = "\n\n".join(p.strip() for p in "\n".join(md).split("\n\n") if p.strip())
        if s:
            cells.append(make_cell("markdown", s))
        md.clear()

    if title_m and re.search(r"\\maketitle", body):
        md.append(f"# {title}")
    pattern = re.compile(
        r"\\(?P<sec>part|chapter|section|subsection|subsubsection|paragraph)\*?\s*\{"
        r"|\\begin\{(?P<env>[A-Za-z*]+)\}(?:\[(?P<opt>[^\]]*)\])?"
        r"|\\\[|\$\$")
    pos = 0
    while True:
        m = pattern.search(body, pos)
        if not m:
            md.append(_tex_inline_to_md(body[pos:]))
            break
        md.append(_tex_inline_to_md(body[pos:m.start()]))
        if m.group("sec"):
            heading, pos = _braced(body, m.end() - 1)
            md.append(f"\n\n{_TEX_SECTIONS[m.group('sec')]} {_tex_inline_to_md(heading).strip()}\n\n")
            continue
        token = m.group(0)
        if token in (r"\[", "$$"):
            close = r"\]" if token == r"\[" else "$$"
            end = body.find(close, m.end())
            end = len(body) if end < 0 else end
            md.append(f"\n\n$${body[m.end():end].strip()}$$\n\n")
            pos = end + len(close)
            continue
        env, opt = m.group("env"), m.group("opt") or ""
        end_tag = f"\\end{{{env}}}"
        end = body.find(end_tag, m.end())
        end = len(body) if end < 0 else end
        inner = body[m.end():end]
        pos = end + len(end_tag)
        if env in _TEX_DISPLAY_ENVS:
            content = re.sub(r"\\(label|nonumber|notag)\{?[^}\s]*\}?", "", inner).strip()
            if env.startswith("align") or env.startswith("gather") or env.startswith("multline"):
                content = r"\begin{aligned}" + content + r"\end{aligned}"
            md.append(f"\n\n$${content}$$\n\n")
        elif env in ("itemize", "enumerate"):
            items = [it.strip() for it in re.split(r"\\item\b", inner)[1:]]
            mark = "-" if env == "itemize" else "1."
            md.append("\n\n" + "\n".join(f"{mark} {_tex_inline_to_md(it)}" for it in items) + "\n\n")
        elif env in ("verbatim", "lstlisting", "minted"):
            if "maxima" in opt.lower():
                flush()
                cells.append(make_cell("code", inner.strip("\n")))
            else:
                md.append("\n\n```\n" + inner.strip("\n") + "\n```\n\n")
        elif env in ("quote", "quotation"):
            md.append("\n\n" + "\n".join("> " + ln for ln in _tex_inline_to_md(inner).strip().splitlines()) + "\n\n")
        elif env in ("abstract",):
            md.append("\n\n**Abstract.** " + _tex_inline_to_md(inner).strip() + "\n\n")
        else:
            md.append(_tex_inline_to_md(inner))
    flush()
    return {"title": title.strip() or fallback_title, "cells": cells or [make_cell("markdown", "")]}


def import_tex(path: Path) -> dict:
    return latex_to_cells(path.read_text(encoding="utf-8", errors="replace"), path.stem)


IMPORTERS = {".wxm": import_wxm, ".wxmx": import_wxmx, ".mac": import_mac,
             ".md": import_markdown, ".markdown": import_markdown, ".tex": import_tex}


# ======================================================================= export
def _doc(nb: dict) -> dict:
    if "doc" not in nb:
        raise ValueError("export needs a version-2 notebook")
    return nb["doc"]


def _statements(source: str) -> str:
    """Source with every statement terminated, as batch() requires."""
    try:
        return "\n".join(s.text for s in split_statements(source))
    except SplitError:
        return source  # keep the user's text; Maxima will report the problem


def _code_sources(node: dict):
    """Maxima statements in a block, in order: the block's own source and any
    computed inline formulas (definitions and "= Tab" results) inside it."""
    t = node.get("type")
    a = node.get("attrs", {})
    if t == "maxima" and a.get("source", "").strip():
        yield a["source"].strip()
    elif t == "math_block" and a.get("source", "").strip() and (a.get("run") or a.get("result")):
        yield a["source"].strip()
    elif t == "math_inline" and a.get("source", "").strip() and a.get("result"):
        yield a["source"].strip()
    for c in node.get("content", []) or []:
        yield from _code_sources(c)


def export_mac(nb: dict) -> str:
    doc = _doc(nb)
    parts = [f"/* {nb.get('title', 'Untitled')} -- exported from Maxbook */"]
    for block in document.walk_blocks(doc):
        if block["type"] not in document.EVALUATED:
            text = plain_text(block).strip().replace("*/", "* /")
            if text:
                parts.append("/* " + text + " */")
        parts.extend(_statements(s) for s in _code_sources(block))
    return "\n\n".join(parts) + "\n"


_WXM_KIND = {1: "title", 2: "section", 3: "subsect", 4: "subsubsect"}
_WXMX_KIND = {1: "title", 2: "section", 3: "subsection", 4: "subsubsection"}


def _wx_cells(doc: dict):
    """(kind, text) pairs in wxMaxima terms: heading levels, comment text, input."""
    for block in document.walk_blocks(doc):
        t = block["type"]
        if t == "heading":
            yield ("heading", block["attrs"]["level"]), plain_text(block).strip()
        elif t not in document.EVALUATED:
            text = plain_text(block).strip()
            if text:
                yield ("text", 0), text
        for src in _code_sources(block):
            yield ("input", 0), src


def export_wxm(nb: dict) -> str:
    out = ["/* [wxMaxima batch file version 1] [ DO NOT EDIT BY HAND! ]*/",
           "/* [ Created with Maxbook ] */", ""]
    for (kind, level), text in _wx_cells(_doc(nb)):
        if kind == "input":
            out += ["/* [wxMaxima: input   start ] */", text, "/* [wxMaxima: input   end   ] */", ""]
            continue
        tag = _WXM_KIND.get(level, "subsubsect") if kind == "heading" else "comment"
        body = text.replace("*/", "* /")
        out += [f"/* [wxMaxima: {tag:<7} start ]", body, f"   [wxMaxima: {tag:<7} end   ] */", ""]
    out += ["", "/* Old versions of Maxima abort on loading files that end in a comment. */",
            '"Created with Maxbook"$', ""]
    return "\n".join(out)


def _xml_editor(kind: str, text: str, level: int | None = None) -> str:
    lvl = f' sectioning_level="{level}"' if level else ""
    lines = "".join(f"<line>{xml_escape(ln)}</line>\n" for ln in text.split("\n"))
    return f'<editor type="{kind}"{lvl}>\n{lines}</editor>\n'


def export_wxmx(nb: dict) -> bytes:
    """A wxMaxima .wxmx document (zip): text, sections and input cells.
    Outputs are left for wxMaxima to recompute."""
    cells = []
    for (kind, level), text in _wx_cells(_doc(nb)):
        if kind == "input":
            cells.append(f'<cell type="code">\n<input>\n{_xml_editor("input", text)}</input>\n</cell>\n')
        elif kind == "heading":
            wk = _WXMX_KIND.get(level, "subsubsection")
            cells.append(f'<cell type="{wk}" sectioning_level="{level}">\n{_xml_editor(wk, text, level)}</cell>\n')
        else:
            cells.append(f'<cell type="text">\n{_xml_editor("text", text)}</cell>\n')
    content = ('<?xml version="1.0" encoding="UTF-8"?>\n\n<!--   Created using Maxbook   -->\n'
               '<wxMaximaDocument version="1.5" zoom="100">\n\n' + "\n".join(cells)
               + "\n</wxMaximaDocument>\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # The mimetype entry comes first and uncompressed, as in OpenDocument.
        zf.writestr(zipfile.ZipInfo("mimetype"), "text/x-wxmathml", compress_type=zipfile.ZIP_STORED)
        zf.writestr("format.txt", "This file is a wxMaxima document written by Maxbook.\n"
                                  "content.xml holds the cells; open it with wxMaxima.\n",
                    compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("content.xml", content, compress_type=zipfile.ZIP_DEFLATED)
    return buf.getvalue()


# ----------------------------------------------------------------- Markdown
_MD_ESCAPE = re.compile(r"([\\`*_\[\]<>#$|])")


def _md_inline(nodes) -> str:
    out = []
    for n in nodes or []:
        t = n["type"]
        if t == "text":
            marks = {m["type"]: m for m in n.get("marks", [])}
            if "code" in marks:
                s = "`" + n["text"] + "`"
            else:
                s = _MD_ESCAPE.sub(r"\\\1", n["text"])
            if "em" in marks:
                s = f"*{s}*"
            if "strong" in marks:
                s = f"**{s}**"
            if "link" in marks:
                s = f"[{s}]({marks['link']['attrs']['href']})"
            out.append(s)
        elif t == "hard_break":
            out.append("  \n")
        elif t == "math_inline":
            out.append(f"${inline_math_latex(n['attrs'])}$")
    return "".join(out)


def _md_image(output: dict) -> str:
    mime, data = output.get("mime", ""), output.get("data", "")
    if mime == "image/svg+xml":
        data = base64.b64encode(data.encode("utf-8")).decode("ascii")
    return f"![plot](data:{mime};base64,{data})"


def _md_outputs(outputs) -> list[str]:
    parts = []
    for out in outputs or []:
        kind = out.get("kind")
        if kind == "result" and out.get("latex"):
            label = out.get("label", "")
            tag = f"\\tag*{{({label.replace('%', chr(92) + '%')})}}" if label else ""
            parts.append("$$\n" + out["latex"] + tag + "\n$$")
        elif kind in ("text", "error"):
            parts.append("```text\n" + out.get("text", "") + "\n```")
        elif kind == "image":
            parts.append(_md_image(out))
    return parts


def _md_block(n: dict, indent: str = "") -> list[str]:
    t, a = n["type"], n.get("attrs", {})
    if t == "paragraph":
        return [indent + _md_inline(n.get("content"))]
    if t == "heading":
        return ["#" * a["level"] + " " + _md_inline(n.get("content"))]
    if t == "horizontal_rule":
        return ["---"]
    if t == "code_block":
        return [f"```{a.get('language', '')}\n{plain_text(n)}\n```"]
    if t == "blockquote":
        inner = "\n\n".join(p for c in n.get("content", []) for p in _md_block(c))
        return ["\n".join("> " + ln if ln else ">" for ln in inner.split("\n"))]
    if t in ("bullet_list", "ordered_list"):
        lines = []
        for k, item in enumerate(n.get("content", []), start=a.get("order", 1)):
            mark = f"{k}. " if t == "ordered_list" else "- "
            sub = [p for c in item.get("content", []) for p in _md_block(c)]
            text = "\n\n".join(sub)
            pad = " " * len(mark)
            lines.append(mark + text.replace("\n", "\n" + pad))
        return ["\n".join(lines)]
    if t == "maxima":
        parts = []
        if a.get("source", "").strip():
            parts.append("```maxima\n" + a["source"].strip() + "\n```")
        return parts + _md_outputs(a.get("outputs"))
    if t == "math_block":
        latex = inline_math_latex(a)
        parts = ["$$\n" + latex + "\n$$"] if latex.strip() else []
        return parts + _md_outputs(a.get("outputs"))
    return []


def export_markdown(nb: dict) -> str:
    parts = [p for b in document.walk_blocks(_doc(nb)) for p in _md_block(b)]
    return "\n\n".join(p for p in parts if p.strip()) + "\n"


# ----------------------------------------------------------------- LaTeX
_TEX_SPECIAL = {"\\": r"\textbackslash{}", "#": r"\#", "$": r"\$", "%": r"\%", "&": r"\&",
                "~": r"\textasciitilde{}", "_": r"\_", "^": r"\textasciicircum{}",
                "{": r"\{", "}": r"\}"}


# Characters pdfLaTeX's utf8 input (with T1 fonts) cannot typeset, written as
# commands instead.  Anything else outside the Latin ranges goes through
# \mbkchar, which XeLaTeX/LuaLaTeX print as is and pdfLaTeX shows as a visible
# [U+XXXX] marker, so an export always compiles and never drops text silently.
_GREEK = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa", "lambda",
          "mu", "nu", "xi", "o", "pi", "rho", "varsigma", "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega"]
_TEX_UNICODE = {
    "×": r"\ensuremath{\times}", "÷": r"\ensuremath{\div}", "−": r"\ensuremath{-}", "∓": r"\ensuremath{\mp}",
    "→": r"\ensuremath{\rightarrow}", "←": r"\ensuremath{\leftarrow}", "↔": r"\ensuremath{\leftrightarrow}",
    "⇒": r"\ensuremath{\Rightarrow}", "⇐": r"\ensuremath{\Leftarrow}", "⇔": r"\ensuremath{\Leftrightarrow}",
    "≤": r"\ensuremath{\leq}", "≥": r"\ensuremath{\geq}", "≠": r"\ensuremath{\neq}", "≈": r"\ensuremath{\approx}",
    "≡": r"\ensuremath{\equiv}", "∞": r"\ensuremath{\infty}", "∑": r"\ensuremath{\sum}", "∏": r"\ensuremath{\prod}",
    "∫": r"\ensuremath{\int}", "√": r"\ensuremath{\surd}", "∂": r"\ensuremath{\partial}", "∇": r"\ensuremath{\nabla}",
    "∈": r"\ensuremath{\in}", "∉": r"\ensuremath{\notin}", "⊂": r"\ensuremath{\subset}", "⊆": r"\ensuremath{\subseteq}",
    "∪": r"\ensuremath{\cup}", "∩": r"\ensuremath{\cap}", "∀": r"\ensuremath{\forall}", "∃": r"\ensuremath{\exists}",
    "∅": r"\ensuremath{\emptyset}", "ℝ": r"\ensuremath{\mathbb{R}}", "ℕ": r"\ensuremath{\mathbb{N}}",
    "ℤ": r"\ensuremath{\mathbb{Z}}", "ℚ": r"\ensuremath{\mathbb{Q}}", "ℂ": r"\ensuremath{\mathbb{C}}",
    "≔": r"\ensuremath{\coloneq}", "⋯": r"\ensuremath{\cdots}", "★": r"\ensuremath{\star}",
    "✓": r"\ensuremath{\checkmark}", "✔": r"\ensuremath{\checkmark}", "✗": r"\ding{55}", "✘": r"\ding{56}",
    "✎": r"\ding{46}", "✏": r"\ding{47}", "☐": r"\ensuremath{\square}",
    **{chr(0x3B1 + i): rf"\ensuremath{{\{name}}}" for i, name in enumerate(_GREEK) if name != "o"},
    **{chr(0x391 + i): rf"\ensuremath{{\{name.capitalize()}}}" for i, name in enumerate(_GREEK)
       if name in ("gamma", "delta", "theta", "lambda", "xi", "pi", "sigma", "upsilon", "phi", "psi", "omega")},
}
_TEX_TEXT_OK = set("–—‘’‚“”„…•€†‡‰′″™")


def tex_escape(text: str) -> str:
    out = []
    for ch in text:
        if ch in _TEX_SPECIAL:
            out.append(_TEX_SPECIAL[ch])
        elif ord(ch) < 0x180 or ch in _TEX_TEXT_OK:
            out.append(ch)
        elif ch in _TEX_UNICODE:
            out.append(_TEX_UNICODE[ch])
        else:
            out.append(rf"\mbkchar{{{ch}}}{{{ord(ch):04X}}}")
    # T1 fonts turn << and >> into guillemets
    return "".join(out).replace("<<", "<{}<").replace(">>", ">{}>")


def _tex_inline(nodes) -> str:
    out = []
    for n in nodes or []:
        t = n["type"]
        if t == "text":
            s = tex_escape(n["text"])
            marks = {m["type"]: m for m in n.get("marks", [])}
            if "code" in marks:
                s = rf"\texttt{{{s}}}"
            if "em" in marks:
                s = rf"\emph{{{s}}}"
            if "strong" in marks:
                s = rf"\textbf{{{s}}}"
            if "link" in marks:
                href = marks["link"]["attrs"]["href"].replace("%", r"\%").replace("#", r"\#")
                s = rf"\href{{{href}}}{{{s}}}"
            out.append(s)
        elif t == "hard_break":
            out.append("\\\\\n")
        elif t == "math_inline":
            out.append(f"${inline_math_latex(n['attrs'])}$")
    return "".join(out)


LATEX_PREAMBLE = r"""\documentclass[11pt,a4paper]{article}
\usepackage{iftex}
\ifPDFTeX
  \usepackage[utf8]{inputenc}
  \usepackage[T1]{fontenc}
  \usepackage{lmodern}
  % characters pdfLaTeX has no glyph for are shown as [U+XXXX]
  \newcommand{\mbkchar}[2]{\texttt{[U+#2]}}
\else
  \usepackage{fontspec}
  \newcommand{\mbkchar}[2]{#1}
\fi
\usepackage{amsmath,amssymb,mathtools}
\usepackage{pifont}
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
"""


class _TexWriter:
    def __init__(self, figure_names: dict[int, str]):
        self.figure_names = figure_names
        self.fig = 0

    def outputs(self, outputs) -> list[str]:
        body = []
        for out in outputs or []:
            kind = out.get("kind")
            if kind == "result" and out.get("latex"):
                label = out.get("label", "")
                tag = rf"\tag*{{({tex_escape(label)})}}" if label else ""
                body += [r"\begin{equation*}", out["latex"] + tag, r"\end{equation*}"]
            elif kind in ("text", "error"):
                body += [r"\begin{verbatim}", out.get("text", ""), r"\end{verbatim}"]
            elif kind == "image":
                self.fig += 1
                name = self.figure_names.get(self.fig)
                if name:
                    body += [r"\begin{center}", rf"\includegraphics[width=0.75\linewidth]{{{name}}}",
                             r"\end{center}"]
                else:
                    body.append(rf"\fbox{{Figure {self.fig} omitted: no raster version was provided}}")
        return body

    def block(self, n: dict) -> list[str]:
        t, a = n["type"], n.get("attrs", {})
        if t == "paragraph":
            text = _tex_inline(n.get("content"))
            return [text, ""] if text.strip() else []
        if t == "heading":
            text = _tex_inline(n.get("content"))
            if a["level"] == 1:
                return [r"\begin{center}{\LARGE\bfseries " + text + r"}\end{center}", ""]
            cmd = {2: "section*", 3: "subsection*", 4: "subsubsection*"}[a["level"]]
            return [rf"\{cmd}{{{text}}}", ""]
        if t == "horizontal_rule":
            return [r"\noindent\rule{\linewidth}{0.4pt}", ""]
        if t == "code_block":
            return [r"\begin{verbatim}", plain_text(n), r"\end{verbatim}", ""]
        if t == "blockquote":
            return [r"\begin{quote}", *[ln for c in n.get("content", []) for ln in self.block(c)],
                    r"\end{quote}", ""]
        if t in ("bullet_list", "ordered_list"):
            env = "itemize" if t == "bullet_list" else "enumerate"
            lines = [rf"\begin{{{env}}}"]
            for item in n.get("content", []):
                inner = [ln for c in item.get("content", []) for ln in self.block(c)]
                lines.append(r"  \item " + "\n".join(inner).strip())
            return lines + [rf"\end{{{env}}}", ""]
        if t == "maxima":
            body = []
            if a.get("source", "").strip():
                body += [r"\begin{verbatim}", a["source"].strip(), r"\end{verbatim}"]
            return body + self.outputs(a.get("outputs")) + [""]
        if t == "math_block":
            latex = inline_math_latex(a)
            body = [r"\[", latex, r"\]"] if latex.strip() else []
            return body + self.outputs(a.get("outputs")) + [""]
        return []


def export_latex(nb: dict, figure_names: dict[int, str] | None = None) -> str:
    """LaTeX document.  ``figure_names`` maps image ordinal -> graphics file."""
    doc = _doc(nb)
    title = nb.get("title") or doc["attrs"].get("title") or "Untitled"
    blocks = list(document.walk_blocks(doc))
    has_own_title = bool(blocks) and blocks[0]["type"] == "heading" and blocks[0]["attrs"]["level"] == 1
    writer = _TexWriter(figure_names or {})
    body = [ln for b in blocks for ln in writer.block(b)]
    head = [] if has_own_title else [rf"\title{{{tex_escape(title)}}}", r"\date{}"]
    out = [LATEX_PREAMBLE, *head, r"\begin{document}", "" if has_own_title else r"\maketitle", "",
           *body, r"\end{document}", ""]
    return "\n".join(out)


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


EXPORTERS = {"mac": (".mac", export_mac), "wxm": (".wxm", export_wxm), "wxmx": (".wxmx", export_wxmx),
             "md": (".md", export_markdown), "tex": (".tex", export_latex)}

__all__ = ["EXPORTERS", "IMPORTERS", "export_latex", "latex_to_cells", "markdown_to_cells",
           "write_latex_bundle"]
