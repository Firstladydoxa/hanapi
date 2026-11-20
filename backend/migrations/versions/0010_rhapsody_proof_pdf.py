"""Add generated PDF metadata to Rhapsody layout proofs."""
from alembic import op
import sqlalchemy as sa

revision = "0010_rhapsody_proof_pdf"
down_revision = "0009_rhapsody_layout_proofs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rhapsody_layout_proofs", sa.Column("pdf_storage_key", sa.String(length=500), nullable=True))
    op.add_column("rhapsody_layout_proofs", sa.Column("pdf_sha256", sa.String(length=64), nullable=True))
    op.add_column("rhapsody_layout_proofs", sa.Column("pdf_byte_size", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("rhapsody_layout_proofs", "pdf_byte_size")
    op.drop_column("rhapsody_layout_proofs", "pdf_sha256")
    op.drop_column("rhapsody_layout_proofs", "pdf_storage_key")
