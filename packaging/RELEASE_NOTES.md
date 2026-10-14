Maxbook is a notebook for literate computing with the Maxima computer algebra system: prose, formulas and live computations in one continuous document.

**[Install guide](https://foadsf.github.io/maxbook/install/) · [Tour: your first notebook](https://foadsf.github.io/maxbook/tutorials/first-notebook/) · [Documentation](https://foadsf.github.io/maxbook/)**

## Downloads

Each file is the complete program: download, make it runnable if needed, and start it. Maxbook uses the [Maxima](https://maxima.sourceforge.io/download.html) installed on your computer, so install Maxima first.

| Computer | File |
|---|---|
| Windows (Intel/AMD) | `maxbook-<version>-windows-x64.exe` |
| Windows on Arm | `maxbook-<version>-windows-arm64.exe` |
| Mac with Apple silicon | `maxbook-<version>-macos-arm64` |
| Mac with Intel | `maxbook-<version>-macos-x64` |
| Linux x86-64 (glibc 2.35+) | `maxbook-<version>-linux-x64` |
| Linux Arm 64-bit | `maxbook-<version>-linux-arm64` |

The programs are not code-signed: Windows SmartScreen asks you to confirm (**More info → Run anyway**); on macOS run `xattr -d com.apple.quarantine <file>` and `chmod +x <file>`; on Linux `chmod +x <file>`. `SHA256SUMS.txt` lists the checksums.

## What's new in 0.5

- One continuous document: prose, inline (`$`) and display (`$$`) formulas and Maxima blocks (`>>`); Markdown and LaTeX convert as you type or paste.
- Compute in place: end a formula with `=` and press Tab; `:=` then Tab defines it in Maxima.
- Symbols coloured by name, hover cards, and an Objects panel with your variables, functions and constants.
- wxMaxima-style menus that write the Maxima code, `.wxmx` export, and a Stop that keeps your definitions.
- Edit together: windows stay in sync, and `--share` lets others on your network edit with you.
- An optional AI helper (Anthropic's Claude), off unless you configure it.
