"""Decide whether a press release is one child-sexual-exploitation case.

Awareness, statistics, policy, and guidance are out. A multi-person operation
roster is a roundup: kept only when the text does not list three or more
separately charged people. Separable per-person narratives are not split here;
the collector excludes those roundups and reports them.
"""

from __future__ import annotations

import re

_CHILD = re.compile(
    r"("
    r"child sexual|"
    r"sexual exploitation|"
    r"child pornograph|"
    r"child abuse material|"
    r"child exploitation|"
    r"sexually explicit material|"
    r"sexual solicitation of a minor|"
    r"indecent images? of (?:a )?child|"
    r"sexual offences against children|"
    r"child luring|luring (?:a |of )?(?:a )?child|"
    r"child sex\b|"
    r"\bCSAM\b|\bCSAEM\b|\bOSAEC\b|"
    r"child trafficking\s*(?:&|and)\s*pornograph|"
    r"internet crimes against children|"
    r"\bICAC\b|"
    r"\bminors?\b"
    r")",
    re.I,
)
_CASE = re.compile(
    r"\b("
    r"arrest(?:ed|s)?|charg(?:e|ed|es)|sentenc(?:e|ed|ing)|"
    r"guilt(?:y)?|convict(?:ed|ion)|plea(?:d|ded)?|indict(?:ed|ment)?|"
    r"warrant|remand(?:ed)?|custody|accused|prosecut|"
    r"rescu(?:e|ed)|investigation"
    r")\b",
    re.I,
)
_MULTI = re.compile(
    r"\b(\d{1,3})\s+(?:people|persons|men|women|individuals|adults|albertans|"
    r"suspects|defendants|accused)\b",
    re.I,
)
_WORD_NUM = {
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
}
_WORD_MULTI = re.compile(
    r"\b(" + "|".join(_WORD_NUM) + r")\s+(?:people|persons|men|women|individuals|adults|"
    r"suspects|defendants|accused)\b",
    re.I,
)
_TREND = re.compile(
    r"\b(on the rise|awareness|statistics|tips for parents|campaign|report card)\b",
    re.I,
)
_AWARE = re.compile(
    r"\b(awareness month|statistics|tips for parents|prevention campaign|"
    r"report card|how to keep|guidance for parents|poster contest)\b",
    re.I,
)
_FOOTER = re.compile(
    r"\n\s*(?:"
    r"notes to editors|for more information|anyone with information|"
    r"if you (?:have|suspect)|media (?:contact|enquir)|"
    r"about (?:the )?(?:icac|alert|the task force)|"
    r"editor(?:'|’)s notes"
    r")\b",
    re.I,
)
_PERSON_CHARGE = re.compile(
    r"(?:was|were|has been|have been)\s+(?:arrested|charged|sentenced|convicted)|"
    r"\bcharged with\b",
    re.I,
)


def _about_children(blob: str) -> bool:
    if _CHILD.search(blob):
        return True
    return bool(
        re.search(r"\bchild(?:ren)?\b|\bminors?\b", blob, re.I)
        and re.search(r"sexual|porn|indecent|luring|exploit|sex\b", blob, re.I)
    ) or bool(
        re.search(r"\b(?:1[0-7]|[1-9])-year-old\b", blob, re.I)
        and re.search(r"sex|porn|exploit|indecent|lur", blob, re.I)
    )


def lead_text(body: str) -> str:
    """Drop the standard task-force footer so boilerplate cannot qualify a release."""
    text = body or ""
    match = _FOOTER.search("\n" + text)
    if match and match.start() > 1:
        return text[: match.start() - 1]
    return text


def classify_release(title: str, body: str) -> str:
    """Return ``keep``, ``roundup``, or ``skip``."""
    title = title or ""
    lead = lead_text(body or "")
    blob = f"{title}\n{lead}"
    if (_AWARE.search(title) or _TREND.search(title)) and not _CASE.search(title):
        return "skip"
    if re.search(r"\b(policy|guidance|strategy)\b", title, re.I) and not re.search(
        r"\b(arrest|charged|sentenced|convicted)\b", title, re.I
    ):
        return "skip"
    if not _about_children(blob) or not _CASE.search(blob):
        return "skip"
    head = f"{title}\n{lead[:500]}"
    multi = _MULTI.search(head)
    word_multi = _WORD_MULTI.search(head)
    arrest_count = re.search(r"\b(\d{1,3})\s+arrests?\b", f"{title}\n{lead[:300]}", re.I)
    if (
        (multi and int(multi.group(1)) >= 3)
        or (word_multi and _WORD_NUM[word_multi.group(1).lower()] >= 3)
        or (arrest_count and int(arrest_count.group(1)) >= 3)
    ):
        return "roundup"
    if re.search(r"\boperation\b", title, re.I) and len(_PERSON_CHARGE.findall(lead)) >= 3:
        return "roundup"
    return "keep"
