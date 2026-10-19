"""
Resolution over stored field assertions (CaseLinker 3.0, rule set ``resolve_v3.0``).

Visible, versioned, and re-runnable: resolution reads assertions and never edits
them. Rules, per mention (one span of the original text):

1. ``human`` verdicts win outright for their (case, value).
2. ``unknown`` is abstention, never a competing role.
3. Votes are counted by evidence *family*, not by method. A family that asserts
   two different roles for the same mention contradicts itself and abstains.
   Victim and perpetrator on that same mention block a final from any family:
   the age stays in review.
4. Two families asserting different roles for the same mention veto it: the
   mention is contested and never finalizes.
5. One typed role from ≥2 families → agreed; from one family at confidence ≥0.7
   → resolved; otherwise → needs review. Weak votes (<0.7) that share one
   ``extras.weak`` reason across families are one observation, not agreement.
6. Settled mentions finalize even when other mentions stay contested (partial).
7. No numeric thresholds anywhere. Ages without role evidence never finalize.
8. A value settled as victim at one mention and excluded *or contested* as a
   decoy / claimed / depicted age at another stays contested.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

RULE_SET_VERSION = "resolve_v3.0"

FAMILY = {
    "regex": "surface_pattern",
    "spacy_token": "surface_pattern",
    "victim_age_gate": "surface_pattern",
    "spacy_dep": "dependency",
    "ner_stanza": "ner",
    "statute_lookup": "lookup",
    "temporal": "temporal",
    "llm": "llm",
    "human": "human",
    "compiled_rule": "surface_pattern",
}
SINGLE_FAMILY_MIN_CONFIDENCE = 0.7

FINAL_AGE_ROLES = ("victim", "perpetrator")
BLOCKED_AGE_ROLES = (
    "statutory_threshold", "decoy", "claimed", "depicted_in_material", "prior_case",
    "adult_crime_victim", "not_age", "excluded",
)
# A value settled as a victim at one mention and as a persona/depicted age at another is almost
# always the persona echoed ("attempting to entice a 13-year-old child" in a sting) or a
# material age that also got a weak victim cue: contest, don't finalize.
CONFLICTING_WITH_VICTIM = ("decoy", "claimed", "depicted_in_material")
PERSONA_ROLES = CONFLICTING_WITH_VICTIM  # alias kept for callers/tests
SENTENCE_BUCKETS = ("imposed", "exposure", "supervised_release", "probation", "fine", "custody", "prior")


def family_of(assertion: Dict) -> str:
    return assertion.get("family") or FAMILY.get(assertion.get("method"), assertion.get("method") or "unknown")


def _aid(a: Dict) -> Optional[int]:
    """Stored row id; before storage, the assertion's negative ``seq`` placeholder."""
    return a["id"] if a.get("id") is not None else a.get("seq")


def _result(field: str, status: str, final: Any, rule_id: str, winning: Iterable[Dict] = (),
            disagreement: Optional[Dict] = None, review: Optional[List[Dict]] = None) -> Dict:
    winning = list(winning)
    return {
        "field": field,
        "status": status,
        "final_value": final,
        "rule_id": rule_id,
        "rule_set_version": RULE_SET_VERSION,
        "winning_methods": sorted({a["method"] for a in winning}),
        "winning_assertion_ids": sorted({i for i in (_aid(a) for a in winning) if i is not None}),
        "disagreement": disagreement or {},
        "review": review or [],
    }


def _vote(items: List[Dict]) -> Dict[str, Any]:
    """Family votes for one mention: settled role, contest, or abstention."""
    by_family: Dict[str, Dict[str, List[Dict]]] = defaultdict(lambda: defaultdict(list))
    for a in items:
        role = a.get("role") or "unknown"
        if role != "unknown":
            by_family[family_of(a)][role].append(a)
    votes: Dict[str, str] = {}
    self_contradictions = []
    for fam, roles in by_family.items():
        if len(roles) == 1:
            votes[fam] = next(iter(roles))
        else:
            self_contradictions.append({"family": fam, "roles": sorted(roles)})
    distinct = sorted(set(votes.values()))
    out: Dict[str, Any] = {"self_contradictions": self_contradictions}
    # "jailing of a 22-year-old student": the surface family has both a victim noun
    # and a defendant cue, so it abstains. Another family may still have a clean
    # victim vote. Both cues on one mention means the age is not a final.
    if any(
        "victim" in sc["roles"] and "perpetrator" in sc["roles"]
        for sc in self_contradictions
    ):
        out["state"] = "unknown"
        return out
    if len(distinct) > 1:
        out["state"] = "contested"
        out["roles"] = {r: sorted(f for f, v in votes.items() if v == r) for r in distinct}
        return out
    if not distinct:
        out["state"] = "unknown"
        return out
    role = distinct[0]
    fams = sorted(f for f, v in votes.items() if v == role)
    support = [a for f in fams for a in by_family[f][role]]
    best = max((a.get("confidence") or 0) for a in support)
    out["role"], out["families"], out["support"] = role, fams, support
    # Weak votes that share one weakness reason (regex and spaCy both reading the same bare child
    # noun) are the same observation twice, not agreement; an LLM or NER read of the window is not.
    weak_reasons = {(a.get("extras") or {}).get("weak") for a in support}
    same_weak_basis = best < SINGLE_FAMILY_MIN_CONFIDENCE and len(weak_reasons) == 1 and None not in weak_reasons
    if len(fams) >= 2 and not same_weak_basis:
        out["state"] = "agreed"
    elif best >= SINGLE_FAMILY_MIN_CONFIDENCE:
        out["state"] = "resolved"
    else:
        out["state"] = "weak"
    return out


def _mentions(assertions: List[Dict], field: str) -> Dict[Tuple[int, int], List[Dict]]:
    groups: Dict[Tuple[int, int], List[Dict]] = defaultdict(list)
    for a in assertions:
        if a.get("field") == field and a.get("span_ok") and a.get("span_start") is not None:
            groups[(a["span_start"], a["span_end"])].append(a)
    return dict(sorted(groups.items()))


# ---------------------------------------------------------------------------
# Ages
# ---------------------------------------------------------------------------

def _entity_key(a: Dict) -> Optional[str]:
    ent = ((a.get("extras") or {}).get("entity") or "").strip()
    toks = [t.strip(".,") for t in ent.split() if t.strip(".,") and t.strip(".,").lower() not in ("jr", "sr", "ii", "iii")]
    if not toks or not toks[-1][:1].isupper():
        return None
    return " ".join(toks)


def _collapse_perpetrators(perp_mentions: List[Tuple[int, Dict]]) -> List[Dict]:
    """One age per perpetrator entity; time-qualified ages ("then 27") are kept as other_ages."""
    entities: List[Dict] = []
    for value, vote in perp_mentions:
        support = vote["support"]
        name = next((k for k in (_entity_key(a) for a in support) if k), None)
        qualified = any((a.get("extras") or {}).get("time_qualifier") for a in support)
        target = None
        for ent in entities:
            if name and ent["entity"] and name.split()[-1] == ent["entity"].split()[-1]:
                a, b = name.split(), ent["entity"].split()
                if len(a) == 1 or len(b) == 1 or a[0] == b[0]:
                    target = ent
                    break
            if not name and value in ent["ages"]:
                target = ent
                break
        if target is None:
            target = {"entity": name, "ages": [], "qualified": []}
            entities.append(target)
        elif name and (not target["entity"] or len(name) > len(target["entity"])):
            target["entity"] = name
        target["ages"].append(value)
        target["qualified"].append(qualified)
    out = []
    for ent in entities:
        unqualified = [v for v, q in zip(ent["ages"], ent["qualified"]) if not q]
        age = unqualified[0] if unqualified else ent["ages"][0]
        out.append({
            "entity": ent["entity"],
            "age": age,
            "other_ages": sorted({v for v in ent["ages"] if v != age}),
        })
    return out


def resolve_age(assertions: List[Dict]) -> Dict:
    mentions = _mentions(assertions, "age")
    if not mentions:
        return _result("age", "empty", None, "no_assertions")

    human: Dict[int, List[Dict]] = defaultdict(list)
    for items in mentions.values():
        for a in items:
            if a.get("method") == "human":
                human[int(a["value"])].append(a)

    victims: Dict[int, List[Dict]] = defaultdict(list)
    perp_mentions: List[Tuple[int, Dict]] = []
    excluded: Set[Tuple[int, str]] = set()
    contested: Dict[str, Dict] = {}
    unresolved: List[Dict] = []
    self_contradictions: List[Dict] = []
    all_multi_family = True
    winning: List[Dict] = []

    for (s, e), items in mentions.items():
        value = int(items[0]["value"])
        if value in human:
            role = human[value][-1].get("role")
            if role == "victim":
                victims[value].extend(human[value])
            elif role == "perpetrator":
                perp_mentions.append((value, {"support": human[value], "families": ["human"]}))
            else:
                excluded.add((value, role or "excluded"))
            winning.extend(human[value])
            continue
        vote = _vote(items)
        for sc in vote["self_contradictions"]:
            self_contradictions.append({"value": value, "span": [s, e], **sc})
        state = vote["state"]
        if state == "contested":
            contested[f"{value}@{s}"] = {"value": value, "span": [s, e], "roles": vote["roles"]}
        elif state in ("agreed", "resolved"):
            role = vote["role"]
            if role in FINAL_AGE_ROLES:
                all_multi_family &= state == "agreed"
                winning.extend(vote["support"])
                if role == "victim":
                    victims[value].extend(vote["support"])
                else:
                    perp_mentions.append((value, vote))
            else:
                excluded.add((value, role))
        else:
            unresolved.append({"value": value, "span": [s, e], "state": state, "role": vote.get("role")})

    # A value settled as victim at one mention and perpetrator at another is contested.
    perp_values = {v for v, _ in perp_mentions}
    for value in sorted(set(victims) & perp_values):
        contested[f"{value}@value"] = {"value": value, "roles": {"victim": ["mention"], "perpetrator": ["mention"]}}
        victims.pop(value)
        perp_mentions = [(v, m) for v, m in perp_mentions if v != value]

    for value in sorted(v for v in victims if any((v, r) in excluded for r in CONFLICTING_WITH_VICTIM)):
        conflict = next(r for r in CONFLICTING_WITH_VICTIM if (value, r) in excluded)
        contested[f"{value}@persona"] = {
            "value": value, "roles": {"victim": ["mention"], conflict: ["mention"]},
        }
        victims.pop(value)
    # Same value settled as victim at one mention but *contested with* a persona role at another
    # ("undercover officer he believed was a 12-year-old girl" … "persona of a 12-year-old girl"):
    # the persona evidence was vetoed there, not refuted; the value stays contested.
    for value in sorted(victims):
        hit = next(
            (c for c in contested.values()
             if c.get("value") == value and any(r in CONFLICTING_WITH_VICTIM for r in (c.get("roles") or {}))),
            None,
        )
        if hit is None:
            continue
        conflict = next(r for r in CONFLICTING_WITH_VICTIM if r in hit["roles"])
        contested[f"{value}@persona"] = {
            "value": value, "roles": {"victim": ["mention"], conflict: ["mention"]},
        }
        victims.pop(value)

    settled_values = set(victims) | {v for v, _ in perp_mentions} | {v for v, _ in excluded}
    needs = [u for u in unresolved if u["value"] not in settled_values]
    perp_entities = _collapse_perpetrators(perp_mentions)
    final = {
        "victims": sorted(victims),
        "perpetrators": sorted({p["age"] for p in perp_entities}),
        "perpetrator_entities": perp_entities,
        "excluded": [{"age": v, "role": r} for v, r in sorted(excluded)],
        "contested": contested,
        "unresolved": needs,
    }
    disagreement = {"contested": contested, "self_contradictions": self_contradictions}
    review = [{"reason": "contested", **c} for c in contested.values()]
    review += [{"reason": f"age_{u['state']}", **u} for u in needs]
    has_final = bool(final["victims"] or final["perpetrators"])
    if has_final and not contested and not needs:
        status, rule = ("agreed", "family_agreement") if all_multi_family else ("resolved", "single_family_resolved")
    elif has_final:
        status, rule = "partial", "partial_finals"
    elif contested:
        status, rule = "disagreement", "conflict_veto"
    elif needs:
        status, rule = "needs_review", "no_role_evidence"
    else:
        status, rule = "resolved", "all_mentions_excluded"
    return _result("age", status, final, rule, winning, disagreement, review)


# ---------------------------------------------------------------------------
# Sentences
# ---------------------------------------------------------------------------

def _equivalent(a: Dict, b: Dict) -> bool:
    ea, eb = a.get("extras") or {}, b.get("extras") or {}
    if a.get("role") == "custody" or b.get("role") == "custody":
        return str(a.get("value")).lower() == str(b.get("value")).lower()
    if ea.get("amount") is not None or eb.get("amount") is not None:
        return ea.get("amount") == eb.get("amount")
    if ea.get("life") or eb.get("life"):
        return bool(ea.get("life")) and bool(eb.get("life"))
    ma, mb = ea.get("months"), eb.get("months")
    if ma is None or mb is None:
        return False
    if ea.get("approx") or eb.get("approx"):
        # "Over 7 Years" (84) ~ 90 months and "Nearly Six Years" (72) ~ 70 months: approximations
        # round in either direction, so one term within a year on either side is the same term.
        return abs(ma - mb) <= 12
    if ea.get("headline") != eb.get("headline"):
        return abs(ma - mb) < 12  # a headline rounds the body's exact term
    return abs(ma - mb) <= 1


def _representative(group: List[Dict]) -> Dict:
    """Court-precise first: months over years (2.x Fix A), exact over approximate."""
    def rank(a):
        ex = a.get("extras") or {}
        return (bool(ex.get("approx")), "month" not in str(a.get("value")).lower(), a.get("span_start") or 0)
    return min(group, key=rank)


def _dedupe(items: List[Dict]) -> List[List[Dict]]:
    groups: List[List[Dict]] = []
    for a in sorted(items, key=lambda x: x.get("span_start") or 0):
        for g in groups:
            if _equivalent(g[0], a) or _equivalent(_representative(g), a):
                g.append(a)
                break
        else:
            groups.append([a])
    return groups


def resolve_sentence(assertions: List[Dict]) -> Dict:
    mentions = _mentions(assertions, "sentence")
    if not mentions:
        return _result("sentence", "empty", None, "no_assertions")
    settled: Dict[str, List[Dict]] = defaultdict(list)
    contested: Dict[str, Dict] = {}
    unknown: List[Dict] = []
    winning: List[Dict] = []
    for (s, e), items in mentions.items():
        vote = _vote(items)
        if vote["state"] == "contested":
            contested[f"{items[0]['value']}@{s}"] = {"value": items[0]["value"], "span": [s, e], "roles": vote["roles"]}
        elif vote["state"] in ("agreed", "resolved") and vote["role"] in SENTENCE_BUCKETS:
            rep = dict(min(vote["support"], key=lambda a: a.get("method") != "regex"))
            rep["_support"] = vote["support"]
            settled[vote["role"]].append(rep)
        else:
            unknown.append({"value": str(items[0]["value"]), "span": [s, e]})

    final: Dict[str, Any] = {}
    for bucket in SENTENCE_BUCKETS:
        groups = _dedupe(settled.get(bucket, []))
        if bucket == "imposed":
            groups = _drop_derived_totals(groups)
        final[bucket] = []
        for g in groups:
            final[bucket].append(_representative(g)["value"])
            if bucket not in ("exposure", "prior"):
                winning.extend(x for a in g for x in a["_support"])
    final["contested"] = contested
    has_final = any(final[b] for b in ("imposed", "supervised_release", "probation", "fine", "custody"))
    has_any = has_final or final["exposure"] or final["prior"]
    disagreement = {"contested": contested, "unknown_spans": unknown}
    review = [{"reason": "contested", **c} for c in contested.values()]
    if has_any and not contested:
        status, rule = "resolved", "clause_kind_buckets"
    elif has_any:
        status, rule = "partial", "partial_finals"
    elif contested:
        status, rule = "disagreement", "conflict_veto"
    else:
        status, rule = "needs_review", "unknown_sentence_kind"
        review += [{"reason": "unknown_sentence_kind", **u} for u in unknown]
    return _result("sentence", status, final, rule, winning, disagreement, review)


def _drop_derived_totals(groups: List[List[Dict]]) -> List[List[Dict]]:
    """'for a total of 27 and a half years' = sum of the other imposed terms → not a separate term."""
    totals = [g for g in groups if any((a.get("extras") or {}).get("total") for a in g)]
    if not totals:
        return groups
    rest = [g for g in groups if g not in totals]
    rest_months = sum((_representative(g).get("extras") or {}).get("months") or 0 for g in rest)
    keep = list(rest)
    for g in totals:
        months = (_representative(g).get("extras") or {}).get("months")
        if months is None or abs(months - rest_months) > 1:
            keep.append(g)
    return sorted(keep, key=lambda g: g[0].get("span_start") or 0)


# ---------------------------------------------------------------------------
# Investigation type (CyberTip origin)
# ---------------------------------------------------------------------------

def resolve_investigation_type(assertions: List[Dict]) -> Dict:
    mentions = _mentions(assertions, "investigation_type")
    if not mentions:
        return _result("investigation_type", "empty", None, "no_assertions")
    action: List[Dict] = []
    boiler = 0
    open_items: List[Dict] = []
    contested: Dict[str, Dict] = {}
    for (s, e), items in mentions.items():
        vote = _vote(items)
        if vote["state"] == "contested":
            contested[f"cybertip@{s}"] = {"span": [s, e], "roles": vote["roles"]}
        elif vote["state"] in ("agreed", "resolved") and vote["role"] == "case_action":
            action.extend(vote["support"])
        elif vote["state"] in ("agreed", "resolved") and vote["role"] == "boilerplate":
            boiler += 1
        else:
            open_items.append({"span": [s, e], "state": vote["state"], "role": vote.get("role")})
    disagreement = {"contested": contested, "boilerplate_mentions": boiler, "open": open_items}
    if action:
        status = "partial" if contested else "resolved"
        return _result("investigation_type", status, ["cybertip"], "case_action_cybertip", action, disagreement)
    review = [{"reason": "cybertip_scope_unclear", **x} for x in open_items] + [
        {"reason": "contested", **c} for c in contested.values()
    ]
    if contested:
        return _result("investigation_type", "disagreement", [], "conflict_veto", (), disagreement, review)
    if open_items:
        return _result("investigation_type", "needs_review", [], "unscoped_cybertip", (), disagreement, review)
    return _result("investigation_type", "resolved", [], "boilerplate_only_cybertip", (), disagreement)


# ---------------------------------------------------------------------------
# Dates (informational; legacy date_range stays batch-derived)
# ---------------------------------------------------------------------------

def resolve_date(assertions: List[Dict], batch_date: Optional[str] = None) -> Dict:
    dates = [a for a in assertions if a.get("field") == "date" and a.get("span_ok")]
    if not dates:
        return _result("date", "empty", None, "no_assertions")
    by_role: Dict[str, List[str]] = defaultdict(list)
    for a in dates:
        by_role[a.get("role") or "event"].append(str(a["value"]))
    publication = by_role.get("publication", [None])[0]
    final = {"publication": publication, "batch_date": batch_date,
             **{r: sorted(set(v)) for r, v in by_role.items() if r != "publication"}}
    pub = [a for a in dates if a.get("role") == "publication"][:1]
    if publication and batch_date and publication[:4] != str(batch_date)[:4]:
        review = [{"reason": "publication_vs_batch_date", "publication": publication, "batch_date": batch_date}]
        return _result("date", "disagreement", final, "publication_vs_batch_year", pub,
                       {"publication": publication, "batch_date": batch_date}, review)
    return _result("date", "resolved", final, "temporal_roles", pub)


def resolve_case(
    assertions: List[Dict],
    *,
    batch_date: Optional[str] = None,
    text: Optional[str] = None,
) -> Dict[str, Dict]:
    """Resolve every field. ``text`` is reserved for narrative-aware age collapse."""
    _ = text
    return {
        "age": resolve_age(assertions),
        "sentence": resolve_sentence(assertions),
        "investigation_type": resolve_investigation_type(assertions),
        "date": resolve_date(assertions, batch_date),
    }


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
