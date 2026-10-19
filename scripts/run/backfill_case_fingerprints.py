#!/usr/bin/env python3
"""Map every current case id to a content fingerprint. Does not renumber cases.

Local copy (safe to run now):

    python scripts/run/backfill_case_fingerprints.py --sqlite ~/CaseLinker-backups/content-ids-2026-10-19/caselinker.db

Production, later, by hand. This script refuses a non-local Postgres host.

    pg_dump --format=custom --file=caselinker-before-fingerprints.dump "$DATABASE_URL"
    python scripts/run/backfill_case_fingerprints.py --postgres "$DATABASE_URL"

Verification, after the backfill:

    SELECT
      (SELECT COUNT(*) FROM cases) AS cases,
      (SELECT COUNT(*) FROM case_fingerprints) AS mapped,
      (SELECT COUNT(*) FROM cases c
        LEFT JOIN case_fingerprints f ON f.case_id = c.id
        WHERE f.case_id IS NULL) AS unmapped,
      (SELECT COUNT(*) FROM case_fingerprints
        WHERE normalization_version <> 'fp-1') AS other_versions;
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src" / "Processing Layer"))
sys.path.insert(0, str(REPO / "src" / "Storage Layer"))

from batching import case_batching  # noqa: E402
from case_fingerprint import NORMALIZATION_VERSION  # noqa: E402
from fingerprint_store import report_fingerprints, source_file_from_raw  # noqa: E402
from storage import CaseStorage  # noqa: E402


def _local_host(url: str) -> None:
    host = (urlsplit(url).hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit(f"refusing non-local database host {host or '(missing)'}")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    env_path = REPO / ".env"
    if not env_path.is_file():
        return ""
    for line in env_path.read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _print_report(report: dict) -> None:
    shared = report["shared_sets"]
    print(f"cases={report['cases']} unique_fingerprints={report['unique_fingerprints']} "
          f"shared_sets={len(shared)} shared_cases={sum(len(items) for items in shared)}")
    for items in sorted(shared, key=lambda rows: rows[0]["id"]):
        print("SHARED")
        for item in items:
            print(f"  {item['id']}\t{item['source']}\tchars={item['normalized_chars']}")


def report_sqlite(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    rows = []
    for case_id, source, raw in conn.execute("SELECT id, source, raw_data FROM cases"):
        text = ""
        try:
            text = json.loads(raw or "{}").get("case_text") or ""
        except json.JSONDecodeError:
            text = ""
        rows.append({"id": case_id, "source": source or "", "case_text": text})
    conn.close()
    return report_fingerprints(rows)


def report_postgres(url: str) -> dict:
    import psycopg2

    conn = psycopg2.connect(url)
    conn.set_session(readonly=True, autocommit=True)
    cursor = conn.cursor()
    cursor.execute("SELECT id, source, raw_data FROM cases")
    rows = []
    for case_id, source, raw in cursor.fetchall():
        text = ""
        if isinstance(raw, dict):
            text = raw.get("case_text") or ""
        elif raw:
            try:
                text = json.loads(raw).get("case_text") or ""
            except (json.JSONDecodeError, TypeError):
                text = ""
        rows.append({"id": case_id, "source": source or "", "case_text": text})
    cursor.close()
    conn.close()
    return report_fingerprints(rows)


def backfill_sqlite(path: Path, source: Path | None) -> None:
    if source is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.resolve() == source.resolve():
            raise SystemExit("refusing to backfill the source database in place")
        if not path.exists():
            shutil.copy2(source, path)
    storage = CaseStorage(str(path))
    report = storage.backfill_fingerprints()
    print(f"version={NORMALIZATION_VERSION} mapped={report['mapped']} ids_unchanged={report['ids_unchanged']}")
    _print_report(report)
    if not report["ids_unchanged"]:
        raise SystemExit("case ids changed during backfill")
    unmapped = storage.load_fingerprint_index()
    missing = [case_id for case_id in unmapped.used if not any(
        case_id == row["case_id"]
        for rows in unmapped.by_fingerprint.values()
        for row in rows
    )]
    # Every id noted from the cases table should also have a fingerprint row,
    # except an id with no text still gets a fingerprint of the empty string.
    print(f"index_ids={len(unmapped.used)} fingerprint_keys={len(unmapped.by_fingerprint)} missing_rows={len(missing)}")


def prove_resplit(path: Path) -> None:
    """Re-batch stored listing-page texts, including a reversed order."""
    storage = CaseStorage(str(path))
    index = storage.load_fingerprint_index()
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    samples = [
        ("GBI", "gbi", "gbi.pdf"),
        ("Idaho ICAC", "idaho_icac", "Idaho_ICAC_All.pdf"),
        ("AZICAC", "azicac", "azicac.pdf"),
    ]
    for source, org, filename in samples:
        rows = conn.execute(
            "SELECT id, raw_data FROM cases WHERE source = ? ORDER BY id LIMIT 3",
            (source,),
        ).fetchall()
        articles = []
        for case_id, raw in rows:
            text = json.loads(raw or "{}").get("case_text") or ""
            if len(text) < 80:
                continue
            articles.append((case_id, text, source_file_from_raw(raw) or filename))
        if len(articles) < 2:
            print(f"{source}: not enough stored text to resplit")
            continue
        from case_fingerprint import assign_content_locked_ids

        def _rows(ordered):
            return [
                {"case_text": text, "case_id": f"{org}_2099_001", "year": "2099", "source_file": file_name}
                for _case_id, text, file_name in ordered
            ]

        index = storage.load_fingerprint_index()
        kept_forward, dups_forward = assign_content_locked_ids(_rows(articles), index)
        index = storage.load_fingerprint_index()
        kept_back, dups_back = assign_content_locked_ids(_rows(list(reversed(articles))), index)
        got = [row["case_id"] for row in kept_back]
        expected = [case_id for case_id, _text, _file_name in reversed(articles)]
        print(f"{source} reversed ids {got} expected {expected} dups={len(dups_forward) + len(dups_back)}")
        if got != expected or dups_forward or dups_back:
            raise SystemExit(f"{source} resplit did not keep stored ids")
        if source == "GBI":
            document = "\n# # # # #\n".join(text for _case_id, text, _file_name in reversed(articles))
            batched = case_batching(
                document, org_name=org, source=source, source_file=articles[0][2], fingerprint_index=storage.load_fingerprint_index()
            )
            print(f"GBI case_batching reversed returned {[row['case_id'] for row in batched]}")
    conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-sqlite", type=Path)
    parser.add_argument("--report-postgres", action="store_true")
    parser.add_argument("--sqlite", type=Path, help="local copy to backfill")
    parser.add_argument("--source-sqlite", type=Path, default=REPO / "caselinker.db")
    parser.add_argument("--postgres", help="local Postgres URL to backfill; remote hosts are refused")
    parser.add_argument("--prove-resplit", action="store_true")
    args = parser.parse_args(argv)
    if args.report_sqlite:
        print("SQLITE REPORT")
        _print_report(report_sqlite(args.report_sqlite.expanduser()))
    if args.report_postgres:
        url = _database_url()
        if not url:
            raise SystemExit("DATABASE_URL is not set")
        print("POSTGRES REPORT read-only")
        _print_report(report_postgres(url))
    if args.sqlite:
        backfill_sqlite(args.sqlite.expanduser(), args.source_sqlite.expanduser())
        if args.prove_resplit:
            prove_resplit(args.sqlite.expanduser())
    if args.postgres:
        _local_host(args.postgres)
        os.environ["DATABASE_URL"] = args.postgres
        from storage_postgres import CaseStorage as PostgresStorage

        report = PostgresStorage().backfill_fingerprints()
        print(f"postgres mapped={report['mapped']} ids_unchanged={report['ids_unchanged']}")
        if not report["ids_unchanged"]:
            raise SystemExit("case ids changed during backfill")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
