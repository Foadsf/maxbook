# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Integration tests against a real Maxima.  Skipped (and reported) when absent."""

import threading
import time

import pytest

from maxbook.kernel import KernelError, MaximaKernel, find_maxima
from maxbook.latex2maxima import latex_to_maxima

MAXIMA = find_maxima()
pytestmark = pytest.mark.skipif(MAXIMA is None, reason="Maxima is not installed")


@pytest.fixture(scope="module")
def kernel():
    k = MaximaKernel(MAXIMA)
    k.start()
    yield k
    k.shutdown()


def kinds(res):
    return [o["kind"] for o in res["outputs"]]


def test_handshake(kernel):
    assert kernel.version
    assert kernel.status == "idle"


def test_result_has_latex_and_text(kernel):
    res = kernel.run_cell("integrate(x^2, x);")
    assert not res["error"]
    (out,) = res["outputs"]
    assert out["kind"] == "result"
    assert out["latex"] == r"\frac{x^3}{3}"
    assert out["text"] == "x^3/3"
    assert out["label"].startswith("%o")


def test_labels_and_percent_are_preserved_across_cells(kernel):
    a = kernel.run_cell("7*6;")
    b = kernel.run_cell("%;")
    assert b["outputs"][0]["text"] == "42"
    n_a = int(a["outputs"][0]["label"][2:])
    n_b = int(b["outputs"][0]["label"][2:])
    assert n_b == n_a + 1
    assert b["inputs"] == [n_b]


def test_suppressed_statement_and_state(kernel):
    res = kernel.run_cell("q: 5$ q^2;")
    assert [o["text"] for o in res["outputs"]] == ["25"]
    assert len(res["inputs"]) == 2


def test_print_output_is_shown(kernel):
    res = kernel.run_cell('print("hello θ", x^2)$')
    assert kinds(res) == ["result"]
    assert "θ" in res["outputs"][0]["text"]


def test_error_stops_the_cell(kernel):
    res = kernel.run_cell("1/0; never_reached: 1;")
    assert res["error"]
    assert kinds(res) == ["error"]
    assert "debugmode" in res["outputs"][0]["text"]
    assert kernel.run_cell("never_reached;")["outputs"][0]["text"] == "never_reached"


def test_syntax_error_is_an_error(kernel):
    res = kernel.run_cell("x^;")
    assert res["error"]
    assert "syntax" in res["outputs"][0]["text"]


def test_lisp_error_is_an_error_and_session_survives(kernel):
    res = kernel.run_cell("?car(1);")
    assert res["error"]
    assert kernel.run_cell("1+1;")["outputs"][0]["text"] == "2"


def test_matrix_latex_is_amsmath(kernel):
    res = kernel.run_cell("matrix([1,2],[3,4])^^-1;")
    latex = res["outputs"][0]["latex"]
    assert latex.startswith(r"\begin{pmatrix}") and r"\ifx" not in latex
    assert r"\over" not in latex


def test_unterminated_last_statement_gets_semicolon(kernel):
    assert kernel.run_cell("2+3")["outputs"][0]["text"] == "5"


def test_unterminated_string_is_refused_not_sent(kernel):
    res = kernel.run_cell('s: "abc;')
    assert res["error"] and "unterminated string" in res["outputs"][0]["text"]
    assert kernel.run_cell("1;")["outputs"][0]["text"] == "1"


def test_inline_plot_produces_svg(kernel):
    res = kernel.run_cell("iplot2d(sin(x), [x, 0, 6])$")
    assert kinds(res) == ["image"], res
    assert res["outputs"][0]["mime"] == "image/svg+xml"
    assert "<svg" in res["outputs"][0]["data"]


def test_inline_draw_produces_svg(kernel):
    res = kernel.run_cell("idraw2d(explicit(x^2, x, -1, 1));")
    assert kinds(res) == ["image"], res


def test_quiet_load_still_reports_failure(kernel):
    res = kernel.run_cell('maxbook_quiet_load("no_such_package_xyz");')
    assert res["error"]
    assert "no_such_package_xyz" in " ".join(o.get("text", "") for o in res["outputs"])


def test_wxmaxima_alias(kernel):
    res = kernel.run_cell("wxplot2d(x^2, [x, -1, 1])$")
    assert kinds(res) == ["image"], res


def test_question_and_answer(kernel):
    outputs = []
    result = {}

    def run():
        result.update(kernel.run_cell("integrate(1/x^a, x);", on_output=outputs.append))

    t = threading.Thread(target=run)
    t.start()
    deadline = time.time() + 30
    while kernel.pending_question is None and time.time() < deadline:
        time.sleep(0.05)
    assert kernel.pending_question is not None
    assert "-1" in kernel.pending_question["text"] or kernel.pending_question["parts"]
    kernel.answer("no")
    t.join(30)
    assert not t.is_alive()
    assert not result["error"]
    assert result["outputs"][-1]["kind"] == "result"
    assert "log" not in result["outputs"][-1]["text"]  # a # -1 branch: x^(1-a)/(1-a)


MATH_CASES = [
    (r"\int_{0}^{1}x^2\,\mathrm{d}x", "1/3"),
    (r"\sum_{k=1}^{10}k", "55"),
    (r"\lim_{x\to0}\frac{\sin x}{x}", "1"),
    (r"\frac{d}{dx}x^3", "3*x^2"),
    (r"\frac{\partial^2}{\partial x\partial y}x^2y^3", "6*x*y^2"),
    (r"\begin{pmatrix}1&2\\3&4\end{pmatrix}\begin{pmatrix}1\\1\end{pmatrix}", "matrix([3],[7])"),
    (r"\begin{vmatrix}1&2\\3&4\end{vmatrix}", "-2"),
    (r"\sqrt[3]{27}", "3"),
    (r"\log_{2}8", "log(8)/log(2)"),  # Maxima keeps change-of-base unsimplified
    (r"\mathrm{radcan}\left(\log_{2}8\right)", "3"),
    (r"\binom{5}{2}", "10"),
    (r"e^{i\pi}", "%e^(%pi*i)"),  # bare i is a variable by convention

    (r"\exponentialE^{\imaginaryI\pi}", "-1"),
    (r"\lim_{x\to0^{+}}\frac{1}{x}", "inf"),
    (r"\int_{-\infty}^{\infty}e^{-t^2}dt", "sqrt(%pi)"),
]


@pytest.mark.parametrize("latex,expected", MATH_CASES)
def test_math_cell_conversion_evaluates(kernel, latex, expected):
    res = kernel.run_cell(latex_to_maxima(latex))
    assert not res["error"], res
    assert res["outputs"][-1]["text"] == expected


def test_function_definition_round_trip(kernel):
    kernel.run_cell(latex_to_maxima(r"f(x)\coloneq x^2+1"))
    assert kernel.run_cell(latex_to_maxima("f(3)"))["outputs"][0]["text"] == "10"


def _run_in_thread(k, source):
    result, errors = {}, []

    def run():
        try:
            result.update(k.run_cell(source))
        except KernelError as exc:  # a hard stop surfaces as KernelError
            errors.append(str(exc))

    t = threading.Thread(target=run)
    t.start()
    return t, result, errors


@pytest.mark.parametrize("source", ["for i: 1 thru 10^9 do x: i;", "integrate(1/x^b, x);"])
def test_stop_in_place_keeps_state(source):
    k = MaximaKernel(MAXIMA)
    k.start()
    try:
        if not k.can_interrupt():
            pytest.skip(f"this Maxima build ({k.lisp}) cannot be interrupted in place")
        k.run_cell("keep: 41$")
        t, result, errors = _run_in_thread(k, source)
        time.sleep(2)
        assert k.interrupt()
        t.join(20)
        assert not t.is_alive(), "Maxima did not come back after the interrupt"
        assert not errors, errors
        assert result["error"]
        assert result["outputs"][-1].get("interrupted"), result
        assert k.pending_question is None
        assert k.run_cell("keep + 1;")["outputs"][0]["text"] == "42"
    finally:
        k.shutdown()


def test_hard_stop_restarts():
    k = MaximaKernel(MAXIMA)
    k.start()
    try:
        t, _result, errors = _run_in_thread(k, "for i: 1 thru 10^9 do x: i;")
        time.sleep(2)
        k.hard_stop()
        t.join(30)
        assert not t.is_alive()
        assert errors and "stopped by you" in errors[0]
        k.start()
        assert k.run_cell("1+1;")["outputs"][0]["text"] == "2"
    finally:
        k.shutdown()


def test_semantic_latex_tags_symbols_by_kind(kernel):
    kernel.run_cell("aa: 3$ g2(t) := t^2$")
    res = kernel.run_cell("g2(y) + aa*%pi + z;")
    out = res["outputs"][0]
    sem = out["semantic"]
    assert r"\class{mbk-sym mbk-constant" in sem         # %pi
    assert r"\class{mbk-sym mbk-free" in sem             # y, z
    assert "mbk-n-0079" in sem.lower() and "mbk-n-007a" in sem.lower()  # y, z as hex code points
    assert r"\class" not in out["latex"]                 # plain LaTeX stays plain


def test_symbol_table(kernel):
    kernel.run_cell("vv: [1, 2]$ hh(u, w) := u + w$ declare(cc, constant)$")
    table = kernel.symbols()
    by_name = {e["name"]: e for e in table}
    assert by_name["vv"]["kind"] == "variable" and by_name["vv"]["text"] == "[1,2]"
    assert by_name["hh"]["kind"] == "function" and by_name["hh"]["text"] == "hh(u,w):=u+w"
    assert by_name["cc"]["kind"] == "constant"
    res = kernel.run_cell("cc + vv[1];")
    assert r"\class{mbk-sym mbk-constant" in res["outputs"][0]["semantic"]
    # values are cleaned up like displayed results (no plain-TeX \pmatrix tricks)
    kernel.run_cell("mm: matrix([1, 2], [3, 4])$")
    mm = next(e for e in kernel.symbols() if e["name"] == "mm")
    assert "pmatrix" in mm["latex"] and "\\ifx" not in mm["latex"]
    # Maxbook's own helpers are not the user's symbols
    assert not {"maxbook_plot_dir", "iplot2d", "maxbook_ensure_draw"} & set(by_name)
    # nor what a package defines when it loads (eigenvalues autoloads eigen);
    # the user's own definitions made before the load stay theirs
    kernel.run_cell("eigenvalues(mm);")
    names = {e["name"] for e in kernel.symbols()}
    assert {"vv", "hh", "mm"} <= names
    assert not {"eigenvalues", "hermitianmatrix", "knowneigvals"} & names


def test_run_waits_for_symbol_query_but_not_for_a_computation(kernel):
    # a symbol-table query holds the kernel briefly: a run waits for it
    kernel._run_lock.acquire()
    kernel._symbols_query = True

    def finish():
        time.sleep(0.6)
        kernel._symbols_query = False
        kernel._run_lock.release()

    threading.Thread(target=finish).start()
    res = kernel.run_cell("1+1;")
    assert res["outputs"][0]["text"] == "2"
    # a computation holding the kernel: a second run is refused at once
    kernel._run_lock.acquire()
    try:
        with pytest.raises(KernelError, match="busy"):
            kernel.run_cell("1+1;")
    finally:
        kernel._run_lock.release()


def test_restart_resets_state():
    k = MaximaKernel(MAXIMA)
    k.start()
    try:
        k.run_cell("zz: 9$")
        k.restart()
        assert k.run_cell("zz;")["outputs"][0]["text"] == "zz"
    finally:
        k.shutdown()
