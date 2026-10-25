"""doc_versions: allow a content revert (A -> B -> A) to be a new version (P4)"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# The version store now treats only "same content as the current version" as a no-op,
# so an older hash may legitimately repeat. Windows stay guarded by the btree_gist
# exclusion constraint and version numbers by UNIQUE (document_id, version_no).
UPGRADE = """
ALTER TABLE doc_versions DROP CONSTRAINT doc_versions_document_id_content_hash_key;
CREATE INDEX doc_versions_doc_hash ON doc_versions (document_id, content_hash);
"""

# Fails loudly if a revert row exists: the old schema cannot represent it.
DOWNGRADE = """
DROP INDEX doc_versions_doc_hash;
ALTER TABLE doc_versions
  ADD CONSTRAINT doc_versions_document_id_content_hash_key UNIQUE (document_id, content_hash);
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
