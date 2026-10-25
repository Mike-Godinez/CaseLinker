"""Case-level prosecuting jurisdiction, derived at read time and never stored (#29).

``federal`` / ``state`` / ``unknown`` from the source and the release's prosecutor,
court and charging language. Investigating agencies are not used: FBI, HSI and
NCMEC appear on state prosecutions all the time. Both or neither → ``unknown``;
unknown is never folded into either side. ``basis`` lists signal names only.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

JURISDICTIONS = ("federal", "state", "unknown")

NON_US_SOURCES = frozenset({
    "NZ DIA", "BRAZIL PF", "SCOTLAND POLICE", "EUROPOL", "NBI", "AFP", "NCA", "QPS", "GARDA", "ALERT ICE",
})
DOJ_USAO_SOURCES = frozenset({"DOJ SAFE CHILDHOOD", "DOJ CEOS", "DOJ ARCHIVES", "DOJ AI CSAM"})

_FEDERAL = {
    "us_district_court": re.compile(r"\b(?:U\.\s?S\.|United\s+States)\s+District\s+(?:Court|Judge)\b", re.I),
    "us_attorney": re.compile(
        r"\bAssistant\s+(?:U\.\s?S\.|United\s+States)\s+Attorney\b|\b(?:U\.\s?S\.|United\s+States)\s+Attorney['’]s\s+Office\b", re.I
    ),
    "federal_grand_jury": re.compile(r"\bfederal\s+grand\s+jury\b", re.I),
    "federal_prison": re.compile(r"\bfederal\s+prison\b", re.I),
    "usc_citation": re.compile(r"\b\d+\s+U\.\s?S\.\s?C\.?", re.I),
}
_STATE = {
    # Apostrophe required and not "United States Attorney" / "U.S. Attorney".
    "states_attorney": re.compile(r"(?<!United\s)(?<!U\.S\.\s)\bState['’]s\s+Attorney\b", re.I),
    "district_attorney": re.compile(r"\bDistrict\s+Attorney\b", re.I),
    "commonwealths_attorney": re.compile(r"\bCommonwealth['’]s\s+Attorney\b", re.I),
    "state_trial_court": re.compile(r"(?<!U\.S\.\s)(?<!Federal\s)\b(?:Superior|Circuit)\s+Court\b|\bCourt\s+of\s+Common\s+Pleas\b", re.I),
    "state_prison": re.compile(r"\bstate\s+prison\b", re.I),
    "penal_code": re.compile(r"\bPenal\s+Code\b", re.I),
}
_MILITARY = re.compile(r"\bcourt[-\s]martial\b", re.I)


def _case_text(case: Dict[str, Any]) -> str:
    text = case.get("case_text")
    if isinstance(text, str) and text:
        return text
    raw = case.get("raw_data")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raw = None
    return str((raw or {}).get("case_text") or "") if isinstance(raw, dict) else ""


def derive_jurisdiction(case: Dict[str, Any]) -> Dict[str, Any]:
    """``{"jurisdiction": federal|state|unknown, "jurisdiction_basis": [signal names]}``."""
    source = str(case.get("source") or "").strip().upper()
    if source in NON_US_SOURCES:
        return {"jurisdiction": "unknown", "jurisdiction_basis": ["non_us_source"]}
    text = _case_text(case)
    if _MILITARY.search(text):
        return {"jurisdiction": "unknown", "jurisdiction_basis": ["military_court"]}
    federal: List[str] = ["doj_usao_source"] if source in DOJ_USAO_SOURCES else []
    federal += [name for name, rx in _FEDERAL.items() if rx.search(text)]
    state = [name for name, rx in _STATE.items() if rx.search(text)]
    if federal and not state:
        label = "federal"
    elif state and not federal:
        label = "state"
    else:
        label = "unknown"
    basis = [f"federal:{n}" for n in federal] + [f"state:{n}" for n in state]
    return {"jurisdiction": label, "jurisdiction_basis": basis or ["no_signal"]}
