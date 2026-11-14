"""CLI: create a fresh, isolated database for one scenario.

    uv run buyer-seed            # list scenarios
    uv run buyer-seed S1-MODIFY  # build data/runs/S1-MODIFY__<run_id>.db and print a summary
"""
from __future__ import annotations

import sys

from ..agent.runs import new_run
from ..config import load_env
from ..scenarios.catalog import SCENARIOS
from ..scenarios.seed import summary


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    load_env()
    if not argv:
        for s in SCENARIOS.values():
            print(f"[{s.group}] {s.id:<22} expect {s.expected.decision:<11} {s.title}")
    else:
        run, c = new_run(argv[0])
        print(f"Built {run.path}: {summary(c)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
