"""Per-language glossary, team leader role and the doctrine knowledge category. Idempotent (see 0001)."""
from alembic import op

from app.models.db import GlossaryEntry, GlossaryLead

revision = "0006_glossary_doctrine"
down_revision = "0005_language_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in (GlossaryEntry.__table__, GlossaryLead.__table__):
        table.create(bind, checkfirst=True)
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role")
    op.execute("ALTER TABLE users ADD CONSTRAINT ck_users_role CHECK (role in "
               "('translator','reviewer','project_manager','team_leader','tni_admin','technical_admin','auditor'))")
    op.execute("ALTER TABLE knowledge_documents DROP CONSTRAINT IF EXISTS ck_knowledge_category")
    op.execute("ALTER TABLE knowledge_documents ADD CONSTRAINT ck_knowledge_category CHECK (category in "
               "('institutional','guidelines','terminology','language_resources','platform','faq','doctrine'))")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS glossary_leads CASCADE")
    op.execute("DROP TABLE IF EXISTS glossary_entries CASCADE")
