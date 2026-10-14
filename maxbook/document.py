# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""The structured notebook document (format version 2).

The editor (ProseMirror, see ``web/js/schema.js``) and this module agree on
these node types::

    doc            attrs: title, symbols ({name: {"description": str}})
    paragraph      inline content
    heading        attrs: level (1-4); inline content
    blockquote     block content
    bullet_list    list_item+
    ordered_list   attrs: order; list_item+
    list_item      paragraph block*
    horizontal_rule
    code_block     attrs: language; plain text (verbatim code that is not Maxima)
    maxima         attrs: id, source, outputs, inputs       (a Maxima input block)
    math_block     attrs: id, latex, source, run, outputs, inputs, result
                   (a display formula; run=true makes it an evaluated block)
    text           text, marks (strong, em, code, link{href})
    hard_break
    math_inline    attrs: id, latex, source, result          (formula inside prose;
                   source is its Maxima translation once it has been computed)

``result`` (compute in place) is null or {"latex", "semantic", "text"} or
{"error"}; it is shown after a formula that ends with "=".
"""

from __future__ import annotations

import uuid

BLOCKS = {"paragraph", "heading", "blockquote", "bullet_list", "ordered_list", "list_item",
          "horizontal_rule", "code_block", "maxima", "math_block"}
INLINES = {"text", "hard_break", "math_inline"}
MARKS = {"strong", "em", "code", "link"}
EVALUATED = {"maxima", "math_block"}


class DocumentError(ValueError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _clean_outputs(outs) -> list:
    if not isinstance(outs, list):
        return []
    return [o for o in outs if isinstance(o, dict) and o.get("kind") != "question"]


def _clean_result(res):
    if not isinstance(res, dict):
        return None
    keep = {k: str(v) for k, v in res.items() if k in ("latex", "semantic", "text", "error") and v is not None}
    return keep or None


def _ints(v):
    return v if isinstance(v, list) and all(isinstance(n, int) for n in v) else []


def normalize(doc: dict) -> dict:
    """Validate the tree, fill attribute defaults and make block ids unique."""
    if not isinstance(doc, dict) or doc.get("type") != "doc":
        raise DocumentError("top node must be a doc")
    seen: set[str] = set()

    def node(n: dict, depth: int) -> dict:
        if depth > 50:
            raise DocumentError("document nested too deeply")
        if not isinstance(n, dict) or not isinstance(n.get("type"), str):
            raise DocumentError(f"bad node: {str(n)[:60]}")
        t = n["type"]
        if t not in BLOCKS and t not in INLINES:
            raise DocumentError(f"unknown node type {t!r}")
        attrs = n.get("attrs") if isinstance(n.get("attrs"), dict) else {}
        out: dict = {"type": t}
        if t == "text":
            if not isinstance(n.get("text"), str) or not n["text"]:
                raise DocumentError("empty text node")
            out["text"] = n["text"]
            marks = []
            for m in n.get("marks", []) or []:
                if isinstance(m, dict) and m.get("type") in MARKS:
                    mk = {"type": m["type"]}
                    if m["type"] == "link":
                        mk["attrs"] = {"href": str((m.get("attrs") or {}).get("href", ""))}
                    marks.append(mk)
            if marks:
                out["marks"] = marks
            return out
        if t == "heading":
            level = attrs.get("level", 1)
            out["attrs"] = {"level": level if level in (1, 2, 3, 4) else 1}
        elif t == "ordered_list":
            order = attrs.get("order", 1)
            out["attrs"] = {"order": order if isinstance(order, int) and order >= 0 else 1}
        elif t == "code_block":
            out["attrs"] = {"language": str(attrs.get("language") or "")}
        elif t in EVALUATED:
            nid = str(attrs.get("id") or new_id())
            if nid in seen:
                nid = new_id()
            seen.add(nid)
            a = {"id": nid, "source": str(attrs.get("source") or ""),
                 "outputs": _clean_outputs(attrs.get("outputs")), "inputs": _ints(attrs.get("inputs"))}
            if t == "math_block":
                a.update({"latex": str(attrs.get("latex") or ""), "run": bool(attrs.get("run", False)),
                          "result": _clean_result(attrs.get("result"))})
            out["attrs"] = a
        elif t == "math_inline":
            nid = str(attrs.get("id") or new_id())
            if nid in seen:
                nid = new_id()
            seen.add(nid)
            out["attrs"] = {"id": nid, "latex": str(attrs.get("latex") or ""),
                            "source": str(attrs.get("source") or ""),
                            "result": _clean_result(attrs.get("result"))}
        content = n.get("content")
        if isinstance(content, list) and t not in ("maxima", "math_block", "math_inline", "hard_break",
                                                   "horizontal_rule"):
            kids = [node(c, depth + 1) for c in content]
            if kids:
                out["content"] = kids
        return out

    attrs = doc.get("attrs") if isinstance(doc.get("attrs"), dict) else {}
    symbols = attrs.get("symbols") if isinstance(attrs.get("symbols"), dict) else {}
    clean_symbols = {str(k): {"description": str((v or {}).get("description", ""))}
                     for k, v in symbols.items() if isinstance(v, dict)}
    content = doc.get("content")
    if not isinstance(content, list) or not content:
        content = [{"type": "paragraph"}]
    blocks = [node(c, 1) for c in content]
    for b in blocks:
        if b["type"] not in BLOCKS:
            raise DocumentError(f"{b['type']} cannot be at the top level")
    return {"type": "doc", "attrs": {"title": str(attrs.get("title") or ""), "symbols": clean_symbols},
            "content": blocks}


# ------------------------------------------------------------------ walkers
def inline_math_latex(attrs: dict) -> str:
    """The formula as displayed, including a computed result."""
    latex = attrs.get("latex", "")
    res = attrs.get("result") or {}
    if res.get("latex") and latex.rstrip().endswith("="):
        return f"{latex}{res['latex']}"
    return latex


def plain_text(node: dict) -> str:
    """Text content of a node, formulas as $...$."""
    t = node.get("type")
    if t == "text":
        return node["text"]
    if t == "hard_break":
        return "\n"
    if t == "math_inline":
        return f"${inline_math_latex(node.get('attrs', {}))}$"
    return "".join(plain_text(c) for c in node.get("content", []))


def walk_blocks(doc: dict):
    """Top-level blocks in order."""
    yield from doc.get("content", [])


def evaluated_blocks(doc: dict):
    """Maxima blocks and evaluated formulas, in document order (any depth)."""
    def rec(n):
        if n.get("type") in EVALUATED:
            yield n
        for c in n.get("content", []) or []:
            yield from rec(c)
    yield from rec(doc)
