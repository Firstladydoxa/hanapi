"""Rhapsody segment translations and human review."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_rhapsody_workflow"
down_revision = "0006_rhapsody"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rhapsody_segment_translations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rhapsody_assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rhapsody_segments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("status", sa.String(20), nullable=False, server_default="not_started"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("assignment_id", "segment_id", name="uq_rhapsody_segment_translation"),
        sa.CheckConstraint("status in ('not_started','draft','in_review','approved','changes_requested')", name="ck_rhapsody_segment_translation_status"),
    )
    op.create_index("ix_rhapsody_segment_translations_assignment_id", "rhapsody_segment_translations", ["assignment_id"])
    op.create_index("ix_rhapsody_segment_translations_segment_id", "rhapsody_segment_translations", ["segment_id"])
    op.create_table(
        "rhapsody_translation_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("segment_translation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rhapsody_segment_translations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("target_text", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(8), nullable=False, server_default="human"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("parent_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rhapsody_translation_versions.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("segment_translation_id", "version_number", name="uq_rhapsody_translation_version"),
        sa.CheckConstraint("origin in ('ai','human')", name="ck_rhapsody_translation_origin"),
    )
    op.create_index("ix_rhapsody_translation_versions_segment_translation_id", "rhapsody_translation_versions", ["segment_translation_id"])
    op.create_table(
        "rhapsody_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rhapsody_assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rhapsody_segments.id", ondelete="CASCADE")),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("body", sa.String(3000), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rhapsody_comments_assignment_id", "rhapsody_comments", ["assignment_id"])
    op.create_table(
        "rhapsody_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rhapsody_assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("note", sa.String(3000)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("decision in ('approved','changes_requested')", name="ck_rhapsody_review_decision"),
    )
    op.create_index("ix_rhapsody_reviews_assignment_id", "rhapsody_reviews", ["assignment_id"])


def downgrade() -> None:
    op.drop_table("rhapsody_reviews")
    op.drop_table("rhapsody_comments")
    op.drop_table("rhapsody_translation_versions")
    op.drop_table("rhapsody_segment_translations")
