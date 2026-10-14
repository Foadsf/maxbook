# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
import pytest

from maxbook.latex2maxima import ConversionError, collect_function_names, latex_to_maxima

CASES = [
    # arithmetic and precedence
    ("1+2", "1 + 2;"),
    ("2x", "2*x;"),
    ("2xy", "2*x*y;"),
    ("a-b-c", "a - b - c;"),
    ("a-(b-c)", "a - (b - c);"),
    (r"a\cdot b", "a*b;"),
    (r"a\times b", "a*b;"),
    (r"a\div b", "a/b;"),
    ("-x^2", "-x^2;"),
    ("x^{-1}", "x^(-1);"),
    ("x^2y", "x^2*y;"),
    ("x^{2y}", "x^(2*y);"),
    ("2^{3^4}", "2^(3^4);"),
    ("(2^3)^4", "(2^3)^4;"),
    (r"\frac{1}{2}", "1/2;"),
    (r"\frac{a+b}{c-d}", "(a + b)/(c - d);"),
    (r"\frac{1}{2}x", "1/2*x;"),
    ("n!", "n!;"),
    ("(n+1)!", "(n + 1)!;"),
    (r"\left(x+1\right)^2", "(x + 1)^2;"),
    # constants and symbols
    (r"\pi", "%pi;"),
    ("e^{x}", "%e^x;"),
    (r"\mathrm{e}^{i\pi}", "%e^(i*%pi);"),
    (r"\exponentialE^{\imaginaryI\pi}", "%e^(%i*%pi);"),
    (r"\alpha+\beta", "alpha + beta;"),
    (r"x_{1}+x_2", "x[1] + x[2];"),
    (r"a_{i,j}", "a[i, j];"),
    (r"\infty", "inf;"),
    (r"90^{\circ}", "90*%pi/180;"),
    # functions
    (r"\sin x", "sin(x);"),
    (r"\sin 2x", "sin(2*x);"),
    (r"\sin x\cos x", "sin(x)*cos(x);"),
    (r"\sin\left(x+1\right)", "sin(x + 1);"),
    (r"\sin^2 x+\cos^2x", "sin(x)^2 + cos(x)^2;"),
    (r"\sin^{-1}x", "asin(x);"),
    (r"\ln x", "log(x);"),
    (r"\log_{2}8", "log(8)/log(2);"),
    (r"\sqrt{x}", "sqrt(x);"),
    (r"\sqrt[3]{x}", "x^(1/3);"),
    (r"\left|x\right|", "abs(x);"),
    (r"\binom{5}{2}", "binomial(5, 2);"),
    (r"\lfloor x\rfloor", "floor(x);"),
    (r"f\left(x\right)", "f(x);"),
    (r"f(x,y)", "f(x, y);"),
    ("x(y+1)", "x*(y + 1);"),
    (r"\operatorname{solve}\left(x^2=2,x\right)", "solve(x^2 = 2, x);"),
    (r"solve\left(x^2-1=0,x\right)", "solve(x^2 - 1 = 0, x);"),
    (r"factor(x^2-1)", "factor(x^2 - 1);"),
    (r"\mathrm{expand}\left((x+1)^3\right)", "expand((x + 1)^3);"),
    # calculus
    (r"\int x^2\,dx", "integrate(x^2, x);"),
    (r"\int x^2\,\mathrm{d}x", "integrate(x^2, x);"),
    (r"\int_{0}^{1}x^2\,\mathrm{d}x", "integrate(x^2, x, 0, 1);"),
    (r"\int_0^\infty e^{-x^2}dx", "integrate(%e^(-x^2), x, 0, inf);"),
    (r"\int\frac{1}{1+x^2}dx", "integrate(1/(1 + x^2), x);"),
    (r"\int_{-\infty}^{\infty}e^{-t^2}dt", "integrate(%e^(-t^2), t, minf, inf);"),
    (r"\int_0^1\int_0^1 xy\,dx\,dy", "integrate(integrate(x*y, x, 0, 1), y, 0, 1);"),
    (r"\int dx", "integrate(1, x);"),
    (r"\sum_{i=1}^{n}i^2", "sum(i^2, i, 1, n);"),
    (r"\sum_{k=0}^{\infty}\frac{1}{k!}", "sum(1/k!, k, 0, inf);"),
    (r"\sum_{i=1}^{n}i+1", "sum(i, i, 1, n) + 1;"),
    (r"\prod_{k=1}^{5}k", "product(k, k, 1, 5);"),
    (r"\lim_{x\to0}\frac{\sin x}{x}", "limit(sin(x)/x, x, 0);"),
    (r"\lim_{x\to\infty}\left(1+\frac{1}{x}\right)^x", "limit((1 + 1/x)^x, x, inf);"),
    (r"\lim_{x\to0^{+}}\frac{1}{x}", "limit(1/x, x, 0, plus);"),
    (r"\lim_{x\to 0^-}\frac{1}{x}", "limit(1/x, x, 0, minus);"),
    (r"\frac{d}{dx}x^3", "diff(x^3, x);"),
    (r"\frac{\mathrm{d}}{\mathrm{d}x}\sin x", "diff(sin(x), x);"),
    (r"\frac{d^2}{dx^2}x^4", "diff(x^4, x, 2);"),
    (r"\frac{dy}{dx}", "diff(y, x);"),
    (r"\frac{\partial}{\partial x}x^2y", "diff(x^2*y, x);"),
    (r"\frac{\partial^2f}{\partial x\partial y}", "diff(f, x, 1, y, 1);"),
    (r"\frac{\partial^{2}}{\partial x^{2}}\sin(xy)", "diff(sin(x*y), x, 2);"),
    # linear algebra
    (r"\begin{pmatrix}1&2\\3&4\end{pmatrix}", "matrix([1, 2], [3, 4]);"),
    (r"\begin{bmatrix}a&b\\c&d\end{bmatrix}^{-1}", "matrix([a, b], [c, d])^^(-1);"),
    (r"\begin{pmatrix}1&2\\3&4\end{pmatrix}^T", "transpose(matrix([1, 2], [3, 4]));"),
    (r"\begin{pmatrix}1&2\\3&4\end{pmatrix}^{\top}", "transpose(matrix([1, 2], [3, 4]));"),
    (r"\begin{pmatrix}1&0\\0&1\end{pmatrix}\begin{pmatrix}x\\y\end{pmatrix}",
     "matrix([1, 0], [0, 1]) . matrix([x], [y]);"),
    (r"\begin{vmatrix}a&b\\c&d\end{vmatrix}", "determinant(matrix([a, b], [c, d]));"),
    (r"\det\left(A\right)", "determinant(A);"),
    # relations, assignment, definitions
    (r"x^2+1=0", "x^2 + 1 = 0;"),
    (r"x\le 3", "x <= 3;"),
    (r"x\ne 3", "x # 3;"),
    (r"a\coloneq 5", "a: 5;"),
    (r"a:=5", "a: 5;"),
    (r"f(x)\coloneq x^2+1", "f(x) := x^2 + 1;"),
    (r"g\left(x,y\right):=x\cdot y", "g(x, y) := x*y;"),
    (r"\left[1,2,3\right]", "[1, 2, 3];"),
    (r"\left\lbrace 1,2\right\rbrace", "{1, 2};"),
    (r"3{,}5", "3.5;"),
]


@pytest.mark.parametrize("latex,expected", CASES)
def test_conversion(latex, expected):
    assert latex_to_maxima(latex) == expected


def test_known_functions_from_caller():
    assert latex_to_maxima("u(t)") == "u*(t);"
    assert latex_to_maxima("u(t)", known_functions={"u"}) == "u(t);"
    assert latex_to_maxima(r"\operatorname{myfun}(2)") == "myfun(2);"


def test_terminator():
    assert latex_to_maxima("1+1", terminator="$") == "1 + 1$"


@pytest.mark.parametrize("latex,fragment", [
    ("", "empty"),
    (r"\placeholder{}+1", "empty box"),
    (r"\int x^2", "differential"),
    (r"\int_0 x\,dx", "both limits"),
    (r"\sum_{i}^{n} i", "lower limit"),
    (r"\lim x", "subscript"),
    (r"x\pm 1", "±"),
    (r"\nabla f", "∇"),
    ("x(1,2)", "function"),
    (r"\begin{pmatrix}1&2\\3\end{pmatrix}", "same number"),
    (r"\frac{d^2}{dx}x", "order"),
    ("(1+2", "expected"),
    (r"\mathrm{d}x", "differential"),
])
def test_errors_are_explicit(latex, fragment):
    with pytest.raises(ConversionError) as exc:
        latex_to_maxima(latex)
    assert fragment.lower() in str(exc.value).lower()


def test_collect_function_names():
    names = collect_function_names(["f(x) := x^2;", "kinetic(m, v):=m*v^2/2$ y: 3;"])
    assert names == {"f", "kinetic"}
