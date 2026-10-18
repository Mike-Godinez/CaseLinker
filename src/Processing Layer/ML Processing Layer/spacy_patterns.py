"""
spaCy assertion producers for CaseLinker 3.0.

- ``spacy_token`` (family ``surface_pattern``): token Matcher patterns.
- ``spacy_dep`` (family ``dependency``): DependencyMatcher plus head-chain
  attachment. Roles come from the age's grammatical host: the noun it modifies,
  the person it is appositive to (and whether that person is the syntactic
  subject of a defendant verb), a persona verb (``posed as``), material nouns
  (``images of …``), or ``under the age of``.

Runs only on age-shaped mentions supplied by the caller. Optional: if spaCy or the
model is missing, the layer is skipped and the run records it as unavailable.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

_PROCESSING_LAYER = Path(__file__).resolve().parent.parent
_FIELD_LAYER = _PROCESSING_LAYER / "field_assertions"
for _p in (_FIELD_LAYER, _PROCESSING_LAYER):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import span_gate as sg  # noqa: E402

SPACY_DEP_VERSION = "spacy_dep_1.0.1"
SPACY_TOKEN_VERSION = "spacy_token_1.0.1"
DEFAULT_MODEL = os.environ.get("CASELINKER_SPACY_MODEL", "en_core_web_sm")

_VICTIM_LEMMAS = frozenset(
    "victim girl boy child minor juvenile daughter son stepdaughter stepson niece nephew granddaughter "
    "grandson student teen teenager toddler infant baby youth kid preteen sister brother".split()
)
_ADULT_LEMMAS = frozenset(
    "man woman adult resident defendant suspect offender teacher coach priest pastor officer deputy "
    "employee nurse doctor stepfather father grandfather uncle boyfriend husband soldier sailor airman "
    "marine inmate predator driver".split()
)
_DEFENDANT_LEMMAS = frozenset("arrest charge sentence plead plea convict indict admit confess book accuse face arraign extradite".split())
_PERSONA_LEMMAS = frozenset("pose pretend portray purport masquerade claim represent identify".split())
_PERSONA_FORMS = sorted(
    _PERSONA_LEMMAS
    | set("poses posed posing pretends pretended pretending portrays portrayed portraying purported purporting "
          "masqueraded masquerading claims claimed claiming believe believed believes believing thought think".split())
)
_FICTITIOUS = frozenset("fictitious fictious fictional fake purported notional nonexistent non-existent imaginary".split())
# Nouns that name a persona rather than a person: "persona of a 12-year-old girl", "a 13-year-old girl decoy".
_PERSONA_NOUNS = frozenset("persona decoy profile character identity alias guise".split())
_BELIEF_LEMMAS = frozenset("believe think".split())
_CRIME_NOUN_LEMMAS = frozenset(
    "assault abuse rape murder killing kidnapping attack robbery exploitation molestation homicide shooting "
    "death battery stalking trafficking".split()
)
_MATERIAL_LEMMAS = frozenset("image video photo photograph picture file material depiction content pornography recording".split())
_PRODUCTION_LEMMAS = frozenset("produce create record film take make photograph".split())
_AGE_GLUE = frozenset({"year", "years", "yr", "yrs", "old", "-", "age", "aged"})
_LE_RE = re.compile(
    r"\b(?:undercover|officers?|agents?|deput(?:y|ies)|detectives?|police|investigators?|sting|task\s+force|"
    r"law\s+enforcement|sheriff'?s?|troopers?|FBI|HSI|ICAC|decoys?)\b",
    re.IGNORECASE,
)

_nlp = None
_nlp_error: Optional[str] = None


def load_spacy():
    """Process-wide spaCy pipeline, or None (with the reason in ``spacy_status``)."""
    global _nlp, _nlp_error
    if _nlp is not None or _nlp_error is not None:
        return _nlp
    try:
        import spacy

        _nlp = spacy.load(DEFAULT_MODEL, exclude=["ner"])
    except Exception as exc:  # model or library missing
        _nlp_error = f"{type(exc).__name__}: {exc}"
        _nlp = None
    return _nlp


def spacy_status() -> Dict[str, Optional[str]]:
    nlp = load_spacy()
    if nlp is None:
        return {"spacy_model": f"unavailable ({_nlp_error})"}
    meta = nlp.meta
    return {"spacy_model": f"{meta.get('lang')}_{meta.get('name')}:{meta.get('version')}"}


def _raw(method, version, value, role, s, e, confidence, **extras):
    return {
        "field": "age", "method": method, "method_version": version, "value": value, "role": role,
        "span_start": s, "span_end": e, "confidence": confidence,
        "extras": {k: v for k, v in extras.items() if v is not None},
    }


def _token_at(doc, start: int, end: int):
    span = doc.char_span(start, end, alignment_mode="expand")
    if span is None or not len(span):
        return None
    return span[0]


def _defendant_heads(doc) -> Set[str]:
    """PROPN tokens that are syntactic subjects of defendant verbs (casefolded surface)."""
    out: Set[str] = set()
    for tok in doc:
        subj = tok.head if tok.dep_ == "appos" else tok  # "A Lexington man, Eric Shepherd, 30, was sentenced"
        if tok.pos_ != "PROPN" or subj.dep_ not in ("nsubj", "nsubjpass"):
            continue
        verb = subj.head
        if verb.lemma_.lower() in _DEFENDANT_LEMMAS or (
            verb.lemma_.lower() == "receive" and any(c.lemma_.lower() in ("term", "sentence") for c in verb.subtree)
        ):
            out.add(tok.text.casefold())
    return out


def _ancestors(tok, limit: int = 6):
    out = []
    cur = tok
    for _ in range(limit):
        if cur.head is cur:
            break
        cur = cur.head
        out.append(cur)
    return out


def _host(tok):
    """Climb from the age number through year/old/age glue to its grammatical host."""
    cur = tok
    if cur.dep_ == "conj" and cur.head.like_num:
        cur = cur.head  # "ages of 6 and 11": 11 inherits 6's host
    for _ in range(5):
        if cur.head is cur:
            break
        if cur.head.lower_ in _AGE_GLUE or cur.head.lemma_.lower() in _AGE_GLUE:
            cur = cur.head
            continue
        if cur.lower_ in ("old", "aged", "age") or cur.like_num:
            return cur, cur.head
        break
    return cur, cur.head


def _attached_without_clause(tok, anchor) -> bool:
    """Anchor governs the age with no verb in between ("posed as 13-year-old 'Alex' who met
    John Cotton, 55": the relative-clause verb blocks 55 from the persona)."""
    for a in _ancestors(tok, 8):
        if a.i == anchor.i:
            return True
        # copula of "believed to be a …" and prepositional "including" are not clause boundaries
        if a.pos_ in ("VERB", "AUX") and a.lemma_.lower() not in ("be", "include"):
            return False
    return False


def _fragmented(tok, text: str, s: int, e: int) -> bool:
    """spaCy split a sentence inside the span-gate sentence (PDF line breaks): the parse around
    the mention is unreliable, e.g. "photos of nude\\n5- to 8-year-old girls"."""
    ss, se = sg.sentence_at(text, s, e)
    cut = text[ss : max(ss, tok.sent.start_char)] + " " + text[min(se, tok.sent.end_char) : se]
    # A dateline ("OKLAHOMA – ") split off is harmless; a cut clause ("… shared photos of nude") is not.
    return len(re.findall(r"[a-z]{2,}", cut)) >= 3


def _persona_role(doc, anc, sent_text: str) -> str:
    if anc.lemma_.lower() in ("claim", "represent", "identify"):
        return "claimed"
    if anc.lemma_.lower() in ("believe", "think"):
        return "decoy"
    return "decoy" if _LE_RE.search(sent_text) else "claimed"


def dependency_assertions(doc, mentions: Iterable[Tuple[int, int, int, str]]) -> List[Dict]:
    from spacy.matcher import DependencyMatcher

    nlp_vocab = doc.vocab
    matcher = DependencyMatcher(nlp_vocab)
    matcher.add("STATUTORY", [[
        {"RIGHT_ID": "under", "RIGHT_ATTRS": {"LOWER": {"IN": ["under", "below", "younger"]}}},
        {"LEFT_ID": "under", "REL_OP": ">>", "RIGHT_ID": "age", "RIGHT_ATTRS": {"LEMMA": "age"}},
        {"LEFT_ID": "age", "REL_OP": ">>", "RIGHT_ID": "num", "RIGHT_ATTRS": {"LIKE_NUM": True}},
    ]])
    matcher.add("PERSONA", [[
        {"RIGHT_ID": "verb", "RIGHT_ATTRS": {"LOWER": {"IN": _PERSONA_FORMS}}},
        {"LEFT_ID": "verb", "REL_OP": ">", "RIGHT_ID": "as", "RIGHT_ATTRS": {"LOWER": {"IN": ["as", "be"]}}},
        {"LEFT_ID": "as", "REL_OP": ">>", "RIGHT_ID": "num", "RIGHT_ATTRS": {"LIKE_NUM": True}},
    ]])
    matcher.add("MATERIAL", [[
        {"RIGHT_ID": "mat", "RIGHT_ATTRS": {"LEMMA": {"IN": sorted(_MATERIAL_LEMMAS)}}},
        {"LEFT_ID": "mat", "REL_OP": ">>", "RIGHT_ID": "num", "RIGHT_ATTRS": {"LIKE_NUM": True}},
    ]])
    by_num: Dict[int, Tuple[str, object]] = {}
    for match_id, token_ids in matcher(doc):
        label = nlp_vocab.strings[match_id]
        num = doc[token_ids[-1]]
        anchor = doc[token_ids[0]]
        prev = by_num.get(num.i)
        # Statutory beats persona beats material when patterns overlap.
        rank = {"STATUTORY": 0, "PERSONA": 1, "MATERIAL": 2}
        if prev is None or rank[label] < rank[prev[0]]:
            by_num[num.i] = (label, anchor)

    defendants = _defendant_heads(doc)
    out: List[Dict] = []
    for s, e, age, _shape in mentions:
        tok = _token_at(doc, s, e)
        if tok is None:
            continue
        sent_text = tok.sent.text
        hit = by_num.get(tok.i) or (by_num.get(tok.head.i) if tok.dep_ == "conj" else None)
        if hit:
            label, anchor = hit
            if label == "STATUTORY":
                out.append(_raw("spacy_dep", SPACY_DEP_VERSION, age, "statutory_threshold", s, e, 0.85, dep_pattern="under_age_of"))
                continue
            if label == "PERSONA" and _attached_without_clause(tok, anchor):
                out.append(_raw("spacy_dep", SPACY_DEP_VERSION, age, _persona_role(doc, anchor, sent_text), s, e, 0.85,
                                dep_pattern="persona_as", anchor=anchor.text))
                continue
            if label == "MATERIAL" and not any(a.lemma_.lower() in _PRODUCTION_LEMMAS for a in _ancestors(anchor, 4)):
                # "videos of a twelve-year-old victim": the host noun says victim, same as the regex family
                _, mat_host = _host(tok)
                if mat_host is not None and mat_host.lemma_.lower() == "victim":
                    pass
                elif _attached_without_clause(tok, anchor):
                    out.append(_raw("spacy_dep", SPACY_DEP_VERSION, age, "depicted_in_material", s, e, 0.8,
                                    dep_pattern="material_of", anchor=anchor.text))
                    continue

        if sg.is_closed_age_range(doc.text, s, e):
            out.append(_raw(
                "spacy_dep", SPACY_DEP_VERSION, age, "unknown", s, e, 0.5,
                dep_pattern="age_range", weak="age_range",
            ))
            continue

        nominal, host = _host(tok)
        role, conf, pattern, entity, weak = "unknown", 0.5, "no_host", None, None
        # "he was 17 years-old" under "claimed"
        if nominal.dep_ == "acomp" and any(a.lemma_.lower() == "claim" for a in _ancestors(nominal, 3)):
            role, conf, pattern = "claimed", 0.85, "claimed_acomp"
        elif nominal.dep_ in ("nsubj", "nsubjpass") and nominal.lower_ == "old":
            verb = nominal.head
            if verb.lemma_.lower() in _DEFENDANT_LEMMAS or any(c.lower_ == "allegedly" for c in verb.children):
                role, conf, pattern, entity = "perpetrator", 0.75, "anaphor_subject", "anaphor"
        elif host is not None and host.pos_ == "PROPN":
            entity = " ".join(t.text for t in host.subtree if t.pos_ == "PROPN" and t.i <= host.i)[-60:] or host.text
            if host.text in ("Doe", "Victim"):
                role, conf, pattern = "victim", 0.8, "person_alias"
            elif host.text.casefold() in defendants:
                role, conf, pattern = "perpetrator", 0.85, "appositive_defendant_subject"
            else:
                pattern = "appositive_person"
        elif host is not None and host.pos_ in ("NOUN", "PROPN", "PRON"):
            lemma = host.lemma_.lower()
            entity = host.text
            governor = host.head.head if host.dep_ == "pobj" else None
            persona_head = (
                lemma in _PERSONA_NOUNS
                # "persona of a 12-year-old girl": the noun is the complement of a persona noun
                or (host.dep_ == "pobj" and host.head.lower_ == "of" and governor is not None
                    and governor.lemma_.lower() in _PERSONA_NOUNS)
                # "a 13-year-old girl decoy": compound / mis-parsed subject of a persona noun
                or (host.dep_ in ("compound", "nsubj", "nmod") and host.head.lemma_.lower() in _PERSONA_NOUNS)
                or any(c.lemma_.lower() in _PERSONA_NOUNS and c.i > host.i for c in host.children)
            )
            if any(c.lower_ in _FICTITIOUS for c in host.children) or any(
                c.lower_ in _FICTITIOUS for a in _ancestors(host, 2) for c in a.children if c.dep_ in ("amod", "compound")
            ):
                role, conf, pattern = "decoy", 0.85, "fictitious_host"
            elif persona_head:
                role, conf, pattern = "decoy", 0.85, "persona_noun_host"
            elif lemma in _VICTIM_LEMMAS and any(a.lemma_.lower() in _BELIEF_LEMMAS for a in _ancestors(host, 6)) \
                    and _LE_RE.search(sent_text):
                # "he believed he was communicating … with a thirteen-year-old girl" in an undercover sting
                role, conf, pattern = "decoy", 0.8, "believed_sting"
            elif any(a.lemma_.lower() == "access" for a in _ancestors(host, 3)):
                pattern = "access_to"  # children the defendant could reach are not established victims
            elif governor is not None and host.head.lower_ in ("of", "on", "against") and governor.lemma_.lower() in _CRIME_NOUN_LEMMAS:
                # Adult hosts ("76-year-old woman") are not CSEA child victims.
                if lemma in _ADULT_LEMMAS:
                    role, conf, pattern = "adult_crime_victim", 0.85, "adult_crime_object"
                else:
                    role, conf, pattern = "victim", 0.8, "crime_object"
            elif host.dep_ in ("nsubj", "nsubjpass") and host.head.lemma_.lower() in _DEFENDANT_LEMMAS:
                role, conf, pattern = "perpetrator", 0.85, "noun_subject_of_defendant_verb"
            elif lemma in _VICTIM_LEMMAS:
                role, conf, pattern = "victim", 0.8, "victim_noun_host"
                if lemma != "victim" and not sg.has_victimization_cue(doc.text, s, e):
                    conf, weak = 0.6, "noun_without_victimization_cue"  # child noun alone, no victimization in the sentence
            elif lemma in _ADULT_LEMMAS:
                role, conf, pattern = "perpetrator", 0.8, "adult_noun_host"
            else:
                pattern = "other_noun_host"
        if role == "victim" and sg.is_depicted_material(doc.text, s, e):
            role, conf, pattern, weak = "depicted_in_material", 0.8, "material_in_clause", None
        elif role == "victim" and sg.is_stated_preference(doc.text, s, e):
            role, conf, pattern, weak = "unknown", 0.5, "stated_preference", "stated_preference"
        if role in ("victim", "perpetrator") and conf >= 0.7 and _fragmented(tok, doc.text, s, e):
            conf, weak = 0.6, "fragmented_parse"
        out.append(_raw("spacy_dep", SPACY_DEP_VERSION, age, role, s, e, conf, dep_pattern=pattern, entity=entity, weak=weak))
    return out


def token_assertions(doc, mentions: Iterable[Tuple[int, int, int, str]]) -> List[Dict]:
    """Token Matcher: ``N - year - old NOUN`` / ``posing as a N`` / ``under the age of N``."""
    from spacy.matcher import Matcher

    m = Matcher(doc.vocab)
    m.add("YEAR_OLD_NOUN", [[
        {"LIKE_NUM": True}, {"ORTH": "-", "OP": "?"}, {"LOWER": {"IN": ["year", "years", "yr"]}},
        {"ORTH": "-", "OP": "?"}, {"LOWER": "old"}, {"POS": {"IN": ["PROPN", "ADJ"]}, "OP": "*"},
        {"POS": "NOUN"},
    ]])
    m.add("POSING", [[
        {"LOWER": {"IN": _PERSONA_FORMS}}, {"LOWER": {"IN": ["as", "to"]}},
        {"LOWER": {"IN": ["a", "an", "be"]}, "OP": "*"}, {"LIKE_NUM": True},
    ]])
    m.add("UNDER_AGE", [[
        {"LOWER": {"IN": ["under", "below"]}}, {"LOWER": "the", "OP": "?"}, {"LOWER": "age"},
        {"LOWER": "of"}, {"LIKE_NUM": True},
    ]])
    wanted = {(s, e): (age, shape) for s, e, age, shape in mentions}
    out: List[Dict] = []
    seen: Set[Tuple[int, int]] = set()
    priority = {"UNDER_AGE": 0, "POSING": 1, "YEAR_OLD_NOUN": 2}
    matches = sorted(m(doc), key=lambda t: priority[doc.vocab.strings[t[0]]])
    for match_id, start, end in matches:
        label = doc.vocab.strings[match_id]
        span = doc[start:end]
        nums = [t for t in span if t.like_num]
        if not nums:
            continue
        num = nums[0] if label != "UNDER_AGE" else nums[-1]
        key = (num.idx, num.idx + len(num.text))
        if key not in wanted or key in seen:
            continue
        age = wanted[key][0]
        if label == "UNDER_AGE":
            role = "statutory_threshold"
        elif label == "POSING":
            role = "decoy" if _LE_RE.search(num.sent.text) else "claimed"
        else:
            # Look back within the span-gate sentence, not spaCy's (which splits at PDF line breaks).
            gate_start, _ = sg.sentence_at(doc.text, num.idx, num.idx + len(num.text))
            before = [t for t in doc[max(0, start - 8) : start] if t.idx >= gate_start]
            after = doc[end : min(num.sent.end, end + 2)]
            if any(t.lower_ in _PERSONA_FORMS or t.lower_ in _FICTITIOUS for t in before[-4:]) or any(
                t.lemma_.lower() in _MATERIAL_LEMMAS for t in before
            ):
                continue
            # "undercover persona of a 12-year-old girl" / "a 13-year-old girl decoy": not a person at all
            if any(t.lemma_.lower() in _PERSONA_NOUNS or t.lower_ == "undercover" for t in before[-5:]) or any(
                t.lemma_.lower() in _PERSONA_NOUNS for t in after
            ):
                continue
            if sg.is_closed_age_range(doc.text, key[0], key[1]):
                continue
            noun = span[-1].lemma_.lower()
            role = "victim" if noun in _VICTIM_LEMMAS else "perpetrator" if noun in _ADULT_LEMMAS else None
            if role is None:
                continue
            if role == "victim" and sg.is_depicted_material(doc.text, key[0], key[1]):
                role = "depicted_in_material"
            elif role == "victim" and sg.is_stated_preference(doc.text, key[0], key[1]):
                continue
        conf, weak = 0.75, None
        if label == "YEAR_OLD_NOUN" and role == "victim" and noun != "victim" and not sg.has_victimization_cue(doc.text, key[0], key[1]):
            conf, weak = 0.6, "noun_without_victimization_cue"
        seen.add(key)
        out.append(_raw("spacy_token", SPACY_TOKEN_VERSION, age, role, key[0], key[1], conf, token_pattern=label, weak=weak))
    return out
