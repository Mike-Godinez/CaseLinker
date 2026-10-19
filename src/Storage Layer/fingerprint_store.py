"""Fingerprint map shared by SQLite and Postgres.

One row per case id: the fingerprint, the normalization version that produced
it, and the id. The fingerprint is not unique, because the corpus can already
hold the same text under two ids. New ingests do not add another id for that text.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROC = Path(__file__).resolve().parents[1] / "Processing Layer"
if str(_PROC) not in sys.path:
    sys.path.insert(0, str(_PROC))

from case_fingerprint import (  # noqa: E402
    NORMALIZATION_VERSION,
    FingerprintIndex,
    fingerprint_case_text,
    normalize_case_text,
)


def _ph(dialect: str) -> str:
    return "?" if dialect == "sqlite" else "%s"


def apply_fingerprint_schema(cursor: Any, dialect: str = "sqlite") -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS case_fingerprints (
            case_id TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL,
            normalization_version TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_case_fingerprints_fingerprint
        ON case_fingerprints(fingerprint)
        """
    )


def source_file_from_raw(raw: Any) -> str:
    if isinstance(raw, dict):
        return str(raw.get("source_file") or "")
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("source_file") or "")


def case_text_from_case(case: Dict[str, Any]) -> str:
    text = case.get("case_text")
    if isinstance(text, str) and text.strip():
        return text
    raw = case.get("raw_data")
    if isinstance(raw, dict):
        raw_text = raw.get("case_text")
        return raw_text if isinstance(raw_text, str) else ""
    if isinstance(raw, str) and raw:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return ""
        if isinstance(data, dict) and isinstance(data.get("case_text"), str):
            return data["case_text"]
    return ""


def write_case_fingerprint(cursor: Any, case: Dict[str, Any], dialect: str = "sqlite") -> None:
    """Upsert the fingerprint of the text about to be stored. Does not touch the case id."""
    case_id = str(case.get("id") or case.get("case_id") or "").strip()
    text = case_text_from_case(case)
    digest = case.get("fingerprint") or (fingerprint_case_text(text) if text.strip() else "")
    if not case_id or not digest:
        return
    ph = _ph(dialect)
    version = case.get("normalization_version") or NORMALIZATION_VERSION
    if dialect == "sqlite":
        cursor.execute(
            f"""
            INSERT INTO case_fingerprints (case_id, fingerprint, normalization_version)
            VALUES ({ph}, {ph}, {ph})
            ON CONFLICT(case_id) DO UPDATE SET
                fingerprint = excluded.fingerprint,
                normalization_version = excluded.normalization_version
            """,
            (case_id, digest, version),
        )
        return
    cursor.execute(
        """
        INSERT INTO case_fingerprints (case_id, fingerprint, normalization_version)
        VALUES (%s, %s, %s)
        ON CONFLICT (case_id) DO UPDATE SET
            fingerprint = EXCLUDED.fingerprint,
            normalization_version = EXCLUDED.normalization_version
        """,
        (case_id, digest, version),
    )


def load_fingerprint_index(cursor: Any, dialect: str = "sqlite") -> FingerprintIndex:
    index = FingerprintIndex()
    cursor.execute("SELECT id, raw_data FROM cases")
    sources = {row[0]: source_file_from_raw(row[1]) for row in cursor.fetchall()}
    for case_id in sources:
        index.note_existing_id(case_id)
    cursor.execute(
        "SELECT case_id, fingerprint, normalization_version FROM case_fingerprints"
    )
    for case_id, digest, version in cursor.fetchall():
        index.remember(
            case_id,
            "",
            source_file=sources.get(case_id, ""),
            version=version,
            fingerprint=digest,
        )
    return index


def backfill_fingerprints(cursor: Any, dialect: str = "sqlite") -> Dict[str, Any]:
    """Map every current case id to its text. Does not update ``cases``."""
    cursor.execute("SELECT id FROM cases ORDER BY id")
    ids_before = [row[0] for row in cursor.fetchall()]
    cursor.execute("SELECT id, source, raw_data FROM cases")
    groups: Dict[str, List[Dict[str, Any]]] = {}
    mapped = 0
    for case_id, source, raw in cursor.fetchall():
        text = ""
        if raw:
            try:
                data = json.loads(raw) if not isinstance(raw, dict) else raw
            except (json.JSONDecodeError, TypeError):
                data = {}
            if isinstance(data, dict):
                text = data.get("case_text") or ""
        digest = fingerprint_case_text(text if isinstance(text, str) else "")
        write_case_fingerprint(
            cursor,
            {"id": case_id, "case_text": text if isinstance(text, str) else "", "fingerprint": digest},
            dialect,
        )
        groups.setdefault(digest, []).append({
            "id": case_id,
            "source": source or "",
            "normalized_chars": len(normalize_case_text(text if isinstance(text, str) else "")),
        })
        mapped += 1
    cursor.execute("SELECT id FROM cases ORDER BY id")
    ids_after = [row[0] for row in cursor.fetchall()]
    shared = [rows for rows in groups.values() if len(rows) > 1]
    return {
        "cases": len(ids_before),
        "mapped": mapped,
        "unique_fingerprints": len(groups),
        "shared_sets": shared,
        "ids_unchanged": ids_before == ids_after,
    }


def report_fingerprints(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """``rows`` are ``id``, ``source``, ``case_text``. No writes."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        text = row.get("case_text") or ""
        digest = fingerprint_case_text(text)
        groups.setdefault(digest, []).append({
            "id": row.get("id") or "",
            "source": row.get("source") or "",
            "normalized_chars": len(normalize_case_text(text)),
        })
    shared = [items for items in groups.values() if len(items) > 1]
    return {
        "cases": len(rows),
        "unique_fingerprints": len(groups),
        "shared_case_count": sum(len(items) for items in shared),
        "shared_sets": shared,
    }


def fingerprint_rows(cursor: Any) -> List[Dict[str, str]]:
    cursor.execute(
        """
        SELECT case_id, fingerprint, normalization_version
        FROM case_fingerprints
        ORDER BY case_id
        """
    )
    return [
        {
            "case_id": row[0],
            "fingerprint": row[1],
            "normalization_version": row[2],
        }
        for row in cursor.fetchall()
    ]
