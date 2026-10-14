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

## Single-file programs (GitHub releases)

The programs built by `packaging/build.py` with [PyInstaller](https://pyinstaller.org/) contain a Python runtime (PSF License) and the optional AI helper's packages: `anthropic`, `anyio`, `annotated-types`, `docstring_parser`, `h11`, `httpcore2`, `httpx2`, `idna`, `jiter`, `opentelemetry-api`, `pydantic`, `pydantic_core`, `sniffio`, `truststore`, `typing-inspection` and `typing_extensions` (MIT, BSD-3-Clause, Apache-2.0 or PSF-2.0). Each release includes `THIRD_PARTY_LICENSES.txt` with the full licence texts, collected from the packages that went into the build. PyInstaller's bootloader is GPL-2.0-or-later with an exception that permits distributing it with programs under any licence.

## Documentation site

The site in `docs/` is built with [Antora](https://antora.org/) (MPL-2.0, a build tool, not shipped). It uses the [Antora default UI](https://gitlab.com/antora/antora-ui-default) (MPL-2.0): `docs/ui/ui-bundle.zip` is that bundle with the colours in `css/site.css` replaced by CSS variables by `docs/tools/theme-ui.py` (the only change; the script is the source of the modification). [Asciidoctor Tabs](https://github.com/asciidoctor/asciidoctor-tabs) 1.0.0-beta.6 (MIT, Copyright (c) 2018-present Dan Allen) provides the tabs; its stylesheet and script are copied into `docs/ui/supplemental` with their licence header, the stylesheet's colours replaced by the site's theme variables. Search uses [@antora/lunr-extension](https://gitlab.com/antora/antora-lunr-extension) (MPL-2.0).

Maxbook talks to [Maxima](https://maxima.sourceforge.io/) as a separate program over a pipe and does not include or link Maxima code. Maxima and the gnuplot bundled with its installers are installed separately by the user.
