"""drift + review: per-claim drift events, watch timestamps, review resolution, eval cases (P4)"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

UPGRADE = """
-- One drift event per (answer, new version, claim): a redelivered version.created
-- event must not record a second verdict. Rows written before P4 are answer-level,
-- so they get claim 0 and their answer's tenant.
ALTER TABLE drift_events
  ADD COLUMN claim_idx int NOT NULL DEFAULT 0,
  ADD COLUMN tenant_id uuid REFERENCES tenants(id) ON DELETE CASCADE;
ALTER TABLE drift_events ALTER COLUMN claim_idx DROP DEFAULT;
UPDATE drift_events d SET tenant_id = a.tenant_id FROM answers a WHERE a.id = d.answer_id;
ALTER TABLE drift_events ALTER COLUMN tenant_id SET NOT NULL;
CREATE UNIQUE INDEX drift_events_answer_version_claim
  ON drift_events (answer_id, new_version_id, claim_idx);

ALTER TABLE answers ADD COLUMN watched_at timestamptz;

-- tenant_id stays nullable: the P2 supersession code still queues items without it.
ALTER TABLE review_items
  ADD COLUMN tenant_id uuid REFERENCES tenants(id) ON DELETE CASCADE,
  ADD COLUMN resolution jsonb,
  ADD COLUMN resolved_at timestamptz,
  ADD COLUMN resolved_by text;
UPDATE review_items r SET tenant_id = a.tenant_id
  FROM answers a WHERE r.kind = 'answer' AND a.id = r.ref_id;
-- Relation items reference a relation, or (malformed extractions) a version.
UPDATE review_items r SET tenant_id = s.tenant_id
  FROM relations rel
  JOIN doc_versions v ON v.id = rel.src_version_id
  JOIN documents d ON d.id = v.document_id
  JOIN sources s ON s.id = d.source_id
  WHERE r.kind = 'relation' AND r.tenant_id IS NULL AND rel.id = r.ref_id;
UPDATE review_items r SET tenant_id = s.tenant_id
  FROM doc_versions v
  JOIN documents d ON d.id = v.document_id
  JOIN sources s ON s.id = d.source_id
  WHERE r.kind = 'relation' AND r.tenant_id IS NULL AND v.id = r.ref_id;
CREATE UNIQUE INDEX review_items_open_kind_ref ON review_items (kind, ref_id)
  WHERE status = 'open';

-- A resolved review item becomes a regression case for the eval suite.
CREATE TABLE eval_cases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  source_review_id uuid REFERENCES review_items(id) ON DELETE SET NULL,
  question text NOT NULL,
  as_of timestamptz NOT NULL,
  expected jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Drift looks up watched answers by the chunks they cite.
CREATE INDEX answer_citations_chunk ON answer_citations (chunk_id);
"""

DOWNGRADE = """
DROP INDEX answer_citations_chunk;
DROP TABLE eval_cases;
DROP INDEX review_items_open_kind_ref;
ALTER TABLE review_items
  DROP COLUMN resolved_by,
  DROP COLUMN resolved_at,
  DROP COLUMN resolution,
  DROP COLUMN tenant_id;
ALTER TABLE answers DROP COLUMN watched_at;
DROP INDEX drift_events_answer_version_claim;
ALTER TABLE drift_events
  DROP COLUMN tenant_id,
  DROP COLUMN claim_idx;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
