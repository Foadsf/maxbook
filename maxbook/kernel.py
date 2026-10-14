# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Maxima kernel: one Maxima process driven over stdin/stdout.

The Lisp side (``lisp/maxbook-init.lisp``) frames everything the notebook
needs to parse.  Statements are sent one at a time; Maxima prints a PROMPT
frame when it is ready for the next one, which is how we know a statement is
finished.  A cell stops at the first statement that reports an error.

Interrupting a running computation restarts the process.  Maxima on Windows
(SBCL) has no reliable cross-platform interrupt over a pipe, and a restart is
honest about losing the session state.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .splitter import SplitError, split_statements
from .texfix import maxima_tex_to_latex

STX, US, ETX = "\x02", "\x1f", "\x03"
FRAME_RE = re.compile("\x02([A-Z]+)((?:\x1f[^\x02\x03]*)*)\x03")
# gnuplot builds without a GUI (e.g. Debian's gnuplot-nox) warn about "set mouse"
# in scripts that only write files; the warning says nothing about the result.
HARMLESS_LINE = re.compile(r"line \d+: warning: this copy of gnuplot has no mouse support")
LISP_DIR = Path(__file__).with_name("lisp")
IS_WINDOWS = sys.platform.startswith("win")
IMAGE_MIME = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
              ".jpeg": "image/jpeg", ".gif": "image/gif"}


class KernelError(RuntimeError):
    pass


def _short_path(path: str) -> str:
    """Windows 8.3 path for paths containing spaces (cmd.exe quoting is fragile)."""
    if not IS_WINDOWS or " " not in path:
        return path
    import ctypes
    from ctypes import wintypes

    buf = ctypes.create_unicode_buffer(1024)
    get = ctypes.windll.kernel32.GetShortPathNameW
    get.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    if get(path, buf, 1024):
        return buf.value
    return path


def _resolve_scoop_shim(path: str) -> str:
    """Scoop's ``maxima.cmd`` shim names its target on the first line."""
    try:
        first = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[0]
    except (OSError, IndexError):
        return path
    m = re.match(r"@rem\s+(.+\.bat)\s*$", first, re.IGNORECASE)
    if m and Path(m.group(1)).exists():
        return m.group(1)
    return path


def find_maxima(explicit: str | None = None) -> str | None:
    """Locate the Maxima launcher (``maxima`` / ``maxima.bat``)."""
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    if os.environ.get("MAXBOOK_MAXIMA"):
        candidates.append(os.environ["MAXBOOK_MAXIMA"])
    if IS_WINDOWS:
        home = Path.home()
        patterns = [
            str(home / "scoop" / "apps" / "maxima" / "current" / "bin" / "maxima.bat"),
            r"C:\maxima-*\bin\maxima.bat",
            os.path.expandvars(r"%ProgramFiles%\Maxima-*\bin\maxima.bat"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Maxima-*\bin\maxima.bat"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Maxima-*\bin\maxima.bat"),
        ]
        for pat in patterns:
            candidates.extend(sorted(glob.glob(pat), reverse=True))
    else:
        candidates.extend(["/Applications/Maxima.app/Contents/Resources/opt/bin/maxima"])
    found = shutil.which("maxima")
    if found:
        candidates.append(found)
    for c in candidates:
        if c and Path(c).exists():
            return _resolve_scoop_shim(c) if c.lower().endswith(".cmd") else c
    return None


def find_winkill(maxima_path: str) -> str | None:
    """winkill.exe ships next to maxima.bat in Windows installers."""
    p = Path(maxima_path).resolve().parent / "winkill.exe"
    return str(p) if p.exists() else None


def find_bundled_gnuplot(maxima_path: str) -> str | None:
    """Windows Maxima installers ship gnuplot next to Maxima."""
    prefix = Path(maxima_path).resolve().parent.parent
    for rel in ("gnuplot/bin/gnuplot.exe", "gnuplot/bin/gnuplot"):
        p = prefix / rel
        if p.exists():
            return str(p)
    return None


@dataclass
class Output:
    kind: str  # result | text | error | image | question
    data: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"kind": self.kind, **self.data}


@dataclass
class StatementResult:
    outputs: list[Output]
    error: bool
    input_number: int | None


class MaximaKernel:
    def __init__(self, maxima_path: str | None = None, workdir: str | None = None,
                 startup_timeout: float = 90.0):
        self.maxima_path = maxima_path or find_maxima()
        self.workdir = workdir or os.getcwd()
        self.startup_timeout = startup_timeout
        self.proc: subprocess.Popen | None = None
        self.version = ""
        self.lisp = ""
        self.status = "stopped"
        self.last_error = ""
        self._buf = ""
        self._pos = 0
        self._cond = threading.Condition()
        self._eof = False
        self._markers: dict[str, str] = {}
        self._linenum = 1
        self._tmp: tempfile.TemporaryDirectory | None = None
        self._run_lock = threading.Lock()
        self._symbols_query = False
        self._answer: str | None = None
        self.pending_question: dict | None = None
        self.stop_requested = False
        self.hard_stopped = False
        self.lisp_pid: int | None = None
        self.symbol_table: list[dict] = []
        self._generation = 0

    # ------------------------------------------------------------------ process
    def start(self) -> None:
        if not self.maxima_path:
            self.status = "missing"
            self.last_error = ("Maxima was not found. Install Maxima or pass --maxima PATH "
                               "(or set MAXBOOK_MAXIMA).")
            raise KernelError(self.last_error)
        self._tmp = tempfile.TemporaryDirectory(prefix="maxbook-")
        init = _short_path(str(LISP_DIR / "maxbook-init.lisp"))
        cmd = [self.maxima_path, "--very-quiet", "-p", init]
        if IS_WINDOWS and self.maxima_path.lower().endswith((".bat", ".cmd")):
            cmd = ["cmd", "/c"] + cmd
        kwargs: dict = {}
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        # Makes maxima.bat load win_signals.lisp, so winkill.exe can interrupt a
        # computation in place (SBCL/CCL builds on Windows; ignored elsewhere).
        env = dict(os.environ, MAXIMA_SIGNALS_THREAD="1")
        self._buf, self._pos, self._eof = "", 0, False
        self._generation += 1
        self.pending_question = None
        self.lisp_pid = None
        self.status = "starting"
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, cwd=self.workdir, env=env, **kwargs)
        threading.Thread(target=self._reader, args=(self.proc, self._generation),
                         daemon=True).start()
        hello = self._wait_frame("HELLO", self.startup_timeout)
        if hello is None:
            tail = self._buf[-2000:]
            self.kill()
            self.status = "dead"
            self.last_error = "Maxima did not start (no handshake). Output:\n" + tail
            raise KernelError(self.last_error)
        fields = hello[1]
        self._markers = {"error": fields[0], "syntax": fields[1], "lisp": fields[2]}
        self.version, self.lisp = fields[3], fields[4]
        try:
            pid = int(fields[5])
            self.lisp_pid = pid if pid > 0 else None
        except (IndexError, ValueError):
            self.lisp_pid = None
        prompt = self._wait_frame("PROMPT", self.startup_timeout)
        if prompt is None:
            self.kill()
            self.status = "dead"
            raise KernelError("Maxima started but never became ready")
        self._linenum = int(prompt[1][0])
        self._configure_session()
        self.status = "idle"

    def _configure_session(self) -> None:
        plot_dir = Path(self._tmp.name).as_posix()
        mac = (LISP_DIR / "maxbook.mac").as_posix()
        lines = [
            f':lisp (setq $maxima_tempdir "{plot_dir}")',
            f':lisp ($load "{mac}")',
            f':lisp (setq $maxbook_plot_dir "{plot_dir}")',
        ]
        gnuplot = find_bundled_gnuplot(self.maxima_path) if IS_WINDOWS else None
        if gnuplot:
            # Maxima 5.50/SBCL on Windows passes "-persist file" to gnuplot as a
            # single quoted argument, so gnuplot ignores the script and blocks on
            # stdin.  Put -persist into the command and pass the file alone.
            gp = _short_path(gnuplot).replace("\\", "/")
            lines.append(f':lisp (setq $gnuplot_command "{gp} -persist" $gnuplot_view_args "~a")')
        lines.append(":lisp (maxima::mbk-mark-system)")
        for line in lines:
            res = self._exec(line, timeout=60)
            if res.error:
                raise KernelError("Session setup failed: " + " ".join(
                    o.data.get("text", "") for o in res.outputs))

    def _reader(self, proc: subprocess.Popen, generation: int) -> None:
        stream = proc.stdout
        assert stream is not None
        while True:
            try:
                chunk = stream.read1(65536)
            except (OSError, ValueError):
                chunk = b""
            with self._cond:
                if generation != self._generation:
                    return
                if not chunk:
                    self._eof = True
                    self._cond.notify_all()
                    return
                self._buf += chunk.decode("utf-8", errors="replace")
                self._cond.notify_all()

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def interrupt(self) -> bool:
        """Ask Maxima to abandon the current computation and keep its state.

        Returns True when an interrupt was delivered.  The running cell then
        ends with an "interrupted" output once Maxima is back at its prompt;
        callers should fall back to :meth:`hard_stop` if that does not happen.
        """
        if not self.alive() or not self.lisp_pid:
            return False
        self.stop_requested = True
        try:
            if IS_WINDOWS:
                winkill = find_winkill(self.maxima_path or "")
                if not winkill:
                    return False
                res = subprocess.run([winkill, "-INT", str(self.lisp_pid)], capture_output=True,
                                     check=False, creationflags=subprocess.CREATE_NO_WINDOW)
                ok = res.returncode == 0
            else:
                os.kill(self.lisp_pid, signal.SIGINT)
                ok = True
        except OSError:
            ok = False
        with self._cond:
            self._cond.notify_all()  # wakes a cell that is waiting for an answer
        return ok

    def hard_stop(self) -> None:
        """Kill Maxima (state is lost).  The caller restarts it."""
        self.stop_requested = True
        self.hard_stopped = True
        self.kill()

    def _exit_reason(self) -> str:
        if self.stop_requested:
            return "stopped by you; Maxima had to be restarted, so earlier definitions are gone"
        return "Maxima exited unexpectedly"

    def can_interrupt(self) -> bool:
        if not self.lisp_pid:
            return False
        return bool(find_winkill(self.maxima_path or "")) if IS_WINDOWS else True

    def symbols(self, timeout: float = 20) -> list[dict] | None:
        """User variables, functions and declared constants; None while busy."""
        if not self._run_lock.acquire(blocking=False):
            return None
        self._symbols_query = True
        try:
            if not self.alive():
                return []
            self._exec(":lisp (maxima::mbk-symbols)", timeout=timeout)
            return self.symbol_table
        finally:
            self._symbols_query = False
            self._run_lock.release()

    def _acquire_for_run(self) -> bool:
        """Take the run lock; wait out a symbol-table query, but not a computation."""
        if self._run_lock.acquire(timeout=0.25):
            return True
        if self._symbols_query:
            return self._run_lock.acquire(timeout=30)
        return False

    def kill(self) -> None:
        self.pending_question = None
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                               capture_output=True, check=False)
            else:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        with self._cond:
            self._generation += 1
            self._eof = True
            self._cond.notify_all()
        if self._tmp:
            self._tmp.cleanup()
            self._tmp = None
        self.status = "stopped"

    def restart(self) -> None:
        self.kill()
        self.start()

    def shutdown(self) -> None:
        if self.alive():
            try:
                assert self.proc and self.proc.stdin
                self.proc.stdin.write(b"quit();\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired, AssertionError):
                pass
        self.kill()

    # ------------------------------------------------------------------ parsing
    def _wait_frame(self, kind: str, timeout: float):
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                for m in FRAME_RE.finditer(self._buf, self._pos):
                    if m.group(1) == kind:
                        self._pos = m.end()
                        return kind, m.group(2).split(US)[1:]
                if self._eof:
                    return None
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self._cond.wait(left)

    def _send(self, text: str) -> None:
        if not self.alive():
            raise KernelError("Maxima is not running")
        assert self.proc and self.proc.stdin
        self.proc.stdin.write((text.rstrip("\n") + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def _is_error_text(self, text: str) -> bool:
        return any(m and m in text for m in self._markers.values())

    def _exec(self, statement: str, timeout: float | None = None,
              on_output=None) -> StatementResult:
        """Send one statement and collect frames until the next PROMPT."""
        self._send(statement)
        outputs: list[Output] = []
        error = False
        in_question: list[str] | None = None
        question_parts: list[dict] = []
        deadline = None if timeout is None else time.monotonic() + timeout

        def emit(out: Output) -> None:
            outputs.append(out)
            if on_output:
                on_output(out)

        def flush_text(text: str) -> None:
            nonlocal error
            text = "\n".join(line for line in text.splitlines() if not HARMLESS_LINE.search(line))
            text = text.strip("\r\n")
            if not text.strip():
                return
            if in_question is not None:
                in_question.append(text)
                return
            if self._is_error_text(text):
                error = True
                if self.stop_requested and "interrupt" in text.lower():
                    emit(Output("error", {"text": "Stopped by you. Maxima kept its state.",
                                          "interrupted": True}))
                else:
                    emit(Output("error", {"text": text}))
            else:
                emit(Output("text", {"text": text}))

        with self._cond:
            while True:
                m = FRAME_RE.search(self._buf, self._pos)
                if m is None:
                    if self._eof:
                        flush_text(self._buf[self._pos:])
                        self._pos = len(self._buf)
                        raise KernelError(self._exit_reason())
                    left = None if deadline is None else deadline - time.monotonic()
                    if left is not None and left <= 0:
                        raise KernelError("timeout waiting for Maxima")
                    self._cond.wait(left if left is not None else 0.5)
                    continue
                flush_text(self._buf[self._pos:m.start()])
                self._pos = m.end()
                kind, fields = m.group(1), m.group(2).split(US)[1:]
                if kind == "PROMPT":
                    new_line = int(fields[0])
                    number = self._linenum if new_line != self._linenum else None
                    self._linenum = new_line
                    return StatementResult(outputs, error, number)
                if kind == "OUT":
                    label, tex, text, semtex = (fields + ["", "", "", ""])[:4]
                    item = {"label": label, "latex": maxima_tex_to_latex(tex), "text": text}
                    if semtex and semtex != tex:
                        item["semantic"] = maxima_tex_to_latex(semtex)
                    if in_question is not None:
                        question_parts.append(item)
                    else:
                        emit(Output("result", item))
                elif kind == "IMG":
                    emit(self._image_output(fields[0] if fields else ""))
                elif kind == "SYM":
                    try:
                        table = json.loads(fields[0]) if fields else []
                    except ValueError:
                        table = []
                    for entry in table:
                        # the same clean-up as displayed results (matrices, \verb strings...)
                        if entry.get("latex"):
                            entry["latex"] = maxima_tex_to_latex(entry["latex"])
                    self.symbol_table = table
                elif kind == "ASK":
                    in_question = []
                    question_parts = []
                elif kind == "ASKEND":
                    q = {"text": "\n".join(in_question or []),
                         "parts": question_parts}
                    in_question = None
                    emit(Output("question", q))
                    answer = self._await_answer(q)
                    if answer is None:
                        continue  # stopped while asking: the interrupt ends the statement
                    emit(Output("text", {"text": "» " + answer}))
                    self._cond.release()
                    try:
                        self._send(answer if answer.rstrip().endswith((";", "$"))
                                   else answer + ";")
                    finally:
                        self._cond.acquire()

    def _await_answer(self, question: dict) -> str | None:
        """The user's answer, or None when Stop was pressed meanwhile."""
        self.pending_question = question
        self.status = "asking"
        self._answer = None
        try:
            while self._answer is None:
                if not self.alive():
                    raise KernelError(self._exit_reason())
                if self.stop_requested:
                    self.status = "busy"
                    return None
                self._cond.wait(0.25)
            answer, self._answer = self._answer, None
        finally:
            self.pending_question = None
        self.status = "busy"
        return answer

    def answer(self, text: str) -> None:
        with self._cond:
            self._answer = text.strip() or ";"
            self._cond.notify_all()

    def _wait_for_file(self, p: Path, timeout: float = 15.0) -> bool:
        """Wait until ``p`` exists and stops growing (gnuplot may still be
        writing it).  Called with ``self._cond`` held; waiting releases it."""
        deadline = time.monotonic() + timeout
        last = -1
        while time.monotonic() < deadline:
            size = p.stat().st_size if p.exists() else -1
            complete = size > 0 and (p.suffix.lower() != ".svg" or b"</svg>" in p.read_bytes()[-64:])
            if complete and size == last:
                return True
            last = size
            self._cond.wait(0.1)
        return p.exists()

    def _image_output(self, path: str) -> Output:
        p = Path(path)
        mime = IMAGE_MIME.get(p.suffix.lower())
        if mime is None or not self._wait_for_file(p):
            return Output("error", {"text": f"image not found or unsupported: {path}"})
        if mime == "image/svg+xml":
            return Output("image", {"mime": mime, "data": p.read_text(encoding="utf-8", errors="replace")})
        import base64
        return Output("image", {"mime": mime, "data": base64.b64encode(p.read_bytes()).decode("ascii")})

    # ------------------------------------------------------------------ public
    def run_cell(self, source: str, on_output=None) -> dict:
        """Run all statements of a cell; stop at the first error."""
        if not self._acquire_for_run():
            raise KernelError("kernel is busy")
        self.stop_requested = False
        self.hard_stopped = False
        try:
            if not self.alive():
                self.start()
            try:
                statements = split_statements(source)
            except SplitError as exc:
                out = Output("error", {"text": f"Cannot run cell: {exc}."})
                if on_output:
                    on_output(out)
                return {"outputs": [out.to_json()], "error": True, "inputs": []}
            self.status = "busy"
            outputs: list[Output] = []
            inputs: list[int] = []
            error = False
            for st in statements:
                res = self._exec(st.text, on_output=on_output)
                outputs.extend(res.outputs)
                if res.input_number is not None:
                    inputs.append(res.input_number)
                if res.error:
                    error = True
                    break
            return {"outputs": [o.to_json() for o in outputs], "error": error, "inputs": inputs}
        finally:
            if self.status in ("busy", "asking"):
                self.status = "idle" if self.alive() else "dead"
            self._run_lock.release()

    def evaluate_silently(self, source: str, timeout: float = 30) -> list[Output]:
        """Evaluate helper input (not shown in the notebook)."""
        if not self._run_lock.acquire(timeout=timeout):
            raise KernelError("kernel is busy")
        try:
            outs: list[Output] = []
            for st in split_statements(source):
                outs.extend(self._exec(st.text, timeout=timeout).outputs)
            return outs
        finally:
            self._run_lock.release()

    def info(self) -> dict:
        return {
            "status": self.status if (self.alive() or self.status in ("missing", "dead")) else "stopped",
            "version": self.version,
            "lisp": self.lisp,
            "maxima_path": self.maxima_path,
            "error": self.last_error,
            "question": self.pending_question,
            "can_interrupt": self.can_interrupt(),
        }
