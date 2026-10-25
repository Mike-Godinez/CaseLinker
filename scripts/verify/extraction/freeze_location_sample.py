#!/usr/bin/env python3
"""Freeze 150 seeded grounded case×location pairs for precision measurement."""

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
SAMPLE_PATH = OUT / "location_precision_sample.json"
SEED = 20261020
N = 150


def _load_lg():
    spec = importlib.util.spec_from_file_location("location_grounding", PROC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["location_grounding"] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
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
        grounds = lg.ground_case_locations(
            locs, source=r["source"], case_text=text, case_id=r["id"]
        )
        for gnd in grounds:
            if gnd.get("status") != "grounded":
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
                }
            )
    conn.close()
    rng = random.Random(SEED)
    rng.shuffle(candidates)
    # Stratify a bit by hint_source
    by_src: dict[str, list] = {}
    for c in candidates:
        by_src.setdefault(c["hint_source"] or "none", []).append(c)
    sample = []
    # take round-robin until N
    keys = sorted(by_src)
    idxs = {k: 0 for k in keys}
    while len(sample) < N and any(idxs[k] < len(by_src[k]) for k in keys):
        for k in keys:
            if idxs[k] < len(by_src[k]) and len(sample) < N:
                sample.append(by_src[k][idxs[k]])
                idxs[k] += 1
    # stable id for each pair
    for row in sample:
        key = f"{row['case_id']}|{row['mention']}|{row['fips']}"
        row["pair_id"] = hashlib.sha1(key.encode()).hexdigest()[:12]
    SAMPLE_PATH.write_text(json.dumps({"seed": SEED, "n": len(sample), "pairs": sample}, indent=2))
    print(f"wrote {SAMPLE_PATH} n={len(sample)} from {len(candidates)} grounded candidates")
    print("hint_source counts:", {k: sum(1 for s in sample if s['hint_source']==k) for k in sorted({s['hint_source'] for s in sample})})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
