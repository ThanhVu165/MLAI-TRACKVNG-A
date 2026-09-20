-- 001_init.sql: Schema SQLite theo Mục 6 của PROJECT_SPEC.md

CREATE TABLE IF NOT EXISTS cases (
  case_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  sender TEXT,
  subject TEXT,
  body_raw TEXT,
  body_clean TEXT,
  body_masked TEXT,
  language TEXT,
  received_at TEXT,
  created_at TEXT NOT NULL,
  status TEXT NOT NULL,
  corpus_version TEXT NOT NULL,
  injection_suspected INTEGER DEFAULT 0,
  send_deadline TEXT,
  parent_case_id TEXT
);

CREATE TABLE IF NOT EXISTS extractions (
  case_id TEXT PRIMARY KEY REFERENCES cases(case_id),
  payload_json TEXT NOT NULL,
  llm_error TEXT,
  latency_ms INTEGER,
  prompt_hash TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
  decision_id TEXT PRIMARY KEY,
  case_id TEXT REFERENCES cases(case_id),
  decision TEXT NOT NULL,
  escalation_type TEXT,
  rule_id TEXT NOT NULL,
  reason TEXT NOT NULL,
  evidence_ids_json TEXT,
  evidence_status TEXT,
  corpus_version TEXT NOT NULL,
  is_override INTEGER DEFAULT 0,
  superseded_by TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drafts (
  draft_id TEXT PRIMARY KEY,
  case_id TEXT REFERENCES cases(case_id),
  kind TEXT NOT NULL,
  subject TEXT,
  body TEXT,
  citations_json TEXT,
  grounded INTEGER,
  guard_failures_json TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS escalations (
  case_id TEXT PRIMARY KEY REFERENCES cases(case_id),
  escalation_type TEXT NOT NULL,
  summary TEXT,
  facts_json TEXT,
  basis_json TEXT,
  question TEXT,
  options_json TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS human_decisions (
  id TEXT PRIMARY KEY,
  case_id TEXT REFERENCES cases(case_id),
  actor TEXT NOT NULL,
  choice TEXT NOT NULL,
  reason TEXT NOT NULL,
  shown_at TEXT,
  decided_at TEXT,
  review_seconds REAL
);

CREATE TABLE IF NOT EXISTS sources (
  doc_id TEXT PRIMARY KEY,
  title TEXT,
  issuer TEXT,
  source_url TEXT,
  source_kind TEXT,
  sha256 TEXT UNIQUE,
  fetched_at TEXT,
  is_synthetic INTEGER DEFAULT 0,
  published_at TEXT,
  effective_from TEXT,
  effective_to TEXT,
  applies_to_json TEXT,
  cohorts_json TEXT,
  domains_json TEXT,
  supersedes_json TEXT,
  superseded_by TEXT,
  superseded_at TEXT,
  transitional_clause INTEGER DEFAULT 0,
  status TEXT NOT NULL,
  content_hash TEXT,
  created_at TEXT,
  activated_at TEXT,
  activated_by TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
  chunk_id TEXT PRIMARY KEY,
  doc_id TEXT REFERENCES sources(doc_id),
  article_no TEXT,
  clause_no TEXT,
  breadcrumb TEXT NOT NULL,
  text TEXT NOT NULL,
  domain TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT 'human_only',
  conflict_flag INTEGER DEFAULT 0,
  conflict_with TEXT,
  ord INTEGER,
  token_count INTEGER
);

CREATE TABLE IF NOT EXISTS corpus_versions (
  corpus_version TEXT PRIMARY KEY,
  created_at TEXT,
  actor TEXT,
  note TEXT,
  active_doc_ids_json TEXT
);

CREATE TABLE IF NOT EXISTS audit_events (
  event_id TEXT PRIMARY KEY,
  case_id TEXT,
  ts TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  rule_id TEXT,
  input_ref TEXT,
  output_ref TEXT,
  reason TEXT,
  sources_json TEXT,
  corpus_version TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_events(case_id);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_events(ts);

CREATE TABLE IF NOT EXISTS step_latencies (
  case_id TEXT,
  step TEXT,
  ms INTEGER,
  ok INTEGER,
  ts TEXT
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT,
  actor TEXT
);
