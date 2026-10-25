"""Imposed-only sentencing stats over the persisted sentence-kind buckets (#29).

Reads the latest ``sentence`` resolution of each case's current extraction run
(``final_value`` buckets: imposed / exposure / supervised_release / probation /
fine / custody / prior). The legacy ``prosecution_outcome.sentences`` list is
never read: it flattens the kinds. Each case gets exactly one outcome; anything
that cannot honestly be reduced to one imposed prison term is dropped with a
named reason and counted.
"""

from __future__ import annotations

import importlib.util
import re
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SPAN_GATE = _REPO_ROOT / "src" / "Processing Layer" / "field_assertions" / "span_gate.py"

_spec = importlib.util.spec_from_file_location("caselinker_span_gate", _SPAN_GATE)
sg = importlib.util.module_from_spec(_spec)
assert _spec.loader
_spec.loader.exec_module(sg)

INTERPRETATION_KIND = "imposed_sentence_summary"
INTERPRETATION_NOTE = (
    "Descriptive summary of extracted imposed terms only; not a validated disparity or "
    "sentencing-severity claim. Unit is the release (case), not the defendant; value is the "
    "longest single imposed custodial term, nominal as written. Life is counted, not given "
    "months. Dropped and counted, never guessed: spans the resolver left unlabelled or under "
    "review (kind_unknown), multi-defendant, split/suspended or indeterminate terms, imposed "
    "spans without sentencing context, exposure-only (statutory_max) and not-yet-sentenced "
    "cases. 'pending' is a heuristic from booking_status. Death sentences are not extracted."
)

USED = ("custodial", "life", "non_custodial")
DROP_REASONS = (
    "not_found",
    "kind_unknown",
    "unparseable_term",
    "doubtful_imposed_context",
    "multi_defendant_suspected",
    "split_or_suspended_term",
    "indeterminate_term",
    "statutory_max",
    "pending",
    "no_sentence",
)
PENDING_STATUSES = frozenset({"arrested", "booked", "charged", "indicted", "pleaded_guilty", "convicted"})
_WINDOW = 150

_MULTI_DEFENDANT_RE = re.compile(
    r"\bco-?defendants?\b|\brespectively\b|\beach\s+(?:was\s+|were\s+)?sentenced\b"
    r"|\bboth\s+(?:men|women|defendants)\b|\bthe\s+(?:two|three|four|five)\s+(?:men|women|defendants|brothers)\b",
    re.IGNORECASE,
)
_SPLIT_RE = re.compile(
    r"\bsuspended\b|\ball\s+but\b|\bactively\s+serve\b|\bparole\s+eligib|\beligible\s+for\s+parole\b"
    r"|\bbefore\s+(?:being\s+)?eligible\b|\bminimum\s+of\b|\bhome\s+(?:confinement|detention)\b|\bwork\s+release\b"
    r"|\bcredit\s+for\b",
    re.IGNORECASE,
)
# A resolver-labelled imposed span needs sentencing context: a sentencing verb before it or a
# custody noun right after it ("may one day wear the uniform" is not a term), and no statutory
# wording just before it ("mandatory minimum period of imprisonment of 15 years").
_SENTENCING_VERB_RE = re.compile(r"\bsentenc|\bto\s+serve\b|\bwas\s+given\b|\breceived\b", re.IGNORECASE)
_CUSTODY_AFTER_RE = re.compile(
    r"^\W{0,3}(?:of\s+)?(?:in\s+(?:a\s+)?(?:federal\s+|state\s+|county\s+)?(?:prison|jail|custody)|imprisonment|incarceration|behind\s+bars)",
    re.IGNORECASE,
)
_JAILED_FOR_RE = re.compile(r"\b(?:jailed|imprisoned|locked\s+up)\s+(?:for\s+)?$|\bimposed\s+(?:a|an|the)?\s*$", re.IGNORECASE)
_STATUTORY_BEFORE_RE = re.compile(
    r"\bmandatory\s+minimum\b|\bmaximum\b|\bminimum\s+(?:penalty|sentence|term)\b|\bfaces?\b|\bpunishable\b|\bup\s+to\s*$",
    re.IGNORECASE,
)
_VERB_WINDOW, _STATUTORY_WINDOW = 250, 60


def _imposed_context_ok(text: str, start: int, end: int) -> bool:
    if _STATUTORY_BEFORE_RE.search(text[max(0, start - _STATUTORY_WINDOW) : start]):
        return False
    return bool(
        _SENTENCING_VERB_RE.search(text[max(0, start - _VERB_WINDOW) : start])
        or _JAILED_FOR_RE.search(text[max(0, start - 25) : start])
        or _CUSTODY_AFTER_RE.search(text[end : end + 40])
    )
_INDETERMINATE_LIFE_RE = re.compile(r"\bup\s+to\s+life\b|\b(?:years?|yrs?|months?)\s+to\s+life\b", re.IGNORECASE)


def parse_term(value: str) -> Dict[str, Any]:
    """{'kind': 'months'|'life'|'indeterminate'|'unparseable', 'months', 'list_form'}."""
    v = sg.normalize_surface(str(value)).strip()
    if _INDETERMINATE_LIFE_RE.search(v):
        return {"kind": "indeterminate", "months": None, "list_form": False}
    if sg.LIFE_RE.fullmatch(v) or v.lower() in ("life", "lifetime"):
        return {"kind": "life", "months": None, "list_form": False}
    m = sg.DURATION_RE.fullmatch(v)
    if not m:
        return {"kind": "unparseable", "months": None, "list_form": False}
    months = sg.duration_months(m)
    if months is None:
        return {"kind": "unparseable", "months": None, "list_form": False}
    if m.group("low") is None:
        return {"kind": "months", "months": months, "list_form": False}
    connector = v[m.end("low"):m.start("n")].strip().lower()
    if connector != "and":
        return {"kind": "indeterminate", "months": None, "list_form": False}
    # "360 and 24 months" is a list of two terms, not a range: duration_months returns the second.
    low = sg.parse_number(m.group("low")) or 0
    unit = m.group("unit").lower().rstrip("s")
    low_months = low * sg._UNIT_MONTHS.get(unit, 0)
    return {"kind": "months", "months": max(months, low_months), "list_form": True}


def _kind_unknown_detail(resolution: Optional[Dict[str, Any]]) -> Optional[str]:
    if not resolution:
        return "no_current_resolution"
    if not str(resolution.get("rule_set_version") or "").startswith("resolve_v3"):
        return "old_rule_set"
    if resolution.get("status") in ("needs_review", "disagreement"):
        return "review_status"
    final = resolution.get("final_value") or {}
    disagreement = resolution.get("disagreement") or {}
    if final.get("contested") or disagreement.get("contested") or disagreement.get("unknown_spans"):
        return "unlabelled_span"
    return None


def _near_imposed(text: str, assertions: Sequence[Dict[str, Any]], rx: re.Pattern) -> bool:
    for a in assertions:
        s, e = a.get("span_start"), a.get("span_end")
        if a.get("role") != "imposed" or s is None or e is None:
            continue
        if rx.search(text[max(0, s - _WINDOW) : e + _WINDOW]):
            return True
    return False


def classify_case(
    case: Optional[Dict[str, Any]],
    resolution: Optional[Dict[str, Any]],
    assertions: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    """One outcome (used) or drop reason per case, first match wins."""
    if case is None:
        return {"outcome": None, "reason": "not_found"}
    detail = _kind_unknown_detail(resolution)
    if detail:
        return {"outcome": None, "reason": "kind_unknown", "detail": detail}
    final = (resolution or {}).get("final_value") or {}
    imposed = [str(v) for v in final.get("imposed") or []]
    text = str(case.get("case_text") or "")
    if imposed:
        terms = [parse_term(v) for v in imposed]
        base = {"imposed": imposed, "list_form": any(t["list_form"] for t in terms)}
        if any(t["kind"] == "unparseable" for t in terms):
            return {**base, "outcome": None, "reason": "unparseable_term"}
        wanted = {sg.normalize_surface(v).strip().lower() for v in imposed}
        spans = [
            a for a in assertions
            if a.get("role") == "imposed" and a.get("span_start") is not None
            and sg.normalize_surface(str(a.get("value"))).strip().lower() in wanted
        ]
        if not spans or any(not _imposed_context_ok(text, a["span_start"], a["span_end"]) for a in spans):
            return {**base, "outcome": None, "reason": "doubtful_imposed_context"}
        defendants = {(a.get("extras") or {}).get("defendant") for a in assertions if a.get("role") == "imposed"}
        if len(defendants - {None, ""}) > 1 or _near_imposed(text, assertions, _MULTI_DEFENDANT_RE):
            return {**base, "outcome": None, "reason": "multi_defendant_suspected"}
        months = [t["months"] for t in terms if t["kind"] == "months"]
        if _near_imposed(text, assertions, _SPLIT_RE) or (len(months) > 1 and min(months) > 0 and max(months) / min(months) >= 2):
            return {**base, "outcome": None, "reason": "split_or_suspended_term"}
        if any(t["kind"] == "indeterminate" for t in terms):
            return {**base, "outcome": None, "reason": "indeterminate_term"}
        if any(t["kind"] == "life" for t in terms):
            return {**base, "outcome": "life", "reason": None, "months": None}
        return {**base, "outcome": "custodial", "reason": None, "months": max(months), "multiple_terms": len(imposed) > 1}
    if final.get("probation") or final.get("fine"):
        return {"outcome": "non_custodial", "reason": None}
    if final.get("exposure"):
        return {"outcome": None, "reason": "statutory_max"}
    status = (case.get("prosecution_outcome") or {}).get("status") or (case.get("prosecution_outcome") or {}).get("booking_status")
    if status in PENDING_STATUSES:
        return {"outcome": None, "reason": "pending", "booking_status": status}
    return {"outcome": None, "reason": "no_sentence"}


def summarize(results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    dropped = {r: 0 for r in DROP_REASONS}
    detail: Dict[str, int] = {}
    outcomes = {o: 0 for o in USED}
    months: List[float] = []
    flags = {"multiple_imposed_terms": 0, "list_form": 0}
    for res in results.values():
        if res.get("outcome"):
            outcomes[res["outcome"]] += 1
            if res.get("months") is not None:
                months.append(float(res["months"]))
            flags["multiple_imposed_terms"] += bool(res.get("multiple_terms"))
            flags["list_form"] += bool(res.get("list_form"))
        else:
            dropped[res["reason"]] += 1
            if res.get("detail"):
                detail[res["detail"]] = detail.get(res["detail"], 0) + 1
    stats = {"n": len(months)}
    if months:
        stats.update(
            median=statistics.median(months),
            mean=round(statistics.fmean(months), 1),
            min=min(months),
            max=max(months),
        )
    n_used = sum(outcomes.values())
    return {
        "n_requested": len(results),
        "n_used": n_used,
        "n_dropped": len(results) - n_used,
        "dropped": dropped,
        "kind_unknown_detail": detail,
        "outcomes": outcomes,
        "custodial_months": stats,
        "flags": flags,
        "cases": [{"case_id": cid, **res} for cid, res in results.items()],
        "interpretation_kind": INTERPRETATION_KIND,
        "interpretation_note": INTERPRETATION_NOTE,
    }


def sentencing_stats_payload(case_ids: Sequence[str]) -> Dict[str, Any]:
    """Load only the requested cases from the local DB and summarize (MCP-local)."""
    from caselinker_mcp.facet_local import CaseStorage, _db_path

    ids = list(dict.fromkeys(c.strip() for c in case_ids if c and c.strip()))
    db = _db_path()
    if not db.exists():
        raise FileNotFoundError(f"Database not found: {db}")
    storage = CaseStorage(str(db))
    cases = {c["id"]: c for c in storage.get_cases_by_ids(ids, include_raw_data=True) or []}
    results: Dict[str, Dict[str, Any]] = {}
    for cid in ids:
        case = cases.get(cid)
        if case is None:
            results[cid] = classify_case(None, None)
            continue
        got = storage.get_case_assertions(cid, field="sentence")
        results[cid] = classify_case(case, (got.get("resolutions") or {}).get("sentence"), got.get("assertions") or [])
    return summarize(results)
