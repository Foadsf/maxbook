# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Translate the LaTeX produced by a structural math editor into Maxima input.

Math cells are edited visually (MathLive); Maxima needs linear input.  This
module parses the subset of LaTeX that the editor emits and prints Maxima
syntax.  Anything outside the subset raises :class:`ConversionError` with a
message the notebook shows next to the cell; nothing is guessed silently.

Conventions (documented in docs/math-input.md):

* ``e`` and ``\\mathrm{e}`` are Euler's number ``%e``; ``\\pi`` is ``%pi``;
  ``\\imaginaryI`` / ``\\mathrm{i}`` is ``%i`` (a plain ``i`` stays a variable,
  because it is the usual summation index).
* ``x_{k}`` is the subscripted variable ``x[k]``.
* ``f(x)`` is a function call when ``f`` is a known function (Maxima built-ins,
  f/g/h, or names the caller passes in ``known_functions``); otherwise it is
  the product ``f*(x)``.
* ``a := 3`` assigns (``a : 3``); ``f(x) := x^2`` defines a function.
* ``\\frac{d}{dx}``, ``\\frac{dy}{dx}``, ``\\frac{\\partial^2 f}{\\partial x\\partial y}``
  are derivatives; ``\\int ... dx`` needs its differential.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class ConversionError(ValueError):
    pass


# --------------------------------------------------------------------- tokens
@dataclass
class Tok:
    kind: str  # cmd | char | num | letter | lbrace | rbrace | sup | sub | amp | rowsep | ws
    value: str

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{self.kind}:{self.value}"


_SPACING = {r"\,", r"\;", r"\:", r"\!", r"\ ", r"\quad", r"\qquad", r"\enspace",
            r"\thinspace", r"\medspace", r"\thickspace", r"\displaystyle",
            r"\textstyle", r"\mathstrut", r"\limits", r"\nolimits", r"\left.", r"\right."}


def tokenize(src: str) -> list[Tok]:
    toks: list[Tok] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
        elif c == "\\":
            if i + 1 < n and src[i + 1].isalpha():
                j = i + 1
                while j < n and src[j].isalpha():
                    j += 1
                name = src[i:j]
                if name in (r"\left", r"\right") and j < n and src[j] == ".":
                    j += 1
                    name += "."
                toks.append(Tok("cmd", name))
                i = j
            elif i + 1 < n and src[i + 1] == "\\":
                toks.append(Tok("rowsep", r"\\"))
                i += 2
            else:
                toks.append(Tok("cmd", src[i:i + 2]))
                i += 2
        elif c.isdigit() or (c == "." and i + 1 < n and src[i + 1].isdigit()):
            j = i
            while j < n and (src[j].isdigit() or src[j] == "."):
                j += 1
            # MathLive writes a decimal comma as "{,}"
            while src.startswith("{,}", j) and j + 3 < n and src[j + 3].isdigit():
                j += 3
                while j < n and src[j].isdigit():
                    j += 1
            toks.append(Tok("num", src[i:j].replace("{,}", ".")))
            i = j
        elif c == "{":
            toks.append(Tok("lbrace", c))
            i += 1
        elif c == "}":
            toks.append(Tok("rbrace", c))
            i += 1
        elif c == "^":
            toks.append(Tok("sup", c))
            i += 1
        elif c == "_":
            toks.append(Tok("sub", c))
            i += 1
        elif c == "&":
            toks.append(Tok("amp", c))
            i += 1
        elif c.isalpha():
            toks.append(Tok("letter", c))
            i += 1
        else:
            toks.append(Tok("char", c))
            i += 1
    out = [t for t in toks if not (t.kind == "cmd" and t.value in _SPACING)]
    return out


# ------------------------------------------------------------------------ AST
@dataclass
class Node:
    pass


@dataclass
class Num(Node):
    value: str


@dataclass
class Sym(Node):
    name: str


@dataclass
class Str(Node):
    value: str


@dataclass
class Call(Node):
    name: str
    args: list[Node]


@dataclass
class Apply(Node):
    """``name(args)`` that is either a call or a product, decided at print time."""
    name: str
    args: list[Node]


@dataclass
class BinOp(Node):
    op: str
    left: Node
    right: Node


@dataclass
class Neg(Node):
    operand: Node


@dataclass
class Index(Node):
    base: Node
    indices: list[Node]


@dataclass
class Group(Node):
    items: list[Node]
    kind: str = "paren"  # paren | list | set


@dataclass
class Matrix(Node):
    rows: list[list[Node]]


@dataclass
class Postfix(Node):
    op: str
    operand: Node


@dataclass
class Raw(Node):
    text: str
    prec: int = 100


@dataclass
class Statement:
    node: Node
    assign: Node | None = None
    is_function_def: bool = False


# ---------------------------------------------------------------- vocabulary
GREEK = {
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta", "theta",
    "vartheta", "iota", "kappa", "lambda", "mu", "nu", "xi", "rho", "varrho", "sigma",
    "varsigma", "tau", "upsilon", "phi", "varphi", "chi", "psi", "omega",
    "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Upsilon", "Phi", "Psi", "Omega",
}

LATEX_FUNCTIONS = {
    r"\sin": "sin", r"\cos": "cos", r"\tan": "tan", r"\sec": "sec", r"\csc": "csc",
    r"\cot": "cot", r"\arcsin": "asin", r"\arccos": "acos", r"\arctan": "atan",
    r"\sinh": "sinh", r"\cosh": "cosh", r"\tanh": "tanh", r"\coth": "coth",
    r"\sech": "sech", r"\csch": "csch", r"\ln": "log", r"\log": "log", r"\lg": "log10",
    r"\exp": "exp", r"\det": "determinant", r"\max": "max", r"\min": "min",
    r"\gcd": "gcd", r"\Re": "realpart", r"\Im": "imagpart", r"\arg": "carg",
    r"\deg": "deg", r"\dim": "dim", r"\ker": "ker", r"\sgn": "signum",
}
INVERSE_TRIG = {"sin": "asin", "cos": "acos", "tan": "atan", "sec": "asec", "csc": "acsc",
                "cot": "acot", "sinh": "asinh", "cosh": "acosh", "tanh": "atanh"}

# Names that are always treated as functions when followed by parentheses.
BUILTIN_FUNCTIONS = {
    "sin", "cos", "tan", "sec", "csc", "cot", "asin", "acos", "atan", "atan2", "sinh",
    "cosh", "tanh", "asinh", "acosh", "atanh", "log", "exp", "sqrt", "abs", "floor",
    "ceiling", "round", "signum", "max", "min", "gcd", "lcm", "mod", "binomial",
    "factorial", "gamma", "beta", "erf", "realpart", "imagpart", "conjugate", "carg",
    "diff", "integrate", "limit", "sum", "product", "taylor", "solve", "linsolve",
    "algsys", "allroots", "realroots", "find_root", "expand", "factor", "simplify",
    "ratsimp", "fullratsimp", "radcan", "trigsimp", "trigexpand", "trigreduce",
    "partfrac", "num", "denom", "subst", "ev", "float", "bfloat", "rat", "ode2",
    "ic1", "ic2", "bc2", "desolve", "laplace", "ilt", "determinant", "invert",
    "transpose", "eigenvalues", "eigenvectors", "rank", "charpoly", "echelon",
    "matrix", "length", "first", "last", "rest", "makelist", "map", "apply", "print",
    "display", "plot2d", "plot3d", "iplot2d", "iplot3d", "draw2d", "draw3d", "idraw2d",
    "idraw3d", "fourier", "powerseries", "residue", "nusum", "tex", "string",
    "coeff", "hipow", "lopow", "divide", "quotient", "remainder", "resultant",
    "primep", "ifactors", "divisors", "totient", "fib", "zeta", "bessel_j",
    "bessel_y", "airy_ai", "elliptic_f", "elliptic_e", "lambert_w", "polylog",
    "logcontract", "logexpand", "rectform", "polarform", "demoivre", "exponentialize",
}

DEFAULT_USER_FUNCTIONS = {"f", "g", "h", "F", "G", "H"}

RELATIONS = {
    "=": "=", "<": "<", ">": ">", r"\lt": "<", r"\gt": ">", r"\le": "<=", r"\leq": "<=",
    r"\leqslant": "<=", r"\ge": ">=", r"\geq": ">=", r"\geqslant": ">=", r"\ne": "#",
    r"\neq": "#",
}
ASSIGN = {r"\coloneq", r"\coloneqq", r"\colonequals", ":="}
ARROWS = {r"\to", r"\rightarrow", r"\longrightarrow", r"\mapsto"}
MULTIPLY = {r"\cdot": "*", r"\times": "*", "*": "*", r"\ast": "*", r"\bullet": "."}
UNSUPPORTED_HINT = {
    r"\placeholder": "fill in every empty box first",
    r"\pm": "± has no single value in Maxima; write the two cases separately",
    r"\mp": "∓ has no single value in Maxima; write the two cases separately",
    r"\nabla": "∇ is not supported in math cells yet; use a Maxima code cell",
    r"\oint": "contour integrals are not supported",
}


# --------------------------------------------------------------------- parser
@dataclass
class Parser:
    toks: list[Tok]
    known: set[str] = field(default_factory=set)
    pos: int = 0
    integrand_depth: int = 0

    # -- token helpers --------------------------------------------------------
    def peek(self, k: int = 0) -> Tok | None:
        j = self.pos + k
        return self.toks[j] if j < len(self.toks) else None

    def next(self) -> Tok:
        t = self.peek()
        if t is None:
            raise ConversionError("unexpected end of formula")
        self.pos += 1
        return t

    def at(self, kind: str, value: str | None = None, k: int = 0) -> bool:
        t = self.peek(k)
        return t is not None and t.kind == kind and (value is None or t.value == value)

    def at_cmd(self, *names: str) -> bool:
        t = self.peek()
        return t is not None and t.kind == "cmd" and t.value in names

    def at_char(self, *chars: str) -> bool:
        t = self.peek()
        return t is not None and t.kind == "char" and t.value in chars

    def expect(self, kind: str, value: str | None = None) -> Tok:
        t = self.peek()
        if t is None or t.kind != kind or (value is not None and t.value != value):
            want = value or kind
            got = "end of formula" if t is None else t.value
            raise ConversionError(f"expected {want!r}, found {got!r}")
        self.pos += 1
        return t

    def brace_group_tokens(self) -> list[Tok]:
        """Consume ``{...}`` and return the inner tokens."""
        self.expect("lbrace")
        depth, start = 1, self.pos
        while depth:
            t = self.next()
            if t.kind == "lbrace":
                depth += 1
            elif t.kind == "rbrace":
                depth -= 1
        return self.toks[start:self.pos - 1]

    def brace_text(self) -> str:
        return "".join(t.value for t in self.brace_group_tokens())

    def sub_parser(self, toks: list[Tok]) -> Parser:
        return Parser(toks, self.known, 0, self.integrand_depth)

    def parse_group(self) -> Node:
        """A ``{...}`` argument parsed as a full expression."""
        p = self.sub_parser(self.brace_group_tokens())
        node = p.parse_expression()
        p.finish()
        return node

    def script_arg(self) -> Node:
        """Argument of ^ or _: a brace group or a single token."""
        if self.at("lbrace"):
            return self.parse_group()
        t = self.next()
        if t.kind == "num":
            # x^23 in TeX means x^2 3; only the first digit is the exponent.
            if len(t.value) > 1:
                self.pos -= 1
                self.toks[self.pos] = Tok("num", t.value[1:])
                return Num(t.value[0])
            return Num(t.value)
        if t.kind == "letter":
            return self.letter_symbol(t.value)
        if t.kind == "cmd":
            self.pos -= 1
            return self.parse_primary()
        raise ConversionError(f"cannot use {t.value!r} as a script")

    def finish(self) -> None:
        if self.peek() is not None:
            raise ConversionError(f"unexpected {self.peek().value!r}")

    # -- grammar ---------------------------------------------------------------
    def parse_statement(self) -> Statement:
        lhs = self.parse_expression()
        if self.at_cmd(*ASSIGN) or (self.at_char(":") and self.at("char", "=", 1)):
            if self.at_char(":"):
                self.pos += 2
            else:
                self.pos += 1
            rhs = self.parse_expression()
            self.finish()
            if isinstance(lhs, (Apply, Call)):
                if not all(isinstance(a, Sym) for a in lhs.args):
                    raise ConversionError("function parameters must be plain names")
                return Statement(rhs, Call(lhs.name, lhs.args), is_function_def=True)
            if isinstance(lhs, (Sym, Index)):
                return Statement(rhs, lhs)
            raise ConversionError("left side of := must be a name or a function like f(x)")
        if self.at_char(":"):
            self.pos += 1
            rhs = self.parse_expression()
            self.finish()
            if not isinstance(lhs, (Sym, Index)):
                raise ConversionError("left side of : must be a name")
            return Statement(rhs, lhs)
        self.finish()
        return Statement(lhs)

    def parse_expression(self) -> Node:
        left = self.parse_additive()
        while True:
            t = self.peek()
            if t is None:
                return left
            op = RELATIONS.get(t.value) if t.kind in ("char", "cmd") else None
            if op is None:
                return left
            self.pos += 1
            right = self.parse_additive()
            left = BinOp(op, left, right)

    def parse_additive(self) -> Node:
        if self.at_char("-"):
            self.pos += 1
            node: Node = Neg(self.parse_term())
        else:
            if self.at_char("+"):
                self.pos += 1
            node = self.parse_term()
        while self.at_char("+", "-"):
            op = self.next().value
            node = BinOp(op, node, self.parse_term())
        return node

    def starts_factor(self) -> bool:
        t = self.peek()
        if t is None:
            return False
        if self.integrand_depth and self.at_differential():
            return False
        if t.kind in ("num", "letter", "lbrace"):
            return True
        if t.kind == "char":
            return t.value in "(|["
        if t.kind == "cmd":
            v = t.value
            if v in RELATIONS or v in ASSIGN or v in MULTIPLY or v in ARROWS:
                return False
            return v not in (r"\right", r"\right.", r"\end", r"\rvert", r"\rfloor", r"\rceil",
                             r"\div", r"\rbrace", r"\}", r"\rangle")
        return False

    def parse_term(self) -> Node:
        node = self.parse_factor()
        while True:
            t = self.peek()
            if t is None:
                return node
            if t.kind in ("cmd", "char") and t.value in MULTIPLY:
                self.pos += 1
                op = MULTIPLY[t.value]
                rhs = self.parse_factor()
                if op == "*" and (isinstance(node, Matrix) or isinstance(rhs, Matrix)):
                    op = "."
                node = BinOp(op, node, rhs)
            elif (t.kind == "char" and t.value == "/") or (t.kind == "cmd" and t.value == r"\div"):
                self.pos += 1
                node = BinOp("/", node, self.parse_factor())
            elif self.starts_factor():
                rhs = self.parse_factor()
                op = "." if isinstance(node, Matrix) and isinstance(rhs, Matrix) else "*"
                node = BinOp(op, node, rhs)
            else:
                return node

    def parse_factor(self) -> Node:
        if self.at_char("-"):
            self.pos += 1
            return Neg(self.parse_factor())
        node = self.parse_primary()
        return self.parse_postfix(node)

    def parse_postfix(self, node: Node) -> Node:
        while True:
            if self.at("sup"):
                self.pos += 1
                matrixish = isinstance(node, Matrix) or (
                    isinstance(node, Sym) and len(node.name) == 1 and node.name.isupper())
                if self.at("lbrace") and self.is_transpose_group(matrixish):
                    self.brace_group_tokens()
                    node = Call("transpose", [node])
                    continue
                if self.at_cmd(r"\top", r"\intercal", r"\mathsf", r"\mathrm") and self.is_transpose_single():
                    node = Call("transpose", [node])
                    continue
                if matrixish and self.at("letter", "T"):
                    self.pos += 1
                    node = Call("transpose", [node])
                    continue
                if self.at_cmd(r"\circ") or (self.at("lbrace") and self.at("cmd", r"\circ", 1)
                                             and self.at("rbrace", k=2)):
                    self.pos += 3 if self.at("lbrace") else 1
                    node = BinOp("*", node, Raw("%pi/180", 3))
                    continue
                if self.at_cmd(r"\prime"):
                    raise ConversionError("primes (f') are not supported; use d/dx")
                exp = self.script_arg()
                if isinstance(node, Matrix) and isinstance(exp, Neg) and isinstance(exp.operand, Num):
                    node = BinOp("^^", node, exp)
                else:
                    node = BinOp("^", node, exp)
            elif self.at("sub"):
                self.pos += 1
                if self.at("lbrace"):
                    items = self.comma_list(self.brace_group_tokens())
                else:
                    items = [self.script_arg()]
                node = Index(node, items)
            elif self.at_char("!"):
                self.pos += 1
                node = Postfix("!", node)
            elif self.at_char("'"):
                raise ConversionError("primes (f') are not supported; use d/dx")
            else:
                return node

    def comma_list(self, toks: list[Tok]) -> list[Node]:
        parts: list[list[Tok]] = [[]]
        depth = 0
        for t in toks:
            if t.kind == "lbrace" or (t.kind == "char" and t.value in "([") or \
                    (t.kind == "cmd" and t.value == r"\left"):
                depth += 1
            elif t.kind == "rbrace" or (t.kind == "char" and t.value in ")]") or \
                    (t.kind == "cmd" and t.value == r"\right"):
                depth -= 1
            if depth == 0 and t.kind == "char" and t.value == ",":
                parts.append([])
            else:
                parts[-1].append(t)
        out = []
        for part in parts:
            p = self.sub_parser(part)
            out.append(p.parse_expression())
            p.finish()
        return out

    def is_transpose_group(self, matrixish: bool = True) -> bool:
        inner = []
        depth, j = 0, self.pos
        while j < len(self.toks):
            t = self.toks[j]
            if t.kind == "lbrace":
                depth += 1
                if depth == 1:
                    j += 1
                    continue
            elif t.kind == "rbrace":
                depth -= 1
                if depth == 0:
                    break
            inner.append(t)
            j += 1
        vals = [t.value for t in inner if t.kind not in ("lbrace", "rbrace")]
        if vals == ["T"]:
            return matrixish
        return vals in ([r"\top"], [r"\intercal"], [r"\mathsf", "T"], [r"\mathrm", "T"])

    def is_transpose_single(self) -> bool:
        t = self.peek()
        if t.value in (r"\top", r"\intercal"):
            self.pos += 1
            return True
        if self.at("lbrace", k=1) and self.at("letter", "T", 2) and self.at("rbrace", k=3):
            self.pos += 4
            return True
        return False

    # -- primaries ---------------------------------------------------------------
    def letter_symbol(self, ch: str) -> Node:
        if ch == "e":
            return Raw("%e")
        return Sym(ch)

    def parse_primary(self) -> Node:
        t = self.peek()
        if t is None:
            raise ConversionError("formula is incomplete")
        if t.kind == "num":
            self.pos += 1
            return Num(t.value)
        if t.kind == "letter":
            return self.parse_letters()
        if t.kind == "lbrace":
            return self.parse_group()
        if t.kind == "char":
            if t.value == "(":
                self.pos += 1
                return self.parse_delimited(")", None)
            if t.value == "[":
                self.pos += 1
                return self.parse_delimited("]", None, kind="list")
            if t.value == "|":
                self.pos += 1
                inner = self.parse_expression()
                if not self.at_char("|"):
                    raise ConversionError("missing closing |")
                self.pos += 1
                return Call("abs", [inner])
            raise ConversionError(f"unexpected {t.value!r}")
        if t.kind == "cmd":
            return self.parse_command()
        raise ConversionError(f"unexpected {t.value!r}")

    def parse_letters(self) -> Node:
        """A run of single letters: maybe a function name typed letter by letter."""
        j = self.pos
        while self.at("letter", k=j - self.pos):
            j += 1
        run = "".join(t.value for t in self.toks[self.pos:j])
        after_paren = j < len(self.toks) and (
            (self.toks[j].kind == "char" and self.toks[j].value == "(")
            or (self.toks[j].kind == "cmd" and self.toks[j].value == r"\left"))
        if len(run) > 1 and after_paren:
            # Longest suffix-free prefix that names a function: "solve(" etc.
            for k in range(len(run), 1, -1):
                name = run[:k]
                if name in BUILTIN_FUNCTIONS or name in self.known:
                    if k == len(run):
                        self.pos = j
                        return self.parse_application(name)
                    break
        ch = self.next().value
        if after_paren and j == self.pos and (ch in self.known or ch in DEFAULT_USER_FUNCTIONS):
            return self.parse_application(ch)
        node = self.letter_symbol(ch)
        if j == self.pos and after_paren and isinstance(node, Sym):
            args = self.parse_call_args()
            return Apply(ch, args)
        return node

    def parse_application(self, name: str) -> Node:
        return Call(name, self.parse_call_args())

    def parse_call_args(self) -> list[Node]:
        if self.at_cmd(r"\left"):
            self.pos += 1
            self.expect("char", "(")
            node = self.parse_delimited(")", r"\right", kind="tuple")
        else:
            self.expect("char", "(")
            node = self.parse_delimited(")", None, kind="tuple")
        assert isinstance(node, Group)
        return node.items

    def parse_delimited(self, close: str, right_cmd: str | None, kind: str = "paren") -> Node:
        """Parse comma-separated expressions up to ``close`` (after ``\\right``)."""
        items: list[Node] = []
        saved = self.integrand_depth
        self.integrand_depth = 0
        while True:
            if self.closing(close, right_cmd):
                break
            items.append(self.parse_expression())
            if self.at_char(","):
                self.pos += 1
                continue
            if not self.closing(close, right_cmd):
                t = self.peek()
                raise ConversionError(f"expected {close!r}, found {t.value if t else 'end of formula'!r}")
        self.consume_closing(close, right_cmd)
        self.integrand_depth = saved
        if kind == "paren":
            if len(items) == 1:
                return Group(items, "paren")
            return Group(items, "tuple")
        return Group(items, kind)

    def closing(self, close: str, right_cmd: str | None) -> bool:
        if right_cmd:
            return self.at_cmd(right_cmd)
        if close in ("}",) :
            return self.at_cmd(r"\}", r"\rbrace")
        return self.at_char(close)

    def consume_closing(self, close: str, right_cmd: str | None) -> None:
        if right_cmd:
            self.expect("cmd", right_cmd)
            if close == "}":
                if self.at_cmd(r"\}", r"\rbrace"):
                    self.pos += 1
                    return
                raise ConversionError("expected closing brace")
            self.expect("char", close) if close != "|" else self.expect("char", "|")
        elif close == "}":
            self.pos += 1
        else:
            self.expect("char", close)

    def parse_command(self) -> Node:
        t = self.next()
        v = t.value
        if v in UNSUPPORTED_HINT:
            raise ConversionError(UNSUPPORTED_HINT[v])
        name = v[1:]
        if name in GREEK:
            return Sym(name)
        if v == r"\pi":
            return Raw("%pi")
        if v in (r"\infty", r"\infin"):
            return Raw("inf")
        if v in (r"\exponentialE",):
            return Raw("%e")
        if v in (r"\imaginaryI", r"\imath"):
            return Raw("%i")
        if v == r"\left":
            return self.parse_left()
        if v in (r"\frac", r"\dfrac", r"\tfrac", r"\cfrac"):
            return self.parse_frac()
        if v == r"\sqrt":
            if self.at_char("["):
                self.pos += 1
                start = self.pos
                while not self.at_char("]"):
                    self.next()
                idx_p = self.sub_parser(self.toks[start:self.pos])
                index = idx_p.parse_expression()
                self.pos += 1
                radicand = self.parse_group()
                return BinOp("^", Group([radicand]), Group([BinOp("/", Num("1"), index)]))
            return Call("sqrt", [self.parse_group()])
        if v == r"\binom":
            return Call("binomial", [self.parse_group(), self.parse_group()])
        if v in (r"\mathrm", r"\operatorname", r"\mathit", r"\text", r"\textrm", r"\mathbf",
                 r"\boldsymbol", r"\mathsf", r"\textit"):
            return self.parse_named(v)
        if v in LATEX_FUNCTIONS:
            return self.parse_function(LATEX_FUNCTIONS[v])
        if v in (r"\int", r"\iint", r"\iiint"):
            return self.parse_integral(v)
        if v in (r"\sum", r"\prod"):
            return self.parse_bigop("sum" if v == r"\sum" else "product")
        if v == r"\lim":
            return self.parse_limit()
        if v == r"\begin":
            return self.parse_environment()
        if v in (r"\lvert", r"\vert", r"\|"):
            inner = self.parse_expression()
            self.expect("cmd")
            return Call("abs", [inner])
        if v == r"\lfloor":
            inner = self.parse_expression()
            self.expect("cmd", r"\rfloor")
            return Call("floor", [inner])
        if v == r"\lceil":
            inner = self.parse_expression()
            self.expect("cmd", r"\rceil")
            return Call("ceiling", [inner])
        if v == r"\overline":
            return Call("conjugate", [self.parse_group()])
        if v in (r"\{", r"\lbrace"):
            return self.parse_delimited("}", None, kind="set")
        if v == r"\partial":
            raise ConversionError("use \\frac{\\partial f}{\\partial x} for partial derivatives")
        if v in (r"\differentialD",):
            raise ConversionError("a differential d is only allowed at the end of an integral")
        raise ConversionError(f"{v} is not supported in math cells (try a Maxima code cell)")

    def parse_left(self) -> Node:
        t = self.next()
        if t.kind == "char" and t.value == "(":
            return self.parse_delimited(")", r"\right")
        if t.kind == "char" and t.value == "[":
            return self.parse_delimited("]", r"\right", kind="list")
        if (t.kind == "char" and t.value == "|") or (t.kind == "cmd" and t.value in (r"\vert", r"\lvert")):
            inner = self.parse_expression()
            self.expect("cmd", r"\right")
            self.next()
            return Call("abs", [inner])
        if t.kind == "cmd" and t.value in (r"\{", r"\lbrace"):
            return self.parse_delimited("}", r"\right", kind="set")
        if t.kind == "cmd" and t.value == r"\lfloor":
            inner = self.parse_expression()
            self.expect("cmd", r"\right")
            self.next()
            return Call("floor", [inner])
        if t.kind == "cmd" and t.value == r"\lceil":
            inner = self.parse_expression()
            self.expect("cmd", r"\right")
            self.next()
            return Call("ceiling", [inner])
        if t.kind == "cmd" and t.value in (r"\|", r"\Vert"):
            raise ConversionError("norms ‖x‖ are not supported; use a Maxima code cell")
        raise ConversionError(f"unsupported delimiter \\left{t.value}")

    def parse_named(self, cmd: str) -> Node:
        text = self.brace_text().strip()
        if cmd in (r"\text", r"\textrm", r"\textit"):
            return Str(text)
        if text == "d":
            raise ConversionError("a differential d is only allowed at the end of an integral")
        if text == "e":
            return Raw("%e")
        if text == "i":
            return Raw("%i")
        if not re.fullmatch(r"[A-Za-z_%][A-Za-z0-9_%]*", text):
            raise ConversionError(f"{text!r} is not a valid Maxima name")
        if self.at_char("(") or self.at_cmd(r"\left"):
            if self.at_cmd(r"\left") and not self.at("char", "(", 1):
                return Sym(text)
            return Call(text, self.parse_call_args())
        return Sym(text)

    def parse_function(self, fname: str) -> Node:
        power: Node | None = None
        base: Node | None = None
        while self.at("sup") or self.at("sub"):
            if self.at("sup"):
                self.pos += 1
                power = self.script_arg()
            else:
                self.pos += 1
                base = self.script_arg()
        if isinstance(power, Neg) and isinstance(power.operand, Num) and power.operand.value == "1" \
                and fname in INVERSE_TRIG:
            fname, power = INVERSE_TRIG[fname], None
        if self.at_char("(") or (self.at_cmd(r"\left") and self.at("char", "(", 1)):
            args = self.parse_call_args()
        else:
            args = [self.parse_function_argument()]
        if fname == "log" and base is not None:
            node: Node = BinOp("/", Call("log", args), Call("log", [base]))
        elif fname == "log10":
            node = BinOp("/", Call("log", args), Call("log", [Num("10")]))
        else:
            if base is not None:
                raise ConversionError(f"subscripts on {fname} are not supported")
            node = Call(fname, args)
        if power is not None:
            node = BinOp("^", node, power)
        return node

    def parse_function_argument(self) -> Node:
        """Argument of ``\\sin x``: a product of factors up to the next operator."""
        if not self.starts_factor():
            raise ConversionError("function needs an argument")
        node = self.parse_factor()
        while self.starts_factor() and not (self.peek().kind == "cmd" and self.peek().value in LATEX_FUNCTIONS):
            node = BinOp("*", node, self.parse_factor())
        return node

    # -- calculus ------------------------------------------------------------
    def at_differential(self) -> bool:
        """``dx``, ``\\mathrm{d}x``, ``\\differentialD x`` ahead?"""
        t = self.peek()
        if t is None:
            return False
        if t.kind == "letter" and t.value == "d":
            nxt = self.peek(1)
            return nxt is not None and (nxt.kind == "letter" or
                                        (nxt.kind == "cmd" and nxt.value[1:] in GREEK))
        if t.kind == "cmd" and t.value == r"\differentialD":
            return True
        if t.kind == "cmd" and t.value in (r"\mathrm", r"\operatorname", r"\text"):
            return (self.at("lbrace", k=1) and self.at("letter", "d", 2) and self.at("rbrace", k=3))
        return False

    def consume_differential(self) -> Node:
        t = self.next()
        if t.kind == "cmd" and t.value in (r"\mathrm", r"\operatorname", r"\text"):
            self.pos += 3
        nxt = self.next()
        if nxt.kind == "letter":
            return Sym(nxt.value)
        if nxt.kind == "cmd" and nxt.value[1:] in GREEK:
            return Sym(nxt.value[1:])
        raise ConversionError("expected the integration variable after d")

    def parse_limits(self) -> tuple[Node | None, Node | None]:
        lower = upper = None
        for _ in range(2):
            if self.at("sub"):
                self.pos += 1
                lower = self.script_arg()
            elif self.at("sup"):
                self.pos += 1
                upper = self.script_arg()
        return lower, upper

    def parse_integral(self, cmd: str) -> Node:
        if cmd != r"\int":
            raise ConversionError("write multiple integrals as nested \\int ... dx dy")
        lower, upper = self.parse_limits()
        if (lower is None) != (upper is None):
            raise ConversionError("a definite integral needs both limits")
        self.integrand_depth += 1
        try:
            if self.at_differential():
                integrand: Node = Num("1")
            else:
                integrand = self.parse_additive()
            if not self.at_differential():
                raise ConversionError("integral is missing its differential (dx)")
            var = self.consume_differential()
        finally:
            self.integrand_depth -= 1
        # "\int \frac{1}{x} dx" style is handled above; also allow "dx f(x)".
        args = [integrand, var]
        if lower is not None:
            args += [lower, upper]
        return Call("integrate", args)

    def parse_bigop(self, fname: str) -> Node:
        lower, upper = self.parse_limits()
        if not (isinstance(lower, BinOp) and lower.op == "=" and isinstance(lower.left, (Sym, Raw))):
            raise ConversionError(f"{fname} needs a lower limit like i=1")
        if upper is None:
            raise ConversionError(f"{fname} needs an upper limit")
        body = self.parse_term()
        return Call(fname, [body, lower.left, lower.right, upper])

    def parse_limit(self) -> Node:
        if not self.at("sub"):
            raise ConversionError("limit needs a subscript like x \\to 0")
        self.pos += 1
        sub = self.brace_group_tokens() if self.at("lbrace") else [self.next()]
        arrow = next((i for i, t in enumerate(sub) if t.kind == "cmd" and t.value in ARROWS), None)
        if arrow is None:
            raise ConversionError("limit subscript must look like x \\to a")
        target_toks = sub[arrow + 1:]
        # One-sided limits are written a^{+} / a^{-}.
        direction = None
        tail = "".join(t.value for t in target_toks[-4:])
        for suffix, d, cut in (("^{+}", "plus", 4), ("^{-}", "minus", 4)):
            if tail.endswith(suffix):
                direction, target_toks = d, target_toks[:-cut]
        if direction is None and len(target_toks) >= 2 and target_toks[-2].kind == "sup" \
                and target_toks[-1].value in "+-":
            direction = "plus" if target_toks[-1].value == "+" else "minus"
            target_toks = target_toks[:-2]
        p = self.sub_parser(sub[:arrow])
        var = p.parse_additive()
        p.finish()
        q = self.sub_parser(target_toks)
        target = q.parse_additive()
        q.finish()
        if self.at_differential():
            raise ConversionError("unexpected differential after limit")
        body = self.parse_term()
        args = [body, var, target]
        if direction:
            args.append(Raw(direction))
        return Call("limit", args)

    def parse_frac(self) -> Node:
        num_toks = self.brace_group_tokens()
        den_toks = self.brace_group_tokens()
        deriv = self.derivative_from_frac(num_toks, den_toks)
        if deriv is not None:
            return deriv
        num = self.sub_parser(num_toks)
        n = num.parse_expression()
        num.finish()
        den = self.sub_parser(den_toks)
        d = den.parse_expression()
        den.finish()
        return BinOp("/", Group([n]), Group([d]))

    @staticmethod
    def _strip_d(toks: list[Tok], partial: bool) -> list[Tok] | None:
        """Remove a leading d / \\mathrm{d} / \\partial; None when absent."""
        if partial:
            if toks and toks[0].kind == "cmd" and toks[0].value == r"\partial":
                return toks[1:]
            return None
        if toks and toks[0].kind == "letter" and toks[0].value == "d":
            return toks[1:]
        if toks and toks[0].kind == "cmd" and toks[0].value == r"\differentialD":
            return toks[1:]
        if (len(toks) >= 4 and toks[0].kind == "cmd" and toks[0].value in (r"\mathrm", r"\operatorname")
                and toks[1].kind == "lbrace" and toks[2].value == "d" and toks[3].kind == "rbrace"):
            return toks[4:]
        return None

    def _order(self, toks: list[Tok]) -> tuple[int, list[Tok]]:
        """Leading ``^{n}`` / ``^n`` on the numerator d."""
        if toks and toks[0].kind == "sup":
            if len(toks) > 1 and toks[1].kind == "num":
                return int(toks[1].value), toks[2:]
            if len(toks) > 3 and toks[1].kind == "lbrace" and toks[2].kind == "num" and toks[3].kind == "rbrace":
                return int(toks[2].value), toks[4:]
            raise ConversionError("derivative order must be a number")
        return 1, toks

    def derivative_from_frac(self, num_toks: list[Tok], den_toks: list[Tok]) -> Node | None:
        for partial in (False, True):
            rest = self._strip_d(num_toks, partial)
            if rest is None or self._strip_d(den_toks, partial) is None:
                continue
            order, func_toks = self._order(rest)
            variables = self.parse_derivative_denominator(den_toks, partial)
            if sum(k for _, k in variables) != order:
                raise ConversionError("derivative order in numerator and denominator differ")
            if func_toks:
                p = self.sub_parser(func_toks)
                f = p.parse_expression()
                p.finish()
            else:
                if not self.starts_factor():
                    raise ConversionError("d/dx needs something to differentiate")
                f = self.parse_term()
            args: list[Node] = [f]
            for var, k in variables:
                args.append(var)
                args.append(Num(str(k)))
            if len(variables) == 1 and variables[0][1] == 1:
                args = args[:2]
            return Call("diff", args)
        return None

    def parse_derivative_denominator(self, toks: list[Tok], partial: bool) -> list[tuple[Node, int]]:
        out: list[tuple[Node, int]] = []
        rest = toks
        while rest:
            stripped = self._strip_d(rest, partial)
            if stripped is None:
                raise ConversionError("could not read the derivative's denominator")
            if not stripped:
                raise ConversionError("missing variable in derivative denominator")
            t = stripped[0]
            if t.kind == "letter":
                var: Node = Sym(t.value)
            elif t.kind == "cmd" and t.value[1:] in GREEK:
                var = Sym(t.value[1:])
            else:
                raise ConversionError("derivative variable must be a single letter")
            rest = stripped[1:]
            k = 1
            if rest and rest[0].kind == "sup":
                k, rest = self._order(rest)
            out.append((var, k))
        return out

    def parse_environment(self) -> Node:
        env = self.brace_text()
        if env not in ("matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "smallmatrix"):
            raise ConversionError(f"environment {env!r} is not supported")
        rows: list[list[Node]] = [[]]
        start = self.pos
        depth = 0
        cells: list[list[Tok]] = [[]]
        grid: list[list[list[Tok]]] = []
        while True:
            t = self.next()
            if t.kind == "cmd" and t.value == r"\begin":
                depth += 1
            if t.kind == "cmd" and t.value == r"\end":
                if depth == 0:
                    self.brace_text()
                    break
                depth -= 1
            if depth == 0 and t.kind == "amp":
                cells.append([])
            elif depth == 0 and t.kind == "rowsep":
                grid.append(cells)
                cells = [[]]
            else:
                cells[-1].append(t)
        if any(c for c in cells):
            grid.append(cells)
        del start
        rows = []
        for row in grid:
            parsed = []
            for cell in row:
                p = self.sub_parser(cell)
                node = p.parse_expression()
                p.finish()
                parsed.append(node)
            rows.append(parsed)
        width = len(rows[0]) if rows else 0
        if not rows or any(len(r) != width for r in rows):
            raise ConversionError("matrix rows must have the same number of entries")
        m = Matrix(rows)
        if env == "vmatrix":
            return Call("determinant", [m])
        return m


# -------------------------------------------------------------------- printer
PREC = {"=": 1, "<": 1, ">": 1, "<=": 1, ">=": 1, "#": 1, "+": 2, "-": 2, "*": 3, "/": 3,
        ".": 3, "neg": 4, "^": 5, "^^": 5, "!": 6}


class Printer:
    def __init__(self, known: set[str]):
        self.known = known

    def prec(self, node: Node) -> int:
        if isinstance(node, Group) and node.kind == "paren" and len(node.items) == 1:
            return self.prec(node.items[0])
        if isinstance(node, BinOp):
            return PREC[node.op]
        if isinstance(node, Neg):
            return PREC["neg"]
        if isinstance(node, Postfix):
            return PREC["!"]
        if isinstance(node, Raw):
            return node.prec
        if isinstance(node, Apply) and not self.is_call(node):
            return PREC["*"]
        return 100

    def is_call(self, node: Apply) -> bool:
        return node.name in self.known or node.name in DEFAULT_USER_FUNCTIONS

    def wrap(self, node: Node, min_prec: int, strict: bool = False) -> str:
        s = self.p(node)
        p = self.prec(node)
        if p < min_prec or (strict and p == min_prec):
            return f"({s})"
        return s

    def p(self, node: Node) -> str:
        if isinstance(node, Num):
            return node.value
        if isinstance(node, Sym):
            return node.name
        if isinstance(node, Raw):
            return node.text
        if isinstance(node, Str):
            return '"' + node.value.replace("\\", "\\\\").replace('"', '\\"') + '"'
        if isinstance(node, Call):
            return f"{node.name}({', '.join(self.p(a) for a in node.args)})"
        if isinstance(node, Apply):
            if self.is_call(node):
                return f"{node.name}({', '.join(self.p(a) for a in node.args)})"
            if len(node.args) != 1:
                raise ConversionError(
                    f"{node.name}(…) with several arguments: is {node.name} a function? "
                    f"Define it first or write \\operatorname{{{node.name}}}")
            return f"{node.name}*({self.p(node.args[0])})"
        if isinstance(node, Group):
            if node.kind == "list":
                return "[" + ", ".join(self.p(a) for a in node.items) + "]"
            if node.kind == "set":
                return "{" + ", ".join(self.p(a) for a in node.items) + "}"
            if node.kind == "tuple":
                raise ConversionError("a parenthesised list (a, b) is only valid as function arguments")
            return self.wrap(node.items[0], 0) if len(node.items) == 1 else self.p(node.items[0])
        if isinstance(node, Neg):
            if isinstance(node.operand, Raw) and node.operand.text == "inf":
                return "minf"
            return "-" + self.wrap(node.operand, PREC["neg"] + 1)
        if isinstance(node, Postfix):
            return self.wrap(node.operand, PREC["!"], strict=True) + "!"
        if isinstance(node, Index):
            return self.wrap(node.base, 100) + "[" + ", ".join(self.p(i) for i in node.indices) + "]"
        if isinstance(node, Matrix):
            return "matrix(" + ", ".join("[" + ", ".join(self.p(c) for c in r) + "]" for r in node.rows) + ")"
        if isinstance(node, BinOp):
            op = node.op
            pr = PREC[op]
            if op in ("^", "^^"):
                left = self.wrap(node.left, pr, strict=True)
                right = self.wrap(node.right, pr)
                if isinstance(node.right, (Neg,)) or self.prec(node.right) < 100:
                    right = f"({self.p(node.right)})"
                return f"{left}{op}{right}"
            left = self.wrap(node.left, pr)
            right = self.wrap(node.right, pr, strict=op in ("-", "/", "."))
            if op in ("*", "/", "^", "."):
                sep = op if op != "." else " . "
                return f"{left}{sep}{right}"
            return f"{left} {op} {right}"
        raise ConversionError(f"cannot print {type(node).__name__}")  # pragma: no cover


def collect_function_names(sources: list[str]) -> set[str]:
    """Names defined as functions (``name(...) :=``) in Maxima sources."""
    names = set()
    for src in sources:
        names.update(re.findall(r"([A-Za-z_%][A-Za-z0-9_%]*)\s*\([^()]*\)\s*:=", src))
    return names


def latex_to_maxima(latex: str, known_functions: set[str] | None = None,
                    terminator: str = ";") -> str:
    """Convert one math-cell formula to a Maxima statement."""
    if not latex.strip():
        raise ConversionError("empty formula")
    known = set(known_functions or ()) | BUILTIN_FUNCTIONS
    parser = Parser(tokenize(latex), known)
    st = parser.parse_statement()
    pr = Printer(known)
    body = pr.p(st.node)
    if st.assign is None:
        return body + terminator
    if st.is_function_def:
        return f"{pr.p(st.assign)} := {body}{terminator}"
    return f"{pr.p(st.assign)}: {body}{terminator}"
