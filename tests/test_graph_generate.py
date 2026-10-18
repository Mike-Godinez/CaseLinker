"""graph_generate writes flattened Turtle and a resume file."""

from __future__ import annotations

import sys
from pathlib import Path

from rdflib import Dataset, Literal, URIRef

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
if str(ONTOLOGY) not in sys.path:
    sys.path.insert(0, str(ONTOLOGY))

import features_to_cac  # noqa: E402
import graph_generate  # noqa: E402


class _Storage:
    def __init__(self):
        self.calls = []

    def get_case(self, case_id):
        self.calls.append(case_id)
        return {"id": case_id}

    def get_case_assertions(self, case_id, field=None):
        return {"case_id": case_id, "run_id": None, "assertions": [], "resolutions": {}}


def _dataset(case_id: str, iri: str) -> Dataset:
    ds = Dataset()
    graph = ds.graph(URIRef(f"https://example.org/graph/{case_id}"))
    graph.add((URIRef(iri), URIRef("http://www.w3.org/2000/01/rdf-schema#label"), Literal(case_id)))
    return ds


class _GoodMapper:
    def map_case(self, case):
        cid = case["id"]
        return _dataset(cid, f"https://w3id.org/caselinker/resource/case/{cid}"), []

    def validate(self, _graph):
        return True, ""


class _RejectedIriMapper:
    def __init__(self, iri: str):
        self.iri = iri

    def map_case(self, case):
        cid = case["id"]
        return _dataset(cid, self.iri.format(cid=cid)), []

    def validate(self, _graph):
        return True, ""


def test_generate_writes_turtle_and_resumes(tmp_path, monkeypatch):
    monkeypatch.setattr(features_to_cac, "CaseToCAC", _GoodMapper)
    out = tmp_path / "graphs"
    storage = _Storage()
    first = graph_generate.generate_graphs(
        ["aa_2020_001", "aa_2020_002"],
        out,
        provenance=True,
        storage=storage,
    )
    assert first["generated"] == ["aa_2020_001", "aa_2020_002"]
    assert first["no_provenance"] == ["aa_2020_001", "aa_2020_002"]
    turtle = (out / "aa_2020_001.ttl").read_text()
    assert "w3id.org/caselinker/resource/case/aa_2020_001" in turtle
    assert (out / "done.txt").read_text().splitlines() == ["aa_2020_001", "aa_2020_002"]

    again = _Storage()
    second = graph_generate.generate_graphs(
        ["aa_2020_001", "aa_2020_002"],
        out,
        provenance=True,
        storage=again,
    )
    assert second["generated"] == []
    assert again.calls == []


def test_projectvic_resource_iri_is_not_marked_done(tmp_path, monkeypatch):
    monkeypatch.setattr(
        features_to_cac,
        "CaseToCAC",
        lambda: _RejectedIriMapper("https://caselinker.projectvic.org/resource/case/{cid}"),
    )
    out = tmp_path / "graphs"
    result = graph_generate.generate_graphs(
        ["bb_2020_001"],
        out,
        provenance=False,
        storage=_Storage(),
    )
    assert result["generated"] == []
    assert result["failed"][0]["case_id"] == "bb_2020_001"
    assert "projectvic IRI" in result["failed"][0]["reason"]
    assert not (out / "done.txt").exists()


def test_railway_resource_iri_is_not_marked_done(tmp_path, monkeypatch):
    monkeypatch.setattr(
        features_to_cac,
        "CaseToCAC",
        lambda: _RejectedIriMapper("https://caselinker.up.railway.app/resource/case/{cid}"),
    )
    out = tmp_path / "graphs"
    result = graph_generate.generate_graphs(
        ["cc_2020_001"],
        out,
        provenance=False,
        storage=_Storage(),
    )
    assert result["generated"] == []
    assert "railway resource IRI" in result["failed"][0]["reason"]
    assert not (out / "done.txt").exists()
