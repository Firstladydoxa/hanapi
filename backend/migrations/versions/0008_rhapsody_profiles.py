"""Managed Rhapsody fonts and per-language publishing profiles."""
from alembic import op
from app.models.db import RhapsodyFontAsset, RhapsodyLanguageProfile, RhapsodyProfileFont

revision = "0008_rhapsody_profiles"
down_revision = "0007_rhapsody"
branch_labels = None
depends_on = None

TABLES = (RhapsodyFontAsset, RhapsodyLanguageProfile, RhapsodyProfileFont)


def upgrade() -> None:
    bind = op.get_bind()
    for model in TABLES:
        model.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for model in reversed(TABLES):
        model.__table__.drop(bind=bind, checkfirst=True)
