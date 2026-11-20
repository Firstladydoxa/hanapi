"""Rhapsody reproducible multilingual layout proofs."""
from alembic import op
from app.models.db import RhapsodyLayoutProof

revision = "0013_rhapsody_layout_proofs"
down_revision = "0012_rhapsody_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    RhapsodyLayoutProof.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    RhapsodyLayoutProof.__table__.drop(bind=op.get_bind(), checkfirst=True)
