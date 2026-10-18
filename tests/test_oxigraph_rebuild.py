"""Canonical TTL selection and N-Quads named-graph build."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
if str(ONTOLOGY) not in sys.path:
    sys.path.insert(0, str(ONTOLOGY))

from oxigraph_rebuild import (  # noqa: E402
    CASE_GRAPH_BASE,
    build_nquads,
    canonical_ttl_paths,
    case_graph_iri,
    pool_label_for_path,
    provenance_graph_iri,
)


def _write_ttl(path: Path, subject: str, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        f"<{subject}> rdfs:label \"{label}\" .\n",
        encoding="utf-8",
    )


def test_canonical_priority_universe_over_staging_big_bang_analysis(tmp_path: Path):
    shared = "case_shared"
    _write_ttl(tmp_path / "universe" / f"{shared}.ttl", "http://ex.org/u", "universe")
    _write_ttl(tmp_path / f"{shared}.ttl", "http://ex.org/s", "staging")
    _write_ttl(tmp_path / "big_bang" / f"{shared}.ttl", "http://ex.org/b", "big_bang")
    _write_ttl(tmp_path / "analysis" / f"{shared}.ttl", "http://ex.org/a", "analysis")

    _write_ttl(tmp_path / "only_staging.ttl", "http://ex.org/st", "staging-only")
    _write_ttl(tmp_path / "big_bang" / "only_bang.ttl", "http://ex.org/bb", "bang-only")
    _write_ttl(tmp_path / "analysis" / "only_analysis.ttl", "http://ex.org/an", "analysis-only")

    chosen = canonical_ttl_paths(tmp_path)
    assert chosen[shared] == tmp_path / "universe" / f"{shared}.ttl"
    assert chosen["only_staging"] == tmp_path / "only_staging.ttl"
    assert chosen["only_bang"] == tmp_path / "big_bang" / "only_bang.ttl"
    assert chosen["only_analysis"] == tmp_path / "analysis" / "only_analysis.ttl"
    assert pool_label_for_path(chosen[shared]) == "universe"
    assert pool_label_for_path(chosen["only_staging"], graph_root=tmp_path) == "staging"


def test_canonical_includes_pacer_pool_without_colliding_press_release(tmp_path: Path):
    case_id = "ky_sp_2025_038"
    _write_ttl(
        tmp_path / "universe" / f"{case_id}.ttl",
        "http://ex.org/pr",
        "press-release",
    )
    _write_ttl(
        tmp_path / "pacer" / f"pacer_{case_id}.ttl",
        "http://ex.org/pacer",
        "pacer",
    )

    chosen = canonical_ttl_paths(tmp_path)
    assert chosen[case_id] == tmp_path / "universe" / f"{case_id}.ttl"
    assert chosen[f"pacer_{case_id}"] == tmp_path / "pacer" / f"pacer_{case_id}.ttl"
    assert pool_label_for_path(chosen[f"pacer_{case_id}"]) == "pacer"


def test_build_nquads_uses_per_case_named_graph(tmp_path: Path):
    ttl = tmp_path / "universe" / "nj_ag_2017_001.ttl"
    _write_ttl(
        ttl,
        "https://w3id.org/caselinker/resource/case/nj_ag_2017_001",
        "fixture",
    )
    out = tmp_path / "out.nq"
    result = build_nquads({"nj_ag_2017_001": ttl}, out)
    assert result["cases_loaded"] == 1
    assert result["provenance_loaded"] == 0
    assert result["quads"] == 1
    text = out.read_text(encoding="utf-8")
    graph_iri = str(case_graph_iri("nj_ag_2017_001"))
    assert graph_iri == CASE_GRAPH_BASE + "nj_ag_2017_001"
    assert graph_iri in text
    # Fourth N-Quads slot is the named graph.
    assert text.strip().endswith(f"<{graph_iri}> .")


def test_provenance_sidecar_loads_beside_the_chosen_case_only(tmp_path: Path):
    case_id = "nj_ag_2017_001"
    _write_ttl(
        tmp_path / "universe" / f"{case_id}.ttl",
        f"https://w3id.org/caselinker/resource/case/{case_id}",
        "case",
    )
    _write_ttl(
        tmp_path / "universe" / f"{case_id}.provenance.ttl",
        f"https://w3id.org/caselinker/resource/case/{case_id}/assertion/1",
        "provenance",
    )
    _write_ttl(tmp_path / f"{case_id}.provenance.ttl", "http://ex.org/stale", "stale")
    _write_ttl(tmp_path / "orphan.provenance.ttl", "http://ex.org/orphan", "orphan")

    chosen = canonical_ttl_paths(tmp_path)
    assert list(chosen) == [case_id]
    out = tmp_path / "out.nq"
    result = build_nquads(chosen, out)
    assert result["cases_loaded"] == 1
    assert result["provenance_loaded"] == 1
    assert result["provenance_failed"] == []
    text = out.read_text(encoding="utf-8")
    case_iri = str(case_graph_iri(case_id))
    prov_iri = str(provenance_graph_iri(case_id))
    assert prov_iri == case_iri + "/provenance"
    assert f"<{prov_iri}>" in text
    assert "stale" not in text
    assert "orphan" not in text
    case_lines = [line for line in text.splitlines() if line.endswith(f"<{case_iri}> .")]
    prov_lines = [line for line in text.splitlines() if line.endswith(f"<{prov_iri}> .")]
    assert len(case_lines) == 1
    assert len(prov_lines) == 1
    assert "assertion/1" in prov_lines[0]
    assert "assertion/1" not in case_lines[0]


def test_broken_provenance_sidecar_does_not_drop_the_case(tmp_path: Path):
    case_id = "nj_ag_2017_001"
    _write_ttl(
        tmp_path / f"{case_id}.ttl",
        f"https://w3id.org/caselinker/resource/case/{case_id}",
        "case",
    )
    (tmp_path / f"{case_id}.provenance.ttl").write_text("this is not turtle {\n", encoding="utf-8")
    out = tmp_path / "out.nq"
    result = build_nquads({case_id: tmp_path / f"{case_id}.ttl"}, out)
    assert result["cases_loaded"] == 1
    assert result["provenance_loaded"] == 0
    assert result["provenance_failed"][0]["case_id"] == case_id
    assert str(case_graph_iri(case_id)) in out.read_text(encoding="utf-8")


def test_rebuild_lock_round_trip(monkeypatch, tmp_path: Path):
    run = ROOT / "run"
    if str(run) not in sys.path:
        sys.path.insert(0, str(run))
    import sparql_rebuild_lock as lock

    path = tmp_path / "rebuild.lock"
    monkeypatch.setenv("SPARQL_REBUILD_LOCK", str(path))
    assert lock.rebuild_in_progress() is False
    lock.acquire_rebuild_lock()
    assert path.is_file()
    assert lock.rebuild_in_progress() is True
    lock.release_rebuild_lock()
    assert lock.rebuild_in_progress() is False
    assert not path.exists()
