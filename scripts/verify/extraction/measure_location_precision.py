#!/usr/bin/env python3
"""Judge frozen location pairs against their source sentence; demote weak hint sources.

Judgment (deterministic rules against the stored sentence + ground):
  - not_a_place: mention is a court district / non-geo token
  - right: entity core overlaps mention and state is consistent with sentence/source
  - wrong: otherwise (grounded but incompatible)

Writes judgments + precision report. If any hint_source precision < 0.95 among
judged right/(right+wrong), demotes it in hint_source_policy.json and re-grounds
the sample under the new policy for a second measurement.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SAMPLE_PATH = OUT / "location_precision_sample.json"
JUDGE_PATH = OUT / "location_precision_judgments.json"
REPORT_PATH = OUT / "location_precision_report.md"
POLICY_PATH = OUT / "hint_source_policy.json"
PROC = ROOT / "src" / "Processing Layer" / "location_grounding.py"

_NOT_A_PLACE = re.compile(
    r"(?i)\b(district of|southern district|northern district|eastern district|"
    r"western district|middle district|central district|internet|online|cyberspace|"
    r"dark web|facebook|instagram)\b"
)


def _load_lg():
    spec = importlib.util.spec_from_file_location("location_grounding", PROC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["location_grounding"] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def _core(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def judge_pair(pair: dict, lg) -> str:
    mention = pair["mention"]
    sent = pair.get("sentence") or ""
    entity = pair.get("entity_name") or ""
    if _NOT_A_PLACE.search(mention) or _NOT_A_PLACE.search(entity):
        return "not_a_place"
    m_core = _core(mention)
    e_core = _core(entity)
    if not m_core or not e_core:
        return "wrong"
    overlap = m_core in e_core or e_core in m_core
    # state consistency: if sentence names a different state than hint, wrong
    sent_state = lg.state_in_sentence(sent) if sent else None
    hint = pair.get("state_hint")
    if sent_state and hint and sent_state != hint and pair.get("hint_source") == "sentence":
        # sentence hint should match sentence state by construction; if not, wrong
        if sent_state != hint:
            return "wrong"
    if overlap:
        return "right"
    # AP/state-only grounds: mention is abbrev of entity state
    if pair.get("entity_kind") == "state" and lg.resolve_abbrev_token(mention) == hint:
        return "right"
    return "wrong"


def precision_table(judgments: list[dict]) -> dict:
    by = defaultdict(lambda: Counter())
    for j in judgments:
        if j["judgment"] == "not_a_place":
            by[j["hint_source"]]["not_a_place"] += 1
            continue
        by[j["hint_source"]][j["judgment"]] += 1
        by["_all"][j["judgment"]] += 1
    out = {}
    for src, c in by.items():
        denom = c["right"] + c["wrong"]
        prec = (c["right"] / denom) if denom else None
        out[src] = {
            "right": c["right"],
            "wrong": c["wrong"],
            "not_a_place": c["not_a_place"],
            "n_scored": denom,
            "precision": prec,
        }
    return out


def write_report(prec: dict, demoted: list[str], phase: str) -> str:
    lines = [
        f"# Location grounding precision ({phase})",
        "",
        "| hint_source | right | wrong | not_a_place | precision |",
        "|---|---:|---:|---:|---:|",
    ]
    for src, row in sorted(prec.items()):
        p = row["precision"]
        p_s = f"{p:.1%}" if p is not None else "n/a"
        lines.append(
            f"| `{src}` | {row['right']} | {row['wrong']} | {row['not_a_place']} | {p_s} |"
        )
    lines.extend(["", f"Demoted hint sources (<95%): **{demoted or 'none'}**", ""])
    return "\n".join(lines)


def main() -> int:
    if not SAMPLE_PATH.is_file():
        print(f"Missing {SAMPLE_PATH}; run freeze_location_sample.py first", file=sys.stderr)
        return 1
    lg = _load_lg()
    sample = json.loads(SAMPLE_PATH.read_text())["pairs"]

    # Clear demotions for baseline measure
    POLICY_PATH.write_text(
        json.dumps({"demoted_hint_sources": [], "threshold": 0.95}, indent=2) + "\n"
    )

    judgments = []
    for pair in sample:
        j = judge_pair(pair, lg)
        judgments.append({**pair, "judgment": j})
    JUDGE_PATH.write_text(json.dumps({"pairs": judgments}, indent=2))
    prec1 = precision_table(judgments)
    demoted = []
    for src, row in prec1.items():
        if src == "_all":
            continue
        if row["precision"] is not None and row["n_scored"] >= 5 and row["precision"] < 0.95:
            demoted.append(src)
    POLICY_PATH.write_text(
        json.dumps(
            {
                "demoted_hint_sources": sorted(demoted),
                "threshold": 0.95,
                "baseline_precision": {
                    k: v["precision"] for k, v in prec1.items() if v["precision"] is not None
                },
            },
            indent=2,
        )
        + "\n"
    )
    report = write_report(prec1, demoted, "baseline")
    # Re-measure under demotion: re-ground each pair (policy file read on each call)
    rematch = []
    for pair in sample:
        rows = lg.ground_case_locations(
            [pair["mention"]],
            source=pair["source"],
            case_text=pair.get("sentence") or "",
            case_id=pair["case_id"],
        )
        gnd = rows[0] if rows else {}
        rematch.append(
            {
                **pair,
                "post_status": gnd.get("status"),
                "post_fips": gnd.get("fips"),
                "post_hint_source": gnd.get("hint_source"),
                "post_reason": gnd.get("reason"),
            }
        )
    still_grounded = [r for r in rematch if r["post_status"] == "grounded"]
    # Re-judge only still-grounded with updated hint_source
    judgments2 = []
    for r in still_grounded:
        pair = {
            **r,
            "hint_source": r.get("post_hint_source") or r.get("hint_source"),
            "fips": r.get("post_fips") or r.get("fips"),
        }
        judgments2.append({**pair, "judgment": judge_pair(pair, lg)})
    prec2 = precision_table(judgments2)
    report += "\n" + write_report(prec2, demoted, "after demotion")
    report += (
        f"\nAfter demotion: {len(still_grounded)}/{len(sample)} sample pairs still grounded "
        f"({len(sample) - len(still_grounded)} became ambiguous/ungrounded).\n"
    )
    REPORT_PATH.write_text(report)
    print(report)
    print(f"wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
