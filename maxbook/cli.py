# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Command line entry point: ``maxbook [FILE]``."""

from __future__ import annotations

import argparse
import sys
import threading

from . import __version__
from .kernel import find_maxima
from .launcher import open_app_window, open_browser, run_native_window
from .server import App, create_server


def main(argv: list[str] | None = None) -> int:
    # Print lines as they happen even when the output goes to a pipe or a log
    # (the URL line is how scripts and the release smoke test find the server).
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    parser = argparse.ArgumentParser(
        prog="maxbook", description="Literate notebooks for the Maxima computer algebra system.")
    parser.add_argument("file", nargs="?",
                        help="notebook (.maxbook; a new name starts a new notebook) or file to import "
                             "(.wxm, .wxmx, .mac, .md, .tex)")
    parser.add_argument("--maxima", metavar="PATH", help="Maxima executable (default: auto-detect)")
    parser.add_argument("--port", type=int, default=0, help="port on 127.0.0.1 (default: any free port)")
    parser.add_argument("--window", choices=["auto", "native", "app", "browser", "none"], default="auto",
                        help="how to show the UI (default: native window if pywebview is installed, "
                             "else a Chromium app window, else the default browser)")
    parser.add_argument("--share", action="store_true",
                        help="also listen on the local network and print a link others can use to edit "
                             "the open notebook with you (they cannot run Maxima or touch your files)")
    parser.add_argument("--version", action="version", version=f"maxbook {__version__}")
    args = parser.parse_args(argv)

    maxima = args.maxima or find_maxima()
    if not maxima:
        print("warning: Maxima not found; the UI will open but cannot compute. "
              "Install Maxima or use --maxima PATH.", file=sys.stderr)
    app = App(maxima_path=maxima, initial_file=args.file, share=args.share)
    httpd = create_server(app, args.port)
    url = f"http://127.0.0.1:{app.port}/#token={app.token}"
    app.start_kernel_async()
    print(f"Maxbook {__version__} at http://127.0.0.1:{app.port}/ (Maxima: {maxima or 'not found'})")
    if args.share:
        print("Sharing is ON. Anyone on your network with one of these links can read and edit the open")
        print("notebook (not run Maxima, not open or save files). Share them only with people you trust:")
        for link in app.share_info()["urls"] or ["(no network address found)"]:
            print("  " + link)
    print(f"AI helper: {'on (' + app.ai.model + ')' if app.ai.enabled else 'off - ' + app.ai.reason}")
    print("Press Ctrl+C to quit.")

    serve = threading.Thread(target=httpd.serve_forever, daemon=True)
    serve.start()
    try:
        if args.window in ("auto", "native") and run_native_window(url, "Maxbook"):
            return 0  # window closed
        if args.window == "native":
            print("pywebview is not installed; falling back to an app window.", file=sys.stderr)
        if args.window == "none":
            print(f"Open this URL: {url}")
        else:
            if args.window == "browser":
                open_browser(url)
            elif open_app_window(url) is None:  # auto, native or app
                open_browser(url)
            print(f"If no window opened, open this URL in a browser: {url}")
        serve.join()
    except KeyboardInterrupt:
        pass
    finally:
        app.kernel.shutdown()
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
