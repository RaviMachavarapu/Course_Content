"""Student "Me" dashboards (spec.md §3.16): Progress, My Listening, Achievements.

Achievement set is a documented default pending O5 (owner sign-off) — course
complete / quiz score threshold / flashcard deck finished, matching the three
examples named in spec.md §3.16.
"""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel


class MyProgressCourse(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    percent_complete: int
    modules_started: int
    modules_total: int


class MyProgressResponse(BaseModel):
    courses: list[MyProgressCourse]


class ListeningRow(BaseModel):
    artifact_id: uuid.UUID
    course_slug: str
    course_title: str
    module_index: int
    module_title: str
    duration_seconds: int
    audio_position_seconds: int
    percent_listened: int
    completed: bool


class MyListeningResponse(BaseModel):
    rows: list[ListeningRow]


class Achievement(BaseModel):
    key: str
    label: str
    description: str
    icon: str
    earned: bool
    earned_at: dt.datetime | None = None


class AchievementsResponse(BaseModel):
    earned: list[Achievement]
    locked: list[Achievement]
