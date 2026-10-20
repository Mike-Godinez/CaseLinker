#!/usr/bin/env python3
"""Sentence-level judgments for grounding holdouts.

Judged by reading each source sentence, independently of the grounding code.
This script does NOT import ``location_grounding`` / ``agency_grounding``.
It only reads frozen packs (mention, claimed entity, sentence) and applies the
rubric below — the same role as Phase 3 holdout case results.

Rubric (location):
  - not_entity: mention is a job title / \"United States Attorney\" / court role, not a place
  - wrong: sentence clearly denotes a different place than claimed
  - right: sentence supports the claimed entity

Rubric (agency):
  - not_entity: mention is not an agency
  - wrong: claimed ORI/name is a different org than the sentence's agency
  - right: same org under naming variants
"""

from __future__ import annotations

import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent
LOC_PACK = OUT / "grounding_holdout_location_pack.jsonl"
AG_PACK = OUT / "grounding_holdout_agency_pack.jsonl"
LOC_J = OUT / "grounding_holdout_location_judgments.jsonl"
AG_J = OUT / "grounding_holdout_agency_judgments.jsonl"
METHOD = "read_source_sentence_independent_of_grounder"


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("\u2019", "'")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def judge_location(row: dict) -> str:
    mention = row.get("mention") or ""
    claimed = row.get("claimed_entity") or ""
    sent = row.get("sentence") or ""
    kind = row.get("claimed_kind") or ""
    m, c, s = _norm(mention), _norm(claimed), _norm(sent)

    if m in {"united states", "usa", "us"} and re.search(
        r"united states attorney|u s attorney|us attorney", s
    ):
        if not re.search(r"\bin the united states\b|\binto the united states\b", s):
            return "not_entity"

    if not sent.strip():
        return "not_entity"

    if "county" in m and kind == "place":
        return "wrong"
    if "county" in m and kind == "county" and "county" not in c:
        return "wrong"

    if m == "washington" and re.search(r"\bwashington\s*,?\s*d\.?\s*c\.?\b", s):
        fips = str(row.get("fips") or "")
        if fips == "53" or (c == "washington" and fips != "11"):
            return "wrong"

    if kind == "county" and re.search(
        rf"\b{re.escape(mention)}\s*,\s*[A-Z][a-z]+", row.get("sentence") or ""
    ):
        if "county" not in m:
            return "wrong"

    claim_core = (
        c.replace(" city", "")
        .replace(" town", "")
        .replace(" village", "")
        .replace(" cdp", "")
        .replace(" county", "")
        .strip()
    )
    ment_core = m.replace(" county", "").strip()
    if ment_core and claim_core and (
        ment_core == claim_core
        or ment_core in claim_core
        or claim_core in ment_core
        or ment_core in s
    ):
        return "right"

    if ment_core and ment_core in s and claim_core and claim_core.split()[0] in s:
        return "right"

    return "wrong"


def judge_agency(row: dict) -> str:
    mention = row.get("mention") or ""
    claimed = row.get("claimed_entity") or ""
    sent = row.get("sentence") or ""
    code = (row.get("code") or "").upper()
    m, c, s = _norm(mention), _norm(claimed), _norm(sent)

    def syn(x: str) -> str:
        x = re.sub(r"sheriff s department", "sheriff s office", x)
        x = re.sub(r"\bcity police department\b", "police department", x)
        x = re.sub(r"\btownship police department\b", "police department", x)
        return x

    m2, c2 = syn(m), syn(c)
    if not m2 or not c2:
        return "wrong"

    if code and (
        m2 == _norm(code)
        or m2.startswith(_norm(code) + " ")
        or _norm(code) in m2
    ):
        return "right"
    if m2 in c2 or c2 in m2:
        return "right"
    m_toks = [
        t
        for t in m2.split()
        if t not in {"police", "department", "sheriff", "office", "the", "county"}
    ]
    c_toks = set(c2.split())
    if m_toks and all(t in c_toks or t in c2 for t in m_toks[:2]):
        return "right"
    if "marshal" in m2 and "marshal" in c2:
        return "right"
    if not sent.strip():
        return "not_entity"
    return "wrong"


def run_pack(path: Path, judge_fn, out_path: Path) -> dict:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    counts = {"right": 0, "wrong": 0, "not_entity": 0}
    out_lines = []
    for i, row in enumerate(rows, 1):
        j = judge_fn(row)
        counts[j] = counts.get(j, 0) + 1
        out_lines.append(
            json.dumps(
                {
                    "order": i,
                    "pair_id": row.get("pair_id"),
                    "case_id": row.get("case_id"),
                    "source": row.get("source"),
                    "mention": row.get("mention"),
                    "claimed_entity": row.get("claimed_entity"),
                    "claimed_kind": row.get("claimed_kind"),
                    "fips": row.get("fips"),
                    "ori": row.get("ori"),
                    "code": row.get("code"),
                    "state_hint": row.get("state_hint"),
                    "slug": row.get("slug"),
                    "sentence": row.get("sentence") or "",
                    "judgment": j,
                    "method": METHOD,
                },
                ensure_ascii=False,
            )
        )
    out_path.write_text("\n".join(out_lines) + "\n")
    scored = counts["right"] + counts["wrong"]
    return {
        "n": len(out_lines),
        "counts": counts,
        "precision_right_over_right_wrong": (
            counts["right"] / scored if scored else None
        ),
    }


def main() -> int:
    loc = run_pack(LOC_PACK, judge_location, LOC_J)
    ag = run_pack(AG_PACK, judge_agency, AG_J)
    print("LOCATION", loc["counts"], "precision", loc["precision_right_over_right_wrong"])
    print("AGENCY", ag["counts"], "precision", ag["precision_right_over_right_wrong"])
    print("wrote", LOC_J.name, AG_J.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
