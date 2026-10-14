# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
import pytest

from maxbook.splitter import SplitError, split_statements
from maxbook.texfix import maxima_tex_to_latex


def texts(src):
    return [s.text for s in split_statements(src)]


def test_basic_split_and_terminators():
    st = split_statements("a: 1$ b: 2;\nc;")
    assert [s.text for s in st] == ["a: 1$", "b: 2;", "c;"]
    assert [s.terminator for s in st] == ["$", ";", ";"]


def test_terminators_inside_strings_and_comments_are_ignored():
    assert texts('print("a;b$c"); /* x; y$ */ 1;') == ['print("a;b$c");', "/* x; y$ */ 1;"]


def test_nested_comments():
    assert texts("/* a /* b; */ c; */ 2;") == ["/* a /* b; */ c; */ 2;"]


def test_escaped_terminator_in_identifier():
    assert texts(r"a\;b: 3;") == [r"a\;b: 3;"]


def test_escaped_quote_in_string():
    assert texts(r'"say \"hi\";"; 1;') == [r'"say \"hi\";";', "1;"]


def test_comment_only_input_has_no_statements():
    assert texts("  /* nothing */\n") == []


def test_auto_terminate():
    assert texts("x+1") == ["x+1;"]
    with pytest.raises(SplitError):
        split_statements("x+1", auto_terminate=False)


def test_lisp_lines():
    st = split_statements(":lisp (+ 1 2)\nx;")
    assert [(s.text, s.terminator) for s in st] == [(":lisp (+ 1 2)", "lisp"), ("x;", ";")]


@pytest.mark.parametrize("src,msg", [('s: "abc;', "string"), ("/* open; ", "comment")])
def test_unterminated_input_is_refused(src, msg):
    with pytest.raises(SplitError, match=msg):
        split_statements(src)


@pytest.mark.parametrize("tex,latex", [
    (r"{{x^3}\over{3}}", r"\frac{x^3}{3}"),
    (r"{{{1}\over{2}}\over{x}}", r"\frac{\frac{1}{2}}{x}"),
    (r"\ifx\endpmatrix\undefined\pmatrix{\else\begin{pmatrix}\fi 1&2\cr 3&4\cr "
     r"\ifx\endpmatrix\undefined}\else\end{pmatrix}\fi ",
     r"\begin{pmatrix} 1&2\\ 3&4\end{pmatrix}"),
    (r"{\it gr2d}\left({\it explicit}\right)", r"\mathit{gr2d}\left(\mathit{explicit}\right)"),
    (r"\mbox{ Is  }a\mbox{  equal to  }-1\mbox{ ? }", r"\text{ Is }a\text{ equal to }-1\text{ ? }"),
    (r"\mbox{   }", r"\;"),
    # Maxima 5.47 typesets strings letter by letter with \verb
    (r"\mbox{\verb|f|}\mbox{\verb|_|}\mbox{ draw }\mbox{\verb| |}\mbox{\verb|}|}",
     r"\text{f\_ draw  \}}"),
    (r"\mbox{\verb|a|}+\mbox{\verb|b|}", r"\text{a}+\text{b}"),
    (r"$$x$$", "x"),
])
def test_tex_cleanup(tex, latex):
    assert maxima_tex_to_latex(tex) == latex
