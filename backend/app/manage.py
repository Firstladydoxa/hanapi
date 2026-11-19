"""Account management CLI (no default credentials; passwords are generated and shown once).

  python -m app.manage add-users --project "TNI Translator Pilot" --role translator a@x.org b@x.org
  python -m app.manage reset-password a@x.org

Share each generated password with its owner over a private channel; they can be reset at any time.
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from sqlalchemy import func, select

from .database import SessionLocal
from .models.db import Project, ProjectMember, User
from .security import auth as sec

SYSTEM_ROLE = {"translator": "translator", "reviewer": "reviewer", "project_manager": "project_manager"}


def _display_name(email: str) -> str:
    return email.split("@")[0].replace(".", " ").replace("_", " ").replace("-", " ").title()


def add_users(project_name: str, role: str, emails: List[str]) -> int:
    with SessionLocal() as db:
        project = db.execute(select(Project).where(Project.name == project_name)).scalar_one_or_none()
        if project is None:
            print(f"project not found: {project_name}", file=sys.stderr)
            return 2
        for raw in emails:
            email = raw.strip().lower()
            user = db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none()
            password = None
            if user is None:
                password = sec.generate_password()
                user = User(email=email, display_name=_display_name(email), role=SYSTEM_ROLE[role], password_hash=sec.hash_password(password))
                db.add(user)
                db.flush()
            if db.get(ProjectMember, (project.id, user.id)) is None:
                db.add(ProjectMember(project_id=project.id, user_id=user.id, role=role, can_approve=role != "project_manager"))
            db.commit()
            print(f"{email:<40} {password or '(existing account: password unchanged)'}")
    return 0


def create_user(email: str, name: str, role: str, password: str, project_name: Optional[str]) -> int:
    with SessionLocal() as db:
        email = email.strip().lower()
        if db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none():
            print("user already exists (use reset-password)", file=sys.stderr)
            return 2
        user = User(email=email, display_name=name, role=role, password_hash=sec.hash_password(password))
        db.add(user)
        db.flush()
        if project_name:
            project = db.execute(select(Project).where(Project.name == project_name)).scalar_one_or_none()
            if project is not None:
                db.add(ProjectMember(project_id=project.id, user_id=user.id, role="reviewer", can_approve=True))
        db.commit()
        print(f"created {email} as {role}")
    return 0


def reset_password(email: str) -> int:
    with SessionLocal() as db:
        user = db.execute(select(User).where(func.lower(User.email) == email.strip().lower())).scalar_one_or_none()
        if user is None:
            print("user not found", file=sys.stderr)
            return 2
        password = sec.generate_password()
        user.password_hash = sec.hash_password(password)
        db.commit()
        print(f"{user.email:<40} {password}")
    return 0


def maintenance(cmd: str) -> int:
    from . import knowledge, languages
    from .han import conversations

    with SessionLocal() as db:
        if cmd == "purge-conversations":
            print(f"purged {conversations.purge_deleted(db)} conversation(s)")
        elif cmd == "enable-all-languages":
            print(f"opened {languages.enable_all_directions(db)} direction(s) for controlled testing")
        elif cmd == "seed-knowledge":
            print(knowledge.seed_platform_guide(db))
        else:
            print(f"indexed {knowledge.reindex_missing_embeddings(db)} chunk(s)")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add-users")
    a.add_argument("--project", required=True)
    a.add_argument("--role", choices=sorted(SYSTEM_ROLE), default="translator")
    a.add_argument("emails", nargs="+")
    r = sub.add_parser("reset-password")
    r.add_argument("email")
    c = sub.add_parser("create-user", help="create an account with a chosen password")
    c.add_argument("email")
    c.add_argument("--name", required=True)
    c.add_argument("--role", choices=["translator", "reviewer", "project_manager", "tni_admin"], required=True)
    c.add_argument("--password", required=True)
    c.add_argument("--project")
    sub.add_parser("purge-conversations", help="permanently remove conversations deleted longer ago than the retention period")
    sub.add_parser("enable-all-languages", help="open every English<->X direction (not failed) for controlled testing")
    sub.add_parser("seed-knowledge", help="load and index the built-in HAN platform guide")
    sub.add_parser("reindex-knowledge", help="compute missing embeddings for approved knowledge")
    args = ap.parse_args(argv)
    if args.cmd in ("purge-conversations", "seed-knowledge", "reindex-knowledge", "enable-all-languages"):
        return maintenance(args.cmd)
    if args.cmd == "create-user":
        return create_user(args.email, args.name, args.role, args.password, args.project)
    return add_users(args.project, args.role, args.emails) if args.cmd == "add-users" else reset_password(args.email)


if __name__ == "__main__":
    sys.exit(main())
