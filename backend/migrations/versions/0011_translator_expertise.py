"""Translator language of expertise."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0011_translator_expertise"
down_revision = "0010_email_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in inspect(op.get_bind()).get_columns("users")}
    if "expertise_language" not in cols:
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("expertise_language", sa.String(16), sa.ForeignKey("languages.code"), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("expertise_language")
