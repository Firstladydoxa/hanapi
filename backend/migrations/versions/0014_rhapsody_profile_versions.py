"""Rhapsody language profile revision history."""
from alembic import op
from app.models.db import RhapsodyProfileVersion

revision = "0014_rhapsody_profile_versions"
down_revision = "0013_rhapsody_layout_proofs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    RhapsodyProfileVersion.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    RhapsodyProfileVersion.__table__.drop(bind=op.get_bind(), checkfirst=True)
