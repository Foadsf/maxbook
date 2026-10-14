# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Make the Antora default UI themable: colours become CSS variables.

    python docs/tools/theme-ui.py ui-bundle.zip docs/ui/ui-bundle.zip

The input is the Antora default UI bundle (MPL-2.0,
https://gitlab.com/antora/antora-ui-default).  Every colour literal in
css/site.css is replaced by ``var(--mbx-<hex>)`` and the variables are
defined for a light theme (Maxbook's paper tones) and a dark theme, chosen by
``prefers-color-scheme`` or by ``data-theme`` on <html> (the theme toggle in
docs/ui/supplemental).  Nothing else in the bundle changes.  Colours that
serve two roles in the default UI (the navbar uses the heading colour, admonition
icons use the page background) are pinned in supplemental/css/maxbook.css.
"""

from __future__ import annotations

import re
import sys
import zipfile

#          default    light (Maxbook)  dark
PALETTE = {
    "fff": ("#fffefb", "#16171b"),      # page background
    "fafafa": ("#f8f6f1", "#1c1d22"),   # navigation, toolbar, inline code
    "f0f0f0": ("#f1eee7", "#23252b"),
    "f5f5f5": ("#f3f1ec", "#25272d"),
    "e1e1e1": ("#e4e0d7", "#2c2e35"),   # lines
    "dbdbdb": ("#dcd7cc", "#3a3c44"),
    "c1c1c1": ("#d0cabd", "#474a53"),
    "9c9c9c": ("#9a958a", "#6b6d75"),
    "8e8e8e": ("#8a867d", "#8d8b85"),   # muted text
    "5d5d5d": ("#5f5c55", "#b0ada6"),
    "4c4c4c": ("#4a4843", "#c3c1ba"),
    "4a4a4a": ("#4a4843", "#c3c1ba"),
    "424242": ("#3f3d39", "#d0cec8"),
    "333": ("#2a2926", "#e2e0da"),      # body text
    "222": ("#1d1c1a", "#ecebe7"),
    "191919": ("#1d1c1a", "#f0eee9"),   # headings
    "000": ("#000000", "#000000"),
    "1565c0": ("#3b5bdb", "#8aa4ff"),   # links
    "104d92": ("#2b45b0", "#b3c3ff"),
    "d32f2f": ("#c92a2a", "#ff8787"),
    "217ee7": ("#3b5bdb", "#5c7cfa"),   # admonition icons
    "41af46": ("#2f9e44", "#37b24d"),
    "e18114": ("#e8590c", "#f76707"),
    "a0439c": ("#ae3ec9", "#be4bdb"),
    # syntax highlighting
    "998": ("#8a867d", "#8d8b85"),
    "999": ("#8a867d", "#8d8b85"),
    "d14": ("#c2255c", "#ff8fb1"),
    "900": ("#9c2c2c", "#ff8a80"),
    "458": ("#3b5bdb", "#9ab4ff"),
    "009926": ("#2b8a3e", "#7ee08a"),
    "990073": ("#7048e8", "#c4a8ff"),
    "0086b3": ("#1971c2", "#6ccff6"),
    "fdd": ("#fff0f0", "#4a2020"),
    "dfd": ("#ebfbee", "#1f3a22"),
}

HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def theme(css: str) -> str:
    missing = sorted({m.lower() for m in HEX.findall(css)} - set(PALETTE))
    if missing:
        raise SystemExit(f"colours without a theme entry: {missing}")
    body = HEX.sub(lambda m: f"var(--mbx-{m.group(1).lower()})", css)
    light = ";".join(f"--mbx-{k}:{v[0]}" for k, v in PALETTE.items())
    dark = ";".join(f"--mbx-{k}:{v[1]}" for k, v in PALETTE.items())
    head = (f":root{{{light};color-scheme:light}}"
            f":root[data-theme=dark]{{{dark};color-scheme:dark}}"
            f"@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{{dark};color-scheme:dark}}}}\n")
    # keep a leading /*! licence comment first
    m = re.match(r"\s*/\*!.*?\*/", body, re.S)
    return body[:m.end()] + "\n" + head + body[m.end():] if m else head + body


def main(src: str, dst: str) -> None:
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "css/site.css":
                data = theme(data.decode("utf-8")).encode("utf-8")
            zout.writestr(info, data)
    print(f"wrote {dst}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
