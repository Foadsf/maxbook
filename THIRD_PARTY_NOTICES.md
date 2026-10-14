# Third-party components

Maxbook itself is licensed under GPL-3.0-or-later (see `LICENSE`). The components below keep their own licences, which are compatible with it.

Maxbook vendors JavaScript packages so the notebook works offline, with no network access and no build step at run time.

MathLive is an unmodified copy of the published npm tarball; its license files are shipped next to it.

| Package | Version | Files | License | npm integrity |
|---|---|---|---|---|
| [MathLive](https://github.com/arnog/mathlive) | 0.110.0 | `maxbook/web/vendor/mathlive/` (module, static CSS, fonts) | MIT, see `LICENSE.txt` there | `sha512-UOpJsQ6h1eeN0xZULGTl1MwUB/lZLCDuzKeHvKEh7Zra8U/rtgDNrssj5PZdJtBTIV48AfEhtv6rv47AeMOxJA==` |
| [KaTeX fonts](https://github.com/KaTeX/katex-fonts) (inside the MathLive package) | as shipped with MathLive 0.110.0 | `maxbook/web/vendor/mathlive/fonts/` | MIT, Copyright (c) 2018 Khan Academy, see `LICENSE-KaTeX-fonts.txt` there | (part of the MathLive tarball) |

The document editor uses [ProseMirror](https://prosemirror.net/) and [markdown-it](https://github.com/markdown-it/markdown-it). Their packages are bundled, unmodified, into one ES module, `maxbook/web/vendor/prosemirror/prosemirror.mjs`, by `tools/vendor/build.mjs` (esbuild). The exact versions are pinned in `tools/vendor/package.json` and `package-lock.json` (with npm integrity hashes); `PACKAGES.txt` next to the bundle lists every package whose code it contains with its licence, and each package's licence file is copied there as `LICENSE-<package>`. All of them are MIT-licensed except `entities` (BSD-2-Clause). To rebuild: `cd tools/vendor && npm ci && node build.mjs`.

Versions were pinned to releases at least two weeks old at the time of vendoring (2026-10-14).

Maxbook talks to [Maxima](https://maxima.sourceforge.io/) as a separate program over a pipe and does not include or link Maxima code. Maxima and the gnuplot bundled with its installers are installed separately by the user.
