"""Rhapsody segment translations and human review.

The initial schema migration uses metadata.create_all on fresh installs.
checkfirst keeps this revision idempotent for both fresh and existing DBs.
"""
from alembic import op
from app.models.db import (
    RhapsodySegmentTranslation, RhapsodyTranslationVersion,
    RhapsodyComment, RhapsodyReview,
)

revision = "0007_rhapsody_workflow"
down_revision = "0006_rhapsody"
branch_labels = None
depends_on = None

TABLES = (
    RhapsodySegmentTranslation, RhapsodyTranslationVersion,
    RhapsodyComment, RhapsodyReview,
)


def upgrade() -> None:
    bind = op.get_bind()
    for model in TABLES:
        model.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for model in reversed(TABLES):
        model.__table__.drop(bind=bind, checkfirst=True)
