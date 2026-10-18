"""
Temporal tagging (evidence family ``temporal``) for CaseLinker 3.0.

- ``date`` assertions: every explicit date mention with a role — publication,
  biography (born / ordained / hired …), prior_case, or event.
- ``sentence`` assertions with role ``prior``: durations inside clauses about an
  earlier case ("previously arrested in 2018 … sentenced to three months"),
  so a prior sentence never finalizes as this case's sentence.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

_PROCESSING_LAYER = Path(__file__).resolve().parent.parent
_FIELD_LAYER = _PROCESSING_LAYER / "field_assertions"
if str(_FIELD_LAYER) not in sys.path:
    sys.path.insert(0, str(_FIELD_LAYER))
if str(_PROCESSING_LAYER) not in sys.path:
    sys.path.insert(0, str(_PROCESSING_LAYER))

import span_gate as sg  # noqa: E402

TEMPORAL_VERSION = "temporal_1.0.1"

_MONTHS = {
    m: i for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december"], start=1)
}
_MONTH_ABBR = {k[:3]: v for k, v in _MONTHS.items()} | {"sept": 9}
_MONTH_RE = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_DATE_RES = (
    (re.compile(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+((?:19|20)\d{{2}})\b"), "mdy"),
    (re.compile(r"\b((?:19|20)\d{2})-(\d{2})-(\d{2})\b"), "iso"),
    (re.compile(rf"\b({_MONTH_RE})\.?\s+((?:19|20)\d{{2}})\b"), "my"),
    (re.compile(r"\b(?:in|since|during|from|until|by|of)\s+((?:19|20)\d{2})\b", re.I), "y"),  # "In 2008, …"
)
_PUBLICATION_LINE = re.compile(r"^\s*(?:Publication\s+date|Date\s+Posted|Published|Posted|Updated)\s*:?", re.I | re.M)
_BIOGRAPHY_CUES = re.compile(
    r"\b(?:born|ordained|graduated|married|enlisted|hired|joined|retired|served\s+as|appointed|elected|founded)\b", re.I
)
_PRIOR_CUES = re.compile(
    r"\b(?:previously\s+(?:been\s+)?(?:convicted|arrested|sentenced|served|incarcerated|charged)"
    r"|prior\s+(?:\w+\s+)?(?:conviction|case|arrest|sentence|offense)s?|earlier\s+(?:case|conviction|arrest)"
    r"|at\s+the\s+time|was\s+released\s+(?:from|in)|had\s+served|not\s+the\s+first\s+time"
    r"|in\s+a\s+(?:prior|previous|separate)\s+case|(?:convicted|sentenced|arrested)\s+in\s+(?:19|20)\d{2}"
    # a different person's case described in the same release
    r"|the\s+other\s+(?:individual|man|woman|defendant|offender)|co-?defendant|accomplice"
    # a term the defendant is already serving from another case ("consecutive to the four years
    # Dokes is serving after he was convicted in two gun cases")
    r"|consecutive(?:ly)?\s+to\s+(?:the|a|an|his|her)\s+(?:[\w-]+\s+){0,3}?(?:sentences?|terms?|years?|months?)"
    r"|(?:is|was|been)\s+(?:currently\s+|already\s+)?serving\s+(?:a|an|the|his|her|time|that|this|\d+|[\w-]+\s+(?:years?|months?|sentences?|terms?))"
    r"|currently\s+serving)\b",
    re.I,
)
_CURRENT_CUES = re.compile(
    r"\b(?:today|yesterday|this\s+week|on\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday))\b", re.I
)
_SENTENCING_VERBS = re.compile(r"\b(?:sentenced|received\s+a\s+(?:prison\s+)?sentence|imposed)\b", re.I)
# "jailed in August 2022 to 14 years, with five years on licence" is one earlier term.
_PAST_CUSTODY_VERBS = re.compile(r"\b(?:jailed|imprisoned)\b", re.I)
# Convictions / pleas also predate a release, sometimes by two years; only a gap of three or
# more years marks a prior case.
_CONVICTION_VERBS = re.compile(r"\b(?:convicted|pleaded\s+guilty|pled\s+guilty|found\s+guilty)\b", re.I)
PRIOR_CONVICTION_YEARS = 3
# A sentence that names the judge / court / hearing describes this case's sentencing, so it
# never continues a prior-conviction recap ("previously convicted … At sentencing, Judge X imposed").
_CURRENT_SENTENCING_ANCHORS = re.compile(
    r"\b(?:judge|court|u\.s\.|united\s+states|federal|at\s+sentencing|hearing|today|yesterday)\b", re.I
)
# The duration itself, not the whole sentence: "today" later in the sentence is this case's term.
_LOCAL_PRIOR_BEFORE = re.compile(
    r"\b(?:previously|earlier)\s+(?:been\s+)?(?:jailed|imprisoned|sentenced|served|incarcerated)\s+(?:for\s+)?(?:a\s+)?$",
    re.I,
)
_JAILED_IN_YEAR_BEFORE = re.compile(
    r"\b(?:jailed|imprisoned|sentenced)\s+in\s+(?:[A-Za-z]+\s+)?((?:19|20)\d{2})\s+to\s+$",
    re.I,
)
_STATUTE_NAME_BEFORE = re.compile(r"\bAct\s+of\s+$", re.I)
PRIOR_DAYS = 180


def _month_num(tok: str) -> Optional[int]:
    t = tok.lower().rstrip(".")
    return _MONTHS.get(t) or _MONTH_ABBR.get(t[:4] if t.startswith("sept") else t[:3])


def date_mentions(text: str) -> List[Dict]:
    out: List[Dict] = []
    taken: List[tuple] = []
    for rx, kind in _DATE_RES:
        for m in rx.finditer(text):
            span = (m.start(), m.end()) if kind != "y" else (m.start(1), m.end(1))
            if any(span[0] < e and span[1] > s for s, e in taken):
                continue
            if _STATUTE_NAME_BEFORE.search(text[max(0, span[0] - 12) : span[0]]):
                continue  # "Victim Assistance Act of 2018" is a statute name, not an event
            if kind == "mdy":
                mo, day, year = _month_num(m.group(1)), int(m.group(2)), int(m.group(3))
                if not mo or not 1 <= day <= 31:
                    continue
                value = f"{year:04d}-{mo:02d}-{day:02d}"
            elif kind == "iso":
                value = m.group(0)
            elif kind == "my":
                mo = _month_num(m.group(1))
                if not mo:
                    continue
                value = f"{int(m.group(2)):04d}-{mo:02d}"
            else:
                value = m.group(1)
            taken.append(span)
            out.append({"start": span[0], "end": span[1], "value": value, "year": int(value[:4])})
    return sorted(out, key=lambda d: d["start"])


def publication_year(text: str, mentions: List[Dict], fallback: Optional[int]) -> Optional[int]:
    for d in mentions:
        line_start = text.rfind("\n", 0, d["start"]) + 1
        if _PUBLICATION_LINE.match(text[line_start : d["start"]]) or d["start"] < 300:
            return d["year"]
    return fallback


def _raw(field, value, role, s, e, confidence, **extras):
    return {
        "field": field, "method": "temporal", "method_version": TEMPORAL_VERSION, "value": value,
        "role": role, "span_start": s, "span_end": e, "confidence": confidence, "extras": extras,
    }


def _days(value: str) -> Optional[int]:
    """Approximate day number for YYYY / YYYY-MM / YYYY-MM-DD (month-precision → mid-month)."""
    parts = [int(p) for p in value.split("-")]
    if len(parts) == 1:
        return None
    year, month = parts[0], parts[1]
    day = parts[2] if len(parts) > 2 else 15
    return year * 365 + (month - 1) * 30 + day


def _is_earlier(d: Dict, pub_value: Optional[str], pub_year: Optional[int]) -> bool:
    """Clearly before publication: >180 days for dated mentions, ≥2 years for year-only ones."""
    pub_days = _days(pub_value) if pub_value else None
    days = _days(d["value"])
    if days is not None and pub_days is not None:
        return pub_days - days > PRIOR_DAYS
    return bool(pub_year) and d["year"] < pub_year - 1


def _prior_sentence_ids(
    text: str, mentions: List[Dict], pub_value: Optional[str], pub_year: Optional[int], *, for_ages: bool
) -> set:
    """
    Indexes of sentences about an earlier or different case. Offense conduct, pleas, and
    verdicts also predate a release, so an early date counts only next to "sentenced", and
    only for durations. Ages need an explicit cue; "at the time" there is a time qualifier
    ("five years old at the time"), not a prior case.
    """
    spans = sg.sentence_spans(text)
    prior = set()
    for i, (ss, se) in enumerate(spans):
        sentence = text[ss:se]
        if _CURRENT_CUES.search(sentence):
            continue
        cue = _PRIOR_CUES.search(sentence)
        if cue and not (for_ages and cue.group(0).lower().startswith("at the time")):
            prior.add(i)
            continue
        if for_ages:
            continue  # pleas and verdicts in this case also predate the release; ages need a cue
        in_sentence = [d for d in mentions if ss <= d["start"] < se]
        early = any(_is_earlier(d, pub_value, pub_year) for d in in_sentence)
        if early and (_SENTENCING_VERBS.search(sentence) or _PAST_CUSTODY_VERBS.search(sentence)):
            prior.add(i)
            continue
        # "in 1999, Bowers was convicted of … Bowers was sentenced to 20 years in state prison":
        # a conviction two or more years before publication is an earlier case.
        far_early = bool(pub_year) and any(d["year"] <= pub_year - PRIOR_CONVICTION_YEARS for d in in_sentence)
        if far_early and _CONVICTION_VERBS.search(sentence):
            prior.add(i)
            continue
        # "Lacy was sentenced on February 2, 2009 … He received a sentence of 60 months" — the
        # sentence right after a dated earlier sentencing continues it (same paragraph only).
        if not for_ages and i and (i - 1) in prior:
            ps, pe = spans[i - 1]
            prev = text[ps:pe]
            if "\n\n" in text[pe:ss] or in_sentence:
                continue
            if _SENTENCING_VERBS.search(prev):
                prior.add(i)
            elif _CONVICTION_VERBS.search(prev) and not _CURRENT_SENTENCING_ANCHORS.search(sentence):
                # "in 1999, Bowers was convicted … Bowers was sentenced to 20 years in state prison"
                prior.add(i)
    return prior


def temporal_assertions(
    text: str,
    sentence_candidates: List[Dict],
    batch_year: Optional[int] = None,
    age_mentions: Iterable[Tuple[int, int, int, str]] = (),
) -> List[Dict]:
    mentions = date_mentions(text)
    pub_year = publication_year(text, mentions, batch_year)
    out: List[Dict] = []
    pub_value: Optional[str] = None
    for d in mentions:
        line_start = text.rfind("\n", 0, d["start"]) + 1
        ss, se = sg.sentence_at(text, d["start"], d["end"])
        sentence = text[ss:se]
        if _PUBLICATION_LINE.match(text[line_start : d["start"]]) or (
            d["start"] < 300 and text[line_start : d["start"]].strip() == ""
        ):
            role = "publication"
            if pub_value is None and len(d["value"]) == 10:
                pub_value = d["value"]
        elif _BIOGRAPHY_CUES.search(sentence):
            role = "biography"
        elif _is_earlier(d, pub_value, pub_year) and _PRIOR_CUES.search(sentence):
            role = "prior_case"
        else:
            role = "event"
        out.append(_raw("date", d["value"], role, d["start"], d["end"], 0.8, publication_year=pub_year))

    spans = sg.sentence_spans(text)
    prior = _prior_sentence_ids(text, mentions, pub_value, pub_year, for_ages=False)
    prior_ages = _prior_sentence_ids(text, mentions, pub_value, pub_year, for_ages=True)

    def sentence_index(pos: int) -> Optional[int]:
        return next((i for i, (ss, se) in enumerate(spans) if ss <= pos < se), None)

    anchor_year = pub_year or batch_year
    for cand in sentence_candidates:
        before = sg.normalize_surface(text[max(0, cand["span_start"] - 60) : cand["span_start"]])
        year_hit = _JAILED_IN_YEAR_BEFORE.search(before)
        earlier_year = bool(
            year_hit and anchor_year and int(year_hit.group(1)) <= anchor_year - PRIOR_CONVICTION_YEARS
        )
        if sentence_index(cand["span_start"]) in prior or _LOCAL_PRIOR_BEFORE.search(before) or earlier_year:
            out.append(_raw("sentence", cand["value"], "prior", cand["span_start"], cand["span_end"], 0.8, prior_cue=True))
    for s, e, age, shape in age_mentions:
        # "Name, 45," and "19-year-old Alex Rivera" name the current defendant even
        # inside a sentence that also says he was previously arrested.
        if shape in ("name_comma", "name_paren"):
            continue
        if shape == "year_old" and re.match(r"^\W*years?\W*olds?\s+[A-Z]", text[e:e + 40]):
            continue
        if sentence_index(s) in prior_ages:
            out.append(_raw("age", age, "prior_case", s, e, 0.8, prior_cue=True))
    return out
