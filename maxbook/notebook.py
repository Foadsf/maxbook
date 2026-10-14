# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Notebook files: the native ``.maxbook`` format.

Version 2 (current) stores one structured document, the editor's document
tree as JSON::

    {"format": "maxbook", "version": 2, "title": "...",
     "doc": {"type": "doc", "attrs": {...}, "content": [ ...block nodes... ]},
     "metadata": {...}}

The node types are described in :mod:`maxbook.document`.  Prose, inline
formulas, display formulas and Maxima blocks live in one flow, like a
word-processor document; Maxima blocks and evaluated formulas keep their
outputs so a saved notebook reads like a document without re-running Maxima.

Version 1 stored a list of cells (Markdown, Maxima code, math).  Version 1
files and imported files (.wxm, .wxmx, .mac, .md, .tex) are returned in that
cell form; the editor converts them to a document, and saving writes v2.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from . import document

FORMAT = "maxbook"
VERSION = 2
EXTENSION = ".maxbook"
CELL_TYPES = ("markdown", "code", "math")


class NotebookError(ValueError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# --------------------------------------------------------------- v1 / imports
def make_cell(cell_type: str, source: str = "", latex: str = "", outputs=None) -> dict:
    if cell_type not in CELL_TYPES:
        raise NotebookError(f"unknown cell type {cell_type!r}")
    cell = {"id": new_id(), "type": cell_type, "source": source}
    if cell_type == "math":
        cell["latex"] = latex
    if cell_type != "markdown":
        cell["outputs"] = list(outputs or [])
    return cell


def clean_outputs(outs) -> list:
    """Drop transient question prompts; keep well-formed outputs only."""
    if not isinstance(outs, list):
        return []
    return [o for o in outs if isinstance(o, dict) and o.get("kind") != "question"]


def validate_cells(nb: dict) -> dict:
    """Validate a version-1 (cell list) notebook or an import result."""
    cells = nb.get("cells")
    if not isinstance(cells, list):
        raise NotebookError("notebook has no cell list")
    out_cells = []
    seen = set()
    for c in cells:
        if not isinstance(c, dict) or c.get("type") not in CELL_TYPES:
            raise NotebookError(f"invalid cell: {str(c)[:80]}")
        cid = str(c.get("id") or new_id())
        if cid in seen:
            cid = new_id()
        seen.add(cid)
        cell = {"id": cid, "type": c["type"], "source": str(c.get("source", ""))}
        if c["type"] == "math":
            cell["latex"] = str(c.get("latex", ""))
        if c["type"] != "markdown":
            cell["outputs"] = clean_outputs(c.get("outputs", []))
            inputs = c.get("inputs")
            if isinstance(inputs, list) and all(isinstance(n, int) for n in inputs):
                cell["inputs"] = inputs
        out_cells.append(cell)
    return {"format": FORMAT, "version": 1, "title": str(nb.get("title", "Untitled")),
            "cells": out_cells,
            "metadata": nb.get("metadata", {}) if isinstance(nb.get("metadata"), dict) else {}}


# ---------------------------------------------------------------------- v2
def new_notebook(title: str = "Untitled") -> dict:
    doc = {"type": "doc", "attrs": {"title": title, "symbols": {}},
           "content": [{"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": title}]},
                       {"type": "paragraph"}]}
    return {"format": FORMAT, "version": VERSION, "title": title, "doc": doc, "metadata": {}}


def validate(nb: dict) -> dict:
    """Check a notebook and normalise it; raise NotebookError on bad input.

    Accepts version 2 (document) and version 1 (cells, returned unchanged in
    form so the editor can convert it)."""
    if not isinstance(nb, dict):
        raise NotebookError("notebook must be a JSON object")
    if nb.get("format", FORMAT) != FORMAT:
        raise NotebookError("not a Maxbook notebook")
    try:
        version = int(nb.get("version", 1 if "cells" in nb else VERSION))
    except (TypeError, ValueError) as exc:
        raise NotebookError("bad version field") from exc
    if version > VERSION:
        raise NotebookError("notebook was written by a newer Maxbook")
    if version < 2 or "doc" not in nb:
        return validate_cells(nb)
    try:
        doc = document.normalize(nb["doc"])
    except document.DocumentError as exc:
        raise NotebookError(f"invalid document: {exc}") from exc
    title = str(nb.get("title") or doc["attrs"].get("title") or "Untitled")
    doc["attrs"]["title"] = title
    return {"format": FORMAT, "version": VERSION, "title": title, "doc": doc,
            "metadata": nb.get("metadata", {}) if isinstance(nb.get("metadata"), dict) else {}}


def dumps(nb: dict) -> str:
    nb = validate(nb)
    if nb["version"] != VERSION:
        raise NotebookError("only version-2 notebooks are written; convert the cells first")
    return json.dumps(nb, indent=1, ensure_ascii=False) + "\n"


def loads(text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NotebookError(f"not valid JSON: {exc}") from exc
    return validate(data)


def atomic_write(path: Path, data: str | bytes) -> None:
    """Write via a temp file in the same directory, then replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data.encode("utf-8") if isinstance(data, str) else data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(path: str | Path, nb: dict) -> None:
    path = Path(path)
    if path.suffix.lower() != EXTENSION:
        raise NotebookError(f"notebooks are saved as {EXTENSION}; use Export for other formats")
    atomic_write(path, dumps(nb))


def load(path: str | Path) -> dict:
    """Open a notebook or import a foreign file by extension."""
    from . import formats

    path = Path(path)
    ext = path.suffix.lower()
    if ext == EXTENSION:
        return loads(path.read_text(encoding="utf-8"))
    importer = formats.IMPORTERS.get(ext)
    if importer is None:
        raise NotebookError(f"cannot open {ext or 'extension-less'} files")
    nb = importer(path)
    nb.setdefault("title", path.stem)
    return validate_cells(nb)
