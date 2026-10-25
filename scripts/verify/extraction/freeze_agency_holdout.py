#!/usr/bin/env python3
"""Freeze a holdout sample of 150 grounded agency pairs (disjoint from train)."""

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
TRAIN = OUT / "agency_precision_sample.json"
HOLDOUT = OUT / "agency_precision_holdout.json"
SEED = 20261021
N = 150


def _load():
    spec = importlib.util.spec_from_file_location("agency_grounding", PROC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agency_grounding"] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    train_ids = set()
    if TRAIN.is_file():
        train_ids = {p["pair_id"] for p in json.loads(TRAIN.read_text())["pairs"]}
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
        loc_g = feats.get("location_grounds") if isinstance(feats.get("location_grounds"), list) else []
        for gnd in ag.ground_case_agencies(
            agencies, source=r["source"], case_id=r["id"], location_grounds=loc_g
        ):
            if gnd.get("status") != "grounded":
                continue
            key = f"{r['id']}|{gnd['mention']}|{gnd.get('ori') or gnd.get('code')}"
            pair_id = hashlib.sha1(key.encode()).hexdigest()[:12]
            if pair_id in train_ids:
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
                    "pair_id": pair_id,
                }
            )
    conn.close()
    rng = random.Random(SEED)
    rng.shuffle(candidates)
    sample = candidates[:N]
    HOLDOUT.write_text(
        json.dumps({"seed": SEED, "n": len(sample), "role": "holdout", "pairs": sample}, indent=2)
    )
    print(f"wrote {HOLDOUT} n={len(sample)} (excluded {len(train_ids)} train pair_ids)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
