"""Derived prosecuting jurisdiction: federal / state / unknown, never guessed (#29)."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from caselinker_mcp import server
from storage import CaseStorage

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "run") not in sys.path:
    sys.path.insert(0, str(ROOT / "run"))

from case_jurisdiction import derive_jurisdiction  # noqa: E402

FEDERAL = "Assistant U.S. Attorney Jane Roe prosecuted the case before U.S. District Judge Smith under 18 U.S.C. 2252."
STATE = "The Lake County State's Attorney's Office charged him; he was sentenced in Circuit Court to state prison."
BOTH = "A U.S. District Judge sentenced him. The County District Attorney had dropped earlier state charges."
NEITHER = "Police arrested a man after a CyberTip from NCMEC; the FBI and HSI assisted."
USAO = "United States Attorney John Doe announced the sentence. Assistant United States Attorney Roe prosecuted."

CASES = {
    "fed": ("NCMEC", FEDERAL),
    "st": ("NCMEC", STATE),
    "both": ("NCMEC", BOTH),
    "none": ("NCMEC", NEITHER),
    "doj_ack": ("DOJ SAFE CHILDHOOD", "Thanks to the Frederick County State's Attorney for assistance."),
    "nz": ("NZ DIA", "He was sentenced in the Auckland District Court to two years."),
}


@pytest.mark.parametrize(
    "source,text,label",
    [
        ("NCMEC", FEDERAL, "federal"),
        ("NCMEC", STATE, "state"),
        ("NCMEC", BOTH, "unknown"),
        ("NCMEC", NEITHER, "unknown"),  # agencies alone are never a signal
        ("DOJ SAFE CHILDHOOD", "A man was sentenced today.", "federal"),
        ("DOJ SAFE CHILDHOOD", USAO, "federal"),  # "United States Attorney" is not a State's Attorney
        ("DOJ SAFE CHILDHOOD", CASES["doj_ack"][1], "unknown"),
        ("NZ DIA", CASES["nz"][1], "unknown"),
        ("NCIS", "He was convicted at a general court-martial.", "unknown"),
    ],
)
def test_labels(source, text, label):
    out = derive_jurisdiction({"source": source, "case_text": text})
    assert out["jurisdiction"] == label, out
    assert out["jurisdiction_basis"]


def test_unknown_basis_says_why():
    assert derive_jurisdiction({"source": "NCMEC", "case_text": NEITHER})["jurisdiction_basis"] == ["no_signal"]
    both = derive_jurisdiction({"source": "NCMEC", "case_text": BOTH})["jurisdiction_basis"]
    assert any(b.startswith("federal:") for b in both) and any(b.startswith("state:") for b in both)
    assert derive_jurisdiction({"source": "NZ DIA", "case_text": ""})["jurisdiction_basis"] == ["non_us_source"]


@pytest.fixture
def db(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "j.db"
    storage = CaseStorage(str(path))
    for cid, (source, text) in CASES.items():
        storage.store_case({"id": cid, "source": source, "raw_data": {"source_file": "t.pdf", "case_text": text, "case_id": cid}})
    monkeypatch.setenv("CASELINKER_DB", str(path))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return path


def _filter(**kw):
    fn = getattr(server.filter_cases_by_jurisdiction, "fn", server.filter_cases_by_jurisdiction)
    return asyncio.run(fn(**kw))


def test_mcp_filter_counts_and_keeps_unknown_separate(db):
    out = _filter(case_ids=list(CASES) + ["missing"])
    assert out["counts"] == {"federal": 1, "state": 1, "unknown": 4}
    assert out["not_found"] == ["missing"]
    assert _filter(case_ids=list(CASES), jurisdiction="federal")["case_ids"] == ["fed"]
    assert _filter(case_ids=list(CASES), jurisdiction="state")["case_ids"] == ["st"]
    assert _filter(case_ids=list(CASES), jurisdiction="unknown")["case_ids"] == ["both", "none", "doj_ack", "nz"]
    assert _filter(case_ids=list(CASES), jurisdiction="tribal")["error"]


def test_case_payload_carries_jurisdiction_without_text(db, monkeypatch):
    spec = importlib.util.spec_from_file_location("caselinker_run_main_jurisdiction", ROOT / "run" / "main.py")
    main = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["caselinker_run_main_jurisdiction"] = main
    spec.loader.exec_module(main)
    monkeypatch.setattr(main, "storage", CaseStorage(str(db)))
    got = TestClient(main.app).get("/api/cases/st")
    assert got.status_code == 200
    body = got.json()
    assert body["jurisdiction"] == "state"
    assert "state:states_attorney" in body["jurisdiction_basis"]
    assert "raw_data" not in body  # public payload still has no narrative text
