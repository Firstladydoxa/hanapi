"""Reviewer scoring evidence for language directions. Idempotent (see 0001)."""
from alembic import op

from app.models.db import LanguageReview

revision = "0005_language_reviews"
down_revision = "0004_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    LanguageReview.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS language_reviews CASCADE")
