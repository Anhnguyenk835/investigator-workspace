"""`python -m investigator.guardrails.eval` prints the deterministic scores and exits 1 if
any limit in thresholds.json is broken. `--json PATH` also writes them."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from investigator.guardrails.eval.runner import check, run_all, table

THRESHOLDS = Path(__file__).parent / "thresholds.json"


async def main(argv: list[str]) -> int:
    report = await run_all()
    print(table(report))
    if "--json" in argv:
        Path(argv[argv.index("--json") + 1]).write_text(
            report.model_dump_json(indent=1)
        )
    bad = check(report, json.loads(THRESHOLDS.read_text()))
    for line in bad:
        print("FAIL:", line)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
