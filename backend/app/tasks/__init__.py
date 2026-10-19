"""Celery application and task modules.

Importing this package registers every task with `celery_app` (worker/beat run
`celery -A app.tasks.celery_app`).
"""

from app.tasks import (
    generation,  # noqa: F401  (registers generate_module / generate_artifact)
    maintenance,  # noqa: F401  (registers app.tasks.media_gc)
)
from app.tasks.celery_app import celery_app

__all__ = ["celery_app"]
