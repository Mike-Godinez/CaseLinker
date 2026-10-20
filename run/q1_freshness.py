"""Describe a frozen Q1 index without upgrading its metadata to current evidence."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def snapshot_freshness(meta: object) -> dict[str, Any]:
    """Return declared build scope; current corpus identity remains unverified.

    Counts and generation dates alone cannot establish that the live corpus or
    its extraction versions still match this index, even when counts agree.
    """
    metadata = meta if isinstance(meta, Mapping) else {}

    def count(name: str) -> int | None:
        value = metadata.get(name)
        return value if type(value) is int and value >= 0 else None

    generated = metadata.get("generated")
    generated_at = generated if isinstance(generated, str) and generated.strip() else None
    db_gaps = count("db_gaps")
    return {
        "status": "unverified_snapshot",
        "artifact_kind": "precomputed_q1_index",
        "generated_at": generated_at,
        "cases_processed": count("cases_processed"),
        "db_gaps": db_gaps,
        "text_cap": count("text_cap"),
        "coverage_status": "reported_gaps" if db_gaps is not None and db_gaps > 0 else "unverified",
        "current_corpus_verified": False,
        "live_case_count": None,
        "coverage_pct": None,
        "stale": None,
        "warning": (
            "This is a precomputed Q1 snapshot, not a live corpus query. "
            "Build counts and db_gaps describe the recorded build; current "
            "corpus coverage and content freshness have not been verified. "
            "Equal case counts would not establish matching source or extraction versions."
        ),
    }


def with_snapshot_freshness(payload: Mapping[str, Any], meta: object) -> dict[str, Any]:
    """Add the same disclosure to index and filtered responses without mutation."""
    return {**payload, "_meta": meta, "freshness": snapshot_freshness(meta)}
