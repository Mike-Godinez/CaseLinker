"""
Detector registry for CaseLinker 3.0.

A detector reads original text and emits raw assertions (field, value, role, span,
method). It does not decide the final. The span gate and resolution do that, for
every document kind.

``press_release`` runs the press-release detectors (age grammar, sentences,
CyberTip scope, statutes, temporal tags, spaCy). ``pacer``,
``investigative_note``, and ``cybertip`` are accepted document types. They do
not run those press detectors. Add one with ``register_detector`` and name the
kind it applies to. It returns the same assertion dicts. The gate and the
resolver stay as they are.

    from detectors import register_detector

    def pacer_ages(ctx):
        return [...]  # same assertion dicts the press detectors return

    register_detector("pacer_ages", ("pacer",), pacer_ages, order=10)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

DOCUMENT_KINDS = ("press_release", "pacer", "investigative_note", "cybertip")


@dataclass
class DetectorContext:
    """One document, plus whatever earlier detectors left for later ones."""

    text: str
    doc_kind: str
    case_id: str = ""
    ner_entities: Optional[Dict[str, Any]] = None
    mentions: List[Tuple] = field(default_factory=list)
    batch_year: Optional[int] = None
    overrides: Optional[Dict] = None
    use_spacy: bool = True
    sentence_raw: List[Dict] = field(default_factory=list)
    durations: List[Dict] = field(default_factory=list)
    compiled_rules: Optional[Tuple] = None
    spacy_doc: Any = None


@dataclass(frozen=True)
class Detector:
    name: str
    kinds: Tuple[str, ...]
    fn: Callable[[DetectorContext], List[Dict]]
    order: int = 100


_DETECTORS: List[Detector] = []


def register_detector(name: str, kinds: Tuple[str, ...], fn: Callable, *, order: int = 100) -> None:
    unknown = [k for k in kinds if k not in DOCUMENT_KINDS]
    if unknown:
        raise ValueError(f"{name} registered for unknown document kinds {unknown}")
    if any(d.name == name for d in _DETECTORS):
        raise ValueError(f"detector {name} is already registered")
    _DETECTORS.append(Detector(name, tuple(kinds), fn, order))


def unregister_detector(name: str) -> None:
    global _DETECTORS
    _DETECTORS = [d for d in _DETECTORS if d.name != name]


def detectors_for(kind: str) -> List[Detector]:
    if kind not in DOCUMENT_KINDS:
        raise ValueError(f"unknown document_kind {kind!r}; expected one of {DOCUMENT_KINDS}")
    return sorted((d for d in _DETECTORS if kind in d.kinds), key=lambda d: (d.order, d.name))
