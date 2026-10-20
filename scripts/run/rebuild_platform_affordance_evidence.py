#!/usr/bin/env python3
"""Rebuild platform affordance evidence when the corpus identity changes.

The builder reads caselinker.db. This script compares that database to the
recorded corpus_case_count and extraction_run_fingerprint.

  python3 scripts/run/rebuild_platform_affordance_evidence.py --check
  python3 scripts/run/rebuild_platform_affordance_evidence.py --check --strict
  python3 scripts/run/rebuild_platform_affordance_evidence.py

--check prints the decision and the db_gaps gate and does not write.
--strict makes --check exit 1 when a rebuild is required or db_gaps is above
the warning threshold. Without --check, a rebuild decision runs the builder.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "run"
if str(RUN) not in sys.path:
    sys.path.insert(0, str(RUN))

from platform_affordance_evidence_freshness import (  # noqa: E402
    gap_gate,
    read_corpus_identity,
    rebuild_decision,
)

EVIDENCE = ROOT / "ontology" / "platform_affordance_evidence" / "platform_affordance_evidence.json"
DB = ROOT / "caselinker.db"
BUILDER = ROOT / "ontology" / "platform_affordance_evidence" / "platform_affordance_evidence.py"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report only; do not rebuild")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="with --check, exit 1 when a rebuild is required or db_gaps warns",
    )
    args = parser.parse_args(argv)
    if not EVIDENCE.is_file():
        print(f"missing {EVIDENCE}", file=sys.stderr)
        return 1
    meta = json.loads(EVIDENCE.read_text(encoding="utf-8")).get("_meta") or {}
    gate = gap_gate(meta.get("db_gaps"))
    print(f"db_gaps={meta.get('db_gaps')} gate={gate}")
    if not DB.is_file():
        print("caselinker.db is absent; corpus identity was not compared", file=sys.stderr)
        return 1 if args.strict else 0
    with sqlite3.connect(DB) as conn:
        live = read_corpus_identity(conn)
    decision = rebuild_decision(meta, live)
    print(f"decision={decision} live_cases={None if live is None else live.get('case_count')}")
    if args.check:
        if args.strict and (decision != "current" or gate != "ok"):
            return 1
        return 0
    if decision == "current":
        print("snapshot identity matches; not rebuilding")
        return 0
    if decision == "unknown":
        print("corpus identity unavailable; not rebuilding", file=sys.stderr)
        return 1
    completed = subprocess.run([sys.executable, str(BUILDER)], cwd=ROOT)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
