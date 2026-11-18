"""Persistent conversations: titles, status, ordering, metadata, rolling summary.

Extends the existing chat_conversations / chat_messages tables (no duplicate tables). Idempotent (see 0001).
"""
from alembic import op

revision = "0002_conversations"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chat_conversations ALTER COLUMN project_id DROP NOT NULL")
    for ddl in (
        "title varchar(200)",
        "status varchar(16) NOT NULL DEFAULT 'active'",
        "summary text",
        "summary_upto integer NOT NULL DEFAULT 0",
        "last_message_at timestamptz",
        "deleted_at timestamptz",
    ):
        op.execute(f"ALTER TABLE chat_conversations ADD COLUMN IF NOT EXISTS {ddl}")
    op.execute("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS seq integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS metadata jsonb")
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_conversation_status') THEN
            ALTER TABLE chat_conversations ADD CONSTRAINT ck_conversation_status CHECK (status in ('active','archived','deleted'));
          END IF;
        END $$;
        """
    )
    # backfill for rows created before this revision: strict order, public role name, last activity, a readable title
    op.execute(
        """
        UPDATE chat_messages m SET seq = r.rn
        FROM (SELECT id, row_number() OVER (PARTITION BY conversation_id ORDER BY created_at, id) AS rn FROM chat_messages) r
        WHERE m.id = r.id AND m.seq = 0
        """
    )
    op.execute("UPDATE chat_messages SET role = 'assistant' WHERE role = 'han'")
    op.execute(
        "UPDATE chat_conversations c SET last_message_at = (SELECT max(created_at) FROM chat_messages WHERE conversation_id = c.id) "
        "WHERE last_message_at IS NULL"
    )
    op.execute(
        "UPDATE chat_conversations c SET title = left((SELECT content FROM chat_messages WHERE conversation_id = c.id AND role = 'user' "
        "ORDER BY seq LIMIT 1), 60) WHERE title IS NULL"
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_message_seq ON chat_messages (conversation_id, seq)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_conversations_project_id ON chat_conversations (project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_conversations_user_id ON chat_conversations (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_conversations_last_message_at ON chat_conversations (last_message_at)")


def downgrade() -> None:
    op.execute("ALTER TABLE chat_messages DROP CONSTRAINT IF EXISTS uq_message_seq")  # fresh installs have it as a constraint
    op.execute("DROP INDEX IF EXISTS uq_message_seq")  # upgraded databases have it as a plain unique index
    op.execute("ALTER TABLE chat_conversations DROP CONSTRAINT IF EXISTS ck_conversation_status")
    for col in ("title", "status", "summary", "summary_upto", "last_message_at", "deleted_at"):
        op.execute(f"ALTER TABLE chat_conversations DROP COLUMN IF EXISTS {col}")
    op.execute("ALTER TABLE chat_messages DROP COLUMN IF EXISTS seq")
    op.execute("ALTER TABLE chat_messages DROP COLUMN IF EXISTS metadata")
