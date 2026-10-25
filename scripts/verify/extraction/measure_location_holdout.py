#!/usr/bin/env python3
"""Score the location holdout sample under the current demotion policy."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
HOLDOUT = OUT / "location_precision_holdout.json"
REPORT = OUT / "location_precision_holdout_report.md"
PROC = ROOT / "src" / "Processing Layer" / "location_grounding.py"

_NOT_A_PLACE = re.compile(
    r"(?i)\b(district of|southern district|northern district|eastern district|"
    r"western district|middle district|central district|internet|online)\b"
)


def _load():
    spec = importlib.util.spec_from_file_location("location_grounding", PROC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["location_grounding"] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def _core(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def judge(pair, lg) -> str:
    mention = pair["mention"]
    entity = pair.get("entity_name") or ""
    if _NOT_A_PLACE.search(mention) or _NOT_A_PLACE.search(entity):
        return "not_a_place"
    m_core, e_core = _core(mention), _core(entity)
    if not m_core or not e_core:
        return "wrong"
    if m_core in e_core or e_core in m_core:
        return "right"
    if pair.get("entity_kind") == "state" and lg.resolve_abbrev_token(mention) == pair.get(
        "state_hint"
    ):
        return "right"
    return "wrong"


def main() -> int:
    if not HOLDOUT.is_file():
        print(f"Missing {HOLDOUT}", file=sys.stderr)
        return 1
    lg = _load()
    pairs = json.loads(HOLDOUT.read_text())["pairs"]
    # re-ground under current policy
    rows = []
    for pair in pairs:
        gnds = lg.ground_case_locations(
            [pair["mention"]],
            source=pair["source"],
            case_text=pair.get("sentence") or "",
            case_id=pair["case_id"],
        )
        gnd = gnds[0] if gnds else {}
        if gnd.get("status") != "grounded":
            rows.append({**pair, "judgment": "dropped", "post_status": gnd.get("status")})
            continue
        merged = {
            **pair,
            "entity_name": gnd.get("entity_name") or pair.get("entity_name"),
            "hint_source": gnd.get("hint_source") or pair.get("hint_source"),
            "fips": gnd.get("fips") or pair.get("fips"),
        }
        rows.append({**merged, "judgment": judge(merged, lg)})
    by = defaultdict(Counter)
    for r in rows:
        if r["judgment"] == "dropped":
            by["_dropped"][r.get("post_status") or "unknown"] += 1
            continue
        if r["judgment"] == "not_a_place":
            by[r.get("hint_source") or "none"]["not_a_place"] += 1
            continue
        by[r.get("hint_source") or "none"][r["judgment"]] += 1
        by["_all"][r["judgment"]] += 1
    lines = ["# Location grounding holdout", "", "| hint_source | right | wrong | precision |", "|---|---:|---:|---:|"]
    for src, c in sorted(by.items()):
        if src == "_dropped":
            continue
        denom = c["right"] + c["wrong"]
        p = f"{c['right']/denom:.1%}" if denom else "n/a"
        lines.append(f"| `{src}` | {c['right']} | {c['wrong']} | {p} |")
    lines.append("")
    lines.append(f"Dropped (not grounded under policy): **{sum(by['_dropped'].values())}** {dict(by['_dropped'])}")
    lines.append("")
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
