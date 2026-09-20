from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone

SOURCE_COLUMNS = frozenset(
    {
        "doc_id",
        "title",
        "issuer",
        "source_url",
        "source_kind",
        "sha256",
        "fetched_at",
        "is_synthetic",
        "published_at",
        "effective_from",
        "effective_to",
        "applies_to_json",
        "cohorts_json",
        "domains_json",
        "supersedes_json",
        "superseded_by",
        "superseded_at",
        "transitional_clause",
        "status",
        "content_hash",
        "created_at",
        "activated_at",
        "activated_by",
    }
)
CHUNK_COLUMNS = frozenset(
    {
        "chunk_id",
        "doc_id",
        "article_no",
        "clause_no",
        "breadcrumb",
        "text",
        "domain",
        "label",
        "conflict_flag",
        "conflict_with",
        "ord",
        "token_count",
    }
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_columns(record: Mapping[str, object], allowed: frozenset[str]) -> None:
    unknown = set(record) - allowed
    if unknown:
        raise ValueError(f"Cột không hợp lệ: {', '.join(sorted(unknown))}")


def create_source(conn: sqlite3.Connection, source: Mapping[str, object]) -> None:
    _validate_columns(source, SOURCE_COLUMNS)
    if not source.get("doc_id") or not source.get("status"):
        raise ValueError("doc_id và status là bắt buộc")
    values = dict(source)
    values.setdefault("created_at", now_iso())
    columns = list(values)
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO sources ({', '.join(columns)}) VALUES ({placeholders})",
        [values[column] for column in columns],
    )
    conn.commit()


def get_source(conn: sqlite3.Connection, doc_id: str) -> dict[str, object] | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM sources WHERE doc_id = ?", (doc_id,)).fetchone()
    return dict(row) if row else None


def list_sources(conn: sqlite3.Connection, status: str | None = None) -> list[dict[str, object]]:
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM sources"
    params: tuple[object, ...] = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    rows = conn.execute(query + " ORDER BY created_at, doc_id", params).fetchall()
    return [dict(row) for row in rows]


def update_source(conn: sqlite3.Connection, doc_id: str, **changes: object) -> None:
    _validate_columns(changes, SOURCE_COLUMNS - {"doc_id"})
    if not changes:
        return
    assignments = ", ".join(f"{column} = ?" for column in changes)
    cursor = conn.execute(
        f"UPDATE sources SET {assignments} WHERE doc_id = ?",
        [*changes.values(), doc_id],
    )
    if cursor.rowcount != 1:
        conn.rollback()
        raise KeyError(doc_id)
    conn.commit()


def replace_chunks(
    conn: sqlite3.Connection, doc_id: str, chunks: Iterable[Mapping[str, object]]
) -> None:
    prepared = []
    for chunk in chunks:
        _validate_columns(chunk, CHUNK_COLUMNS)
        row = {**chunk, "doc_id": doc_id}
        row.setdefault("label", "human_only")
        row.setdefault("conflict_flag", 0)
        prepared.append(row)

    conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
    for row in prepared:
        columns = list(row)
        conn.execute(
            f"INSERT INTO chunks ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            [row[column] for column in columns],
        )
    conn.commit()


def list_chunks(
    conn: sqlite3.Connection,
    *,
    doc_id: str | None = None,
    active_only: bool = False,
) -> list[dict[str, object]]:
    conn.row_factory = sqlite3.Row
    conditions: list[str] = []
    params: list[object] = []
    if doc_id:
        conditions.append("chunks.doc_id = ?")
        params.append(doc_id)
    if active_only:
        conditions.append("sources.status = 'ACTIVE'")
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        "SELECT chunks.* FROM chunks JOIN sources ON sources.doc_id = chunks.doc_id"
        + where
        + " ORDER BY chunks.doc_id, chunks.ord, chunks.chunk_id",
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def compute_corpus_version(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT doc_id, content_hash FROM sources WHERE status = 'ACTIVE' ORDER BY doc_id"
    ).fetchall()
    payload = "".join(f"{doc_id}:{content_hash or ''}" for doc_id, content_hash in rows)
    return "cv_" + hashlib.sha256(payload.encode()).hexdigest()[:12]


def bump_corpus_version(conn: sqlite3.Connection, actor: str, note: str) -> str:
    version = compute_corpus_version(conn)
    active_ids = [
        row[0]
        for row in conn.execute(
            "SELECT doc_id FROM sources WHERE status = 'ACTIVE' ORDER BY doc_id"
        ).fetchall()
    ]
    created_at = now_iso()
    conn.execute(
        "INSERT OR IGNORE INTO corpus_versions "
        "(corpus_version, created_at, actor, note, active_doc_ids_json) VALUES (?, ?, ?, ?, ?)",
        (version, created_at, actor, note, json.dumps(active_ids, ensure_ascii=False)),
    )
    conn.execute(
        "INSERT INTO settings (key, value, updated_at, actor) VALUES "
        "('current_corpus_version', ?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
        "updated_at=excluded.updated_at, actor=excluded.actor",
        (version, created_at, actor),
    )
    conn.commit()
    return version


def current_corpus_version(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = 'current_corpus_version'").fetchone()
    return str(row[0]) if row else compute_corpus_version(conn)
