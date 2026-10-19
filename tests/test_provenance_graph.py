"""Provenance graphs sit beside the CAC case graph and do not invent case roles."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from rdflib import RDF, URIRef

REPO = Path(__file__).resolve().parents[1]
ONTOLOGY = REPO / "ontology"
sys.path.insert(0, str(ONTOLOGY))

from features_to_cac import AZICAC_2011_006_FIXTURE, CaseToCAC  # noqa: E402
from provenance_export import (  # noqa: E402
    CAC_CORE,
    CL,
    OA,
    PROV,
    build_provenance_graph,
    graph_uses_case_roles,
    validate_provenance,
)

pytest.importorskip("pyshacl")


def _sample():
    assertions = [
        {
            "field": "age", "method": "regex", "method_version": "regex_3.0.1",
            "family": "surface_pattern", "value": 40, "role": "perpetrator",
            "span_start": 10, "span_end": 12, "span_text": "40", "confidence": 0.9,
        },
        {
            "field": "age", "method": "regex", "method_version": "regex_3.0.1",
            "family": "surface_pattern", "value": 14, "role": "decoy",
            "span_start": 40, "span_end": 42, "span_text": "14", "confidence": 0.9,
        },
    ]
    resolutions = {
        "age": {
            "status": "partial",
            "rule_set_version": "resolve_v3.0",
            "final_value": {"victims": [], "perpetrators": [40], "contested": {}},
        }
    }
    return assertions, resolutions


def test_resolution_only_graph_has_the_case_hop_and_no_annotations():
    """An extraction that stored empty resolutions and no assertions still exports."""
    graph = build_provenance_graph(
        "brazil_pf_2026_001",
        [],
        {
            "age": {
                "status": "empty",
                "rule_id": "no_assertions",
                "rule_set_version": "resolve_v3.0",
                "run_id": "run_empty",
            },
            "sentence": {
                "status": "empty",
                "rule_id": "no_assertions",
                "rule_set_version": "resolve_v3.0",
                "run_id": "run_empty",
            },
        },
        run_id="run_empty",
    )
    conforms, report = validate_provenance(graph)
    assert conforms, report
    assert graph_uses_case_roles(graph) is False
    assert not any(graph.triples((None, RDF.type, OA.Annotation)))
    case = URIRef("https://w3id.org/caselinker/resource/case/brazil_pf_2026_001")
    activity = next(graph.subjects(RDF.type, PROV.Activity))
    assert (case, PROV.wasGeneratedBy, activity) in graph
    statuses = {str(o) for o in graph.objects(None, CL.resolutionStatus)}
    assert statuses == {"empty"}


def test_export_writes_sidecar_for_resolution_only_case(tmp_path):
    class _Store:
        def get_case_assertions(self, case_id, field=None):
            return {
                "case_id": case_id,
                "run_id": "run_empty",
                "assertions": [],
                "resolutions": {
                    "age": {
                        "status": "empty",
                        "rule_id": "no_assertions",
                        "rule_set_version": "resolve_v3.0",
                        "run_id": "run_empty",
                    }
                },
            }

        def extraction_run_started_at(self, run_id):
            return "2026-10-18T04:51:27.469384Z"

    path = __import__("provenance_export").export_stored_case(
        "brazil_pf_2026_001", tmp_path, _Store()
    )
    assert path is not None
    graph = __import__("rdflib").Graph()
    graph.parse(path, format="turtle")
    conforms, report = validate_provenance(graph)
    assert conforms, report
    assert not any(graph.triples((None, RDF.type, OA.Annotation)))


def test_provenance_graph_validates_and_keeps_decoys_off_case_roles():
    graph = build_provenance_graph(
        "example_case", *_sample(), run_id="run_test", issued_at="2026-10-17T18:00:00.000000Z"
    )
    conforms, report = validate_provenance(graph)
    assert conforms, report
    assert graph_uses_case_roles(graph) is False
    labels = {str(o) for o in graph.objects(None, __import__("rdflib").RDFS.label)}
    assert "decoy" in labels
    assert "perpetrator" in labels
    assert any(graph.triples((None, RDF.type, PROV.Activity)))
    assert any(graph.triples((None, RDF.type, PROV.SoftwareAgent)))
    assert any(graph.triples((None, RDF.type, OA.TextPositionSelector)))
    assert any(graph.triples((None, RDF.type, OA.TextQuoteSelector)))
    assert any(graph.triples((None, CAC_CORE.hasConfidence, None)))
    assert any(graph.triples((None, CAC_CORE.issuedAtTime, None)))
    assert any(graph.triples((None, CL.evidenceFamily, None)))
    assert any(graph.triples((None, CL.resolutionStatus, None)))
    assert any(graph.triples((None, CL.ruleSetVersion, None)))
    case = URIRef("https://w3id.org/caselinker/resource/case/example_case")
    narrative = URIRef("https://w3id.org/caselinker/resource/case/example_case/narrative")
    activity = next(graph.subjects(RDF.type, PROV.Activity))
    assert (case, PROV.wasGeneratedBy, activity) in graph
    assert (case, PROV.wasDerivedFrom, narrative) in graph
    assert any(graph.triples((None, PROV.wasGeneratedBy, activity)))


class _SidecarStore:
    """Stand-in for the database case export actually read. Not caselinker.db."""

    def get_case(self, case_id):
        if case_id != "prov_sidecar_001":
            return None
        case = dict(AZICAC_2011_006_FIXTURE)
        case["id"] = case_id
        return case

    def get_case_assertions(self, case_id, field=None):
        return {
            "case_id": case_id,
            "run_id": "run_prov_sidecar",
            "assertions": [
                {
                    "field": "age", "method": "regex", "method_version": "regex_3.0.1",
                    "family": "surface_pattern", "value": 41, "role": "perpetrator",
                    "span_start": 10, "span_end": 12, "span_text": "41", "confidence": 0.9,
                }
            ],
            "resolutions": {
                "age": {
                    "status": "resolved",
                    "rule_set_version": "resolve_v3.0",
                    "final_value": {"perpetrators": [41]},
                }
            },
        }

    def extraction_run_started_at(self, run_id):
        assert run_id == "run_prov_sidecar"
        return "2026-10-17T18:00:00.000000Z"


def test_provenance_sidecar_reads_the_store_the_case_export_uses(tmp_path, monkeypatch):
    """A deploy that loads the case from Postgres must not open repo caselinker.db."""
    store = _SidecarStore()
    monkeypatch.setattr(CaseToCAC, "_open_local_sqlite", staticmethod(lambda: None))
    monkeypatch.setattr(CaseToCAC, "_open_postgres", staticmethod(lambda db_url=None: store))
    result = CaseToCAC().export_case("prov_sidecar_001", output_dir=tmp_path)
    assert result["shacl_conforms"], result["shacl_report"]
    # rdflib serializes a Dataset to Turtle as an empty default graph.
    # The JSON-LD file is the fixture graph this export actually writes.
    case_jsonld = Path(result["jsonld_path"]).read_text(encoding="utf-8")
    assert "https://w3id.org/caselinker/resource/case/prov_sidecar_001" in case_jsonld
    assert "https://w3id.org/caselinker/resource/case/prov_sidecar_001/provenance" in case_jsonld
    assert "caselinker.projectvic.org/resource" not in case_jsonld
    assert "caselinker.up.railway.app/resource" not in case_jsonld
    path = result["provenance_ttl_path"]
    assert path, "provenance sidecar did not read the database that held the case"
    text = Path(path).read_text(encoding="utf-8")
    assert "prov_sidecar_001" in text
    assert "2026-10-17T18:00:00.000000Z" in text
    assert "https://w3id.org/caselinker/resource/" in text
    assert "https://w3id.org/caselinker/ns/provenance#" in text
    assert "caselinker.up.railway.app/ns/provenance" not in text
    graph = __import__("rdflib").Graph()
    graph.parse(path, format="turtle")
    conforms, report = validate_provenance(graph)
    assert conforms, report
    assert graph_uses_case_roles(graph) is False


def test_export_turtle_contains_the_named_graph_triples(tmp_path, monkeypatch):
    """Serializing the Dataset writes an empty Turtle file. export_case must not."""
    from rdflib import Graph

    mapper = CaseToCAC()
    dataset, _warnings = mapper.map_case(AZICAC_2011_006_FIXTURE)
    empty = tmp_path / "dataset.ttl"
    dataset.serialize(destination=str(empty), format="turtle")
    assert empty.stat().st_size < 20

    case = dict(AZICAC_2011_006_FIXTURE)

    class _Store:
        def get_case(self, case_id):
            return case

        def get_case_assertions(self, case_id, field=None):
            return {"assertions": [], "resolutions": {}, "run_id": None}

    monkeypatch.setattr(CaseToCAC, "_storage_for_case", staticmethod(lambda *a, **k: _Store()))
    result = mapper.export_case("azicac_2011_006", output_dir=tmp_path)
    parsed = Graph()
    parsed.parse(result["ttl_path"], format="turtle")
    assert len(parsed) > 0


def test_existing_case_graph_still_validates_and_still_has_roles():
    mapper = CaseToCAC()
    graph, _warnings = mapper.map_case(AZICAC_2011_006_FIXTURE)
    conforms, report = mapper.validate(graph)
    assert conforms, report
    types = set()
    for ctx in graph.graphs():
        for obj in ctx.objects(None, RDF.type):
            types.add(obj)
    assert mapper_has(types, "VictimRole")
    assert mapper_has(types, "OffenderRole")


def mapper_has(types, local: str) -> bool:
    return any(str(t).endswith(local) or str(t).endswith("#" + local) for t in types)
