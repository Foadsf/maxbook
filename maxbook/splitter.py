# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Split Maxima input text into top-level statements.

Maxima reads one statement at a time, terminated by ``;`` (display result) or
``$`` (suppress result).  The kernel sends statements one by one so it can stop
a cell at the first error, so it needs to find those terminators exactly the
way Maxima's reader does: ignoring them inside strings and (nested) comments,
and honouring backslash escapes.  ``:lisp`` break commands are line-based.
"""

from __future__ import annotations

from dataclasses import dataclass

LISP_PREFIXES = (":lisp-quiet", ":lisp")


@dataclass(frozen=True)
class Statement:
    text: str
    """Statement text including its terminator (or the ``:lisp`` line)."""
    terminator: str
    """``;``, ``$`` or ``lisp`` for a ``:lisp`` break command."""


class SplitError(ValueError):
    pass


def _is_blank(fragment: str) -> bool:
    """True when ``fragment`` holds only whitespace and complete comments."""
    i, n = 0, len(fragment)
    while i < n:
        c = fragment[i]
        if c.isspace():
            i += 1
        elif fragment.startswith("/*", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if fragment.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif fragment.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            if depth:
                return False
        else:
            return False
    return True


def split_statements(text: str, auto_terminate: bool = True) -> list[Statement]:
    """Return the statements in ``text``.

    A trailing statement without terminator gets ``;`` appended when
    ``auto_terminate`` is true (the usual notebook convenience); otherwise a
    :class:`SplitError` is raised.  Unterminated strings or comments always
    raise, because sending them would make Maxima wait for more input forever.
    """
    out: list[Statement] = []
    i, n = 0, len(text)
    start = 0
    at_statement_start = True
    while i < n:
        c = text[i]
        if at_statement_start:
            # Skip leading whitespace to see whether this is a :lisp line.
            j = i
            while j < n and text[j] in " \t\r\n":
                j += 1
            low = text[j:j + 11].lower()
            if any(low.startswith(p) for p in LISP_PREFIXES):
                end = text.find("\n", j)
                end = n if end == -1 else end
                out.append(Statement(text[j:end].rstrip(), "lisp"))
                i = start = end
                continue
            at_statement_start = False
        if c == "\\":
            i += 2
        elif c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            if i >= n:
                raise SplitError("unterminated string")
            i += 1
        elif text.startswith("/*", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if text.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif text.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            if depth:
                raise SplitError("unterminated comment")
        elif c in ";$":
            body = text[start:i + 1]
            if not _is_blank(body[:-1]):
                out.append(Statement(body.strip(), c))
            i += 1
            start = i
            at_statement_start = True
        else:
            i += 1
    rest = text[start:]
    if not _is_blank(rest):
        if not auto_terminate:
            raise SplitError("last statement has no terminator (; or $)")
        out.append(Statement(rest.strip() + ";", ";"))
    return out
