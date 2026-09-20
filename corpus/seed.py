from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path

from corpus.chunker import LegalChunk, chunk_document
from corpus.store import bump_corpus_version, create_source, now_iso, replace_chunks


@dataclass(frozen=True)
class SeedDocument:
    filename: str
    doc_id: str
    title: str
    issuer: str
    domain: str
    published_at: str
    effective_from: str
    status: str = "ACTIVE"
    supersedes: tuple[str, ...] = ()
    transitional_clause: bool = False
    human_ords: frozenset[int] = frozenset()


SEED_DOCUMENTS = (
    SeedDocument(
        "01_quy_dinh_ren_luyen_2026.txt",
        "RL-2026-3150",
        "QĐ 3150/2026",
        "Phòng Công tác Sinh viên",
        "conduct_score",
        "2026-07-07",
        "2026-07-07",
        supersedes=("RL-2025-2363",),
        transitional_clause=True,
        human_ords=frozenset({3, 8, 9}),
    ),
    SeedDocument(
        "02_quy_dinh_ren_luyen_2025.txt",
        "RL-2025-2363",
        "QĐ 2363/2025",
        "Phòng Công tác Sinh viên",
        "conduct_score",
        "2025-07-01",
        "2025-07-01",
        status="SUPERSEDED",
        human_ords=frozenset({6, 9}),
    ),
    SeedDocument(
        "03_quy_che_rut_hoc_phan_2026.txt",
        "WD-2026-20",
        "QĐ 20/2026",
        "Phòng Đào tạo",
        "course_withdrawal",
        "2026-08-01",
        "2026-08-01",
        human_ords=frozenset({3, 6}),
    ),
    SeedDocument(
        "04_huong_dan_phuc_khao_diem.txt",
        "GA-2026-08",
        "HD 08/2026",
        "Phòng Khảo thí",
        "grade_appeal",
        "2026-08-05",
        "2026-08-05",
        human_ords=frozenset({3, 4, 7, 8, 9}),
    ),
    SeedDocument(
        "05_thong_bao_hoc_phi_2026_1.txt",
        "TU-2026-01",
        "TB học phí 2026-1",
        "Phòng Tài chính",
        "course_withdrawal",
        "2026-08-10",
        "2026-08-10",
        human_ords=frozenset({9}),
    ),
    SeedDocument(
        "06_quyet_dinh_phan_cap_tham_quyen.txt",
        "AUTH-2026-01",
        "QĐ phân cấp 01/2026",
        "Hiệu trưởng",
        "conduct_score",
        "2026-01-05",
        "2026-01-05",
        human_ords=frozenset(range(1, 10)),
    ),
)


def _domain_for_chunk(document: SeedDocument, chunk: LegalChunk) -> str:
    if document.doc_id != "AUTH-2026-01":
        return document.domain
    return {"1": "conduct_score", "2": "course_withdrawal", "3": "grade_appeal"}.get(
        chunk.article_no or "", document.domain
    )


def seed_if_empty(
    conn: sqlite3.Connection,
    *,
    seed_dir: str | Path | None = None,
    actor: str = "ADMIN:seed",
) -> int:
    if conn.execute("SELECT 1 FROM sources LIMIT 1").fetchone():
        return 0
    root = Path(seed_dir) if seed_dir else Path(__file__).parents[1] / "data" / "seed_docs"
    activated_at = now_iso()

    for document in SEED_DOCUMENTS:
        text = (root / document.filename).read_text(encoding="utf-8")
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        create_source(
            conn,
            {
                "doc_id": document.doc_id,
                "title": document.title,
                "issuer": document.issuer,
                "source_kind": "text",
                "sha256": content_hash,
                "is_synthetic": 1,
                "published_at": document.published_at,
                "effective_from": document.effective_from,
                "applies_to_json": json.dumps(["undergraduate"]),
                "cohorts_json": json.dumps(["K48", "K49", "K50"]),
                "domains_json": json.dumps(
                    ["conduct_score", "course_withdrawal", "grade_appeal"]
                    if document.doc_id == "AUTH-2026-01"
                    else [document.domain]
                ),
                "supersedes_json": json.dumps(document.supersedes),
                "superseded_by": "RL-2026-3150" if document.doc_id == "RL-2025-2363" else None,
                "superseded_at": activated_at if document.doc_id == "RL-2025-2363" else None,
                "transitional_clause": int(document.transitional_clause),
                "status": document.status,
                "content_hash": content_hash,
                "activated_at": activated_at if document.status == "ACTIVE" else None,
                "activated_by": actor if document.status == "ACTIVE" else None,
            },
        )
        chunks = chunk_document(
            text,
            doc_id=document.doc_id,
            doc_title=document.title,
            domain=document.domain,
        )
        labelled = [
            replace(
                chunk,
                domain=_domain_for_chunk(document, chunk),
                label="human_only" if chunk.ord in document.human_ords else "auto_answerable",
            ).to_record()
            for chunk in chunks
        ]
        replace_chunks(conn, document.doc_id, labelled)

    bump_corpus_version(conn, actor, "Nạp bộ corpus giả lập ban đầu")
    return len(SEED_DOCUMENTS)
