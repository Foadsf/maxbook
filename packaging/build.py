# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Build the single-file Maxbook executable for this platform and smoke-test it.

    python -m pip install "pyinstaller==6.22.3" ".[ai]"
    python packaging/build.py

Writes dist/maxbook-<version>-<os>-<arch>[.exe] and a .sha256 file next to
it.  The smoke test runs the binary: --version, then the server with no
window, fetching the page, the editor bundle and the session API, then asks
it to shut down.  Maxima is not needed (the binary uses the one installed on
the computer); without it the kernel reports "missing", which is expected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def platform_tag() -> str:
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)
    return f"{system}-{arch}"


def build(name: str) -> Path:
    import PyInstaller.__main__

    work = ROOT / "build" / "pyinstaller"
    args = [
        str(ROOT / "packaging" / "entry.py"),
        "--onefile", "--console", "--noconfirm", "--clean",
        "--name", name,
        "--collect-data", "maxbook",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(work),
        "--specpath", str(work),
    ]
    if sys.platform == "win32":
        args += ["--icon", str(ROOT / "packaging" / "maxbook.ico")]
    PyInstaller.__main__.run(args)
    exe = ROOT / "dist" / (name + (".exe" if sys.platform == "win32" else ""))
    if not exe.exists():
        raise SystemExit(f"build produced no {exe}")
    return exe


# Installed only to build the program; not part of it.
BUILD_ONLY = {"maxbook", "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pip", "setuptools",
              "wheel", "packaging", "pywin32-ctypes", "macholib", "pillow"}


def write_licenses(target: Path) -> None:
    """The licence texts of Python and of every package bundled into the program."""
    import importlib.metadata as md
    import sysconfig

    parts = ["Third-party software in the Maxbook single-file program",
             "(Maxbook itself: GPL-3.0-or-later, see LICENSE in the source repository)", "",
             "The program is packed with PyInstaller, whose bootloader is GPL-2.0-or-later with an exception",
             "that allows it to be distributed with programs under any licence.", ""]
    python_licence = next((p for p in (Path(sys.base_prefix) / "LICENSE.txt",
                                       Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt") if p.exists()), None)
    parts += [f"===== Python {platform.python_version()} (PSF License) =====",
              python_licence.read_text(encoding="utf-8", errors="replace") if python_licence
              else "See https://docs.python.org/3/license.html", ""]
    for dist in sorted(md.distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = dist.metadata["Name"]
        if name.lower() in BUILD_ONLY:
            continue
        licence = dist.metadata.get("License-Expression") or dist.metadata.get("License") or ""
        files = [f for f in (dist.files or []) if re.search(r"(LICEN[CS]E|COPYING|NOTICE)", f.name, re.I)]
        parts.append(f"===== {name} {dist.version} ({licence.splitlines()[0] if licence else 'see below'}) =====")
        texts = [Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace") for f in files
                 if Path(dist.locate_file(f)).is_file()]
        parts += texts or [licence or "(no licence file shipped in the package)"]
        parts.append("")
    target.write_text("\n".join(parts), encoding="utf-8")


def get(url: str, token: str | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"X-Maxbook-Token": token} if token else {})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status, resp.read()


def smoke_test(exe: Path, version: str) -> None:
    out = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=120, check=True)
    assert out.stdout.strip() == f"maxbook {version}", out.stdout
    print("ok   --version:", out.stdout.strip())

    proc = subprocess.Popen([str(exe), "--window", "none"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    try:
        url = None
        lines = []
        deadline = time.monotonic() + 120  # the first start unpacks the archive
        assert proc.stdout is not None
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            lines.append(line.rstrip())
            m = re.search(r"Open this URL: (http://127\.0\.0\.1:\d+/)#token=([\w-]+)", line)
            if m:
                url = m.groups()
                break
        if not url:
            raise AssertionError("the server never printed its URL:\n" + "\n".join(lines))
        base, token = url
        status, body = get(base)
        assert status == 200 and b"Maxbook" in body, status
        print("ok   page served")
        status, body = get(base + "vendor/prosemirror/prosemirror.mjs")
        assert status == 200 and len(body) > 100_000, (status, len(body))
        print("ok   editor bundle served,", len(body), "bytes")
        status, body = get(base + "api/session", token)
        session = json.loads(body)
        assert status == 200 and session["version"] == version, session.get("version")
        print("ok   session API; kernel status:", session["kernel"].get("status"))
        req = urllib.request.Request(base + "api/shutdown", data=b"{}", method="POST",
                                     headers={"X-Maxbook-Token": token, "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
        proc.wait(timeout=60)
        print("ok   shut down")
    finally:
        if proc.poll() is None:
            proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-build", action="store_true", help="only smoke-test an existing binary")
    args = parser.parse_args()
    from maxbook import __version__

    name = f"maxbook-{__version__}-{platform_tag()}"
    exe = ROOT / "dist" / (name + (".exe" if sys.platform == "win32" else ""))
    if not args.skip_build:
        exe = build(name)
    smoke_test(exe, __version__)
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    (exe.parent / (exe.name + ".sha256")).write_text(f"{digest}  {exe.name}\n", encoding="utf-8")
    write_licenses(exe.parent / "THIRD_PARTY_LICENSES.txt")
    print(f"built {exe} ({exe.stat().st_size / 1e6:.1f} MB), sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
