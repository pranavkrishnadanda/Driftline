"""retrieval + agent support: ask jobs, answers per job, LLM call accounting (P3)"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE jobs ADD COLUMN payload jsonb NOT NULL DEFAULT '{}';

ALTER TABLE answers
  ADD COLUMN job_id uuid REFERENCES jobs(id) ON DELETE SET NULL,
  ADD COLUMN status text NOT NULL DEFAULT 'answered'
    CHECK (status IN ('answered', 'insufficient_evidence', 'refused')),
  ADD COLUMN degraded boolean NOT NULL DEFAULT false,
  ADD COLUMN cost_usd numeric(12, 6) NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX answers_job_id ON answers (job_id) WHERE job_id IS NOT NULL;

CREATE TABLE llm_calls (
  id bigserial PRIMARY KEY,
  job_id uuid REFERENCES jobs(id) ON DELETE CASCADE,
  tenant_id uuid REFERENCES tenants(id) ON DELETE CASCADE,
  node text NOT NULL,
  tier text NOT NULL,
  provider text NOT NULL,
  model text NOT NULL,
  input_tokens int NOT NULL CHECK (input_tokens >= 0),
  output_tokens int NOT NULL CHECK (output_tokens >= 0),
  cost_usd numeric(12, 6) NOT NULL CHECK (cost_usd >= 0),
  latency_ms real NOT NULL,
  degraded boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX llm_calls_job ON llm_calls (job_id);

CREATE INDEX doc_versions_version_key ON doc_versions (version_key);
"""

DOWNGRADE = """
DROP INDEX doc_versions_version_key;
DROP TABLE llm_calls;
DROP INDEX answers_job_id;
ALTER TABLE answers
  DROP COLUMN cost_usd,
  DROP COLUMN degraded,
  DROP COLUMN status,
  DROP COLUMN job_id;
ALTER TABLE jobs DROP COLUMN payload;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
