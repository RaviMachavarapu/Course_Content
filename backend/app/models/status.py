"""Derived (cached) status for modules and courses.

`artifact.status` is authoritative and set by the pipeline. `module.status` and
`course.status` are *derived* from their children and recomputed on every
relevant change (BR3). The rules here are the single source of truth for that
derivation and are exercised by a transition-table unit test.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models.enums import ArtifactStatus, CourseStatus, ModuleStatus


def derive_module_status(artifact_statuses: Sequence[ArtifactStatus]) -> ModuleStatus:
    """Roll six artifact statuses up to one module status.

    Precedence:
      1. any artifact still processing (or the module has no artifacts yet) -> processing
      2. every artifact published                                          -> published
      3. some (1..n-1) artifacts published                                 -> partially_published
      4. any artifact in error                                             -> error
      5. any artifact ready                                                -> pending_review
      6. otherwise (all pending)                                           -> processing
    """
    statuses = list(artifact_statuses)
    if not statuses or any(s is ArtifactStatus.processing for s in statuses):
        return ModuleStatus.processing

    published = sum(1 for s in statuses if s is ArtifactStatus.published)
    if published == len(statuses):
        return ModuleStatus.published
    if published > 0:
        return ModuleStatus.partially_published
    if any(s is ArtifactStatus.error for s in statuses):
        return ModuleStatus.error
    if any(s is ArtifactStatus.ready for s in statuses):
        return ModuleStatus.pending_review
    return ModuleStatus.processing


def derive_course_status(module_statuses: Sequence[ModuleStatus]) -> CourseStatus:
    """Roll module statuses up to one course status.

    Precedence: processing > (all published) > any published-ish >
    error > pending_review > draft (also: a course with no modules is draft).
    """
    statuses = list(module_statuses)
    if not statuses:
        return CourseStatus.draft
    if any(s is ModuleStatus.processing for s in statuses):
        return CourseStatus.processing
    if all(s is ModuleStatus.published for s in statuses):
        return CourseStatus.published
    if any(s in (ModuleStatus.published, ModuleStatus.partially_published) for s in statuses):
        return CourseStatus.partially_published
    if any(s is ModuleStatus.error for s in statuses):
        return CourseStatus.error
    if any(s is ModuleStatus.pending_review for s in statuses):
        return CourseStatus.pending_review
    return CourseStatus.draft
