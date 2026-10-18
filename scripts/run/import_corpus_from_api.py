#!/usr/bin/env python3
"""
Pull the production corpus via trusted CaseLinker-Key and load local caselinker.db.

One request: GET /api/corpus. Rows are inserted as they arrive. Primary keys are
kept. Columns the local sqlite schema does not have are ignored.

Usage (from repo root, venv active):
  export CASELINKER_KEY='your-trusted-key'
  python3 scripts/run/import_corpus_from_api.py

  # optional overrides
  CASELINKER_API_URL=https://caselinker.up.railway.app \\
  CASELINKER_DB=caselinker.db \\
  python3 scripts/run/import_corpus_from_api.py

Request a trusted key: mramachandra@umass.edu
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "Storage Layer"))
sys.path.insert(0, str(ROOT / "run"))

from corpus_export import CORPUS_TABLES  # noqa: E402
from storage import CaseStorage  # noqa: E402

ALLOWED_TABLES = set(CORPUS_TABLES)
AUTO_INCREMENT_TABLES = (
    "field_assertions",
    "field_resolutions",
    "review_queue",
    "precomputed_clusters",
)


def _scan_string(buf: str, start: int) -> int | None:
    i = start + 1
    while i < len(buf):
        if buf[i] == "\\":
            if i + 1 >= len(buf):
                return None
            i += 2
            continue
        if buf[i] == '"':
            return i + 1
        i += 1
    return None


def _scan_object(buf: str, start: int) -> int | None:
    depth = 0
    i = start
    while i < len(buf):
        char = buf[i]
        if char == '"':
            i = _scan_string(buf, i)
            if i is None:
                return None
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


class CorpusParser:
    """Pull (table, row) pairs out of a streamed JSON object of arrays."""

    def __init__(self) -> None:
        self.buf = ""
        self.pos = 0
        self.state = "start"
        self.table: str | None = None
        self.closed = False

    def feed(self, text: str) -> list[tuple[str, dict]]:
        if text:
            self.buf += text
        rows: list[tuple[str, dict]] = []
        while self._step(rows):
            pass
        if self.pos:
            self.buf = self.buf[self.pos :]
            self.pos = 0
        return rows

    def finish(self) -> None:
        self.feed("")
        if not self.closed or self.buf[self.pos :].strip():
            raise ValueError("truncated corpus body")

    def _skip_ws(self) -> None:
        n = len(self.buf)
        i = self.pos
        while i < n and self.buf[i] in " \t\r\n":
            i += 1
        self.pos = i

    def _rest(self) -> str:
        return self.buf[self.pos :]

    def _step(self, rows: list[tuple[str, dict]]) -> bool:
        self._skip_ws()
        rest = self._rest()
        if not rest:
            return False
        if self.state == "done":
            if rest.strip():
                raise ValueError("trailing data after corpus object")
            return False
        if self.state == "start":
            if rest[0] != "{":
                raise ValueError("corpus body must be a JSON object")
            self.pos += 1
            self.state = "key"
            return True
        if self.state == "key":
            if rest[0] == "}":
                self.pos += 1
                self.state = "done"
                self.closed = True
                return True
            if rest[0] == ",":
                self.pos += 1
                return True
            if rest[0] != '"':
                raise ValueError("expected a table name")
            end = _scan_string(self.buf, self.pos)
            if end is None:
                return False
            self.table = json.loads(self.buf[self.pos : end])
            self.pos = end
            self.state = "colon"
            return True
        if self.state == "colon":
            if rest[0] != ":":
                raise ValueError("expected ':' after table name")
            self.pos += 1
            self.state = "array"
            return True
        if self.state == "array":
            if rest[0] != "[":
                raise ValueError(f"{self.table} must be an array of rows")
            self.pos += 1
            self.state = "row"
            return True
        if rest[0] == "]":
            self.pos += 1
            self.table = None
            self.state = "key"
            return True
        if rest[0] == ",":
            self.pos += 1
            return True
        if rest[0] != "{":
            raise ValueError(f"{self.table} row must be an object")
        end = _scan_object(self.buf, self.pos)
        if end is None:
            return False
        row = json.loads(self.buf[self.pos : end])
        if not isinstance(row, dict):
            raise ValueError(f"{self.table} row must be an object")
        self.pos = end
        rows.append((self.table or "", row))
        return True


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]


def _bind(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def insert_row(conn: sqlite3.Connection, table: str, row: dict, columns: list[str]) -> None:
    if table not in ALLOWED_TABLES:
        return
    wanted = set(columns)
    keys = [name for name in columns if name in row and name in wanted]
    if not keys:
        return
    col_sql = ", ".join(f'"{name}"' for name in keys)
    placeholders = ", ".join("?" for _ in keys)
    conn.execute(
        f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})',
        [_bind(row[name]) for name in keys],
    )


def sync_sqlite_sequence(conn: sqlite3.Connection) -> None:
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "sqlite_sequence" not in names:
        return
    for table in AUTO_INCREMENT_TABLES:
        if table not in names:
            continue
        max_id = conn.execute(f'SELECT MAX(id) FROM "{table}"').fetchone()[0]
        if max_id is None:
            continue
        max_id = int(max_id)
        existing = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = ?",
            (table,),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)",
                (table, max_id),
            )
        else:
            conn.execute(
                "UPDATE sqlite_sequence SET seq = ? WHERE name = ?",
                (max_id, table),
            )


def load_corpus(chunks, db_path: Path) -> dict[str, int]:
    """Create a fresh sqlite at db_path and insert streamed corpus rows."""
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()
    CaseStorage(str(db_path))
    conn = sqlite3.connect(db_path)
    present = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    columns: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    parser = CorpusParser()
    try:
        for chunk in chunks:
            text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            for table, row in parser.feed(text):
                if table not in ALLOWED_TABLES or table not in present:
                    continue
                if table not in columns:
                    columns[table] = _columns(conn, table)
                insert_row(conn, table, row, columns[table])
                counts[table] = counts.get(table, 0) + 1
        parser.finish()
        sync_sqlite_sequence(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        if db_path.exists():
            db_path.unlink()
        raise
    conn.close()
    return counts


def import_corpus(api_base: str, key: str, db_path: Path) -> int:
    try:
        import httpx
    except ImportError:
        print("httpx is required (pip install httpx / requirements.txt)", file=sys.stderr)
        return 1

    url = f"{api_base.rstrip('/')}/api/corpus"
    print(f"Downloading {url} …")
    timeout = httpx.Timeout(600.0, connect=30.0)
    headers = {
        "CaseLinker-Key": key,
        "Accept": "application/json",
        "User-Agent": "CaseLinker-import_corpus_from_api",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code != 200:
                    body = resp.read()[:400].decode("utf-8", errors="replace")
                    print(f"HTTP {resp.status_code}: {body}", file=sys.stderr)
                    return 1
                counts = load_corpus(resp.iter_text(), db_path)
    except Exception as exc:
        print(f"import failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"Wrote {db_path}")
    for table in ("cases", "field_assertions", "field_resolutions", "review_queue"):
        print(f"  {table}: {counts.get(table, 0)}")
    return 0


def main() -> int:
    key = (os.environ.get("CASELINKER_KEY") or "").strip()
    if not key:
        print(
            "Set CASELINKER_KEY to a trusted CaseLinker-Key.\n"
            "Request access: mramachandra@umass.edu",
            file=sys.stderr,
        )
        return 1
    api_base = (os.environ.get("CASELINKER_API_URL") or "https://caselinker.up.railway.app").rstrip("/")
    db_path = Path(os.environ.get("CASELINKER_DB") or ROOT / "caselinker.db")
    return import_corpus(api_base, key, db_path)


if __name__ == "__main__":
    raise SystemExit(main())
