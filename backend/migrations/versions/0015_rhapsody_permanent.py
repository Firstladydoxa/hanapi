"""Rhapsody permanent content library and publication approvals."""
from alembic import op
from app.models.db import RhapsodyPermanentContent, RhapsodyPublicationApproval

revision = "0015_rhapsody_permanent"
down_revision = "0014_rhapsody_profile_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    RhapsodyPermanentContent.__table__.create(bind=bind, checkfirst=True)
    RhapsodyPublicationApproval.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    RhapsodyPublicationApproval.__table__.drop(bind=bind, checkfirst=True)
    RhapsodyPermanentContent.__table__.drop(bind=bind, checkfirst=True)
