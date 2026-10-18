"""Provenance graphs sit beside the CAC case graph and do not invent case roles."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from rdflib import RDF

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
    assert "https://caselinker.projectvic.org/resource/case/prov_sidecar_001" in case_jsonld
    assert "caselinker.up.railway.app/resource" not in case_jsonld
    path = result["provenance_ttl_path"]
    assert path, "provenance sidecar did not read the database that held the case"
    text = Path(path).read_text(encoding="utf-8")
    assert "prov_sidecar_001" in text
    assert "2026-10-17T18:00:00.000000Z" in text
    assert "https://caselinker.projectvic.org/resource/" in text
    graph = __import__("rdflib").Graph()
    graph.parse(path, format="turtle")
    conforms, report = validate_provenance(graph)
    assert conforms, report
    assert graph_uses_case_roles(graph) is False


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
