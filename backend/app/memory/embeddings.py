"""OPTIONAL semantic Translation-Memory retrieval hook. OFF by default.

Nothing in HAN depends on this module: exact + fuzzy TM matching (translation_memory.py) works
on plain PostgreSQL. To enable semantic retrieval an operator must:

  1. run PostgreSQL with the pgvector extension (the Compose file uses `pgvector/pgvector:pg16`)
     and `CREATE EXTENSION vector;`,
  2. add an embeddings column/migration (e.g. `translation_memory.embedding vector(N)`),
  3. implement `EmbeddingProvider` below with a real, evaluated multilingual embedding model and
     register it with `set_embedding_provider(...)`,
  4. set HAN_SEMANTIC_TM=1.

No fake or hashed "embeddings" are provided on purpose: semantic matches must come from a real
model, and project + language filters must always be retained (see `semantic_search`).
"""
from __future__ import annotations

from typing import List, Optional, Protocol, Sequence

from ..config import get_settings


class SemanticRetrievalDisabled(RuntimeError):
    pass


class EmbeddingProvider(Protocol):
    dimensions: int

    def embed(self, texts: Sequence[str]) -> List[List[float]]: ...


_provider: Optional[EmbeddingProvider] = None


def set_embedding_provider(provider: Optional[EmbeddingProvider]) -> None:
    global _provider
    _provider = provider


def is_enabled() -> bool:
    return bool(get_settings().semantic_tm and _provider is not None)


def semantic_search(db, project_id, source_language: str, target_language: str, query: str, limit: int = 5):
    """Placeholder contract: returns nearest approved TM entries WITHIN the project and language pair.

    Raises SemanticRetrievalDisabled unless enabled; the vector query itself is intentionally
    left to the deployment that adds the pgvector column (step 2 above).
    """
    if not is_enabled():
        raise SemanticRetrievalDisabled("semantic TM retrieval is not enabled")
    raise NotImplementedError("add the pgvector column + query for your embedding model (see module docstring)")
