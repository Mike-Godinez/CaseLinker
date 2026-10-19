#!/usr/bin/env python3
"""
Provenance graph for one case. Separate file from the CAC case graph.

The case graph (features_to_cac.py) is not modified. Decoys and contested
mentions are annotations here. They are not VictimRole or OffenderRole nodes.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef
from rdflib.namespace import DCTERMS, XSD

_ONTOLOGY = Path(__file__).resolve().parent
_REPO = _ONTOLOGY.parent
_SHAPES = _ONTOLOGY / "caselinker-provenance-shapes.ttl"
_STORAGE = _REPO / "src" / "Storage Layer"

PROV = Namespace("http://www.w3.org/ns/prov#")
OA = Namespace("http://www.w3.org/ns/oa#")
CAC_CORE = Namespace("https://cacontology.projectvic.org/core#")
CL = Namespace("https://w3id.org/caselinker/ns/provenance#")
BASE = Namespace("https://w3id.org/caselinker/resource/")

_ROLE_TYPE = {
    "victim": Namespace("https://cacontology.projectvic.org#").VictimRole,
    "perpetrator": Namespace("https://cacontology.projectvic.org#").OffenderRole,
}


def _dec(value: Any) -> Literal:
    try:
        number = Decimal(str(value if value is not None else "0")).quantize(Decimal("0.01"))
    except Exception:
        number = Decimal("0.00")
    return Literal(number, datatype=XSD.decimal)


def _iri(case_id: str, *parts: str) -> URIRef:
    slug = "/".join(quote_part(p) for p in parts)
    return BASE[f"case/{quote_part(case_id)}/{slug}"]


def quote_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(value))


def build_provenance_graph(
    case_id: str,
    assertions: List[Dict[str, Any]],
    resolutions: Dict[str, Dict[str, Any]],
    *,
    run_id: str = "unrecorded",
    issued_at: Optional[str] = None,
) -> Graph:
    """One graph: an extraction activity, one agent per method, one annotation per assertion."""
    g = Graph()
    g.bind("prov", PROV)
    g.bind("oa", OA)
    g.bind("cac-core", CAC_CORE)
    g.bind("caselinker", CL)
    g.bind("dcterms", DCTERMS)

    activity = _iri(case_id, "extraction", quote_part(run_id))
    rule_set = ""
    for res in (resolutions or {}).values():
        if res.get("rule_set_version"):
            rule_set = str(res["rule_set_version"])
            break
    g.add((activity, RDF.type, PROV.Activity))
    g.add((activity, CL.ruleSetVersion, Literal(rule_set or "resolve_v3.0")))
    g.add((activity, DCTERMS.identifier, Literal(run_id)))

    narrative = _iri(case_id, "narrative")
    g.add((narrative, RDF.type, PROV.Entity))
    g.add((narrative, DCTERMS.identifier, Literal(case_id)))

    # The case IRI is the same node as cac:CACInvestigation. Sharing the
    # extraction activity with the annotations is the hop from case to evidence.
    case = BASE[f"case/{quote_part(case_id)}"]
    g.add((case, PROV.wasGeneratedBy, activity))
    g.add((case, PROV.wasDerivedFrom, narrative))

    agents: Dict[str, URIRef] = {}

    def agent_for(assertion: Dict[str, Any]) -> URIRef:
        method = str(assertion.get("method") or "unknown")
        family = str(assertion.get("family") or method)
        if method in agents:
            return agents[method]
        node = BASE[f"extractor/{quote_part(method)}"]
        g.add((node, RDF.type, PROV.SoftwareAgent))
        g.add((node, DCTERMS.identifier, Literal(method)))
        g.add((node, CL.evidenceFamily, Literal(family)))
        if assertion.get("method_version"):
            g.add((node, DCTERMS.hasVersion, Literal(str(assertion["method_version"]))))
        g.add((activity, PROV.wasAssociatedWith, node))
        agents[method] = node
        return node

    by_field: Dict[str, List[URIRef]] = {}
    ordered = sorted(
        [a for a in assertions if a.get("span_start") is not None and a.get("span_end") is not None],
        key=lambda a: (a.get("field") or "", int(a["span_start"]), str(a.get("method"))),
    )
    for index, assertion in enumerate(ordered, start=1):
        node = _iri(case_id, "assertion", str(index))
        field = str(assertion.get("field") or "")
        role = str(assertion.get("role") or "unknown")
        by_field.setdefault(field, []).append(node)
        g.add((node, RDF.type, OA.Annotation))
        g.add((node, RDF.type, CAC_CORE.AssessmentResult))
        g.add((node, RDFS.label, Literal(role)))
        g.add((node, DCTERMS.subject, Literal(field)))
        g.add((node, PROV.value, Literal(str(assertion.get("value")))))
        g.add((node, CAC_CORE.hasConfidence, _dec(assertion.get("confidence"))))
        if issued_at:
            g.add((node, CAC_CORE.issuedAtTime, Literal(issued_at, datatype=XSD.dateTimeStamp)))
        g.add((node, CAC_CORE.generatedBy, activity))
        g.add((node, CAC_CORE.usesMethod, agent_for(assertion)))
        g.add((node, CAC_CORE.assesses, narrative))
        g.add((node, PROV.wasGeneratedBy, activity))

        target = _iri(case_id, "assertion", str(index), "target")
        position = _iri(case_id, "assertion", str(index), "position")
        quote = _iri(case_id, "assertion", str(index), "quote")
        g.add((node, OA.hasTarget, target))
        g.add((target, RDF.type, OA.SpecificResource))
        g.add((target, OA.hasSource, narrative))
        g.add((target, OA.hasSelector, position))
        g.add((target, OA.hasSelector, quote))
        g.add((position, RDF.type, OA.TextPositionSelector))
        g.add((position, OA.start, Literal(int(assertion["span_start"]), datatype=XSD.nonNegativeInteger)))
        g.add((position, OA.end, Literal(int(assertion["span_end"]), datatype=XSD.nonNegativeInteger)))
        g.add((quote, RDF.type, OA.TextQuoteSelector))
        exact = assertion.get("span_text") or str(assertion.get("value") or "")
        g.add((quote, OA.exact, Literal(exact)))

    for field, res in sorted((resolutions or {}).items()):
        node = _iri(case_id, "resolution", quote_part(field))
        g.add((node, RDF.type, PROV.Entity))
        g.add((node, DCTERMS.subject, Literal(field)))
        g.add((node, CL.resolutionStatus, Literal(str(res.get("status") or "empty"))))
        g.add((node, CL.ruleSetVersion, Literal(str(res.get("rule_set_version") or rule_set or "resolve_v3.0"))))
        g.add((node, PROV.wasGeneratedBy, activity))
        for source in by_field.get(field, []):
            g.add((node, PROV.wasDerivedFrom, source))
    return g


def validate_provenance(graph: Graph) -> tuple[bool, str]:
    """Validate a provenance graph against caselinker-provenance-shapes.ttl."""
    from pyshacl import validate as shacl_validate

    shapes = Graph()
    shapes.parse(str(_SHAPES), format="turtle")
    conforms, _results, text = shacl_validate(
        data_graph=graph,
        shacl_graph=shapes,
        inference="none",
        advanced=False,
        allow_infos=True,
        abort_on_first=False,
    )
    return bool(conforms), text or ""


def graph_uses_case_roles(graph: Graph) -> bool:
    """True if this graph types anything as VictimRole or OffenderRole."""
    for role in _ROLE_TYPE.values():
        if any(graph.triples((None, RDF.type, role))):
            return True
    return False


def export_stored_case(case_id: str, output_dir: Path, storage: Any = None) -> Optional[Path]:
    """
    Write ``{case_id}.provenance.ttl`` beside a case export.

    ``storage`` is the SQLite or Postgres handle the case export already
    opened. When it is omitted, the same lookup is used: local SQLite if
    that file has the case, otherwise Postgres via DATABASE_URL.
    Returns None when that case has neither assertions nor resolutions.
    A resolution-only run (no assertion rows) still gets a graph: the
    extraction activity, the case hop, and one resolution entity per field.
    """
    if storage is None:
        if str(_ONTOLOGY) not in sys.path:
            sys.path.insert(0, str(_ONTOLOGY))
        from features_to_cac import CaseToCAC  # type: ignore

        storage = CaseToCAC._storage_for_case(case_id)
    if storage is None:
        return None
    payload = storage.get_case_assertions(case_id)
    assertions = payload.get("assertions") or []
    resolutions = payload.get("resolutions") or {}
    if not assertions and not resolutions:
        return None
    run_id = str(payload.get("run_id") or "")
    if not run_id:
        for res in resolutions.values():
            if res.get("run_id"):
                run_id = str(res["run_id"])
                break
    if not run_id:
        run_id = "unrecorded"
    started = None
    hook = getattr(storage, "extraction_run_started_at", None)
    if callable(hook) and run_id != "unrecorded":
        started = hook(run_id)
    # A run row can be missing after a manual re-resolve. SHACL still requires
    # cac-core:issuedAtTime on each assertion, so fall back to the resolution
    # timestamp the store already returned.
    if not started:
        for res in resolutions.values():
            stamp = res.get("resolved_at") or res.get("created_at")
            if stamp:
                started = stamp
                break
    if assertions and not started:
        raise RuntimeError(
            f"no extraction-run or resolution timestamp for {case_id} (run_id={run_id})"
        )
    graph = build_provenance_graph(
        case_id,
        assertions,
        resolutions,
        run_id=run_id,
        issued_at=str(started) if started else None,
    )
    conforms, report = validate_provenance(graph)
    if not conforms:
        raise RuntimeError(f"provenance SHACL failed for {case_id}: {report[:500]}")
    if graph_uses_case_roles(graph):
        raise RuntimeError(f"provenance graph for {case_id} typed a case role")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{case_id}.provenance.ttl"
    graph.serialize(destination=str(path), format="turtle")
    return path


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Write a provenance graph for one stored case.")
    parser.add_argument("case_id")
    parser.add_argument("--out", type=Path, default=_ONTOLOGY / "output")
    args = parser.parse_args()
    path = export_stored_case(args.case_id, args.out)
    if path is None:
        print(f"{args.case_id}: no stored assertions or resolutions")
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
