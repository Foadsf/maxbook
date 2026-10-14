# Architecture

```
browser / native window ──HTTP (127.0.0.1, token)──▶ maxbook.server ──stdin/stdout──▶ maxima (+ maxbook-init.lisp)
        web/js/*.js                                     kernel.py                          gnuplot (plots)
```

## Python side (`maxbook/`)

| Module | Responsibility |
|---|---|
| `cli.py`, `__main__.py` | command line, starts server and window |
| `launcher.py` | pywebview window, Chromium `--app` window, or default browser |
| `server.py` | static files, JSON API, token and Host checks, cell jobs |
| `kernel.py` | the Maxima process: start, send statements, parse frames, questions, stop |
| `splitter.py` | split cell text into Maxima statements (strings, nested comments, escapes, `:lisp`) |
| `texfix.py` | turn Maxima's `tex1` output into LaTeX that browser renderers accept |
| `latex2maxima.py` | math-cell formulas to Maxima statements (see `math-input.md`) |
| `notebook.py` | `.maxbook` format: validation, atomic save, load/import dispatch |
| `formats.py` | import `.wxm`, `.wxmx`, `.mac`, `.md`; export `.mac`, `.wxm`, `.md`, `.tex` |

## Wire protocol with Maxima

Maxima is started as `maxima --very-quiet -p lisp/maxbook-init.lisp`. The init file:

- installs `*alt-display2d*` / `*alt-display1d*` so every displayed result is written as a frame `STX OUT US label US tex US text ETX` (STX = U+0002, US = U+001F, ETX = U+0003);
- replaces the main prompt with a `PROMPT n` frame, which is how the kernel knows a statement has finished;
- sets `*prompt-prefix*` / `*prompt-suffix*` to `ASK` / `ASKEND` frames, so questions from `asksign`, `read()` and friends are recognisable;
- defines `maxbook_show_image(file)`, which emits an `IMG` frame (used by the inline plot functions in `lisp/maxbook.mac`);
- sends a `HELLO` frame with Maxima's own (possibly translated) error markers and the version.

Text outside frames is ordinary output (print, warnings, error messages). A statement is an error when its text contains one of the markers from `HELLO`; the cell then stops.

Statements are sent one at a time, so a cell can stop at the first error and input/output labels stay those of a normal Maxima session.

### Windows plotting workaround

Maxima 5.50 with SBCL on Windows starts gnuplot as `gnuplot "-persist <file>"` (one quoted argument) when an output file is requested. gnuplot then ignores the script and waits on standard input, which hangs the session. Each session therefore sets `gnuplot_command` to the gnuplot bundled with Maxima plus ` -persist`, and `gnuplot_view_args` to `"~a"`.

## Stopping

Maxima over a pipe has no portable interrupt, so Stop kills the process tree (`taskkill /T` on Windows, the process group elsewhere) and starts a new Maxima. The running cell reports that it was stopped and that definitions are gone.

## Front end (`maxbook/web/`)

Plain ES modules, no build step. `main.js` owns the notebook state and cell views; `markdown.js` renders Markdown with math via marked and MathLive; `highlight.js` colours Maxima code; `templates.js` holds the search-as-you-type templates; `export.js` builds the self-contained HTML export (fonts inlined) and rasterises SVG plots for the LaTeX export. The page has a strict Content Security Policy (`script-src 'self'`).

## API

All endpoints need `X-Maxbook-Token`. `GET /api/session`, `GET /api/kernel`, `POST /api/run` → job id, `GET /api/job?id=&since=` (incremental outputs, pending question), `POST /api/answer`, `POST /api/interrupt`, `POST /api/restart`, `POST /api/convert`, `POST /api/open`, `POST /api/save`, `POST /api/export`, `POST /api/new`, `GET /api/fs`, `POST /api/shutdown`.
