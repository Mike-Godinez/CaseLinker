#!/usr/bin/env python3
"""Agency precision: train sample, holdout, error breakdown, corpus status counts."""

from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
TRAIN_PATH = OUT / "agency_precision_sample.json"
HOLDOUT_PATH = OUT / "agency_precision_holdout.json"
JUDGE_PATH = OUT / "agency_precision_judgments.json"
REPORT_PATH = OUT / "agency_precision_report.md"
PROC = ROOT / "src" / "Processing Layer" / "agency_grounding.py"


def _load():
    spec = importlib.util.spec_from_file_location("agency_grounding", PROC)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agency_grounding"] = mod
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


def _core(text: str) -> str:
    s = (text or "").lower()
    s = re.sub(r"sheriff'?s?\s+department", "sheriff's office", s)
    s = re.sub(r"\bcity police department\b", "police department", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def judge_pair(pair: dict) -> str:
    mention = pair.get("mention") or ""
    entity = pair.get("agency_name") or ""
    m, e = _core(mention), _core(entity)
    if not m or not e:
        return "wrong"
    if m in e or e in m:
        return "right"
    if pair.get("reason") == "federal_table":
        code = _core(pair.get("code") or "")
        # "FBI" / "NCMEC" / "HSI Newark" against canonical long names
        if code and (m == code or m.startswith(code) or code in m):
            return "right"
        if code and code in e:
            return "right"
        # "… U.S. Marshals … Task Force" → USMS
        if code == "usms" and "marshal" in (mention or "").lower():
            return "right"
        if code == "hsi" and "homeland" in (mention or "").lower():
            return "right"
    return "wrong"


def score(pairs: list[dict]) -> dict:
    right = sum(1 for p in pairs if p["judgment"] == "right")
    wrong = sum(1 for p in pairs if p["judgment"] == "wrong")
    denom = right + wrong
    return {
        "right": right,
        "wrong": wrong,
        "n": len(pairs),
        "precision": (right / denom) if denom else None,
    }


def reground_sample(ag, sample: list[dict]) -> list[dict]:
    out = []
    for pair in sample:
        rows = ag.ground_case_agencies(
            [pair["mention"]], source=pair.get("source"), case_id=pair.get("case_id")
        )
        gnd = rows[0] if rows else {}
        merged = {
            **pair,
            "post_status": gnd.get("status"),
            "ori": gnd.get("ori") if gnd.get("status") == "grounded" else pair.get("ori"),
            "code": gnd.get("code") if gnd.get("status") == "grounded" else pair.get("code"),
            "agency_name": gnd.get("agency_name") or pair.get("agency_name"),
            "reason": gnd.get("reason") or pair.get("reason"),
            "hint_source": gnd.get("hint_source") or pair.get("hint_source"),
        }
        if gnd.get("status") == "grounded":
            merged["judgment"] = judge_pair(merged)
        else:
            merged["judgment"] = "dropped"
            merged["drop_status"] = gnd.get("status")
        out.append(merged)
    return out


def corpus_status_counts(ag) -> Counter:
    conn = sqlite3.connect(f"file:{ROOT / 'caselinker.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, source, extracted_features FROM cases "
        "WHERE extracted_features IS NOT NULL"
    ).fetchall()
    counts: Counter = Counter()
    ungrounded_reasons: Counter = Counter()
    oor_examples: Counter = Counter()
    for r in rows:
        feats = json.loads(r["extracted_features"])
        agencies = feats.get("agencies_involved") or []
        if not isinstance(agencies, list) or not agencies:
            continue
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
            st = gnd.get("status") or "ungrounded"
            counts[st] += 1
            if st == "ungrounded":
                ungrounded_reasons[gnd.get("reason") or "unknown"] += 1
            if st == "out_of_registry":
                oor_examples[gnd.get("mention") or "?"] += 1
    conn.close()
    return counts, ungrounded_reasons, oor_examples


def main() -> int:
    if not TRAIN_PATH.is_file():
        print(f"Missing {TRAIN_PATH}", file=sys.stderr)
        return 1
    ag = _load()
    train = json.loads(TRAIN_PATH.read_text())["pairs"]
    judged = reground_sample(ag, train)
    JUDGE_PATH.write_text(json.dumps({"pairs": judged}, indent=2))
    train_scored = [p for p in judged if p["judgment"] in ("right", "wrong")]
    train_stats = score(train_scored)
    wrong = [p for p in train_scored if p["judgment"] == "wrong"]
    dropped = [p for p in judged if p["judgment"] == "dropped"]

    lines = [
        "# Agency grounding precision",
        "",
        "## Train sample (re-grounded after tightening)",
        "",
        f"- n still grounded: **{train_stats['n']}** / {len(judged)}",
        f"- right: **{train_stats['right']}**",
        f"- wrong: **{train_stats['wrong']}**",
        (
            f"- precision: **{train_stats['precision']:.1%}**"
            if train_stats["precision"] is not None
            else "- precision: n/a"
        ),
        f"- dropped (no longer grounded): **{len(dropped)}** "
        f"({Counter(p.get('drop_status') for p in dropped)})",
        "",
        "### Error breakdown (wrong)",
        "",
    ]
    if not wrong:
        lines.append("_none_")
    for p in wrong:
        lines.append(
            f"- `{p['case_id']}`: «{p['mention']}» → «{p.get('agency_name')}» "
            f"({p.get('ori') or p.get('code')}; {p.get('reason')})"
        )

    if HOLDOUT_PATH.is_file():
        hold = json.loads(HOLDOUT_PATH.read_text())["pairs"]
        hold_j = reground_sample(ag, hold)
        hold_scored = [p for p in hold_j if p["judgment"] in ("right", "wrong")]
        hs = score(hold_scored)
        lines.extend(
            [
                "",
                "## Holdout sample",
                "",
                f"- n: **{hs['n']}**",
                f"- right/wrong: **{hs['right']}** / **{hs['wrong']}**",
                (
                    f"- precision: **{hs['precision']:.1%}**"
                    if hs["precision"] is not None
                    else "- precision: n/a"
                ),
                "",
            ]
        )

    print("Counting corpus statuses…", flush=True)
    corpus, ungrounded_reasons, oor_examples = corpus_status_counts(ag)
    lines.extend(
        [
            "## Corpus status counts",
            "",
            "| status | n |",
            "|---|---:|",
        ]
    )
    for k, n in corpus.most_common():
        lines.append(f"| `{k}` | {n} |")
    lines.extend(
        [
            "",
            "### Ungrounded reasons",
            "",
            "| reason | n |",
            "|---|---:|",
        ]
    )
    for k, n in ungrounded_reasons.most_common(15):
        lines.append(f"| `{k}` | {n} |")
    lines.extend(
        [
            "",
            "### out_of_registry top mentions",
            "",
        ]
    )
    for mention, n in oor_examples.most_common(15):
        lines.append(f"- {n}× «{mention}»")
    lines.append("")
    REPORT_PATH.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
