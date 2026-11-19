"""Rhapsody HAN drafting: assignment draft progress and draft provenance on translation versions. Idempotent (see 0001)."""
from alembic import op

revision = "0009_rhapsody_drafting"
down_revision = "0008_rhapsody_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in (
        "ALTER TABLE rhapsody_assignments ADD COLUMN IF NOT EXISTS draft_status VARCHAR(12) NOT NULL DEFAULT 'idle'",
        "ALTER TABLE rhapsody_assignments ADD COLUMN IF NOT EXISTS draft_total INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE rhapsody_assignments ADD COLUMN IF NOT EXISTS draft_done INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE rhapsody_assignments ADD COLUMN IF NOT EXISTS draft_note VARCHAR(500)",
        "ALTER TABLE rhapsody_translation_versions ADD COLUMN IF NOT EXISTS meta JSONB",
    ):
        op.execute(stmt)


def downgrade() -> None:
    op.execute("ALTER TABLE rhapsody_translation_versions DROP COLUMN IF EXISTS meta")
    for c in ("draft_note", "draft_done", "draft_total", "draft_status"):
        op.execute(f"ALTER TABLE rhapsody_assignments DROP COLUMN IF EXISTS {c}")
