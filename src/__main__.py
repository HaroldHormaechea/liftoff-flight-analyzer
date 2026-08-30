#!/usr/bin/env python3
"""The front door.

    python "<clone>/src" <command> [options]

CPython, handed a DIRECTORY as the script argument, prepends that directory to
sys.path and executes its __main__.py. So this file's own folder lands on
sys.path[0], `import fpv_review...` resolves, and the working directory is left
exactly where the user was standing. That last part is the point: every output
default in this tool is bare-relative to the working directory, so a launcher
that quietly changed it would write replays, reports and PB history into the
toolkit itself.

Documented CPython behaviour since 2.6, not a trick. It was chosen over three
alternatives, each of which fails something this project needs:

  * cwd set to <clone>/src   - moves the user's data into the toolkit
  * PYTHONPATH=src           - bash-only syntax, silently wrong in PowerShell
  * pip install -e .         - breaks clone-and-go, which is the whole install

There is no sys.path line anywhere in this codebase; CPython does the work.
"""

import sys

from fpv_review.cli import main

if __name__ == "__main__":
    sys.exit(main())
