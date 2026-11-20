"""Verified email and one-time email authentication challenges."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from app.models.db import EmailAuthChallenge, RegistrationReminder

revision = "0008_email_auth"
down_revision = "0007_rhapsody_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # 0001_initial uses current metadata.create_all on fresh databases. On those
    # databases this column already exists; older installations need it added.
    if "email_verified" not in {c["name"] for c in inspect(bind).get_columns("users")}:
        op.add_column("users", sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.true()))
    EmailAuthChallenge.__table__.create(bind, checkfirst=True)
    RegistrationReminder.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    RegistrationReminder.__table__.drop(bind, checkfirst=True)
    EmailAuthChallenge.__table__.drop(bind, checkfirst=True)
    if "email_verified" in {c["name"] for c in inspect(bind).get_columns("users")}:
        op.drop_column("users", "email_verified")
