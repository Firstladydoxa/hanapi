"""Rhapsody of Realities publication foundation."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_rhapsody"
down_revision = "0005_language_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rhapsody_editions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("active_master_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("year", "month", name="uq_rhapsody_edition_period"),
        sa.CheckConstraint("month between 1 and 12", name="ck_rhapsody_month"),
        sa.CheckConstraint("year between 2000 and 2200", name="ck_rhapsody_year"),
        sa.CheckConstraint("status in ('draft','ready','active','archived')", name="ck_rhapsody_edition_status"),
    )
    op.create_table(
        "rhapsody_source_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("edition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rhapsody_editions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(120), nullable=False),
        sa.Column("format", sa.String(12), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False, unique=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("format in ('docx','xliff')", name="ck_rhapsody_source_format"),
    )
    op.create_index("ix_rhapsody_source_files_edition_id", "rhapsody_source_files", ["edition_id"])
    op.create_table(
        "rhapsody_master_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("edition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rhapsody_editions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source_file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rhapsody_source_files.id"), nullable=False),
        sa.Column("structure", postgresql.JSONB(), nullable=False),
        sa.Column("validation", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("edition_id", "version_number", name="uq_rhapsody_master_version"),
    )
    op.create_index("ix_rhapsody_master_versions_edition_id", "rhapsody_master_versions", ["edition_id"])
    op.create_table(
        "rhapsody_sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("master_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rhapsody_master_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rhapsody_sections.id", ondelete="CASCADE")),
        sa.Column("stable_key", sa.String(200), nullable=False),
        sa.Column("section_type", sa.String(40), nullable=False, server_default="content"),
        sa.Column("title", sa.String(500)),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("day_number", sa.Integer()),
        sa.Column("formatting", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("master_version_id", "stable_key", name="uq_rhapsody_section_key"),
    )
    op.create_index("ix_rhapsody_sections_master_version_id", "rhapsody_sections", ["master_version_id"])
    op.create_table(
        "rhapsody_segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("master_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rhapsody_master_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("section_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rhapsody_sections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stable_key", sa.String(240), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("source_markup", sa.Text()),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("master_version_id", "stable_key", name="uq_rhapsody_segment_key"),
    )
    op.create_index("ix_rhapsody_segments_master_version_id", "rhapsody_segments", ["master_version_id"])
    op.create_index("ix_rhapsody_segments_section_id", "rhapsody_segments", ["section_id"])
    op.create_table(
        "rhapsody_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("master_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rhapsody_master_versions.id"), nullable=False),
        sa.Column("target_language", sa.String(16), sa.ForeignKey("languages.code"), nullable=False),
        sa.Column("translator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False, server_default="assigned"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("master_version_id", "target_language", "translator_id", name="uq_rhapsody_assignment"),
        sa.CheckConstraint("status in ('assigned','in_progress','submitted','in_review','changes_requested','approved','published')", name="ck_rhapsody_assignment_status"),
    )
    op.create_index("ix_rhapsody_assignments_master_version_id", "rhapsody_assignments", ["master_version_id"])
    op.create_index("ix_rhapsody_assignments_translator_id", "rhapsody_assignments", ["translator_id"])


def downgrade() -> None:
    op.drop_table("rhapsody_assignments")
    op.drop_table("rhapsody_segments")
    op.drop_table("rhapsody_sections")
    op.drop_table("rhapsody_master_versions")
    op.drop_table("rhapsody_source_files")
    op.drop_table("rhapsody_editions")
