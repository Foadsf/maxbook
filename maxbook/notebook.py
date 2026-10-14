# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Notebook document model and the native ``.maxbook`` file format.

A notebook is plain JSON::

    {"format": "maxbook", "version": 1, "title": "...",
     "cells": [{"id": "...", "type": "markdown" | "code" | "math",
                "source": "...", "latex": "...", "outputs": [...]}],
     "metadata": {...}}

``source`` is Markdown for text cells and Maxima input for code cells.  Math
cells keep the editor's ``latex`` and the Maxima ``source`` generated from it.
Outputs are stored so a saved notebook reads like a document without
re-running Maxima.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

FORMAT = "maxbook"
VERSION = 1
EXTENSION = ".maxbook"
CELL_TYPES = ("markdown", "code", "math")


class NotebookError(ValueError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def make_cell(cell_type: str, source: str = "", latex: str = "", outputs=None) -> dict:
    if cell_type not in CELL_TYPES:
        raise NotebookError(f"unknown cell type {cell_type!r}")
    cell = {"id": new_id(), "type": cell_type, "source": source}
    if cell_type == "math":
        cell["latex"] = latex
    if cell_type != "markdown":
        cell["outputs"] = list(outputs or [])
    return cell


def new_notebook(title: str = "Untitled") -> dict:
    return {
        "format": FORMAT,
        "version": VERSION,
        "title": title,
        "cells": [make_cell("markdown", f"# {title}\n"), make_cell("code", "")],
        "metadata": {},
    }


def validate(nb: dict) -> dict:
    """Check structure and fill defaults; raise NotebookError on bad input."""
    if not isinstance(nb, dict):
        raise NotebookError("notebook must be a JSON object")
    if nb.get("format", FORMAT) != FORMAT:
        raise NotebookError("not a Maxbook notebook")
    if int(nb.get("version", VERSION)) > VERSION:
        raise NotebookError("notebook was written by a newer Maxbook")
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
            outs = c.get("outputs", [])
            cell["outputs"] = [o for o in outs if isinstance(o, dict) and o.get("kind") != "question"] \
                if isinstance(outs, list) else []
            inputs = c.get("inputs")
            if isinstance(inputs, list) and all(isinstance(n, int) for n in inputs):
                cell["inputs"] = inputs
        out_cells.append(cell)
    return {
        "format": FORMAT,
        "version": VERSION,
        "title": str(nb.get("title", "Untitled")),
        "cells": out_cells,
        "metadata": nb.get("metadata", {}) if isinstance(nb.get("metadata"), dict) else {},
    }


def dumps(nb: dict) -> str:
    return json.dumps(validate(nb), indent=1, ensure_ascii=False) + "\n"


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
    return validate(nb)
