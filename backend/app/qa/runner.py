"""QA runner: builds the context (project-scoped terminology / prior approvals) and runs every rule."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..memory import translation_memory as tm
from ..models.db import Language
from ..terminology import terminology as term_service
from . import QAContext, consistency, formatting, names, numbers
from . import terminology as terminology_rule

RULES = (numbers.check, terminology_rule.check, names.check, consistency.check, formatting.check)


def run_rules(ctx: QAContext) -> List[Dict[str, Any]]:
    """DB-free rule execution (unit-testable)."""
    warnings: List[Dict[str, Any]] = []
    for rule in RULES:
        warnings.extend(rule(ctx))
    return warnings


def run_all(
    db: Session,
    project_id: uuid.UUID,
    source_text: str,
    target_text: str,
    source_language: str,
    target_language: str,
    terms: Optional[list] = None,
) -> List[Dict[str, Any]]:
    lang = db.get(Language, target_language)
    if terms is None:
        terms = term_service.find_in_text(db, project_id, source_language, target_language, source_text)
    prior = tm.search(db, project_id, source_language, target_language, source_text, min_match=100, limit=3)
    ctx = QAContext(
        source_text=source_text,
        target_text=target_text,
        source_language=source_language,
        target_language=target_language,
        target_script=lang.script if lang else None,
        terms=terms,
        prior_translations=prior,
    )
    return run_rules(ctx)
