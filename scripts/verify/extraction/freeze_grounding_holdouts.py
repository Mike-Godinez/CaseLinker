#!/usr/bin/env python3
"""Freeze grounding holdout samples (150 location + 150 agency pairs).

Writes pair-id lists matching the Phase 3 holdout style
(``phase3_holdout_sample_ids.txt``). Excludes all prior precision-sample ids.
Judgments are recorded separately by reading source sentences
(``judge_grounding_holdouts.py``) — never by reusing matcher logic as the scorer.
"""

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
SEED = 20261022
N = 150
PRIOR = [
    OUT / "location_precision_sample.json",
    OUT / "location_precision_holdout.json",
    OUT / "agency_precision_sample.json",
    OUT / "agency_precision_holdout.json",
]
LOC_IDS = OUT / "grounding_holdout_location_ids.txt"
AG_IDS = OUT / "grounding_holdout_agency_ids.txt"
# Working packs for sentence judgment (local; not the published artifact names)
LOC_PACK = OUT / "grounding_holdout_location_pack.jsonl"
AG_PACK = OUT / "grounding_holdout_agency_pack.jsonl"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def _prior_ids() -> set[str]:
    ids: set[str] = set()
    for p in PRIOR:
        if not p.is_file():
            continue
        data = json.loads(p.read_text())
        for row in data.get("pairs") or []:
            if row.get("pair_id"):
                ids.add(row["pair_id"])
    return ids


def _case_text(raw) -> str:
    if isinstance(raw, str) and raw:
        try:
            blob = json.loads(raw)
            if isinstance(blob, dict):
                return blob.get("case_text") or blob.get("text") or ""
        except json.JSONDecodeError:
            return ""
    return ""


def main() -> int:
    prior = _prior_ids()
    lg = _load(ROOT / "src" / "Processing Layer" / "location_grounding.py", "location_grounding")
    ag = _load(ROOT / "src" / "Processing Layer" / "agency_grounding.py", "agency_grounding")
    conn = sqlite3.connect(f"file:{ROOT / 'caselinker.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, source, extracted_features, raw_data FROM cases "
        "WHERE extracted_features IS NOT NULL"
    ).fetchall()

    loc_cands = []
    ag_cands = []
    for r in rows:
        feats = json.loads(r["extracted_features"])
        text = _case_text(r["raw_data"])
        locs = feats.get("locations") or []
        if isinstance(locs, list) and locs and not lg.is_international_source(r["source"]):
            for gnd in lg.ground_case_locations(
                locs, source=r["source"], case_text=text, case_id=r["id"]
            ):
                if gnd.get("status") != "grounded":
                    continue
                key = f"{r['id']}|{gnd['mention']}|{gnd.get('fips')}"
                pid = hashlib.sha1(key.encode()).hexdigest()[:12]
                if pid in prior:
                    continue
                sent = lg.sentence_containing(text, gnd["mention"]) or ""
                loc_cands.append(
                    {
                        "pair_id": pid,
                        "case_id": r["id"],
                        "source": r["source"],
                        "mention": gnd["mention"],
                        "claimed_entity": gnd.get("entity_name"),
                        "claimed_kind": gnd.get("entity_kind"),
                        "fips": gnd.get("fips"),
                        "state_hint": gnd.get("state_hint"),
                        "hint_source": gnd.get("hint_source"),
                        "slug": gnd.get("slug"),
                        "sentence": sent[:800],
                    }
                )
        agencies = feats.get("agencies_involved") or []
        if isinstance(agencies, list) and agencies:
            loc_g = (
                feats.get("location_grounds")
                if isinstance(feats.get("location_grounds"), list)
                else []
            )
            for gnd in ag.ground_case_agencies(
                agencies,
                source=r["source"],
                case_id=r["id"],
                location_grounds=loc_g,
            ):
                if gnd.get("status") != "grounded":
                    continue
                key = f"{r['id']}|{gnd['mention']}|{gnd.get('ori') or gnd.get('code')}"
                pid = hashlib.sha1(key.encode()).hexdigest()[:12]
                if pid in prior:
                    continue
                sent = ""
                if text and gnd["mention"]:
                    sent = lg.sentence_containing(text, gnd["mention"]) or ""
                if not sent and text:
                    sent = text[:500]
                ag_cands.append(
                    {
                        "pair_id": pid,
                        "case_id": r["id"],
                        "source": r["source"],
                        "mention": gnd["mention"],
                        "claimed_entity": gnd.get("agency_name"),
                        "ori": gnd.get("ori"),
                        "code": gnd.get("code"),
                        "state_hint": gnd.get("state_hint"),
                        "hint_source": gnd.get("hint_source"),
                        "slug": gnd.get("slug"),
                        "reason": gnd.get("reason"),
                        "sentence": sent[:800],
                    }
                )
    conn.close()
    rng = random.Random(SEED)
    rng.shuffle(loc_cands)
    rng.shuffle(ag_cands)
    loc = loc_cands[:N]
    agen = ag_cands[:N]
    LOC_IDS.write_text("\n".join(p["pair_id"] for p in loc) + "\n")
    AG_IDS.write_text("\n".join(p["pair_id"] for p in agen) + "\n")
    with LOC_PACK.open("w") as f:
        for row in loc:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with AG_PACK.open("w") as f:
        for row in agen:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {LOC_IDS.name} n={len(loc)} (excluded {len(prior)} prior ids)")
    print(f"wrote {AG_IDS.name} n={len(agen)}")
    print(f"working packs: {LOC_PACK.name}, {AG_PACK.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
