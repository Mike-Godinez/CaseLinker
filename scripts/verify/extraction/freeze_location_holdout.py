#!/usr/bin/env python3
"""Freeze a holdout sample of 150 grounded location pairs (disjoint from train)."""

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
PROC = ROOT / "src" / "Processing Layer" / "location_grounding.py"
TRAIN = OUT / "location_precision_sample.json"
HOLDOUT = OUT / "location_precision_holdout.json"
SEED = 20261021
N = 150


def _load_lg():
    spec = importlib.util.spec_from_file_location("location_grounding", PROC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["location_grounding"] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    train_ids = set()
    if TRAIN.is_file():
        train_ids = {p["pair_id"] for p in json.loads(TRAIN.read_text())["pairs"]}
    lg = _load_lg()
    conn = sqlite3.connect(f"file:{ROOT / 'caselinker.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, source, extracted_features, raw_data FROM cases "
        "WHERE extracted_features IS NOT NULL"
    ).fetchall()
    candidates = []
    for r in rows:
        feats = json.loads(r["extracted_features"])
        locs = feats.get("locations") or []
        if not isinstance(locs, list) or not locs:
            continue
        if lg.is_international_source(r["source"]):
            continue
        text = ""
        raw = r["raw_data"]
        if isinstance(raw, str) and raw:
            try:
                blob = json.loads(raw)
                if isinstance(blob, dict):
                    text = blob.get("case_text") or blob.get("text") or ""
            except json.JSONDecodeError:
                text = ""
        for gnd in lg.ground_case_locations(
            locs, source=r["source"], case_text=text, case_id=r["id"]
        ):
            if gnd.get("status") != "grounded":
                continue
            key = f"{r['id']}|{gnd['mention']}|{gnd.get('fips')}"
            pair_id = hashlib.sha1(key.encode()).hexdigest()[:12]
            if pair_id in train_ids:
                continue
            sent = lg.sentence_containing(text, gnd["mention"]) or ""
            candidates.append(
                {
                    "case_id": r["id"],
                    "source": r["source"],
                    "mention": gnd["mention"],
                    "fips": gnd.get("fips"),
                    "entity_name": gnd.get("entity_name"),
                    "entity_kind": gnd.get("entity_kind"),
                    "state_hint": gnd.get("state_hint"),
                    "hint_source": gnd.get("hint_source"),
                    "gazetteer_version": gnd.get("gazetteer_version"),
                    "slug": gnd.get("slug"),
                    "sentence": sent[:500],
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
