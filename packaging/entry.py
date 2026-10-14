# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Entry point of the single-file executables built by packaging/build.py."""

import sys

from maxbook.cli import main

if __name__ == "__main__":
    sys.exit(main())
