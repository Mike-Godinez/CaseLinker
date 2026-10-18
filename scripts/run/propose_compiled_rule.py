#!/usr/bin/env python3
"""
Draft one compiled extraction rule from quotes a reviewer has already confirmed.

The draft is validated against those quotes and written under
config/compiled_rules/proposed/. It does not run. To make it run, commit the
printed dict into APPROVED in src/Processing Layer/compiled_rules.py.

Examples:
  python3 scripts/run/propose_compiled_rule.py \\
    --id screen_name_age --field age --role decoy \\
    --regex 'screen name\\W+(?:\\w+\\W+){0,4}?(\\d{1,2})-year-old' \\
    --positive "used screen name Jake, a 14-year-old from Boise" \\
    --negative "a 14-year-old victim"

  CASELINKER_LLM=1 python3 scripts/run/propose_compiled_rule.py \\
    --id screen_name_age --field age --role decoy --from-llm \\
    --positive "used screen name Jake, a 14-year-old from Boise" \\
    --negative "a 14-year-old victim"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "src" / "Processing Layer"
LAYER = PROC / "field_assertions"
ML = PROC / "ML Processing Layer"
for path in (LAYER, ML):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import compiled_rules  # noqa: E402


def _llm_generate(prompt: str) -> str:
    import llm_extraction

    if not llm_extraction.llm_enabled():
        raise SystemExit("CASELINKER_LLM=1 is required for --from-llm")
    cfg = llm_extraction.llm_config()
    text, _latency, status = llm_extraction._generate(cfg, prompt)
    if not text:
        raise SystemExit(f"LLM draft failed ({status})")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True)
    parser.add_argument("--field", required=True, choices=("age", "sentence", "investigation_type"))
    parser.add_argument("--role", required=True)
    parser.add_argument("--positive", action="append", required=True, help="Quote the rule must match. Repeatable.")
    parser.add_argument("--negative", action="append", default=[], help="Quote the rule must not match. Repeatable.")
    parser.add_argument("--kind", action="append", default=["press_release"], dest="kinds")
    parser.add_argument("--regex", help="Reviewer-supplied pattern. Skips the model.")
    parser.add_argument("--from-llm", action="store_true")
    args = parser.parse_args()
    if bool(args.regex) == bool(args.from_llm):
        raise SystemExit("Pass exactly one of --regex or --from-llm")

    proposal = compiled_rules.propose_rule(
        rule_id=args.id,
        field=args.field,
        role=args.role,
        positives=args.positive,
        negatives=args.negative,
        document_kinds=args.kinds,
        regex=args.regex,
        generate=_llm_generate if args.from_llm else None,
    )
    if not proposal.get("ok"):
        print(proposal.get("reason") or proposal, file=sys.stderr)
        return 1
    path = compiled_rules.write_proposal(proposal)
    printable = {k: v for k, v in proposal.items() if k not in ("ok", "approved", "positives", "negatives", "prompt_id")}
    print(f"Proposal written to {path}")
    print("It does not run until this dict is committed in compiled_rules.APPROVED:")
    print(json.dumps(printable, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
