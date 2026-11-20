"""Verified email and one-time email authentication challenges."""
from alembic import op
import sqlalchemy as sa
from app.models.db import EmailAuthChallenge, RegistrationReminder

revision = "0008_email_auth"
down_revision = "0007_rhapsody_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.true()))
    bind = op.get_bind()
    EmailAuthChallenge.__table__.create(bind, checkfirst=True)
    RegistrationReminder.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    RegistrationReminder.__table__.drop(bind, checkfirst=True)
    EmailAuthChallenge.__table__.drop(bind, checkfirst=True)
    op.drop_column("users", "email_verified")
