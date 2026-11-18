"""Seed / bootstrap CLI:  python -m app.seed [--demo]

* Always: languages, model registry defaults (DISABLED, licence not cleared), dev mock model when permitted.
* Bootstrap admins: HAN_BOOTSTRAP_TNI_ADMIN_EMAIL / HAN_BOOTSTRAP_TECH_ADMIN_EMAIL with optional *_PASSWORD env vars.
  A missing password is generated and printed ONCE. There are no default credentials.
* --demo (refused in production): `experimental` directions for a few pairs, a demo project and demo users.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import SessionLocal
from .models.db import Language, LanguageDirection, Project, ProjectMember, User
from .models.registry import ensure_mock_model, seed_registry
from .security import auth as sec

LANGUAGES: List[Tuple[str, str, str, str]] = [
    ("en", "English", "Latin", "Global"), ("de", "German", "Latin", "Europe"), ("fr", "French", "Latin", "Europe"),
    ("es", "Spanish", "Latin", "Europe/Americas"), ("pt", "Portuguese", "Latin", "Europe/Americas"),
    ("sw", "Swahili", "Latin", "Africa"), ("yo", "Yoruba", "Latin", "Africa"), ("ig", "Igbo", "Latin", "Africa"),
    ("ha", "Hausa", "Latin", "Africa"), ("am", "Amharic", "Ethiopic", "Africa"), ("zu", "Zulu", "Latin", "Africa"),
    ("ar", "Arabic", "Arabic", "Middle East/Africa"), ("hi", "Hindi", "Devanagari", "Asia"), ("bn", "Bengali", "Bengali", "Asia"),
    ("zh", "Chinese", "Han (Simplified)", "Asia"), ("ja", "Japanese", "Japanese", "Asia"), ("ko", "Korean", "Hangul", "Asia"),
    ("id", "Indonesian", "Latin", "Asia"), ("th", "Thai", "Thai", "Asia"), ("ru", "Russian", "Cyrillic", "Europe/Asia"),
    ("qu", "Quechua", "Latin", "South America"), ("gn", "Guarani", "Latin", "South America"), ("ay", "Aymara", "Latin", "South America"),
]
DEMO_PAIRS = [("en", "de"), ("de", "en"), ("en", "fr"), ("fr", "en"), ("en", "es"), ("es", "en"), ("en", "sw"), ("sw", "en")]


def seed_languages(db: Session) -> int:
    added = 0
    for code, name, script, region in LANGUAGES:
        if db.get(Language, code) is None:
            db.add(Language(code=code, display_name=name, script=script, region=region))
            added += 1
    db.commit()
    return added


def ensure_user(db: Session, email: str, name: str, role: str, password: Optional[str], grant_engine: bool = False) -> Optional[str]:
    """Create the user if missing. Returns a generated password (shown once) or None."""
    if db.execute(select(User).where(User.email == email.lower())).scalar_one_or_none() is not None:
        return None
    generated = None if password else sec.generate_password()
    db.add(User(email=email.lower(), display_name=name, role=role, password_hash=sec.hash_password(password or generated),
                engine_details_granted=grant_engine))
    db.commit()
    return generated


def bootstrap_admins(db: Session) -> List[str]:
    notes: List[str] = []
    for env_key, name, role in (("TNI_ADMIN", "TNI Administrator", "tni_admin"), ("TECH_ADMIN", "Technical Administrator", "technical_admin")):
        email = os.environ.get(f"HAN_BOOTSTRAP_{env_key}_EMAIL")
        if not email:
            continue
        generated = ensure_user(db, email, name, role, os.environ.get(f"HAN_BOOTSTRAP_{env_key}_PASSWORD"))
        notes.append(f"{role}: {email}" + (f"  generated password (shown once): {generated}" if generated else "  (already existed or password from env)"))
    return notes


def seed_demo(db: Session) -> List[str]:
    if get_settings().is_production:
        raise SystemExit("Refusing to create demo data in production.")
    notes: List[str] = []
    for src, tgt in DEMO_PAIRS:
        if db.get(LanguageDirection, (src, tgt)) is None:
            db.add(LanguageDirection(source_code=src, target_code=tgt, readiness_tier="experimental",
                                     review_note="Demo pair: not evaluated by TNI reviewers."))
    db.commit()
    project = db.execute(select(Project).where(Project.name == "Demo project")).scalar_one_or_none()
    if project is None:
        project = Project(name="Demo project", domain="general", style="neutral", pilot_opt_in=True,
                          instructions="Demo project for evaluating the HAN workflow. Not for client content.")
        db.add(project)
        db.commit()
    for email, name, role, member_role in (("translator@example.test", "Demo Translator", "translator", "translator"),
                                           ("reviewer@example.test", "Demo Reviewer", "reviewer", "reviewer")):
        generated = ensure_user(db, email, name, role, None)
        user = db.execute(select(User).where(User.email == email)).scalar_one()
        if db.get(ProjectMember, (project.id, user.id)) is None:
            db.add(ProjectMember(project_id=project.id, user_id=user.id, role=member_role, can_approve=True))
            db.commit()
        notes.append(f"{role}: {email}" + (f"  generated password (shown once): {generated}" if generated else "  (already existed)"))
    return notes


PILOT_PROJECT = "TNI Translator Pilot"
PILOT_LANGS = ("de", "fr", "es", "sw")


def seed_pilot(db: Session) -> List[str]:
    """Controlled pilot setup (allowed in production): one project that opts in to `experimental` pairs.

    The pairs are marked EXPERIMENTAL on purpose: no TNI translator has evaluated them yet, so HAN labels every draft
    accordingly. An administrator promotes a direction (Administration -> Language readiness) only after evaluation.
    """
    for other in PILOT_LANGS:
        for src, tgt in (("en", other), (other, "en")):
            if db.get(LanguageDirection, (src, tgt)) is None:
                db.add(LanguageDirection(source_code=src, target_code=tgt, readiness_tier="experimental",
                                         review_note="Pilot pair: not yet evaluated by TNI reviewers. Please review carefully."))
    db.commit()
    project = db.execute(select(Project).where(Project.name == PILOT_PROJECT)).scalar_one_or_none()
    if project is None:
        db.add(Project(name=PILOT_PROJECT, domain="general", style="neutral", pilot_opt_in=True,
                       instructions="Pilot project for evaluating HAN. Translate naturally and keep numbers, names and formatting. "
                                    "HAN drafts are suggestions: review and edit every draft, and approve only what you are satisfied with."))
        db.commit()
        return [f"project created: {PILOT_PROJECT}"]
    return [f"project exists: {PILOT_PROJECT}"]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Seed HAN reference data")
    parser.add_argument("--demo", action="store_true", help="create demo project/users/directions (non-production only)")
    parser.add_argument("--pilot", action="store_true", help="create the pilot project and experimental language pairs (allowed in production)")
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        print(f"languages added: {seed_languages(db)}")
        print(f"registry rows added: {seed_registry(db)} (all disabled until an administrator enables and licence-clears them)")
        if ensure_mock_model(db):
            print("development mock model registered (non-production only; output is labelled [MOCK DRAFT])")
        for line in bootstrap_admins(db):
            print(line)
        if args.demo:
            for line in seed_demo(db):
                print(line)
        if args.pilot:
            for line in seed_pilot(db):
                print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
