"""review queue: tenant required on review items, review kinds, `needs_review` jobs (P4)"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

UPGRADE = """
-- Backfill any item still missing its tenant (written by the P2 supersession code
-- before it set one), exactly as 0004 did.
UPDATE review_items r SET tenant_id = a.tenant_id
  FROM answers a WHERE r.tenant_id IS NULL AND r.kind = 'answer' AND a.id = r.ref_id;
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
-- An item whose referent is gone belongs to no tenant: no tenant-scoped API could ever
-- show or resolve it.
DELETE FROM review_items WHERE tenant_id IS NULL;
ALTER TABLE review_items ALTER COLUMN tenant_id SET NOT NULL;

-- 'answer' stays valid for rows written before 0006; the drift hook's broken answers
-- are renamed to the explicit kind.
ALTER TABLE review_items DROP CONSTRAINT review_items_kind_check;
ALTER TABLE review_items ADD CONSTRAINT review_items_kind_check
  CHECK (kind IN ('answer', 'relation', 'broken_answer', 'low_confidence_answer'));
UPDATE review_items SET kind = 'broken_answer'
  WHERE kind = 'answer' AND payload->>'reason' = 'broken'
    AND NOT EXISTS (
      SELECT 1 FROM review_items o
      WHERE o.kind = 'broken_answer' AND o.ref_id = review_items.ref_id AND o.status = 'open'
    );

-- An ask paused by the answer graph's interrupt() until a reviewer resolves it.
ALTER TABLE jobs DROP CONSTRAINT jobs_status_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_status_check
  CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'needs_review'));
"""

DOWNGRADE = """
UPDATE jobs SET status = 'failed', error = 'review_unsupported', finished_at = now()
  WHERE status = 'needs_review';
ALTER TABLE jobs DROP CONSTRAINT jobs_status_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_status_check
  CHECK (status IN ('queued', 'running', 'succeeded', 'failed'));

-- The old schema has no paused asks, and keeps broken answers as 'answer'.
DELETE FROM review_items WHERE kind = 'low_confidence_answer';
UPDATE review_items SET kind = 'answer' WHERE kind = 'broken_answer';
ALTER TABLE review_items DROP CONSTRAINT review_items_kind_check;
ALTER TABLE review_items ADD CONSTRAINT review_items_kind_check
  CHECK (kind IN ('answer', 'relation'));
ALTER TABLE review_items ALTER COLUMN tenant_id DROP NOT NULL;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
