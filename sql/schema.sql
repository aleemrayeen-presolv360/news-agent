-- News Intel pipeline schema (Neon Postgres + pgvector).
-- Run once:  psql "$NEON_DSN" -f sql/schema.sql
-- Idempotent: safe to re-run.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------- sources
CREATE TABLE IF NOT EXISTS sources (
  id                   TEXT PRIMARY KEY,
  name                 TEXT NOT NULL,
  tier                 CHAR(1) NOT NULL,
  kind                 TEXT NOT NULL DEFAULT 'rss',
  feed_url             TEXT,
  enabled              BOOLEAN NOT NULL DEFAULT true,
  note                 TEXT,
  last_poll_at         TIMESTAMPTZ,
  last_success_at      TIMESTAMPTZ,
  last_item_at         TIMESTAMPTZ,
  consecutive_failures INT NOT NULL DEFAULT 0,
  last_error           TEXT
);

-- ------------------------------------------------------------- raw_items
-- Everything ever seen. article_text is nulled at 12 months; the row stays.
CREATE TABLE IF NOT EXISTS raw_items (
  id             BIGSERIAL PRIMARY KEY,
  url_canonical  TEXT UNIQUE NOT NULL,
  url_original   TEXT,
  title          TEXT NOT NULL,
  source_id      TEXT NOT NULL REFERENCES sources(id),
  published_at   TIMESTAMPTZ NOT NULL,
  ingested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  feed_summary   TEXT,
  article_text   TEXT,
  paywalled      BOOLEAN NOT NULL DEFAULT false,
  rules_pass     BOOLEAN,          -- stage 0: regex gate
  rules_reason   TEXT,
  triage_pass    BOOLEAN,          -- stage 2: trained classifier
  triage_score   REAL
);
CREATE INDEX IF NOT EXISTS raw_items_published_idx  ON raw_items (published_at DESC);
CREATE INDEX IF NOT EXISTS raw_items_source_idx     ON raw_items (source_id);
CREATE INDEX IF NOT EXISTS raw_items_triage_idx     ON raw_items (triage_pass)
  WHERE triage_pass IS TRUE;

-- --------------------------------------------------------------- threads
CREATE TABLE IF NOT EXISTS threads (
  id             BIGSERIAL PRIMARY KEY,
  label          TEXT NOT NULL,
  centroid       VECTOR(384),
  first_seen     TIMESTAMPTZ,
  last_seen      TIMESTAMPTZ,
  part_count     INT NOT NULL DEFAULT 0,
  notion_page_id TEXT
);

-- -------------------------------------------------------------- clusters
CREATE TABLE IF NOT EXISTS clusters (
  id                BIGSERIAL PRIMARY KEY,
  canonical_item_id BIGINT,
  member_urls       TEXT[] NOT NULL DEFAULT '{}',   -- becomes "More details"
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------- news_memory
-- THE PERMANENT LAYER. Never deleted. Retention only nulls notion_page_id,
-- so Notion stays tidy (30 days) while old news can still be referenced.
CREATE TABLE IF NOT EXISTS news_memory (
  id              BIGINT PRIMARY KEY REFERENCES raw_items(id),
  headline        TEXT NOT NULL,
  one_liner       TEXT NOT NULL,     -- survives the Notion page being gone
  source_url      TEXT NOT NULL,
  source_name     TEXT NOT NULL,
  published_at    TIMESTAMPTZ NOT NULL,
  embedding       VECTOR(384) NOT NULL,
  entities        TEXT[] NOT NULL DEFAULT '{}',
  topics          TEXT[] NOT NULL DEFAULT '{}',
  score           INT,
  score_breakdown JSONB,
  market_impact   TEXT,
  cluster_id      BIGINT REFERENCES clusters(id),
  thread_id       BIGINT REFERENCES threads(id),
  notion_page_id  TEXT,              -- NULL once archived out of Notion
  notion_status   TEXT NOT NULL DEFAULT 'live',  -- live|archived|restored
  reference_count INT NOT NULL DEFAULT 0,        -- >=2 triggers auto-save
  published_week  DATE,
  carry_over      BOOLEAN NOT NULL DEFAULT false,
  alerted_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS news_memory_embed_idx
  ON news_memory USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS news_memory_published_idx
  ON news_memory (published_at DESC);
CREATE INDEX IF NOT EXISTS news_memory_entities_idx
  ON news_memory USING gin (entities);
CREATE INDEX IF NOT EXISTS news_memory_week_idx
  ON news_memory (published_week);

-- ---------------------------------------------------- labels / feedback
-- Reader thumbs up/down. Reserved for a future trained triage classifier.
CREATE TABLE IF NOT EXISTS feedback (
  id         BIGSERIAL PRIMARY KEY,
  item_id    BIGINT REFERENCES raw_items(id),
  verdict    TEXT NOT NULL,          -- good | noise | missed
  note       TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (item_id)
);

-- ------------------------------------------------------------ run audit
-- Powers the health stats. Without this a quiet week and a broken
-- pipeline look identical.
CREATE TABLE IF NOT EXISTS runs (
  id             BIGSERIAL PRIMARY KEY,
  job            TEXT NOT NULL,
  started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at    TIMESTAMPTZ,
  sources_total  INT,
  sources_ok     INT,
  sources_failed INT,
  items_seen     INT,
  items_new      INT,
  ok             BOOLEAN,
  detail         JSONB
);
