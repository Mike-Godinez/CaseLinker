#!/usr/bin/env python3
"""Shared CaseLinker → JSON-LD/TTL graph generation (features_to_cac)."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY = REPO_ROOT / "ontology"
DEFAULT_GRAPH_DIR = ONTOLOGY / "graph_output"

sys.path.insert(0, str(ONTOLOGY))


def generate_graphs(
    ids: List[str],
    out_dir: Path,
    *,
    validate_shacl: bool = True,
) -> Dict[str, Any]:
    from features_to_cac import CaseToCAC, _load_case_with_fallback  # noqa: E402
    from rdflib import Graph

    out_dir.mkdir(parents=True, exist_ok=True)
    mapper = CaseToCAC()

    generated: List[str] = []
    skipped: List[Dict[str, str]] = []
    failed: List[Dict[str, str]] = []
    shacl_ok: List[str] = []
    shacl_fail: List[Dict[str, Any]] = []

    for i, cid in enumerate(ids, 1):
        try:
            case, src = _load_case_with_fallback(cid)
            if case is None:
                skipped.append({"case_id": cid, "reason": "not in DB"})
                continue

            graph, _warnings = mapper.map_case(case)
            conforms, shacl_report = True, ""
            if validate_shacl:
                conforms, shacl_report = mapper.validate(graph)

            jsonld_path = out_dir / f"{cid}.jsonld"
            ttl_path = out_dir / f"{cid}.ttl"
            graph.serialize(destination=str(jsonld_path), format="json-ld", indent=2)
            flat_g = Graph()
            for ctx in graph.graphs():
                for triple in ctx:
                    flat_g.add(triple)
            for prefix, ns in graph.namespaces():
                flat_g.bind(prefix, ns, replace=True)
            flat_g.serialize(destination=str(ttl_path), format="turtle")

            if validate_shacl and not conforms:
                shacl_fail.append({"case_id": cid, "shacl_report": (shacl_report or "")[:4000]})
            else:
                shacl_ok.append(cid)
            generated.append(cid)

        except Exception as exc:
            failed.append(
                {
                    "case_id": cid,
                    "reason": str(exc),
                    "traceback": traceback.format_exc()[-1500:],
                }
            )
            print(f"  FAIL {cid}: {exc}", file=sys.stderr)

        if i % 50 == 0:
            print(
                f"  [{i}/{len(ids)}] generated={len(generated)} "
                f"shacl_ok={len(shacl_ok)} fail={len(failed)}",
                flush=True,
            )

    return {
        "generated": generated,
        "skipped": skipped,
        "failed": failed,
        "shacl_ok": shacl_ok,
        "shacl_fail": shacl_fail,
        "out_dir": str(out_dir),
    }


def generate_graph_for_ids(case_ids: List[str]) -> Dict[str, Any]:
    """
    Build a merged in-memory CAC ontology graph for specific case IDs.

    Uses the same DB loaders and CaseToCAC mapper as the batch pipeline but
    does not write JSON-LD/TTL files or mutate the database.

    When a case is missing locally, falls back to GET /api/cases/{id} when
    CASELINKER_API_URL is set (aligns MCP stdio dev with the remote corpus).
    """
    import json
    import os

    import requests

    from features_to_cac import CaseToCAC, _load_case_with_fallback  # noqa: E402
    from graph_utils import flat_nodes_to_nodes_edges  # noqa: E402
    from merge_graph_cache import merge_case_into_store  # noqa: E402

    def _load_case(case_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
        case, src = _load_case_with_fallback(case_id)
        if case is not None:
            return case, src
        api_url = os.getenv("CASELINKER_API_URL", "").strip().rstrip("/")
        if not api_url:
            return None, "missing"
        headers = {"Accept": "application/json"}
        key = os.getenv("CASELINKER_KEY", "").strip()
        if key:
            headers["CaseLinker-Key"] = key
        try:
            resp = requests.get(f"{api_url}/api/cases/{case_id}", headers=headers, timeout=30)
            if resp.status_code == 200:
                return resp.json(), "api"
        except requests.RequestException:
            pass
        return None, "missing"

    requested = [str(cid).strip() for cid in case_ids if cid and str(cid).strip()]
    mapper = CaseToCAC()
    store: Dict[str, Dict[str, Any]] = {}
    mapped: List[str] = []
    skipped: List[Dict[str, str]] = []

    for cid in requested:
        case, src = _load_case(cid)
        if case is None:
            skipped.append({"case_id": cid, "reason": "not in DB or API"})
            continue
        graph, _warnings = mapper.map_case(case)
        jsonld_str = graph.serialize(format="json-ld")
        doc = json.loads(jsonld_str)
        merge_case_into_store(store, cid, doc)
        mapped.append(cid)

    flat = list(store.values())
    for node in flat:
        node["_isShared"] = len(node.get("_cases") or []) > 1

    nodes, edges = flat_nodes_to_nodes_edges(flat)
    metadata = {
        "requested_count": len(requested),
        "cases_mapped": mapped,
        "skipped": skipped,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }
    return {"nodes": nodes, "edges": edges, "metadata": metadata, "flat_nodes": flat}


def load_all_case_ids(db_path: Optional[Path] = None) -> List[str]:
    import sqlite3

    db = db_path or (REPO_ROOT / "caselinker.db")
    if not db.is_file():
        raise FileNotFoundError(f"Database not found: {db}")
    conn = sqlite3.connect(str(db))
    try:
        return [r[0] for r in conn.execute("SELECT id FROM cases ORDER BY id").fetchall()]
    finally:
        conn.close()
