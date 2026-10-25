"""ingestion support: version keys, section hashes, chunk tags, source cursors (P2)"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE doc_versions
  ADD COLUMN version_key text,
  ADD COLUMN section_hashes jsonb NOT NULL DEFAULT '{}',
  ADD COLUMN source_meta jsonb NOT NULL DEFAULT '{}';

ALTER TABLE chunks ADD COLUMN tags text[] NOT NULL DEFAULT '{}';

CREATE TABLE source_cursors (
  source_id uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  external_id text NOT NULL,
  cursor text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_id, external_id)
);
"""

DOWNGRADE = """
DROP TABLE source_cursors;
ALTER TABLE chunks DROP COLUMN tags;
ALTER TABLE doc_versions
  DROP COLUMN source_meta,
  DROP COLUMN section_hashes,
  DROP COLUMN version_key;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
