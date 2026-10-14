# Third-party components

Maxbook itself is licensed under GPL-3.0-or-later (see `LICENSE`). The components below keep their own licences, which are compatible with it.

Maxbook vendors two JavaScript packages so the notebook works offline. Both are unmodified copies of the published npm tarballs; their license files are shipped next to them.

| Package | Version | Files | License | npm integrity |
|---|---|---|---|---|
| [MathLive](https://github.com/arnog/mathlive) | 0.110.0 | `maxbook/web/vendor/mathlive/` (module, static CSS, fonts) | MIT, see `LICENSE.txt` there | `sha512-UOpJsQ6h1eeN0xZULGTl1MwUB/lZLCDuzKeHvKEh7Zra8U/rtgDNrssj5PZdJtBTIV48AfEhtv6rv47AeMOxJA==` |
| [KaTeX fonts](https://github.com/KaTeX/katex-fonts) (inside the MathLive package) | as shipped with MathLive 0.110.0 | `maxbook/web/vendor/mathlive/fonts/` | MIT, Copyright (c) 2018 Khan Academy, see `LICENSE-KaTeX-fonts.txt` there | (part of the MathLive tarball) |
| [marked](https://github.com/markedjs/marked) | 18.0.14 | `maxbook/web/vendor/marked/marked.esm.js` | MIT, see `LICENSE` there | `sha512-mBHK6FBHuBAlhgRe88w9F0O1AbwwXJUcQibUbC/QcdTbVGAD7aWza+xt3N6oT/jCZx3/OMeS+8rnuiHZcQ9s7A==` |

Versions were pinned to releases at least two weeks old at the time of vendoring (2026-10-14). To update, fetch with `npm pack <name>@<version>`, check the integrity hash, and copy the same files.

Maxbook talks to [Maxima](https://maxima.sourceforge.io/) as a separate program over a pipe and does not include or link Maxima code. Maxima and the gnuplot bundled with its installers are installed separately by the user.
