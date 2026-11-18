"""Engine / session management (synchronous SQLAlchemy 2.x, psycopg3)."""
from __future__ import annotations

from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Optional[Engine] = None
_factory: Optional[sessionmaker] = None


def normalise_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def get_engine() -> Engine:
    global _engine, _factory
    if _engine is None:
        _engine = create_engine(
            normalise_url(get_settings().database_url), pool_pre_ping=True, pool_size=10, max_overflow=10
        )
        _factory = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=True)
    return _engine


def reset_engine() -> None:
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _factory = None


def SessionLocal() -> Session:
    get_engine()
    assert _factory is not None
    return _factory()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
