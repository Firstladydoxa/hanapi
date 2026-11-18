"""Audit trail. Written in an independent transaction so denials/failures are still recorded."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from .database import SessionLocal
from .logging_config import request_id_var
from .models.db import AuditEvent

log = logging.getLogger("han.audit")


def _uuid(v: Any) -> Optional[uuid.UUID]:
    if v is None:
        return None
    if isinstance(v, uuid.UUID):
        return v
    try:
        return uuid.UUID(str(v))
    except ValueError:
        return None


def record(
    action: str,
    *,
    actor: Any = None,
    outcome: str = "success",
    object_type: Optional[str] = None,
    object_id: Any = None,
    project_id: Any = None,
    details: Optional[Dict[str, Any]] = None,
    ip: Optional[str] = None,
) -> None:
    """Never include translation text or engine/provider identity in `details`."""
    try:
        with SessionLocal() as s:
            s.add(
                AuditEvent(
                    actor_id=_uuid(getattr(actor, "id", actor)),
                    actor_role=getattr(actor, "role", None),
                    project_id=_uuid(project_id),
                    action=action,
                    object_type=object_type,
                    object_id=str(object_id) if object_id is not None else None,
                    outcome=outcome,
                    request_id=request_id_var.get(),
                    ip=ip,
                    details=details or None,
                )
            )
            s.commit()
    except Exception:  # audit failure must not mask the primary operation, but is loud
        log.exception("audit_write_failed", extra={"action": action})
