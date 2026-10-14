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


def test_wxm_round_trip(tmp_path):
    nb = notebook.load(write(tmp_path, "pend.wxm", WXM))
    out = write(tmp_path, "again.wxm", formats.export_wxm(nb))
    nb2 = notebook.load(out)
    def strip(n):
        return [(c["type"], c["source"]) for c in n["cells"]]
    assert strip(nb2) == strip(nb)


def test_save_load_round_trip_and_validation(tmp_path):
    nb = notebook.new_notebook("T")
    nb["cells"][1]["source"] = "1+1;"
    nb["cells"][1]["outputs"] = [{"kind": "result", "label": "%o1", "latex": "2", "text": "2"},
                                 {"kind": "question", "text": "transient"}]
    nb["cells"][1]["inputs"] = [1]
    p = tmp_path / "t.maxbook"
    notebook.save(p, nb)
    back = notebook.load(p)
    assert back["cells"][1]["outputs"] == [{"kind": "result", "label": "%o1", "latex": "2", "text": "2"}]
    assert back["cells"][1]["inputs"] == [1]
    with pytest.raises(NotebookError):
        notebook.save(tmp_path / "t.txt", nb)
    with pytest.raises(NotebookError):
        notebook.loads('{"format": "other", "cells": []}')
    with pytest.raises(NotebookError):
        notebook.loads('{"cells": [{"type": "bogus"}]}')


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
    return notebook.validate({"title": "Sample & test", "cells": [
        {"type": "markdown", "source": "# Sample\n\nProse with **bold**, *em*, `code`, 50% & $x_1^2$.\n\n"
                                       "- item one\n- item $\\alpha$\n\n$$\\int_0^1 x\\,dx$$"},
        {"type": "code", "source": "integrate(x^2, x);", "outputs": [
            {"kind": "result", "label": "%o1", "latex": r"\frac{x^3}{3}", "text": "x^3/3"},
            {"kind": "text", "text": "warning: 100% {braces} & $"},
            {"kind": "error", "text": "expt: undefined"}]},
        {"type": "math", "latex": r"A\coloneq\begin{pmatrix}1&2\\3&4\end{pmatrix}",
         "source": "A: matrix([1, 2], [3, 4]);", "outputs": [
            {"kind": "result", "label": "%o2", "latex": r"\begin{pmatrix} 1&2\\ 3&4\end{pmatrix}", "text": "m"},
            {"kind": "image", "mime": "image/png", "data": png}]},
        {"type": "math", "latex": r"\exponentialE^{\imaginaryI\pi}+\int x\,\differentialD x",
         "source": "", "outputs": []},
    ]}), png


def test_export_mac_and_markdown():
    nb, _ = sample_notebook()
    mac = formats.export_mac(nb)
    assert "integrate(x^2, x);" in mac and "A: matrix([1, 2], [3, 4]);" in mac
    md = formats.export_markdown(nb)
    assert "```maxima\nintegrate(x^2, x);\n```" in md
    assert r"\frac{x^3}{3}\tag*{(\%o1)}" in md
    assert "data:image/png;base64," in md


def test_markdown_to_latex_escapes_text_but_not_math():
    tex = formats.markdown_to_latex("50% & $x_1$ **b** `a_b`")
    assert r"50\% \& $x_1$ \textbf{b} \texttt{a\_b}" in tex


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
    res = subprocess.run([PDFLATEX, "-interaction=nonstopmode", "-halt-on-error", "doc.tex"],
                         cwd=tmp_path, capture_output=True, text=True, timeout=300, check=False)
    assert res.returncode == 0, res.stdout[-3000:]
    assert (tmp_path / "doc.pdf").stat().st_size > 1000
