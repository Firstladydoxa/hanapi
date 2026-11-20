"""Test fixtures. Tests run against a REAL PostgreSQL 16 (embedded via `pgserver`), migrated with Alembic."""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

_PG_DIR = Path(os.environ.get("HAN_TEST_PG_ROOT", Path.home() / ".han-venvs")) / f"pgtest-{os.getpid()}"
_PG_DIR.mkdir(parents=True, exist_ok=True)

import pgserver  # noqa: E402

_server = pgserver.get_server(_PG_DIR, cleanup_mode="delete")
os.environ.update({
    "HAN_ENV": "test",
    "HAN_DATABASE_URL": _server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1),
    "HAN_SECRET_KEY": "test-secret-key-that-is-long-enough-0123456789",
    "HAN_ENABLE_MOCK_PROVIDER": "1",
    "HAN_JOBS_EAGER": "1",
    "HAN_RATE_LIMIT_AUTH_PER_MIN": "1000",
    "HAN_RATE_LIMIT_TRANSLATE_PER_MIN": "1000",
    "HAN_LOG_LEVEL": "WARNING",
    "HAN_PROVIDER_RETRY_BACKOFF_S": "0",
})

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import ratelimit  # noqa: E402
from app.database import SessionLocal, get_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.db import (  # noqa: E402
    Language, LanguageDirection, ModelRegistry, Project, ProjectMember, User,
)
from app.models import registry as registry_mod  # noqa: E402
from app.providers import clear_adapter_cache  # noqa: E402
from app.security import auth as sec  # noqa: E402
from app.seed import LANGUAGES, seed_languages  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
PASSWORD = "correct-horse-battery-staple"


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _migrated():
    command.upgrade(alembic_config(), "head")
    yield
    get_engine().dispose()
    _server.cleanup()
    shutil.rmtree(_PG_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def _clean_db(_migrated):
    with get_engine().begin() as conn:
        tables = [r[0] for r in conn.execute(text("select tablename from pg_tables where schemaname='public' and tablename <> 'alembic_version'"))]
        conn.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"))
    ratelimit.reset()
    registry_mod.ADAPTER_OVERRIDES.clear()
    registry_mod.invalidate_identifier_cache()
    clear_adapter_cache()
    with SessionLocal() as db:
        seed_languages(db)
        registry_mod.seed_registry(db)
        registry_mod.ensure_mock_model(db)
    yield
    registry_mod.ADAPTER_OVERRIDES.clear()
    clear_adapter_cache()


class World:
    """Users, projects and directions used by most tests."""

    def __init__(self):
        self.users = {}
        self.projects = {}


def _make_user(db, email, role, *, grant=False, status="active"):
    u = User(email=email, display_name=email.split("@")[0].title(), role=role, password_hash=sec.hash_password(PASSWORD),
             engine_details_granted=grant, status=status)
    db.add(u)
    db.flush()
    return u


@pytest.fixture
def world() -> World:
    w = World()
    with SessionLocal() as db:
        for name, role, grant in (("alice", "translator", False), ("bob", "translator", False), ("rita", "reviewer", False),
                                   ("pam", "project_manager", False), ("tina", "tni_admin", False), ("tim", "technical_admin", False),
                                   ("gina", "tni_admin", True), ("audrey", "auditor", False)):
            w.users[name] = _make_user(db, f"{name}@example.test", role, grant=grant)
        w.users["alice"].expertise_language = "fr"
        p1 = Project(name="Project One", domain="legal", style="formal", instructions="Use formal register.")
        p2 = Project(name="Project Two", domain="medical")
        db.add_all([p1, p2])
        db.flush()
        w.projects["p1"], w.projects["p2"] = p1, p2
        for user, member_role, can in (("alice", "translator", True), ("rita", "reviewer", True), ("pam", "project_manager", False)):
            db.add(ProjectMember(project_id=p1.id, user_id=w.users[user].id, role=member_role, can_approve=can))
        db.add(ProjectMember(project_id=p2.id, user_id=w.users["bob"].id, role="translator", can_approve=True))
        for src, tgt, tier in (("en", "de", "assisted"), ("de", "en", "production"), ("en", "fr", "experimental"), ("en", "sw", "unsupported")):
            db.add(LanguageDirection(source_code=src, target_code=tgt, readiness_tier=tier))
        db.commit()
        for u in w.users.values():
            db.refresh(u)
        db.refresh(p1)
        db.refresh(p2)
    return w


class Session:
    """A signed-in API client (own cookie jar + CSRF header)."""

    def __init__(self):
        self.client = TestClient(app)
        self.csrf = ""

    def login(self, email: str, password: str = PASSWORD):
        r = self.client.post("/v1/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf_token"]
        return self

    def _h(self, csrf=True):
        return {"X-CSRF-Token": self.csrf} if csrf else {}

    def get(self, url, **kw):
        return self.client.get(url, **kw)

    def post(self, url, json=None, csrf=True, **kw):
        return self.client.post(url, json=json, headers=self._h(csrf), **kw)

    def put(self, url, json=None, csrf=True, **kw):
        return self.client.put(url, json=json, headers=self._h(csrf), **kw)

    def delete(self, url, csrf=True, **kw):
        return self.client.delete(url, headers=self._h(csrf), **kw)

    def patch(self, url, json=None, csrf=True, **kw):
        return self.client.patch(url, json=json, headers=self._h(csrf), **kw)


@pytest.fixture
def login():
    def _login(name_or_email: str) -> Session:
        email = name_or_email if "@" in name_or_email else f"{name_or_email}@example.test"
        return Session().login(email)

    return _login


@pytest.fixture
def anon() -> Session:
    return Session()


def translate(sess: Session, project, text="Hello world", source="en", target="de", **kw):
    return sess.post("/v1/translate", {"project_id": str(project.id), "source_language": source, "target_language": target, "text": text, **kw})
