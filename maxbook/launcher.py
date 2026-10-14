# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Open the UI in a desktop window.

Preference order: a native window via pywebview (if installed), a Chromium
browser in ``--app`` mode (window without browser chrome), then the default
browser.  All three show the same local web UI.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path


def _chromium_candidates() -> list[str]:
    if sys.platform.startswith("win"):
        roots = [os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.environ.get("LOCALAPPDATA", "")]
        rel = [r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe",
               r"BraveSoftware\Brave-Browser\Application\brave.exe", r"Chromium\Application\chrome.exe"]
        return [str(Path(r) / p) for r in roots if r for p in rel]
    if sys.platform == "darwin":
        return ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"]
    names = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
             "microsoft-edge", "brave-browser"]
    return [p for p in (shutil.which(n) for n in names) if p]


def open_app_window(url: str) -> subprocess.Popen | None:
    """Chromium ``--app`` window with its own profile so it is a separate window."""
    for exe in _chromium_candidates():
        if Path(exe).exists():
            profile = Path(tempfile.gettempdir()) / "maxbook-browser-profile"
            try:
                return subprocess.Popen(
                    [exe, f"--app={url}", f"--user-data-dir={profile}", "--no-first-run",
                     "--no-default-browser-check", "--window-size=1280,900"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                continue
    return None


def run_native_window(url: str, title: str) -> bool:
    """Blocking pywebview window; returns False when pywebview is unavailable."""
    try:
        import webview  # type: ignore
    except ImportError:
        return False
    webview.create_window(title, url, width=1280, height=900, min_size=(720, 480))
    webview.start()
    return True


def open_browser(url: str) -> None:
    webbrowser.open(url)
