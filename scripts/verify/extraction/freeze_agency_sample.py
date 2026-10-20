#!/usr/bin/env python3
"""Freeze 150 seeded case×agency pairs for precision measurement."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PROC = ROOT / "src" / "Processing Layer" / "agency_grounding.py"
SAMPLE_PATH = OUT / "agency_precision_sample.json"
SEED = 20261020
N = 150


def _load():
    spec = importlib.util.spec_from_file_location("agency_grounding", PROC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agency_grounding"] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ag = _load()
    conn = sqlite3.connect(f"file:{ROOT / 'caselinker.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, source, extracted_features FROM cases "
        "WHERE extracted_features IS NOT NULL"
    ).fetchall()
    candidates = []
    for r in rows:
        feats = json.loads(r["extracted_features"])
        agencies = feats.get("agencies_involved") or []
        if not isinstance(agencies, list) or not agencies:
            continue
        grounds = ag.ground_case_agencies(
            agencies, source=r["source"], case_id=r["id"]
        )
        for gnd in grounds:
            if gnd.get("status") != "grounded":
                continue
            candidates.append(
                {
                    "case_id": r["id"],
                    "source": r["source"],
                    "mention": gnd["mention"],
                    "ori": gnd.get("ori"),
                    "code": gnd.get("code"),
                    "agency_name": gnd.get("agency_name"),
                    "state_hint": gnd.get("state_hint"),
                    "hint_source": gnd.get("hint_source"),
                    "slug": gnd.get("slug"),
                    "reason": gnd.get("reason"),
                }
            )
    conn.close()
    rng = random.Random(SEED)
    rng.shuffle(candidates)
    by_src: dict[str, list] = {}
    for c in candidates:
        by_src.setdefault(c.get("hint_source") or "none", []).append(c)
    sample = []
    keys = sorted(by_src)
    idxs = {k: 0 for k in keys}
    while len(sample) < N and any(idxs[k] < len(by_src[k]) for k in keys):
        for k in keys:
            if idxs[k] < len(by_src[k]) and len(sample) < N:
                sample.append(by_src[k][idxs[k]])
                idxs[k] += 1
    for row in sample:
        key = f"{row['case_id']}|{row['mention']}|{row.get('ori') or row.get('code')}"
        row["pair_id"] = hashlib.sha1(key.encode()).hexdigest()[:12]
    SAMPLE_PATH.write_text(
        json.dumps({"seed": SEED, "n": len(sample), "pairs": sample}, indent=2)
    )
    print(f"wrote {SAMPLE_PATH} n={len(sample)} from {len(candidates)} grounded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
