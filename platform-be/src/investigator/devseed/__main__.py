"""`python -m investigator.devseed <command>` — see docs/seeding.md."""

from __future__ import annotations

import sys

from investigator.devseed.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
