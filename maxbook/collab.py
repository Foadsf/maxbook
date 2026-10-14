# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Central authority for collaborative editing (prosemirror-collab protocol).

Every editor sends the steps it made, tagged with the document version it
started from.  The authority accepts them only if that version is current and
broadcasts accepted steps to everyone, who then rebase their unconfirmed
work.  The server never interprets steps; it only orders them.

To let late joiners start from a recent state, clients post snapshots (the
document at some version); steps older than the latest snapshot are dropped.
"""

from __future__ import annotations

import secrets
import threading
import time

MAX_STEPS_KEPT = 10_000
PRESENCE_TTL = 30.0


class CollabError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


class CollabHub:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self.doc_id = ""
        self.base_doc: dict | None = None
        self.base_version = 0
        self.steps: list[dict] = []          # {"step": json, "clientID": str} after base_version
        self.path: str | None = None
        self.presence: dict[str, dict] = {}  # clientID -> {name, color, role, seen}

    # -- document lifecycle ------------------------------------------------
    @property
    def version(self) -> int:
        return self.base_version + len(self.steps)

    def start(self, doc: dict, path: str | None) -> dict:
        """A new document replaces the shared one (opening a file, New)."""
        with self._cond:
            self.doc_id = secrets.token_hex(6)
            self.base_doc = doc
            self.base_version = 0
            self.steps = []
            self.path = path
            self._cond.notify_all()
            return {"docId": self.doc_id, "version": 0}

    def state(self) -> dict:
        with self._cond:
            if self.base_doc is None:
                return {"docId": "", "version": 0}
            return {"docId": self.doc_id, "version": self.version, "baseVersion": self.base_version,
                    "doc": self.base_doc, "steps": [s["step"] for s in self.steps],
                    "clientIDs": [s["clientID"] for s in self.steps], "path": self.path}

    def set_path(self, path: str | None) -> None:
        with self._cond:
            self.path = path
            self._cond.notify_all()

    # -- steps --------------------------------------------------------------
    def _check_doc(self, doc_id: str) -> None:
        if not self.doc_id or doc_id != self.doc_id:
            raise CollabError("the shared document changed; reload it", 410)

    def receive(self, doc_id: str, version: int, steps: list, client_id: str) -> int:
        with self._cond:
            self._check_doc(doc_id)
            if version != self.version:
                raise CollabError("version mismatch", 409)
            if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
                raise CollabError("steps must be a list of objects", 400)
            self.steps.extend({"step": s, "clientID": str(client_id)} for s in steps)
            if len(self.steps) > MAX_STEPS_KEPT:
                raise CollabError("too many unsnapshotted steps; post a snapshot", 507)
            self._cond.notify_all()
            return self.version

    def snapshot(self, doc_id: str, version: int, doc: dict) -> None:
        with self._cond:
            self._check_doc(doc_id)
            if version < self.base_version or version > self.version:
                return  # stale or impossible; ignore
            drop = version - self.base_version
            self.steps = self.steps[drop:]
            self.base_version = version
            self.base_doc = doc

    def events(self, doc_id: str, version: int, timeout: float = 25.0) -> dict:
        """Steps after ``version``; waits up to ``timeout`` for new ones."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                if doc_id != self.doc_id:
                    return {"reset": True}
                if version < self.base_version:
                    return {"resync": True}
                if version < self.version or time.monotonic() >= deadline:
                    start = version - self.base_version
                    tail = self.steps[start:]
                    return {"version": self.version, "steps": [s["step"] for s in tail],
                            "clientIDs": [s["clientID"] for s in tail], "users": self._users(),
                            "path": self.path}
                self._cond.wait(max(0.05, deadline - time.monotonic()))

    # -- presence -----------------------------------------------------------
    def touch(self, client_id: str, name: str, color: str, role: str) -> list[dict]:
        with self._cond:
            self.presence[str(client_id)] = {"name": name[:40], "color": color[:20], "role": role,
                                             "seen": time.monotonic()}
            return self._users()

    def leave(self, client_id: str) -> None:
        with self._cond:
            self.presence.pop(str(client_id), None)
            self._cond.notify_all()

    def _users(self) -> list[dict]:
        now = time.monotonic()
        for cid in [c for c, u in self.presence.items() if now - u["seen"] > PRESENCE_TTL]:
            del self.presence[cid]
        return [{"clientID": c, "name": u["name"], "color": u["color"], "role": u["role"]}
                for c, u in self.presence.items()]
