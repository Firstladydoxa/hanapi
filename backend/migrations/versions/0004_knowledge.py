"""TNI knowledge base: governed documents, immutable versions and searchable chunks (pgvector + full-text). Idempotent (see 0001)."""
from alembic import op

from app.models.db import KnowledgeChunk, KnowledgeDocument, KnowledgeVersion

revision = "0004_knowledge"
down_revision = "0003_languages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for table in (KnowledgeDocument.__table__, KnowledgeVersion.__table__, KnowledgeChunk.__table__):
        table.create(bind, checkfirst=True)
    op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_tsv ON knowledge_chunks USING gin (tsv)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_embedding ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    for name in ("knowledge_chunks", "knowledge_versions", "knowledge_documents"):
        op.execute(f"DROP TABLE IF EXISTS {name} CASCADE")
