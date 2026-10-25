"""GET /resource and /ns/provenance describe a local Oxigraph-shaped store."""

from __future__ import annotations

import importlib.util
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import rdflib
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "run"
CASE_ID = "doj_archives_2003_011"
CASE_IRI = f"https://w3id.org/caselinker/resource/case/{CASE_ID}"
PROV_IRI = CASE_IRI + "/provenance"


def _load_main():
    spec = importlib.util.spec_from_file_location("caselinker_run_main_deref", RUN / "main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["caselinker_run_main_deref"] = module
    spec.loader.exec_module(module)
    return module


def _store() -> rdflib.Dataset:
    dataset = rdflib.Dataset()
    case_path = ROOT / "ontology" / "graph_output" / f"{CASE_ID}.ttl"
    prov_path = ROOT / "ontology" / "graph_output" / f"{CASE_ID}.provenance.ttl"
    dataset.graph(rdflib.URIRef(CASE_IRI)).parse(case_path, format="turtle")
    dataset.graph(rdflib.URIRef(PROV_IRI)).parse(prov_path, format="turtle")
    return dataset


def _serve(dataset: rdflib.Dataset) -> str:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            query = self.rfile.read(length).decode("utf-8")
            accept = (self.headers.get("Accept") or "text/turtle").split(",")[0].strip()
            result = dataset.query(query)
            if "sparql-results+json" in accept or result.type == "SELECT":
                body = result.serialize(format="json")
                content_type = "application/sparql-results+json"
            else:
                body = result.serialize(format="turtle")
                content_type = "text/turtle"
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}"


def test_provenance_html_title_names_the_case_not_first_assertion():
    sys.path.insert(0, str(RUN))
    sys.path.insert(0, str(ROOT / "ontology"))
    import deref
    from provenance_export import build_provenance_graph

    # Fresh graph so labels/order match the exporter under test (not a stale TTL).
    graph = build_provenance_graph(
        CASE_ID,
        [
            {
                "field": "age",
                "method": "regex",
                "family": "surface_pattern",
                "value": 30,
                "role": "perpetrator",
                "span_start": 10,
                "span_end": 12,
                "span_text": "30",
                "confidence": 0.9,
            },
            {
                "field": "age",
                "method": "regex",
                "family": "surface_pattern",
                "value": 14,
                "role": "decoy",
                "span_start": 40,
                "span_end": 42,
                "span_text": "14",
                "confidence": 0.9,
            },
        ],
        {"age": {"status": "partial", "rule_set_version": "resolve_v3.0"}},
        run_id="run_deref_order",
        issued_at="2026-10-17T18:00:00.000000Z",
    )
    page = deref.render_html(graph, focus=PROV_IRI)
    assert f"<h1>Provenance · {CASE_ID}</h1>" in page
    assert page.count(f"<h1>Provenance · {CASE_ID}</h1>") == 1
    assert "<h2>age 30 · perpetrator</h2>" in page
    assert "<h2>passage · age 30 · perpetrator</h2>" in page
    assert "target ·" not in page
    assert "assertionRole" in page
    # Assertion section appears before its passage and selectors.
    a = page.find("<h2>age 30 · perpetrator</h2>")
    p = page.find("<h2>passage · age 30 · perpetrator</h2>")
    pos = page.find("<h2>position 10–12</h2>")
    assert a != -1 and p != -1 and pos != -1
    assert a < p < pos


def test_case_html_title_is_case_id_with_classic_section_layout():
    sys.path.insert(0, str(RUN))
    import deref

    graph = rdflib.Graph()
    graph.parse(ROOT / "ontology" / "graph_output" / f"{CASE_ID}.ttl", format="turtle")
    page = deref.render_html(graph, focus=CASE_IRI)
    assert f"<h1>{CASE_ID}</h1>" in page
    # Classic layout: focus node is a section with h2 + self IRI link (not a top-level .iri strip).
    assert f"<h2>" in page
    assert f'href="{CASE_IRI}"' in page
    assert 'class="iri"' not in page
    assert ">provenance</th>" in page
    assert ">type</th>" in page


def test_provenance_vocabulary_is_html_for_browsers_and_turtle_for_clients(monkeypatch):
    monkeypatch.setenv("OXIGRAPH_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    main = _load_main()
    # No lifespan: startup would open the configured database.
    client = TestClient(main.app)
    page = client.get("/ns/provenance", headers={"Accept": "text/html"})
    turtle = client.get("/ns/provenance", headers={"Accept": "text/turtle"})
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "evidence family" in page.text
    assert "resolution status" in page.text
    assert "rule set version" in page.text
    assert turtle.status_code == 200
    assert "text/turtle" in turtle.headers["content-type"]
    assert "owl:Ontology" in turtle.text
    assert 'owl:versionInfo "3.1"' in turtle.text
    assert "caselinker:evidenceFamily" in turtle.text


def test_resource_route_negotiates_a_local_store_and_links_cac_classes(monkeypatch):
    base = _serve(_store())
    monkeypatch.setenv("OXIGRAPH_URL", base)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    main = _load_main()
    client = TestClient(main.app)
    turtle = client.get(f"/resource/case/{CASE_ID}", headers={"Accept": "text/turtle"})
    page = client.get(f"/resource/case/{CASE_ID}", headers={"Accept": "text/html"})
    data = client.get(f"/resource/case/{CASE_ID}", headers={"Accept": "application/ld+json"})
    place = client.get("/resource/location/indiana", headers={"Accept": "text/turtle"})
    prov = client.get(f"/resource/case/{CASE_ID}/provenance", headers={"Accept": "text/turtle"})
    missing = client.get("/resource/case/no_such_case", headers={"Accept": "text/turtle"})
    assert turtle.status_code == 200 and CASE_IRI in turtle.text
    assert "text/html" in page.headers["content-type"]
    assert 'href="https://cacontology.projectvic.org' in page.text
    assert data.status_code == 200 and "application/ld+json" in data.headers["content-type"]
    assert CASE_IRI in data.text
    assert place.status_code == 200 and "indiana" in place.text.lower()
    assert "cacontology.projectvic.org" in place.text
    assert prov.status_code == 200 and "resolve_v3.0" in prov.text
    assert missing.status_code == 404


def test_hub_page_lists_cases_referencing_this(monkeypatch):
    """Agency/platform/location HTML includes a reverse case list from SPARQL."""
    base = _serve(_store())
    monkeypatch.setenv("OXIGRAPH_URL", base)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    main = _load_main()
    client = TestClient(main.app)
    place = client.get("/resource/location/indiana", headers={"Accept": "text/html"})
    assert place.status_code == 200
    assert "Cases referencing this" in place.text
    assert CASE_ID in place.text
    assert f'href="/resource/case/{CASE_ID}"' in place.text


def test_referencing_cases_query_targets_press_release_graphs_only():
    sys.path.insert(0, str(RUN))
    import deref

    iri = "https://w3id.org/caselinker/resource/location/cumberland-county"
    q = deref.referencing_cases_query(iri)
    assert iri in q
    assert 'STRSTARTS(STR(?g), "https://w3id.org/caselinker/resource/case/")' in q
    assert '!STRENDS(STR(?g), "/provenance")' in q
    assert deref.is_hub_resource(iri)
    assert not deref.is_hub_resource(CASE_IRI)
