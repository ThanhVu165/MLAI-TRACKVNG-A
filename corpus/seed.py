"""Corpus seed module for Regulation Ingestion (Option A+B Hybrid).

Pre-seeds the SQLite database with 6 official administrative documents
per Section 9.2 of PROJECT_SPEC.md.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from core.types import ChunkLabel, Domain, SourceStatus

SEED_DIR = Path(__file__).resolve().parent.parent / "data" / "seed_docs"
MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent / "infra" / "migrations" / "001_init.sql"
)

# Specification for 6 seed documents per spec 9.2
SEED_DOCS_SPEC: list[dict[str, Any]] = [
    {
        "doc_id": "DOC-01",
        "title": "Quy định đánh giá kết quả rèn luyện sinh viên năm 2026",
        "issuer": "Hiệu trưởng",
        "source_url": "https://daotao.edu.vn/quy-dinh/ren-luyen-2026.pdf",
        "source_kind": "pdf",
        "filename": "doc_01.txt",
        "domain": Domain.CONDUCT_SCORE.value,
        "domains": [Domain.CONDUCT_SCORE.value],
        "status": SourceStatus.ACTIVE.value,
        "transitional_clause": 1,
        "supersedes": ["DOC-02"],
        "superseded_by": None,
        "published_at": "2026-01-15T08:00:00Z",
        "effective_from": "2026-01-15T08:00:00Z",
        "effective_to": None,
        "human_only_articles": {7, 8, 9},  # Hạ bậc/kỷ luật, đặc cách, điều khoản chuyển tiếp
        "conflict_articles": {},
    },
    {
        "doc_id": "DOC-02",
        "title": "Quy định đánh giá kết quả rèn luyện sinh viên năm 2025",
        "issuer": "Hiệu trưởng",
        "source_url": "https://daotao.edu.vn/quy-dinh/ren-luyen-2025.pdf",
        "source_kind": "pdf",
        "filename": "doc_02.txt",
        "domain": Domain.CONDUCT_SCORE.value,
        "domains": [Domain.CONDUCT_SCORE.value],
        "status": SourceStatus.SUPERSEDED.value,
        "transitional_clause": 0,
        "supersedes": [],
        "superseded_by": "DOC-01",
        "superseded_at": "2026-01-15T08:00:00Z",
        "published_at": "2025-01-10T08:00:00Z",
        "effective_from": "2025-01-10T08:00:00Z",
        "effective_to": "2026-01-14T23:59:59Z",
        "human_only_articles": {5, 6},  # Khiếu nại, Kỷ luật rèn luyện
        "conflict_articles": {},
    },
    {
        "doc_id": "DOC-03",
        "title": "Quy chế rút học phần năm 2026",
        "issuer": "Hiệu trưởng",
        "source_url": "https://daotao.edu.vn/quy-che/rut-hoc-phan-2026.pdf",
        "source_kind": "pdf",
        "filename": "doc_03.txt",
        "domain": Domain.COURSE_WITHDRAWAL.value,
        "domains": [Domain.COURSE_WITHDRAWAL.value],
        "status": SourceStatus.ACTIVE.value,
        "transitional_clause": 0,
        "supersedes": [],
        "superseded_by": None,
        "published_at": "2026-02-10T08:00:00Z",
        "effective_from": "2026-02-10T08:00:00Z",
        "effective_to": None,
        "human_only_articles": {7, 8},  # Cứu xét ngoại lệ Hiệu trưởng & khiếu nại
        "conflict_articles": {},
    },
    {
        "doc_id": "DOC-04",
        "title": "Hướng dẫn phúc khảo điểm học phần năm học 2025-2026",
        "issuer": "Phòng Đào tạo",
        "source_url": "https://daotao.edu.vn/khao-thi/huong-dan-phuc-khao-2026.html",
        "source_kind": "web",
        "filename": "doc_04.txt",
        "domain": Domain.GRADE_APPEAL.value,
        "domains": [Domain.GRADE_APPEAL.value],
        "status": SourceStatus.ACTIVE.value,
        "transitional_clause": 0,
        "supersedes": [],
        "superseded_by": None,
        "published_at": "2026-01-18T08:00:00Z",
        "effective_from": "2026-01-18T08:00:00Z",
        "effective_to": None,
        "human_only_articles": {6, 7},  # Thẩm quyền duyệt sửa điểm & đơn trễ hạn
        "conflict_articles": {},
    },
    {
        "doc_id": "DOC-05",
        "title": "Thông báo học phí và chính sách tài chính học kỳ 2026-1",
        "issuer": "Phòng Kế hoạch - Tài chính",
        "source_url": "https://tckt.edu.vn/thong-bao/hoc-phi-2026-1.html",
        "source_kind": "web",
        "filename": "doc_05.txt",
        "domain": Domain.COURSE_WITHDRAWAL.value,
        "domains": [Domain.COURSE_WITHDRAWAL.value],
        "status": SourceStatus.ACTIVE.value,
        "transitional_clause": 0,
        "supersedes": [],
        "superseded_by": None,
        "published_at": "2026-02-20T08:00:00Z",
        "effective_from": "2026-02-20T08:00:00Z",
        "effective_to": None,
        "human_only_articles": {6},  # Gia hạn nợ học phí
        "conflict_articles": {4: "DOC-03"},  # Mâu thuẫn tỷ lệ hoàn phí tuần 4-6 (60% vs 70%)
    },
    {
        "doc_id": "DOC-06",
        "title": "Quyết định phân cấp thẩm quyền giải quyết công việc học vụ",
        "issuer": "Hiệu trưởng",
        "source_url": "https://daotao.edu.vn/van-ban/phan-cap-tham-quyen-2026.pdf",
        "source_kind": "pdf",
        "filename": "doc_06.txt",
        "domain": Domain.CONDUCT_SCORE.value,
        "domains": [
            Domain.CONDUCT_SCORE.value,
            Domain.COURSE_WITHDRAWAL.value,
            Domain.GRADE_APPEAL.value,
        ],
        "status": SourceStatus.ACTIVE.value,
        "transitional_clause": 0,
        "supersedes": [],
        "superseded_by": None,
        "published_at": "2026-01-05T08:00:00Z",
        "effective_from": "2026-01-05T08:00:00Z",
        "effective_to": None,
        "all_human_only": True,  # 100% human_only per spec
        "human_only_articles": set(),
        "conflict_articles": {},
    },
]


def parse_articles_from_text(text: str) -> list[tuple[int, str, str]]:
    """Parse text into list of (article_num, article_title, article_content)."""
    blocks = re.split(r"\n(?=Điều\s+\d+[\.\:])", text)
    articles = []
    for b in blocks:
        b_strip = b.strip()
        if not b_strip.startswith("Điều"):
            continue
        match = re.match(r"Điều\s+(\d+)[\.\:]\s*([^\n]+)?", b_strip)
        if match:
            art_no = int(match.group(1))
            art_title = (match.group(2) or "").strip()
            articles.append((art_no, art_title, b_strip))
    return articles


def compute_corpus_version(conn: sqlite3.Connection) -> str:
    """Compute corpus version hash based on active documents."""
    active_docs = conn.execute(
        "SELECT doc_id, content_hash FROM sources WHERE status = 'ACTIVE' ORDER BY doc_id"
    ).fetchall()
    corpus_hash_str = "".join(f"{doc_id}:{ch}" for doc_id, ch in active_docs)
    return "cv_" + hashlib.sha256(corpus_hash_str.encode("utf-8")).hexdigest()[:12]


def ensure_tables(conn: sqlite3.Connection) -> None:
    """Ensure required database schema exists."""
    if MIGRATION_PATH.exists():
        sql = MIGRATION_PATH.read_text(encoding="utf-8")
        conn.executescript(sql)
    else:
        raise FileNotFoundError(f"Migration script not found at {MIGRATION_PATH}")


def seed_corpus(
    conn: sqlite3.Connection,
    seed_dir: Path | str | None = None,
    force: bool = False,
    now_iso: str = "2026-02-25T08:00:00Z",
) -> dict[str, Any]:
    """Seed the database with 6 seed documents and their chunks.

    Returns a summary dict with statistics.
    """
    seed_path = Path(seed_dir) if seed_dir else SEED_DIR
    ensure_tables(conn)

    # Check if already seeded
    existing_count = conn.execute("SELECT count(*) FROM sources").fetchone()[0]
    if existing_count > 0 and not force:
        curr_cv = conn.execute(
            "SELECT value FROM settings WHERE key = 'current_corpus_version'"
        ).fetchone()
        return {
            "status": "already_seeded",
            "sources_count": existing_count,
            "corpus_version": curr_cv[0] if curr_cv else None,
        }

    if force and existing_count > 0:
        conn.execute("DELETE FROM chunks")
        conn.execute("DELETE FROM sources")
        conn.execute("DELETE FROM corpus_versions")

    total_chunks = 0
    auto_chunks = 0
    human_chunks = 0

    for doc_spec in SEED_DOCS_SPEC:
        file_path = seed_path / doc_spec["filename"]
        if not file_path.exists():
            raise FileNotFoundError(f"Seed document file not found: {file_path}")

        raw_bytes = file_path.read_bytes()
        text_content = raw_bytes.decode("utf-8")

        file_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        content_hash = hashlib.sha256(
            text_content.strip().encode("utf-8")
        ).hexdigest()

        # Insert source
        conn.execute(
            """
            INSERT OR REPLACE INTO sources (
                doc_id, title, issuer, source_url, source_kind, sha256,
                fetched_at, is_synthetic, published_at, effective_from, effective_to,
                applies_to_json, cohorts_json, domains_json, supersedes_json,
                superseded_by, superseded_at, transitional_clause, status,
                content_hash, created_at, activated_at, activated_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_spec["doc_id"],
                doc_spec["title"],
                doc_spec["issuer"],
                doc_spec["source_url"],
                doc_spec["source_kind"],
                file_sha256,
                now_iso,
                1,  # is_synthetic = 1 for seed docs per spec
                doc_spec["published_at"],
                doc_spec["effective_from"],
                doc_spec["effective_to"],
                json.dumps(["chinh_quy"], ensure_ascii=False),
                json.dumps(["2022", "2023", "2024", "2025", "2026"]),
                json.dumps(doc_spec["domains"], ensure_ascii=False),
                json.dumps(doc_spec["supersedes"], ensure_ascii=False),
                doc_spec.get("superseded_by"),
                doc_spec.get("superseded_at"),
                doc_spec.get("transitional_clause", 0),
                doc_spec["status"],
                content_hash,
                now_iso,
                now_iso if doc_spec["status"] == SourceStatus.ACTIVE.value else None,
                "ADMIN:seed"
                if doc_spec["status"] == SourceStatus.ACTIVE.value
                else None,
            ),
        )

        # Parse articles and insert chunks
        articles = parse_articles_from_text(text_content)
        is_all_human = doc_spec.get("all_human_only", False)
        human_articles = doc_spec.get("human_only_articles", set())
        conflict_map = doc_spec.get("conflict_articles", {})

        for ord_idx, (art_no, art_title, art_text) in enumerate(articles, start=1):
            chunk_id = f"{doc_spec['doc_id']}-A{art_no:02d}"
            breadcrumb = f"{doc_spec['title']} > Điều {art_no}. {art_title}"

            if is_all_human or (art_no in human_articles):
                label = ChunkLabel.HUMAN_ONLY.value
                human_chunks += 1
            else:
                label = ChunkLabel.AUTO_ANSWERABLE.value
                auto_chunks += 1

            has_conflict = 1 if art_no in conflict_map else 0
            conflict_with = conflict_map.get(art_no)
            token_count = len(art_text.split())

            conn.execute(
                """
                INSERT OR REPLACE INTO chunks (
                    chunk_id, doc_id, article_no, clause_no, breadcrumb,
                    text, domain, label, conflict_flag, conflict_with,
                    ord, token_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    doc_spec["doc_id"],
                    str(art_no),
                    None,
                    breadcrumb,
                    art_text,
                    doc_spec["domain"],
                    label,
                    has_conflict,
                    conflict_with,
                    ord_idx,
                    token_count,
                ),
            )
            total_chunks += 1

    # Compute corpus version
    cv = compute_corpus_version(conn)

    # Insert corpus_versions record
    active_doc_ids = [
        s["doc_id"]
        for s in SEED_DOCS_SPEC
        if s["status"] == SourceStatus.ACTIVE.value
    ]
    conn.execute(
        """
        INSERT OR REPLACE INTO corpus_versions (
            corpus_version, created_at, actor, note, active_doc_ids_json
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            cv,
            now_iso,
            "SYSTEM:seed",
            "Initial seed corpus with 6 documents (Option A+B Hybrid)",
            json.dumps(active_doc_ids),
        ),
    )

    # Set current corpus version in settings
    conn.execute(
        """
        INSERT OR REPLACE INTO settings (key, value, updated_at, actor)
        VALUES ('current_corpus_version', ?, ?, 'SYSTEM')
        """,
        (cv, now_iso),
    )

    conn.commit()

    return {
        "status": "seeded",
        "corpus_version": cv,
        "sources_count": len(SEED_DOCS_SPEC),
        "active_sources": len(active_doc_ids),
        "total_chunks": total_chunks,
        "auto_chunks": auto_chunks,
        "human_chunks": human_chunks,
        "auto_ratio": round(auto_chunks / total_chunks, 3)
        if total_chunks
        else 0,
        "human_ratio": round(human_chunks / total_chunks, 3)
        if total_chunks
        else 0,
    }


def seed_corpus_if_empty(
    conn: sqlite3.Connection, seed_dir: Path | str | None = None
) -> dict[str, Any]:
    """Check if corpus is empty, and seed only if needed."""
    ensure_tables(conn)
    row = conn.execute("SELECT count(*) FROM sources").fetchone()
    if row and row[0] > 0:
        cv_row = conn.execute(
            "SELECT value FROM settings WHERE key = 'current_corpus_version'"
        ).fetchone()
        return {
            "status": "already_present",
            "sources_count": row[0],
            "corpus_version": cv_row[0] if cv_row else None,
        }
    return seed_corpus(conn, seed_dir=seed_dir, force=False)


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    db_file = Path(__file__).resolve().parent.parent / "data" / "app.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_file) as connection:
        result = seed_corpus(connection, force=True)
        print("Seed result:", json.dumps(result, indent=2, ensure_ascii=False))
