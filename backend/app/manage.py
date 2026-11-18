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


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add-users")
    a.add_argument("--project", required=True)
    a.add_argument("--role", choices=sorted(SYSTEM_ROLE), default="translator")
    a.add_argument("emails", nargs="+")
    r = sub.add_parser("reset-password")
    r.add_argument("email")
    args = ap.parse_args(argv)
    return add_users(args.project, args.role, args.emails) if args.cmd == "add-users" else reset_password(args.email)


if __name__ == "__main__":
    sys.exit(main())
