"""Verified email and one-time email authentication challenges."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0010_email_auth"
down_revision = "0009_rhapsody_drafting"
branch_labels = None
depends_on = None


def _uuid():
    return sa.Uuid(as_uuid=True)


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    # Fresh databases are built from current metadata by 0001, so the objects may already exist.
    if "email_verified" not in {c["name"] for c in insp.get_columns("users")}:
        op.add_column("users", sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.true()))
    tables = set(insp.get_table_names())
    if "email_auth_challenges" not in tables:
        op.create_table(
            "email_auth_challenges",
            sa.Column("id", _uuid(), primary_key=True),
            sa.Column("user_id", _uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("purpose", sa.String(24), nullable=False),
            sa.Column("code_hash", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True)),
            sa.Column("invalidated_at", sa.DateTime(timezone=True)),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("purpose in ('verify_email','reset_password')", name="ck_email_auth_purpose"),
        )
        op.create_index("ix_email_auth_challenges_user_id", "email_auth_challenges", ["user_id"])
        op.create_index("ix_email_auth_challenges_expires_at", "email_auth_challenges", ["expires_at"])
        op.create_index("ix_email_auth_active", "email_auth_challenges", ["user_id", "purpose", "consumed_at", "invalidated_at"])
    if "registration_reminders" not in tables:
        op.create_table(
            "registration_reminders",
            sa.Column("id", _uuid(), primary_key=True),
            sa.Column("user_id", _uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True)),
            sa.Column("cancelled_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_registration_reminders_user_id", "registration_reminders", ["user_id"])
        op.create_index("ix_registration_reminders_due_at", "registration_reminders", ["due_at"])


def downgrade() -> None:
    op.drop_table("registration_reminders")
    op.drop_table("email_auth_challenges")
    op.drop_column("users", "email_verified")
