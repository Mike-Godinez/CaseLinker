"""Compare a platform-affordance evidence snapshot to the live corpus.

Equal case counts do not prove freshness. ``stale`` is false only when the
snapshot recorded both the corpus case count and the extraction-run
fingerprint, and both still match the database being served.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

# Any positive recorded gap is a coverage warning. Zero gaps still do not
# prove the snapshot matches the live corpus.
DB_GAPS_WARN_ABOVE = 0
REQUIRE_FRESH_MIN_COVERAGE_PCT = 95.0

_CORPUS_SQL = (
    "SELECT COALESCE(extraction_run_id, ''), COUNT(*) FROM cases "
    "GROUP BY COALESCE(extraction_run_id, '')"
)


def _count(metadata: Mapping[str, Any], name: str) -> int | None:
    value = metadata.get(name)
    return value if type(value) is int and value >= 0 else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def corpus_identity_from_groups(rows: object) -> dict[str, Any]:
    """Fingerprint ``(extraction_run_id, count)`` groups from ``cases``."""
    pairs: list[tuple[str, int]] = []
    if isinstance(rows, list) or isinstance(rows, tuple):
        sequence = rows
    else:
        sequence = []
    for row in sequence:
        if isinstance(row, Mapping):
            run_id = row.get("extraction_run_id", row.get("run_id", ""))
            count = row.get("count", row.get("n"))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            run_id, count = row[0], row[1]
        else:
            continue
        if type(count) is not int or count < 0:
            continue
        pairs.append((str(run_id or ""), count))
    pairs.sort()
    payload = "\n".join(f"{run_id}\t{count}" for run_id, count in pairs)
    return {
        "case_count": sum(count for _, count in pairs),
        "extraction_run_fingerprint": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }


def read_corpus_identity(connection: Any) -> dict[str, Any] | None:
    """Read the live corpus identity. The caller owns ``connection``."""
    cursor = connection.cursor()
    try:
        cursor.execute(_CORPUS_SQL)
        rows = cursor.fetchall()
    finally:
        cursor.close()
    return corpus_identity_from_groups(rows)


def identity_matches(meta: object, live: object) -> bool:
    """True only when recorded count and extraction fingerprint both match."""
    if not isinstance(meta, Mapping) or not isinstance(live, Mapping):
        return False
    recorded_count = _count(meta, "corpus_case_count")
    recorded_fp = _text(meta.get("extraction_run_fingerprint"))
    live_count = live.get("case_count")
    live_fp = _text(live.get("extraction_run_fingerprint"))
    if recorded_count is None or type(live_count) is not int or recorded_fp is None or live_fp is None:
        return False
    return recorded_count == live_count and recorded_fp == live_fp


def coverage_percent(cases_processed: int | None, live_case_count: int | None) -> float | None:
    if cases_processed is None or live_case_count is None or live_case_count <= 0:
        return None
    return round(100.0 * cases_processed / live_case_count, 1)


def gap_gate(db_gaps: object, *, threshold: int = DB_GAPS_WARN_ABOVE) -> str:
    """``ok`` at or under the threshold, ``warn`` above it, ``fail`` if not a count."""
    if type(db_gaps) is not int or db_gaps < 0 or type(threshold) is not int:
        return "fail"
    if db_gaps > threshold:
        return "warn"
    return "ok"


def rebuild_decision(meta: object, live: object) -> str:
    """``current`` when the snapshot identity matches, else ``rebuild`` or ``unknown``."""
    if not isinstance(live, Mapping) or type(live.get("case_count")) is not int:
        return "unknown"
    if not _text(live.get("extraction_run_fingerprint")):
        return "unknown"
    if identity_matches(meta, live):
        return "current"
    return "rebuild"


def snapshot_freshness(meta: object, live: object = None) -> dict[str, Any]:
    """Declare build scope and whether this process verified the live corpus."""
    metadata = meta if isinstance(meta, Mapping) else {}
    generated = metadata.get("generated")
    generated_at = generated if isinstance(generated, str) and generated.strip() else None
    cases_processed = _count(metadata, "cases_processed")
    db_gaps = _count(metadata, "db_gaps")
    live_case_count = None
    if isinstance(live, Mapping) and type(live.get("case_count")) is int and live["case_count"] >= 0:
        live_case_count = live["case_count"]
    verified = identity_matches(metadata, live)
    if verified:
        status = "current"
    elif live_case_count is not None:
        status = "stale"
    else:
        status = "unverified_snapshot"
    gaps = gap_gate(db_gaps) if db_gaps is not None else "fail"
    if verified:
        warning = (
            "This snapshot's recorded corpus count and extraction-run fingerprint "
            "match the database being served. db_gaps still describe the build, "
            "not a guarantee that every case names a platform."
        )
    else:
        warning = (
            "This is a precomputed platform affordance evidence snapshot, not a live corpus query. "
            "stale is true unless the recorded corpus count and extraction-run fingerprint "
            "both match the database being served. Equal case counts alone do not establish freshness. "
            "Prefer filter_cases_by_tags for a current cohort."
        )
    return {
        "status": status,
        "artifact_kind": "precomputed_platform_affordance_evidence_index",
        "generated_at": generated_at,
        "cases_processed": cases_processed,
        "db_gaps": db_gaps,
        "text_cap": _count(metadata, "text_cap"),
        "coverage_status": "reported_gaps" if db_gaps is not None and db_gaps > 0 else "unverified",
        "current_corpus_verified": verified,
        "live_case_count": live_case_count,
        "coverage_pct": coverage_percent(cases_processed, live_case_count),
        "stale": not verified,
        "gaps_exceed_threshold": gaps == "warn",
        "db_gaps_warn_above": DB_GAPS_WARN_ABOVE,
        "require_fresh_min_coverage_pct": REQUIRE_FRESH_MIN_COVERAGE_PCT,
        "warning": warning,
    }


def require_fresh_block(
    freshness: Mapping[str, Any],
    *,
    min_coverage: float = REQUIRE_FRESH_MIN_COVERAGE_PCT,
) -> str | None:
    """Reason to refuse the snapshot, or None when require_fresh may proceed."""
    if freshness.get("stale") is not False:
        return "platform affordance evidence snapshot is stale or unverified"
    if freshness.get("gaps_exceed_threshold") is True:
        return "platform affordance evidence db_gaps exceed the warning threshold"
    coverage = freshness.get("coverage_pct")
    if type(coverage) not in (int, float) or isinstance(coverage, bool) or coverage < min_coverage:
        return f"platform affordance evidence coverage is below {min_coverage}"
    return None


def with_snapshot_freshness(
    payload: Mapping[str, Any],
    meta: object,
    live: object = None,
) -> dict[str, Any]:
    """Add the same disclosure to index and filtered responses without mutation."""
    return {**payload, "_meta": meta, "freshness": snapshot_freshness(meta, live)}
