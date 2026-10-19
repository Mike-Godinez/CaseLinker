"""One-shot corpus dump for GET /api/corpus.

Reads this process's database (SQLite file, or Postgres via the pool the server
already opened from DATABASE_URL). Yields one JSON object. Rows are paged off
the database; tables are not loaded into a dict and then serialized.
"""

from __future__ import annotations

import json
import queue
import sqlite3
import threading
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterator

CORPUS_TABLES = (
    "source_documents",
    "source_document_versions",
    "extraction_runs",
    "cases",
    "case_fingerprints",
    "victim_demographics",
    "perpetrator_demographics",
    "prosecution_outcomes",
    "field_assertions",
    "field_resolutions",
    "review_queue",
    "cluster_groups_slim",
    "technology_revolver_slim",
    "automated_analysis_slim",
    "precomputed_clusters",
)

_PAGE = 200


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    return str(value)


def _quote(name: str) -> str:
    if not name.replace("_", "a").isalnum():
        raise ValueError(f"unexpected identifier {name!r}")
    return f'"{name}"'


def _open(storage: Any):
    db_path = getattr(storage, "db_path", None)
    if db_path:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        return conn, "sqlite", conn.close

    from storage_postgres import get_connection, return_connection

    conn = get_connection()

    def release() -> None:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            conn.set_session(readonly=False, autocommit=False)
        except Exception:
            pass
        return_connection(conn)

    try:
        conn.rollback()
        try:
            conn.set_session(readonly=True, autocommit=False)
        except Exception:
            conn.rollback()
            conn.autocommit = False
    except Exception:
        release()
        raise
    return conn, "postgres", release


def _existing_tables(conn: Any, dialect: str) -> set[str]:
    cur = conn.cursor()
    try:
        if dialect == "sqlite":
            cur.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        else:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
        return {row[0] for row in cur.fetchall()}
    finally:
        cur.close()


def _iter_rows(conn: Any, dialect: str, table: str) -> Iterator[dict[str, Any]]:
    quoted = _quote(table)
    if dialect == "sqlite":
        cur = conn.cursor()
        try:
            cur.execute(f"SELECT * FROM {quoted}")
            cols = [desc[0] for desc in cur.description]
            while True:
                batch = cur.fetchmany(_PAGE)
                if not batch:
                    break
                for item in batch:
                    yield dict(zip(cols, item))
        finally:
            cur.close()
        return

    from psycopg2.extras import RealDictCursor

    cur = conn.cursor(name=f"caselinker_corpus_{table}", cursor_factory=RealDictCursor)
    cur.itersize = _PAGE
    try:
        cur.execute(f"SELECT * FROM {quoted}")
        for item in cur:
            yield dict(item)
    finally:
        cur.close()


def _generate(storage: Any) -> Iterator[bytes]:
    conn, dialect, release = _open(storage)
    try:
        present = _existing_tables(conn, dialect)
        yield b"{"
        first_table = True
        for table in CORPUS_TABLES:
            if table not in present:
                continue
            if not first_table:
                yield b","
            first_table = False
            yield f'"{table}":['.encode()
            first_row = True
            for row in _iter_rows(conn, dialect, table):
                if not first_row:
                    yield b","
                first_row = False
                payload = {key: _jsonable(val) for key, val in row.items()}
                yield json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            yield b"]"
        yield b"}"
    finally:
        release()


def iter_corpus_json(storage: Any) -> Iterator[bytes]:
    """Stream the corpus JSON. The database connection stays on one thread."""
    chunks: queue.Queue[bytes | None] = queue.Queue(maxsize=8)
    stop = threading.Event()
    error: list[BaseException] = []

    def produce() -> None:
        try:
            for chunk in _generate(storage):
                if stop.is_set():
                    break
                while not stop.is_set():
                    try:
                        chunks.put(chunk, timeout=0.2)
                        break
                    except queue.Full:
                        continue
        except BaseException as exc:
            error.append(exc)
        finally:
            chunks.put(None)

    thread = threading.Thread(target=produce, name="corpus-export", daemon=True)
    thread.start()
    try:
        while True:
            item = chunks.get()
            if item is None:
                break
            yield item
    finally:
        stop.set()
        while True:
            try:
                chunks.get_nowait()
            except queue.Empty:
                break
        thread.join(timeout=30)
    if error:
        raise error[0]
