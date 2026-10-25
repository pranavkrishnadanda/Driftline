"""initial schema (spec section 6)"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE tenants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL UNIQUE,
  skill_pack text,
  api_key_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sources (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('openfda', 'git_docs', 'upload')),
  config jsonb NOT NULL DEFAULT '{}',
  schedule text,
  last_polled_at timestamptz,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'stale_source', 'paused'))
);

CREATE TABLE documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  external_id text NOT NULL,
  title text,
  UNIQUE (source_id, external_id)
);

CREATE TABLE doc_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  version_no int NOT NULL,
  content_hash text NOT NULL,
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  raw_uri text,
  diff_from_prev jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_id, content_hash),
  UNIQUE (document_id, version_no),
  CHECK (valid_to IS NULL OR valid_to > valid_from),
  EXCLUDE USING gist (document_id WITH =, tstzrange(valid_from, valid_to, '[)') WITH &&)
);
CREATE INDEX doc_versions_doc_from ON doc_versions (document_id, valid_from);

CREATE TABLE chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id uuid NOT NULL REFERENCES doc_versions(id) ON DELETE CASCADE,
  ord int NOT NULL,
  section_path text NOT NULL DEFAULT '',
  text text NOT NULL,
  embedding vector(768),
  embed_model text,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
  UNIQUE (version_id, ord)
);
CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);

CREATE TABLE relations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  src_version_id uuid NOT NULL REFERENCES doc_versions(id) ON DELETE CASCADE,
  dst_document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('supersedes', 'amends', 'deprecates')),
  evidence_chunk_id uuid REFERENCES chunks(id) ON DELETE SET NULL,
  confidence real NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  status text NOT NULL DEFAULT 'applied' CHECK (status IN ('applied', 'pending_review', 'rejected'))
);

CREATE TABLE answers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  question text NOT NULL,
  as_of timestamptz NOT NULL,
  body jsonb NOT NULL,
  confidence real,
  watched boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE answer_citations (
  answer_id uuid NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
  claim_idx int NOT NULL,
  chunk_id uuid NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
  PRIMARY KEY (answer_id, claim_idx, chunk_id)
);

CREATE TABLE drift_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  answer_id uuid NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
  old_version_id uuid REFERENCES doc_versions(id) ON DELETE SET NULL,
  new_version_id uuid REFERENCES doc_versions(id) ON DELETE SET NULL,
  verdict text NOT NULL CHECK (verdict IN ('still_valid', 'changed', 'broken')),
  detail jsonb NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE review_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind text NOT NULL CHECK (kind IN ('answer', 'relation')),
  ref_id uuid NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}',
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid REFERENCES tenants(id) ON DELETE CASCADE,
  kind text NOT NULL,
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
  error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);

CREATE TABLE outbox (
  id bigserial PRIMARY KEY,
  topic text NOT NULL,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz
);
CREATE INDEX outbox_unpublished ON outbox (id) WHERE published_at IS NULL;

CREATE TABLE eval_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  git_sha text NOT NULL,
  corpus text NOT NULL,
  metrics jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""


def upgrade() -> None:
    op.execute(SCHEMA)


def downgrade() -> None:
    op.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
