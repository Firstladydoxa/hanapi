"""Initial HAN schema: projects, users, languages, jobs, segments, immutable versions/approvals, TM, terminology,
model registry, routing events, usage and audit.

The tables come from the SQLAlchemy models as of this revision (this is the baseline; later revisions must be
explicit). Immutability of `translation_versions` and `approvals` is enforced by database triggers (spec §10.1).
"""
from alembic import op

from app.database import Base
from app.models import db as _models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

IMMUTABLE = ("translation_versions", "approvals")


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION han_forbid_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% rows are immutable (% blocked)', TG_TABLE_NAME, TG_OP USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in IMMUTABLE:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION han_forbid_mutation();"
        )


def downgrade() -> None:
    for table in IMMUTABLE:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS han_forbid_mutation()")
    Base.metadata.drop_all(bind=op.get_bind())
