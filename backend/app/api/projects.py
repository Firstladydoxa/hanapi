from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import schemas as S
from ..models.db import Language, LanguageDirection, Project, ProjectDirection, ProjectMember, User
from ..security import serializers as ser
from ..security.permissions import effective_can_approve, get_membership

router = APIRouter(prefix="/v1", tags=["projects"])


def _directions(db: Session, project: Project | None = None) -> List[S.DirectionOut]:
    rows = list(db.execute(select(LanguageDirection).order_by(LanguageDirection.source_code, LanguageDirection.target_code)).scalars())
    if project is not None:
        allowed = {(d.source_code, d.target_code) for d in db.execute(select(ProjectDirection).where(ProjectDirection.project_id == project.id)).scalars()}
        rows = [d for d in rows if (not allowed or (d.source_code, d.target_code) in allowed)
                and (d.readiness_tier != "experimental" or project.pilot_opt_in)]
    return [ser.direction_out(d) for d in rows]


@router.get("/projects", response_model=List[S.ProjectListItem])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Project, ProjectMember).join(ProjectMember, ProjectMember.project_id == Project.id)
                      .where(ProjectMember.user_id == user.id, Project.status == "active").order_by(Project.name)).all()
    return [ser.project_list_item(p, m) for p, m in rows]


@router.get("/projects/{project_id}", response_model=S.ProjectDetail)
def get_project(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    p, m = get_membership(db, user, project_id)
    base = ser.project_list_item(p, m)
    return S.ProjectDetail(**base.model_dump(), instructions=p.instructions, can_approve=effective_can_approve(m),
                           language_directions=_directions(db, p))


@router.get("/languages", response_model=List[S.LanguageOut])
def languages(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Language).where(Language.active.is_(True)).order_by(Language.display_name)).scalars()
    return [S.LanguageOut(code=l.code, display_name=l.display_name, script=l.script) for l in rows]


@router.get("/language-directions", response_model=List[S.DirectionOut])
def language_directions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _directions(db)
