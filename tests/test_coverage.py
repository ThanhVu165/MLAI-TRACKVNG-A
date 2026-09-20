import sqlite3
from dataclasses import dataclass

from corpus.coverage import label_chunk, list_coverage, suggest_labels


@dataclass
class FakeResult:
    ok: bool
    data: dict[str, object]
    error: str | None = None


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE chunks (
          chunk_id TEXT PRIMARY KEY, doc_id TEXT, breadcrumb TEXT NOT NULL,
          text TEXT NOT NULL, label TEXT NOT NULL DEFAULT 'human_only', ord INTEGER
        );
        CREATE TABLE settings (
          key TEXT PRIMARY KEY, value TEXT, updated_at TEXT, actor TEXT
        );
        INSERT INTO chunks VALUES
          ('c1', 'DOC-1', 'QĐ 1 · Điều 1', 'Thủ tục nộp đơn.', 'human_only', 1);
        INSERT INTO settings VALUES ('review:DOC-1', 'APPROVE', NULL, 'ADMIN:vu');
        """
    )
    return conn


def test_human_must_apply_label_and_each_change_is_audited() -> None:
    conn = _db()
    events: list[dict[str, object]] = []
    assert list_coverage(conn, "DOC-1")[0]["label"] == "human_only"

    changed = label_chunk(
        conn,
        "c1",
        "auto_answerable",
        actor="ADMIN:vu",
        audit=lambda **event: events.append(event),
    )

    assert changed
    assert list_coverage(conn, "DOC-1")[0]["label"] == "auto_answerable"
    assert conn.execute("SELECT 1 FROM settings WHERE key='review:DOC-1'").fetchone() is None
    assert events == [
        {
            "case_id": None,
            "actor": "ADMIN:vu",
            "action": "CHUNK_LABELLED",
            "input_ref": "c1",
            "output_ref": "auto_answerable",
            "reason": "Đổi nhãn từ human_only sang auto_answerable",
            "sources": ["c1"],
        }
    ]


def test_llm_suggestion_does_not_mutate_label() -> None:
    conn = _db()
    chunks = list_coverage(conn, "DOC-1")

    def caller(_prompt: str, **_kwargs: object) -> FakeResult:
        return FakeResult(
            True,
            {
                "suggestions": [
                    {"chunk_id": "c1", "label": "auto_answerable", "reason": "Thủ tục rõ"}
                ]
            },
        )

    suggestions = suggest_labels(chunks, case_id="DOC-1", caller=caller)

    assert suggestions["c1"][0] == "auto_answerable"
    assert list_coverage(conn, "DOC-1")[0]["label"] == "human_only"
