"""
Rules distilled from reviewed LLM drafts.

The model proposes one regex. Validation checks it against the quotes a reviewer
already confirmed. Nothing runs until that rule is committed in ``APPROVED``
below. An approved rule is ordinary deterministic code: method ``compiled_rule``,
family ``surface_pattern``, same span gate as every other detector.

Proposals are written under ``config/compiled_rules/proposed/`` (local, not
shipped). Approving one means committing it here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

APPROVED: List[Dict[str, Any]] = [
    # Approved compiled rules. Each dict is a regex a reviewer committed.
    # A proposal does not run until its dict is added to this list.
]

_PROPOSALS = Path(__file__).resolve().parents[3] / "config" / "compiled_rules" / "proposed"
_MAX_REGEX = 240
_BROAD = re.compile(
    r"^\^?(?:\\d\+|\\w\+|\.\*|\.\+|\\s\+|\\D\+|\\S\+)\+?\$?$",
    re.IGNORECASE,
)
PROMPT_ID = "llm_rule_draft_v1"


def assertions_for(text: str, doc_kind: str, rules: Optional[Sequence[Dict]] = None) -> List[Dict]:
    """Raw assertions for approved rules whose document_kinds include doc_kind."""
    out: List[Dict] = []
    for rule in APPROVED if rules is None else rules:
        kinds = tuple(rule.get("document_kinds") or ("press_release",))
        if doc_kind not in kinds:
            continue
        cre = re.compile(rule["regex"], re.IGNORECASE)
        group = int(rule.get("group") or 1)
        for match in cre.finditer(text or ""):
            if match.lastindex is None or group > match.lastindex or match.group(group) is None:
                continue
            start, end = match.span(group)
            out.append({
                "field": rule["field"],
                "method": "compiled_rule",
                "method_version": rule["id"],
                "value": str(match.group(group)).strip(),
                "role": rule["role"],
                "span_start": start,
                "span_end": end,
                "confidence": float(rule.get("confidence") or 0.85),
                "extras": {"rule_id": rule["id"], "pattern": "compiled_rule"},
            })
    return out


def validate_proposal(
    proposal: Dict[str, Any],
    positives: Sequence[str],
    negatives: Sequence[str] = (),
) -> Optional[str]:
    """None when the regex earns the positives and misses the negatives."""
    regex = str(proposal.get("regex") or "")
    if not regex or len(regex) > _MAX_REGEX:
        return "regex missing or longer than 240 characters"
    if _BROAD.match(regex):
        return "regex is too broad"
    if not positives:
        return "at least one positive quote is required"
    try:
        cre = re.compile(regex, re.IGNORECASE)
    except re.error as exc:
        return f"regex does not compile: {exc}"
    group = int(proposal.get("group") or 1)
    if cre.groups < group:
        return "regex needs a capture group around the value"
    field = proposal.get("field")
    for quote in positives:
        match = cre.search(quote)
        if match is None or match.lastindex is None or match.group(group) is None:
            return f"missed a confirmed quote: {quote[:80]}"
        if field == "age" and not re.fullmatch(r"\d{1,3}|[a-z]+(?:[- ][a-z]+)?", match.group(group).strip(), re.I):
            return f"age capture is not a number or number-word: {match.group(group)!r}"
    for quote in negatives:
        if cre.search(quote):
            return f"matched a quote it must leave alone: {quote[:80]}"
    return None


def proposal_dict(
    *,
    rule_id: str,
    field: str,
    role: str,
    regex: str,
    document_kinds: Sequence[str],
    positives: Sequence[str],
    negatives: Sequence[str] = (),
    rationale: str = "",
    group: int = 1,
) -> Dict[str, Any]:
    return {
        "id": rule_id,
        "field": field,
        "role": role,
        "regex": regex,
        "group": group,
        "confidence": 0.85,
        "document_kinds": list(document_kinds),
        "positives": list(positives),
        "negatives": list(negatives),
        "rationale": rationale,
        "prompt_id": PROMPT_ID,
        "approved": False,
    }


def propose_rule(
    *,
    rule_id: str,
    field: str,
    role: str,
    positives: Sequence[str],
    negatives: Sequence[str] = (),
    document_kinds: Sequence[str] = ("press_release",),
    generate: Optional[Callable[[str], str]] = None,
    regex: Optional[str] = None,
    rationale: str = "",
) -> Dict[str, Any]:
    """
    Draft one rule and validate it. Returns the proposal, or ``{ok: False, reason}``.

    ``regex`` skips the model (a reviewer already has a pattern). ``generate``
    receives the prompt and returns the model's text. Neither path approves.
    """
    if regex is None:
        if generate is None:
            return {"ok": False, "reason": "pass regex= or generate="}
        raw = generate(_prompt(field, role, positives, negatives))
        try:
            drafted = json.loads(raw)
        except json.JSONDecodeError:
            return {"ok": False, "reason": "model did not return JSON"}
        regex = str(drafted.get("regex") or "")
        rationale = str(drafted.get("rationale") or rationale)
        rule_id = str(drafted.get("id") or rule_id)
    proposal = proposal_dict(
        rule_id=rule_id, field=field, role=role, regex=regex,
        document_kinds=document_kinds, positives=positives, negatives=negatives,
        rationale=rationale,
    )
    reason = validate_proposal(proposal, positives, negatives)
    if reason:
        return {"ok": False, "reason": reason, "proposal": proposal}
    proposal["ok"] = True
    return proposal


def write_proposal(proposal: Dict[str, Any], directory: Optional[Path] = None) -> Path:
    """Write an unapproved proposal. These files are local and are not loaded."""
    dest = directory or _PROPOSALS
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{proposal['id']}.json"
    path.write_text(json.dumps(proposal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _prompt(field: str, role: str, positives: Sequence[str], negatives: Sequence[str]) -> str:
    pos = "\n".join(f"- {q}" for q in positives)
    neg = "\n".join(f"- {q}" for q in negatives) or "- (none)"
    return (
        "Write one Python regular expression for a CaseLinker extraction rule.\n"
        f"Field: {field}\nRole: {role}\n"
        "The pattern must contain one capturing group around the value itself "
        "(the age number or number-word, the duration, or the tip token).\n"
        "It must match every positive quote and must not match any negative quote.\n"
        'Return only JSON: {"id": "snake_case", "regex": "...", "rationale": "one sentence"}\n\n'
        f"POSITIVES:\n{pos}\n\nNEGATIVES:\n{neg}\n"
    )
