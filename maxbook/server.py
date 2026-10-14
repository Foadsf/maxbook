# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Local HTTP server: serves the web UI and a small JSON API.

Security model: the server binds to 127.0.0.1 only, and every API request
must carry the per-launch secret token (``X-Maxbook-Token``) and a Host header
naming this server.  The token defeats cross-site requests from other pages
in the browser; the Host check defeats DNS-rebinding.  This matters because
Maxima can run shell commands via ``system()``.
"""

from __future__ import annotations

import hmac
import json
import mimetypes
import os
import secrets
import string
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, formats
from .kernel import KernelError, MaximaKernel
from .latex2maxima import ConversionError, collect_function_names, latex_to_maxima
from .notebook import EXTENSION, NotebookError, atomic_write, load, new_notebook, save, validate

WEB_DIR = Path(__file__).with_name("web")
CONFIG_DIR = Path(os.environ.get("MAXBOOK_HOME", Path.home() / ".maxbook"))
MAX_BODY = 64 * 1024 * 1024
OPENABLE = {EXTENSION, *formats.IMPORTERS}


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Job:
    def __init__(self) -> None:
        self.id = secrets.token_hex(6)
        self.state = "running"
        self.outputs: list[dict] = []
        self.inputs: list[int] = []
        self.error = False
        self.lock = threading.Lock()

    def add(self, out) -> None:
        with self.lock:
            self.outputs.append(out.to_json())


class App:
    def __init__(self, maxima_path: str | None = None, initial_file: str | None = None,
                 workdir: str | None = None):
        self.token = secrets.token_urlsafe(24)
        self.kernel = MaximaKernel(maxima_path, workdir=workdir or os.getcwd())
        self.jobs: dict[str, Job] = {}
        self.current_job: Job | None = None
        self.initial_file = initial_file
        self.port = 0
        self.httpd: ThreadingHTTPServer | None = None
        self.config = self._load_config()
        self._kernel_thread: threading.Thread | None = None

    # ---------------------------------------------------------------- config
    def _load_config(self) -> dict:
        try:
            return json.loads((CONFIG_DIR / "config.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"recent": []}

    def _save_config(self) -> None:
        try:
            atomic_write(CONFIG_DIR / "config.json", json.dumps(self.config, indent=1))
        except OSError:
            pass

    def remember(self, path: str) -> None:
        recent = [p for p in self.config.get("recent", []) if p != path]
        self.config["recent"] = [path] + recent[:14]
        self._save_config()

    # ---------------------------------------------------------------- kernel
    def start_kernel_async(self) -> None:
        def run() -> None:
            try:
                self.kernel.start()
            except KernelError as exc:
                self.kernel.last_error = str(exc)
        self._kernel_thread = threading.Thread(target=run, daemon=True)
        self._kernel_thread.start()

    def restart_kernel_async(self) -> None:
        def run() -> None:
            self.kernel.interrupt()
            # Wait for a running cell to notice the dead process and unwind.
            deadline = time.monotonic() + 15
            while self.current_job and self.current_job.state == "running" and time.monotonic() < deadline:
                time.sleep(0.05)
            try:
                self.kernel.start()
            except KernelError as exc:
                self.kernel.last_error = str(exc)
        threading.Thread(target=run, daemon=True).start()

    def run_job(self, source: str) -> Job:
        if self.current_job and self.current_job.state == "running":
            raise ApiError("a cell is already running", 409)
        if self.kernel.status == "starting" and self._kernel_thread:
            self._kernel_thread.join(timeout=120)
        job = Job()
        self.jobs[job.id] = job
        self.current_job = job
        # keep the job table small
        for old in list(self.jobs)[:-20]:
            self.jobs.pop(old, None)

        def work() -> None:
            try:
                res = self.kernel.run_cell(source, on_output=job.add)
                job.inputs = res["inputs"]
                job.error = res["error"]
            except KernelError as exc:
                job.error = True
                with job.lock:
                    job.outputs.append({"kind": "error", "text": f"Maxima stopped: {exc}"})
            except Exception as exc:  # noqa: BLE001 - report any crash in the cell, never lose the job
                job.error = True
                with job.lock:
                    job.outputs.append({"kind": "error", "text": f"Internal error: {exc}"})
                traceback.print_exc()
            finally:
                job.state = "done"
        threading.Thread(target=work, daemon=True).start()
        return job

    # ---------------------------------------------------------------- api
    def api(self, method: str, path: str, query: dict, body: dict) -> dict:
        if method == "GET" and path == "/api/session":
            return self.session()
        if method == "GET" and path == "/api/kernel":
            return self.kernel.info()
        if method == "POST" and path == "/api/run":
            job = self.run_job(str(body.get("source", "")))
            return {"job": job.id}
        if method == "GET" and path == "/api/job":
            job = self.jobs.get(query.get("id", [""])[0])
            if not job:
                raise ApiError("unknown job", 404)
            since = int(query.get("since", ["0"])[0])
            with job.lock:
                outs = job.outputs[since:]
                total = len(job.outputs)
            return {"state": job.state, "outputs": outs, "next": total, "inputs": job.inputs,
                    "error": job.error, "question": self.kernel.pending_question}
        if method == "POST" and path == "/api/answer":
            self.kernel.answer(str(body.get("text", "")))
            return {"ok": True}
        if method == "POST" and path in ("/api/interrupt", "/api/restart"):
            self.restart_kernel_async()
            return {"ok": True}
        if method == "POST" and path == "/api/convert":
            return self.convert(body)
        if method == "POST" and path == "/api/open":
            return self.open_file(str(body.get("path", "")))
        if method == "POST" and path == "/api/save":
            return self.save_file(str(body.get("path", "")), body.get("notebook"))
        if method == "POST" and path == "/api/export":
            return self.export(body)
        if method == "GET" and path == "/api/fs":
            return self.list_dir(query.get("path", [""])[0])
        if method == "POST" and path == "/api/new":
            return {"notebook": new_notebook(str(body.get("title") or "Untitled")), "path": None}
        if method == "POST" and path == "/api/shutdown":
            threading.Thread(target=self.shutdown, daemon=True).start()
            return {"ok": True}
        raise ApiError("not found", 404)

    def session(self) -> dict:
        nb, path, note, suggested = None, None, "", None
        initial = bool(self.initial_file)
        if self.initial_file:
            try:
                res = self.open_file(self.initial_file)
                nb, path, note = res["notebook"], res["path"], res.get("note", "")
                suggested = res.get("suggested")
            except ApiError as exc:
                note = str(exc)
            self.initial_file = None
        if nb is None:
            nb = new_notebook("Untitled")
        return {"version": __version__, "kernel": self.kernel.info(), "notebook": nb,
                "path": path, "note": note, "initial": initial, "suggested": suggested,
                "recent": self.config.get("recent", []),
                "home": str(Path.home()), "cwd": os.getcwd(), "platform": sys.platform}

    def convert(self, body: dict) -> dict:
        latex = str(body.get("latex", ""))
        known = set(body.get("known", []) or [])
        known |= collect_function_names([str(s) for s in body.get("sources", []) or []])
        try:
            return {"maxima": latex_to_maxima(latex, known)}
        except ConversionError as exc:
            return {"error": str(exc)}

    def _abs(self, path: str) -> Path:
        if not path:
            raise ApiError("no path given")
        p = Path(os.path.expanduser(path))
        if not p.is_absolute():
            p = Path(os.getcwd()) / p
        return p.resolve()

    def open_file(self, path: str) -> dict:
        p = self._abs(path)
        if not p.exists():
            raise ApiError(f"file not found: {p}", 404)
        try:
            nb = load(p)
        except (NotebookError, ValueError, OSError) as exc:
            raise ApiError(f"cannot open {p.name}: {exc}") from exc
        if p.suffix.lower() == EXTENSION:
            self.remember(str(p))
            return {"notebook": nb, "path": str(p)}
        target = p.with_suffix(EXTENSION)
        note = f"Imported {p.name}. Saving will create {target.name}; the original is not changed."
        return {"notebook": nb, "path": None, "suggested": str(target), "note": note}

    def save_file(self, path: str, nb) -> dict:
        p = self._abs(path)
        if p.suffix.lower() != EXTENSION:
            p = p.with_suffix(p.suffix + EXTENSION) if p.suffix else p.with_suffix(EXTENSION)
        try:
            save(p, validate(nb))
        except (NotebookError, OSError) as exc:
            raise ApiError(f"cannot save: {exc}") from exc
        self.remember(str(p))
        return {"path": str(p)}

    def export(self, body: dict) -> dict:
        fmt = str(body.get("format", ""))
        p = self._abs(str(body.get("path", "")))
        try:
            nb = validate(body.get("notebook"))
        except NotebookError as exc:
            raise ApiError(str(exc)) from exc
        try:
            if fmt == "html":
                html = str(body.get("html", ""))
                if not html:
                    raise ApiError("no HTML supplied")
                atomic_write(p, html)
                return {"written": [str(p)]}
            if fmt == "tex":
                written = formats.write_latex_bundle(nb, p, list(body.get("figures", []) or []))
                return {"written": [str(w) for w in written]}
            if fmt not in formats.EXPORTERS:
                raise ApiError(f"unknown export format {fmt!r}")
            _ext, fn = formats.EXPORTERS[fmt]
            atomic_write(p, fn(nb))
            return {"written": [str(p)]}
        except OSError as exc:
            raise ApiError(f"cannot write {p}: {exc}") from exc

    def list_dir(self, path: str) -> dict:
        p = self._abs(path) if path else Path(os.getcwd())
        if p.is_file():
            p = p.parent
        if not p.is_dir():
            raise ApiError(f"not a folder: {p}", 404)
        entries = []
        try:
            for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
                if child.name.startswith("."):
                    continue
                try:
                    is_dir = child.is_dir()
                except OSError:
                    continue
                if is_dir or child.suffix.lower() in OPENABLE:
                    entries.append({"name": child.name, "dir": is_dir, "path": str(child)})
        except PermissionError as exc:
            raise ApiError(f"permission denied: {p}", 403) from exc
        drives = []
        if sys.platform.startswith("win"):
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
        return {"path": str(p), "parent": str(p.parent) if p.parent != p else None,
                "entries": entries, "drives": drives}

    def shutdown(self) -> None:
        time.sleep(0.2)
        self.kernel.shutdown()
        if self.httpd:
            self.httpd.shutdown()


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Maxbook/" + __version__

        def log_message(self, fmt, *args):  # quiet by default
            if os.environ.get("MAXBOOK_DEBUG"):
                sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

        # -- helpers ---------------------------------------------------------
        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            return host in (f"127.0.0.1:{app.port}", f"localhost:{app.port}")

        def _send(self, status: int, payload: bytes, ctype: str, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, status: int, obj) -> None:
            self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _static(self, rel: str) -> None:
            rel = rel.lstrip("/") or "index.html"
            target = (WEB_DIR / rel).resolve()
            if WEB_DIR.resolve() not in target.parents and target != WEB_DIR.resolve():
                return self._send(404, b"not found", "text/plain")
            if not target.is_file():
                return self._send(404, b"not found", "text/plain")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if target.suffix in (".js", ".mjs"):
                ctype = "text/javascript"
            if ctype.startswith("text/") or ctype == "image/svg+xml":
                ctype += "; charset=utf-8"
            extra = {}
            if target.name == "index.html":
                extra["Content-Security-Policy"] = (
                    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                    "font-src 'self' data:; script-src 'self'; connect-src 'self'; media-src 'self'")
            self._send(200, target.read_bytes(), ctype, extra)

        def _dispatch(self, method: str) -> None:
            if not self._host_ok():
                return self._send(403, b"forbidden host", "text/plain")
            url = urlparse(self.path)
            if not url.path.startswith("/api/"):
                if method != "GET":
                    return self._send(405, b"method not allowed", "text/plain")
                return self._static(url.path)
            token = self.headers.get("X-Maxbook-Token", "")
            if not hmac.compare_digest(token, app.token):
                return self._json(403, {"error": "missing or wrong token"})
            body: dict = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return self._json(413, {"error": "request too large"})
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw.decode("utf-8") or "{}")
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return self._json(400, {"error": "invalid JSON"})
                if not isinstance(body, dict):
                    return self._json(400, {"error": "JSON object expected"})
            try:
                result = app.api(method, url.path, parse_qs(url.query), body)
                self._json(200, result)
            except ApiError as exc:
                self._json(exc.status, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001 - answer 500 instead of dropping the connection
                traceback.print_exc()
                self._json(500, {"error": f"internal error: {exc}"})

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

    return Handler


def create_server(app: App, port: int = 0) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    httpd.daemon_threads = True
    app.port = httpd.server_address[1]
    app.httpd = httpd
    return httpd
