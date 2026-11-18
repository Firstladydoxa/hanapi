"""Language registry and capability matrix: native names, engine language codes, review flag, per-direction technical/validation status,
and a capability column on the model registry (translation | chat | embedding). Idempotent (see 0001)."""
from alembic import op

revision = "0003_languages"
down_revision = "0002_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for ddl in ("native_name varchar(200)", "model_codes jsonb", "reviewed boolean NOT NULL DEFAULT false", "notes text"):
        op.execute(f"ALTER TABLE languages ADD COLUMN IF NOT EXISTS {ddl}")
    for ddl in (
        "technical_status varchar(16) NOT NULL DEFAULT 'untested'",
        "technical_checked_at timestamptz",
        "technical_detail jsonb",
        "validation_status varchar(16) NOT NULL DEFAULT 'pending'",
    ):
        op.execute(f"ALTER TABLE language_directions ADD COLUMN IF NOT EXISTS {ddl}")
    op.execute("ALTER TABLE model_registry ADD COLUMN IF NOT EXISTS capability varchar(16) NOT NULL DEFAULT 'translation'")


def downgrade() -> None:
    for col in ("native_name", "model_codes", "reviewed", "notes"):
        op.execute(f"ALTER TABLE languages DROP COLUMN IF EXISTS {col}")
    for col in ("technical_status", "technical_checked_at", "technical_detail", "validation_status"):
        op.execute(f"ALTER TABLE language_directions DROP COLUMN IF EXISTS {col}")
    op.execute("ALTER TABLE model_registry DROP COLUMN IF EXISTS capability")
