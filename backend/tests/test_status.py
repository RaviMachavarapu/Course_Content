"""T013 — derived module/course status transition table."""

from __future__ import annotations

import pytest

from app.models.enums import ArtifactStatus as A
from app.models.enums import CourseStatus as C
from app.models.enums import ModuleStatus as M
from app.models.status import derive_course_status, derive_module_status

R = (A.pending, A.processing, A.ready, A.error, A.published)


def s(*n: int) -> list[A]:
    """Build a 6-artifact status list: s(pending, processing, ready, error, published)."""
    out: list[A] = []
    for status, count in zip(R, n, strict=True):
        out.extend([status] * count)
    return out


@pytest.mark.parametrize(
    ("artifacts", "expected"),
    [
        ([], M.processing),
        (s(6, 0, 0, 0, 0), M.processing),  # all pending
        (s(3, 1, 2, 0, 0), M.processing),  # any processing wins
        (s(0, 1, 0, 0, 5), M.processing),  # processing beats published
        (s(0, 0, 0, 0, 6), M.published),  # all published
        (s(2, 0, 3, 0, 1), M.partially_published),  # some published
        (s(0, 0, 5, 1, 0), M.error),  # error beats pending_review
        (s(2, 0, 4, 0, 0), M.pending_review),  # ready, none published/error
        (s(5, 0, 1, 0, 0), M.pending_review),
    ],
)
def test_derive_module_status(artifacts: list[A], expected: M) -> None:
    assert derive_module_status(artifacts) is expected


@pytest.mark.parametrize(
    ("modules", "expected"),
    [
        ([], C.draft),
        ([M.processing, M.published], C.processing),
        ([M.published, M.published], C.published),
        ([M.published, M.pending_review], C.partially_published),
        ([M.partially_published], C.partially_published),
        ([M.error, M.pending_review], C.error),
        ([M.pending_review, M.pending_review], C.pending_review),
    ],
)
def test_derive_course_status(modules: list[M], expected: C) -> None:
    assert derive_course_status(modules) is expected
