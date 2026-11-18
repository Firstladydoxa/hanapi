"""Celery application. Set HAN_JOBS_EAGER=1 to run jobs inline (tests / development without Redis)."""
from __future__ import annotations

from celery import Celery

from ..config import get_settings

_s = get_settings()
celery_app = Celery("han", broker=_s.redis_url, backend=None, include=["app.jobs.tasks"])
celery_app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_time_limit=3600, broker_connection_retry_on_startup=True)
