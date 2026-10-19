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
            result = dataset.query(query)
            body = result.serialize(format="turtle")
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/turtle")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}"


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
