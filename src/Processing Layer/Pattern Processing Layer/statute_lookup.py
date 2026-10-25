"""
Statute lookup (evidence family ``lookup``) for CaseLinker 3.0.

When a press release cites a federal statute and a duration with no imposed or
exposure cue equals that statute's mandatory minimum or statutory maximum, the
duration is statutory exposure, not a sentence. Abstains everywhere else.

Bounds are first-offense penalties from the U.S. Code (months).
"""

from __future__ import annotations

import re
from typing import Dict, List

LOOKUP_VERSION = "usc_bounds_2024"

# (title, section) → (label, min_months, max_months); None max = life.
FEDERAL_BOUNDS: Dict[tuple, tuple] = {
    ("18", "2251"): ("production of CSAM", 180, 360),
    ("18", "2251A"): ("selling or buying of children", 360, None),
    ("18", "2252"): ("receipt/distribution of CSAM", 60, 240),
    ("18", "2252A"): ("receipt/distribution of CSAM", 60, 240),
    ("18", "2422"): ("coercion and enticement", 120, None),
    ("18", "2423"): ("transportation of a minor", 120, None),
    ("18", "1591"): ("sex trafficking of children", 120, None),
    ("18", "1470"): ("obscene material to a minor", 0, 120),
    ("18", "2260"): ("production for importation", 180, 360),
}

_CITATION_RE = re.compile(
    r"\b(18)\s*U\.?\s*S\.?\s*C\.?\s*(?:A\.?\s*)?(?:§+|Sections?|Sec\.?)?\s*(\d{3,4}A?)\b",
    re.IGNORECASE,
)


def cited_statutes(text: str) -> List[tuple]:
    out = []
    for m in _CITATION_RE.finditer(text):
        key = (m.group(1), m.group(2).upper())
        if key in FEDERAL_BOUNDS and key not in out:
            out.append(key)
    return out


def statute_assertions(text: str, sentence_candidates: List[Dict], kind_of) -> List[Dict]:
    """
    ``sentence_candidates``: regex sentence assertions (spans); ``kind_of(s, e)``:
    the gate's clause kind. Emits exposure only for cue-less durations.
    """
    statutes = cited_statutes(text)
    if not statutes:
        return []
    out = []
    for cand in sentence_candidates:
        months = (cand.get("extras") or {}).get("months")
        if months is None or kind_of(cand["span_start"], cand["span_end"]) != "unknown":
            continue
        for key in statutes:
            label, lo, hi = FEDERAL_BOUNDS[key]
            if months in (lo, hi):
                out.append({
                    "field": "sentence",
                    "method": "statute_lookup",
                    "method_version": LOOKUP_VERSION,
                    "value": cand["value"],
                    "role": "exposure",
                    "span_start": cand["span_start"],
                    "span_end": cand["span_end"],
                    "confidence": 0.8,
                    "extras": {
                        "statute": f"{key[0]} U.S.C. {key[1]}",
                        "statute_label": label,
                        "bound": "minimum" if months == lo else "maximum",
                    },
                })
                break
    return out
