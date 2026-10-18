"""A reused case id must not surface an earlier extraction run."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORAGE = ROOT / "src" / "Storage Layer"
if str(STORAGE) not in sys.path:
    sys.path.insert(0, str(STORAGE))

from assertion_store import write_case_assertions  # noqa: E402
from storage import CaseStorage  # noqa: E402


def _assertion(span_text: str, field: str = "age") -> dict:
    return {
        "field": field,
        "method": "regex",
        "method_version": "test",
        "family": "surface_pattern",
        "value": 57,
        "role": "perpetrator",
        "span_start": 0,
        "span_end": len(span_text),
        "span_text": span_text,
        "span_ok": True,
        "confidence": 0.9,
        "extras": {},
    }


def _resolution(field: str, status: str, marker: str) -> dict:
    return {
        field: {
            "rule_set_version": "resolve_v3.0",
            "status": status,
            "rule_id": marker,
            "final_value": {"marker": marker},
            "winning_assertion_ids": [],
            "disagreement": {},
            "review": [{"reason": marker}] if status == "needs_review" else [],
        }
    }


def test_readers_ignore_an_earlier_run_on_the_same_case_id(tmp_path: Path):
    storage = CaseStorage(str(tmp_path / "t.db"))
    storage.store_case({
        "id": "doj_safe_childhood_2026_001",
        "source": "DOJ SAFE CHILDHOOD",
        "source_url": "https://www.justice.gov/example",
        "raw_data": {
            "source_file": "DOJ_SAFE_CHILDHOOD.pdf",
            "case_text": "NEW ARTICLE sixty months",
            "case_id": "doj_safe_childhood_2026_001",
        },
    })
    conn = sqlite3.connect(tmp_path / "t.db")
    cur = conn.cursor()
    old_human = _assertion("OLD HUMAN")
    old_human["method"] = "human"
    old_human["family"] = "human"
    write_case_assertions(
        cur,
        case_id="doj_safe_childhood_2026_001",
        run_id="run-old",
        assertions=[_assertion("OLD ARTICLE"), old_human],
        resolutions=_resolution("age", "needs_review", "old-article"),
        dialect="sqlite",
    )
    write_case_assertions(
        cur,
        case_id="doj_ceos_gone",
        run_id="run-ghost",
        assertions=[_assertion("GHOST ARTICLE")],
        resolutions=_resolution("age", "needs_review", "ghost"),
        dialect="sqlite",
    )
    write_case_assertions(
        cur,
        case_id="doj_safe_childhood_2026_001",
        run_id="run-new",
        assertions=[_assertion("NEW ARTICLE", field="sentence")],
        resolutions=_resolution("sentence", "resolved", "new-article"),
        dialect="sqlite",
    )
    conn.commit()
    conn.close()

    out = storage.get_case_assertions("doj_safe_childhood_2026_001")
    spans = [a.get("span_text") for a in out["assertions"]]
    assert spans == ["NEW ARTICLE"]
    assert out["run_id"] == "run-new"
    assert set(out["resolutions"]) == {"sentence"}
    assert out["resolutions"]["sentence"]["run_id"] == "run-new"

    disagreements = storage.get_field_disagreements()
    listed = {item["case_id"] for item in disagreements["items"]}
    assert "doj_safe_childhood_2026_001" not in listed
    assert "doj_ceos_gone" not in listed
