# Maxbook

Maxbook is a notebook for literate computing with the [Maxima](https://maxima.sourceforge.io/) computer algebra system: prose, formulas and live computations in one document. It is meant as a modern alternative to wxMaxima and TeXmacs for writing mathematics that is computed by Maxima.

Status: **0.1.0, first MVP.** Used and tested by hand on Windows with Maxima 5.50; the automated tests also run on Linux against Maxima 5.46. macOS is untested (see [Limitations](#limitations)).

## What it does

- **Three kinds of cells.** *Text* cells are Markdown with `$…$` / `$$…$$` math. *Maxima* cells hold ordinary Maxima input with syntax highlighting. *Math* cells are edited as formulas (fractions, integrals, matrices with Tab between empty boxes); the Maxima translation is shown live under the formula, so nothing is evaluated that you cannot see.
- **Real Maxima.** Results come back as typeset math with their `%o` labels; `%`, labels and definitions carry across cells as in a Maxima session. A cell stops at its first error. Copy any result as LaTeX or as Maxima text.
- **Questions.** When Maxima asks something (for example "Is a positive, negative or zero?") the question appears in the notebook with quick-answer buttons.
- **Inline plots.** `iplot2d`, `iplot3d`, `idraw2d`, `idraw3d`, `idraw` take the arguments of `plot2d`, `plot3d`, `draw2d`, … and draw into the notebook as SVG. `wxplot2d` and friends are aliases, so wxMaxima worksheets run unchanged.
- **Search as you type.** In a math cell, type a word such as `int`, `frac`, `sum`, `lim`, `matrix`, `det` and press Enter or Tab to insert the structure. Ctrl+K searches all commands and templates.
- **Files.** Notebooks are `.maxbook` (plain JSON, outputs included, diff-friendly). Opens wxMaxima `.wxm` and `.wxmx`, Maxima batch `.mac` and Markdown with ```` ```maxima ```` blocks. Exports LaTeX with PNG figures (compiles with pdflatex), a self-contained offline HTML page, Markdown, `.mac` and `.wxm`.
- **Stop.** Stops a runaway computation by restarting Maxima (the cell says so; definitions are lost).

## Install and run

Requirements: Python 3.9+ and Maxima (any recent version; tested with 5.50 on Windows). No Python packages are required.

```bash
git clone <this repository> maxbook
cd maxbook
python -m maxbook examples/welcome.maxbook
```

Or install the `maxbook` command:

```bash
pip install -e .
maxbook notebook.maxbook
```

The UI opens in a native window when [pywebview](https://pywebview.flowrl.com/) is installed (`pip install -e .[desktop]`), otherwise in a Chromium-based browser in app mode (Edge, Chrome, Brave, Chromium), otherwise in the default browser.

Options: `--maxima PATH` (or environment variable `MAXBOOK_MAXIMA`) when Maxima is not found automatically; `--window none` to only print the URL; `--port N`.

Maxima is found in this order: `--maxima`, `MAXBOOK_MAXIMA`, the usual install folders on Windows (Scoop, `C:\maxima-*`, Program Files) and macOS, then `maxima` on `PATH`.

## Keyboard

| Keys | Action |
|---|---|
| Shift+Enter | Run cell, go to next |
| Ctrl+Enter | Run cell, stay |
| Alt+Enter | Run cell, insert a new cell below |
| Ctrl+Shift+Enter | Run all |
| Ctrl+K | Search commands and templates |
| Ctrl+S, Ctrl+Shift+S, Ctrl+O | Save, Save as, Open/import |
| Tab (math cell) | Next empty box |
| Double-click (text cell) | Edit Markdown |
| F1 | Shortcut overview |

## How it works

A small Python server (standard library only) runs one Maxima process and serves the web UI on `127.0.0.1`. A Lisp file loaded into Maxima at start-up frames every result, question, prompt and image so the server can parse them reliably; statements are sent one at a time. Details in [docs/architecture.md](docs/architecture.md). The math-cell translation rules are in [docs/math-input.md](docs/math-input.md).

Security: the server listens on localhost only and every API call needs a per-launch secret plus a matching `Host` header, because a Maxima session can run shell commands.

## Limitations

These are known and intended to be addressed after the MVP:

- **Platforms.** The full UI was tested by hand on Windows 11 (Maxima 5.50 with SBCL, Python 3.13, Edge). On Linux the automated tests, including the real-Maxima ones, pass in CI (Ubuntu 24.04, Maxima 5.46, Python 3.9 and 3.12), but the desktop window has not been tried there. macOS is untested.
- **Stop restarts Maxima.** There is no in-place interrupt yet, so variables and definitions are lost after Stop.
- **One Maxima session per running Maxbook**, shared by whatever notebook is open. Opening another notebook does not reset Maxima; use Restart.
- **Math cells cover a documented subset** of notation (see docs/math-input.md). Anything else is reported as an error with a hint, never guessed. Matrix multiplication with `\cdot` is only recognised between written-out matrices; use a Maxima cell (`A . B`) for named matrices.
- **No collaboration, no cloud sync.** Files are local.
- LaTeX export rasterises plots to PNG; HTML and Markdown keep them as SVG.
- Large outputs are not truncated or line-broken yet.

## Development

```bash
python -m pytest
ruff check maxbook tests
```

`tests/test_kernel.py` drives a real Maxima and is skipped when Maxima is not installed; `tests/test_formats.py` compiles the LaTeX export when `pdflatex` is available (or set `MAXBOOK_PDFLATEX`). CI runs both on Linux. Front-end behaviour was checked by hand in a browser; there are no automated browser tests yet.

Third-party code is listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Contributions are welcome; please run the tests and `ruff` before opening a pull request.

## Licence

Copyright (C) 2026 Foad S. Farimani.

Maxbook is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; see [LICENSE](LICENSE) for details.

Maxbook is an independent project and is not affiliated with or endorsed by any other notebook or math-editor product. It talks to Maxima as a separate program.
