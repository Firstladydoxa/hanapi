"""Rhapsody of Realities publication foundation.

0001_initial uses SQLAlchemy metadata.create_all on fresh databases, so this
revision must be safe both when the tables already exist and when upgrading an
older installation that predates the Rhapsody models.
"""
from alembic import op
from app.models.db import (
    RhapsodyEdition, RhapsodySourceFile, RhapsodyMasterVersion,
    RhapsodySection, RhapsodySegment, RhapsodyAssignment,
)

revision = "0007_rhapsody"
down_revision = "0006_glossary_doctrine"
branch_labels = None
depends_on = None

TABLES = (
    RhapsodyEdition, RhapsodySourceFile, RhapsodyMasterVersion,
    RhapsodySection, RhapsodySegment, RhapsodyAssignment,
)


def upgrade() -> None:
    bind = op.get_bind()
    for model in TABLES:
        model.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for model in reversed(TABLES):
        model.__table__.drop(bind=bind, checkfirst=True)
