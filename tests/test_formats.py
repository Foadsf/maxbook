# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
import base64
import os
import shutil
import struct
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path

import pytest

from maxbook import formats, notebook
from maxbook.notebook import NotebookError

WXM = """/* [wxMaxima batch file version 1] [ DO NOT EDIT BY HAND! ]*/
/* [ Created with wxMaxima version 23.05.1 ] */
/* [wxMaxima: title   start ]
Pendulum
   [wxMaxima: title   end   ] */

/* [wxMaxima: comment start ]
Small oscillations of a pendulum.
   [wxMaxima: comment end   ] */

/* [wxMaxima: input   start ] */
eq: 'diff(theta, t, 2) + g/L*theta = 0$
ode2(eq, theta, t);
/* [wxMaxima: input   end   ] */

/* [wxMaxima: section start ]
Plot
   [wxMaxima: section end   ] */

/* [wxMaxima: input   start ] */
wxplot2d(sin(t), [t, 0, 10])$
/* [wxMaxima: input   end   ] */

/* Old versions of Maxima abort on loading files that end in a comment. */
"Created with wxMaxima 23.05.1"$
"""

CONTENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<wxMaximaDocument version="1.5" zoom="100">
<cell type="title" sectioning_level="1"><editor type="title" sectioning_level="1"><line>Doc</line></editor></cell>
<cell type="text"><editor type="text"><line>Some text</line><line>over two lines</line></editor></cell>
<cell type="code"><input><editor type="input"><line>a: 2$</line><line>a^2;</line></editor></input>
<output><mth><lbl>(%o2) </lbl><n>4</n></mth></output></cell>
</wxMaximaDocument>"""


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_import_wxm(tmp_path):
    nb = notebook.load(write(tmp_path, "pend.wxm", WXM))
    kinds = [(c["type"], c["source"].splitlines()[0]) for c in nb["cells"]]
    assert kinds == [("markdown", "# Pendulum"), ("markdown", "Small oscillations of a pendulum."),
                     ("code", "eq: 'diff(theta, t, 2) + g/L*theta = 0$"), ("markdown", "## Plot"),
                     ("code", "wxplot2d(sin(t), [t, 0, 10])$")]
    assert nb["title"] == "Pendulum"


def test_import_wxmx(tmp_path):
    p = tmp_path / "doc.wxmx"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("mimetype", "text/x-wxmathml")
        zf.writestr("content.xml", CONTENT_XML)
    nb = notebook.load(p)
    assert [(c["type"], c["source"]) for c in nb["cells"]] == [
        ("markdown", "# Doc"), ("markdown", "Some text\nover two lines"), ("code", "a: 2$\na^2;")]


def test_import_mac(tmp_path):
    nb = notebook.load(write(tmp_path, "lib.mac", "/* Helpers */\nsq(x) := x^2$\n\n/* Use it */\nsq(3);\n"))
    assert [(c["type"], c["source"]) for c in nb["cells"]] == [
        ("markdown", "Helpers"), ("code", "sq(x) := x^2$"), ("markdown", "Use it"), ("code", "sq(3);")]


def test_import_markdown(tmp_path):
    nb = notebook.load(write(tmp_path, "n.md", "# Notes\n\nText $x$.\n\n```maxima\n1+1;\n```\n\nEnd.\n"))
    assert [(c["type"], c["source"]) for c in nb["cells"]] == [
        ("markdown", "# Notes\n\nText $x$."), ("code", "1+1;"), ("markdown", "End.")]
    assert nb["title"] == "Notes"


TEX = r"""\documentclass{article}
\title{Waves \& \emph{Strings}}
\begin{document}
\maketitle
% a comment that must disappear
\section{Setup}
The wave speed is $c = \sqrt{T/\mu}$, see \textbf{below}.
\begin{equation}\label{eq:w}
  u_{tt} = c^2 u_{xx}
\end{equation}
\begin{itemize}
  \item first $a$
  \item second
\end{itemize}
\begin{lstlisting}[language=Maxima]
pde: diff(u, t, 2) = c^2*diff(u, x, 2);
\end{lstlisting}
\subsection*{Notes}
Done.
\end{document}
"""


def test_import_latex(tmp_path):
    nb = notebook.load(write(tmp_path, "w.tex", TEX))
    assert nb["title"] == "Waves & *Strings*"
    md = nb["cells"][0]["source"]
    assert md.startswith("# Waves & *Strings*")
    assert "## Setup" in md and "comment" not in md
    assert r"$c = \sqrt{T/\mu}$" in md and "**below**" in md
    assert r"$$u_{tt} = c^2 u_{xx}$$" in md and "label" not in md
    assert "- first $a$" in md and "- second" in md
    assert nb["cells"][1] == {**nb["cells"][1], "type": "code",
                              "source": "pde: diff(u, t, 2) = c^2*diff(u, x, 2);"}
    assert nb["cells"][2]["source"] == "### Notes\n\nDone."


# ----------------------------------------------------------- v2 documents
def text(s, *marks):
    n = {"type": "text", "text": s}
    if marks:
        n["marks"] = [{"type": m} for m in marks]
    return n


def para(*inline):
    return {"type": "paragraph", "content": list(inline)}


def tiny_png() -> bytes:
    """A valid 2x2 RGB PNG built with zlib (no image library needed)."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * 2 for _ in range(2))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def sample_notebook():
    png = base64.b64encode(tiny_png()).decode()
    doc = {"type": "doc", "attrs": {"title": "Sample & test"}, "content": [
        {"type": "heading", "attrs": {"level": 1}, "content": [text("Sample")]},
        para(text("Prose with "), text("bold", "strong"), text(", "), text("em", "em"), text(", "),
             text("code_x", "code"), text(", 50% & "),
             {"type": "math_inline", "attrs": {"latex": "x_1^2"}}, text(" and "),
             {"type": "math_inline", "attrs": {"latex": "2+3=", "source": "2+3;",
                                               "result": {"latex": "5", "text": "5"}}}),
        {"type": "bullet_list", "content": [
            {"type": "list_item", "content": [para(text("item one"))]},
            {"type": "list_item", "content": [para(text("item "), {"type": "math_inline",
                                                                   "attrs": {"latex": r"\alpha"}})]}]},
        {"type": "heading", "attrs": {"level": 2}, "content": [text("Compute")]},
        {"type": "maxima", "attrs": {"id": "m1", "source": "integrate(x^2, x)", "inputs": [1], "outputs": [
            {"kind": "result", "label": "%o1", "latex": r"\frac{x^3}{3}", "text": "x^3/3"},
            {"kind": "text", "text": "warning: 100% {braces} & $"},
            {"kind": "error", "text": "expt: undefined"},
            {"kind": "question", "text": "transient, must not be saved"}]}},
        {"type": "math_block", "attrs": {
            "id": "b1", "latex": r"A\coloneq\begin{pmatrix}1&2\\3&4\end{pmatrix}",
            "source": "A: matrix([1, 2], [3, 4]);", "run": True, "outputs": [
                {"kind": "result", "label": "%o2", "latex": r"\begin{pmatrix} 1&2\\ 3&4\end{pmatrix}",
                 "text": "m"},
                {"kind": "image", "mime": "image/png", "data": png}]}},
        {"type": "math_block", "attrs": {
            "id": "b1", "latex": r"\exponentialE^{\imaginaryI\pi}+\int x\,\differentialD x"}},
        {"type": "blockquote", "content": [para(text("quoted"))]},
        # text pdfLaTeX's utf8 input cannot typeset directly
        para(text("Unicode: café – ✎ × α → ≤ ✓ 汉; "), text(">> and <<", "code")),
    ]}
    return notebook.validate({"format": "maxbook", "version": 2, "doc": doc}), png


def test_v2_validation_cleans_and_dedupes(tmp_path):
    nb, _ = sample_notebook()
    blocks = nb["doc"]["content"]
    assert nb["title"] == "Sample & test"
    assert all(o["kind"] != "question" for o in blocks[4]["attrs"]["outputs"])
    ids = [b["attrs"]["id"] for b in blocks if b["type"] == "math_block"]
    assert len(set(ids)) == 2, "duplicate block ids must be replaced"
    p = tmp_path / "s.maxbook"
    notebook.save(p, nb)
    assert notebook.load(p) == nb
    with pytest.raises(NotebookError):
        notebook.save(tmp_path / "s.txt", nb)
    with pytest.raises(NotebookError):
        notebook.loads('{"format": "maxbook", "version": 2, "doc": {"type": "doc", "content": [{"type": "evil"}]}}')
    with pytest.raises(NotebookError):
        notebook.loads('{"format": "maxbook", "version": 9, "doc": {"type": "doc"}}')
    v1 = notebook.loads('{"format": "maxbook", "version": 1, "cells": [{"type": "code", "source": "1;"}]}')
    assert v1["version"] == 1 and v1["cells"][0]["source"] == "1;"
    with pytest.raises(NotebookError):
        notebook.dumps(v1)  # only v2 is written


def test_export_mac_and_markdown():
    nb, _ = sample_notebook()
    mac = formats.export_mac(nb)
    assert "integrate(x^2, x);" in mac            # terminator added for batch()
    assert "A: matrix([1, 2], [3, 4]);" in mac
    assert "2+3;" in mac                           # computed inline formula is reproducible
    assert "/* Sample */" in mac
    md = formats.export_markdown(nb)
    assert md.startswith("# Sample\n")
    assert r"**bold**, *em*, `code_x`, 50% & $x_1^2$ and $2+3=5$" in md
    assert "- item one\n- item $\\alpha$" in md
    assert "```maxima\nintegrate(x^2, x)\n```" in md
    assert r"\frac{x^3}{3}\tag*{(\%o1)}" in md
    assert "data:image/png;base64," in md
    assert "> quoted" in md
    assert "transient" not in md


def test_wxm_and_wxmx_exports_round_trip(tmp_path):
    nb, _ = sample_notebook()
    wxm = write(tmp_path, "s.wxm", formats.export_wxm(nb))
    back = notebook.load(wxm)
    kinds = [(c["type"], c["source"].splitlines()[0]) for c in back["cells"]]
    assert kinds[0] == ("markdown", "# Sample")
    assert ("code", "2+3;") in kinds and ("code", "integrate(x^2, x)") in kinds
    assert ("markdown", "## Compute") in kinds
    p = tmp_path / "s.wxmx"
    p.write_bytes(formats.export_wxmx(nb))
    with zipfile.ZipFile(p) as zf:
        first = zf.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"text/x-wxmathml"
    again = notebook.load(p)
    assert [(c["type"], c["source"]) for c in again["cells"]] == [(c["type"], c["source"]) for c in back["cells"]]


def find_pdflatex():
    """pdflatex from MAXBOOK_PDFLATEX, PATH, or a MiKTeX install that is not on PATH."""
    candidates = [os.environ.get("MAXBOOK_PDFLATEX"), shutil.which("pdflatex")]
    if sys.platform.startswith("win"):
        candidates += [str(p) for p in Path.home().glob(
            "scoop/apps/miktex/current/texmfs/install/miktex/bin/x64/pdflatex.exe")]
        candidates += [str(p) for p in Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                       .glob("MiKTeX*/miktex/bin/x64/pdflatex.exe")]
    return next((c for c in candidates if c and Path(c).exists()), None)


PDFLATEX = find_pdflatex()


@pytest.mark.skipif(PDFLATEX is None, reason="pdflatex not installed")
def test_latex_export_compiles(tmp_path):
    nb, png = sample_notebook()
    written = formats.write_latex_bundle(nb, tmp_path / "doc.tex", ["data:image/png;base64," + png])
    assert written[1].name == "figure1.png"
    tex = written[0].read_text(encoding="utf-8")
    assert r"\textbf{bold}" in tex and r"50\% \& $x_1^2$" in tex and "$2+3=5$" in tex
    assert r"\begin{itemize}" in tex and r"\begin{quote}" in tex
    assert r"café – \ding{46} × \ensuremath{\alpha}" in tex and r"\mbkchar{汉}{6C49}" in tex
    assert r"\texttt{>{}> and <{}<}" in tex
    res = subprocess.run([PDFLATEX, "-interaction=nonstopmode", "-halt-on-error", "doc.tex"],
                         cwd=tmp_path, capture_output=True, text=True, timeout=300, check=False)
    assert res.returncode == 0, res.stdout[-3000:]
    assert (tmp_path / "doc.pdf").stat().st_size > 1000
