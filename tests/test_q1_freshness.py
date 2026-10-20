"""Q1 snapshot disclosures retain uncertainty and preserve returned evidence."""
from __future__ import annotations

import ast
import copy
from pathlib import Path
import sys
import unittest
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "run"))
from q1_freshness import snapshot_freshness, with_snapshot_freshness


class SnapshotFreshnessTests(unittest.TestCase):
    def test_recorded_build_scope_is_exposed_without_claiming_currentness(self):
        out = snapshot_freshness({
            "generated": "2026-09-15", "cases_processed": 3092,
            "db_gaps": 7308, "text_cap": 6000,
        })
        self.assertEqual(out["generated_at"], "2026-09-15")
        self.assertEqual(out["cases_processed"], 3092)
        self.assertEqual(out["db_gaps"], 7308)
        self.assertEqual(out["text_cap"], 6000)
        self.assertEqual(out["coverage_status"], "reported_gaps")
        self.assertFalse(out["current_corpus_verified"])
        self.assertIsNone(out["stale"])
        self.assertIsNone(out["coverage_pct"])

    def test_absent_or_malformed_metadata_remains_unknown(self):
        for meta in (None, {}, [], "missing", {"generated": False}):
            with self.subTest(meta=meta):
                out = snapshot_freshness(meta)
                self.assertEqual(out["status"], "unverified_snapshot")
                self.assertIsNone(out["generated_at"])
                self.assertIsNone(out["cases_processed"])
                self.assertEqual(out["coverage_status"], "unverified")

    def test_invalid_counts_are_not_coerced_into_evidence(self):
        for value in (True, False, -1, 1.5, "3092", float("nan")):
            with self.subTest(value=value):
                out = snapshot_freshness(dict.fromkeys(("cases_processed", "db_gaps", "text_cap"), value))
                for field in ("cases_processed", "db_gaps", "text_cap"):
                    self.assertIsNone(out[field])

    def test_zero_gaps_do_not_certify_a_fresh_or_complete_index(self):
        out = snapshot_freshness({"cases_processed": 0, "db_gaps": 0, "text_cap": 0})
        self.assertEqual(out["cases_processed"], 0)
        self.assertEqual(out["db_gaps"], 0)
        self.assertFalse(out["current_corpus_verified"])
        self.assertIsNone(out["stale"])
        self.assertEqual(out["coverage_status"], "unverified")

    def test_payload_and_metadata_are_not_mutated(self):
        payload = {"cases": [{"case_id": "synthetic_1", "tier": "stated", "evidence_quote": "Synthetic quote"}]}
        meta = {"generated": "2026-09-15", "db_gaps": 1}
        before = copy.deepcopy((payload, meta))
        out = with_snapshot_freshness(payload, meta)
        self.assertEqual((payload, meta), before)
        self.assertEqual(out["cases"], payload["cases"])
        self.assertEqual(out["_meta"], meta)
        self.assertNotIn("freshness", payload)


class SnapshotRouteLogicTests(unittest.TestCase):
    """Execute the real route functions without application startup or a database.

    Decorators and the loader are external boundaries; the route, platform
    selection and response construction execute unchanged from run/main.py.
    """
    def setUp(self):
        source = (ROOT / "run" / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {"_q1_resolve_platform_name", "_q1_platform_evidence_index",
                 "_q1_platform_evidence_cases", "api_q1_platform_evidence"}
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.assertEqual(len(functions), len(names))
        for function in functions:
            function.decorator_list = []
        self.data = {
            "_meta": {"generated": "2026-09-15", "cases_processed": 1, "db_gaps": 2},
            "records": [{"platform": "SyntheticChat", "case_id": "synthetic_1",
                         "stated_vs_inferred": "stated", "evidence_quote": "Synthetic source quote"}],
        }

        class RouteError(Exception):
            def __init__(self, status_code, detail):
                self.status_code, self.detail = status_code, detail

        self.error_type = RouteError
        namespace = {
            "Dict": Dict, "List": List, "Any": Any, "Optional": Optional,
            "Request": object, "Query": lambda default=None: default,
            "HTTPException": RouteError,
            "_Q1_VALID_TIERS": frozenset({"stated", "inferred", "named_only"}),
            "_load_q1_evidence": lambda: self.data,
            "with_snapshot_freshness": with_snapshot_freshness,
        }
        module = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
        exec(compile(module, str(ROOT / "run" / "main.py"), "exec"), namespace)
        self.route = namespace["api_q1_platform_evidence"]

    def test_index_response_has_snapshot_disclosure(self):
        out = self.route(None, None, None)
        self.assertEqual(out["platforms"][0]["case_count"], 1)
        self.assertEqual(out["freshness"]["cases_processed"], 1)
        self.assertEqual(out["_meta"], self.data["_meta"])

    def test_filtered_response_preserves_evidence_and_disclosure(self):
        out = self.route(None, "syntheticchat", "STATED")
        self.assertEqual(out["tier"], "stated")
        self.assertEqual(out["cases"][0]["evidence_quote"], "Synthetic source quote")
        self.assertEqual(out["freshness"]["coverage_status"], "reported_gaps")

    def test_invalid_tier_still_fails(self):
        with self.assertRaises(self.error_type) as raised:
            self.route(None, None, "unsupported")
        self.assertEqual(raised.exception.status_code, 400)

    def test_unknown_platform_still_fails(self):
        with self.assertRaises(self.error_type) as raised:
            self.route(None, "MissingChat", None)
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
