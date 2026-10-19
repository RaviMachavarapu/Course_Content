from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.course import Course

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.strip().lower()).strip("-") or "course"


def unique_course_slug(session: Session, title: str) -> str:
    base = slugify(title)[:280]
    slug = base
    n = 2
    while session.scalar(select(Course.id).where(Course.slug == slug)) is not None:
        slug = f"{base}-{n}"
        n += 1
    return slug
