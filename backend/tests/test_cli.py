"""T007 — `seed-admin` behaviour. T044 — `seed-demo` behaviour."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.auth.hashing import verify_password
from app.cli import build_parser, refresh_report_math, seed_admin, seed_demo
from app.models.artifact_version import ArtifactVersion
from app.models.course import Course
from app.models.enums import ArtifactType, CourseStatus, ModuleStatus
from app.models.progress import ArtifactProgress
from app.models.user import User, UserRole
from app.pipeline import orchestrator
from app.pipeline.provider import ProviderError, RawArtifact, StudioJobRef
from tests.integration.test_notebooklm_pipeline import FakeNotebookLm, _artifact, _row


def _count_users(session: Session) -> int:
    return session.scalar(sa.select(sa.func.count()).select_from(User)) or 0


def test_seed_admin_creates_an_active_admin_with_hashed_password(db_session: Session) -> None:
    user, created = seed_admin(
        db_session,
        email="Owner@Example.com",
        display_name="Owner",
        password="a-long-passphrase-123",
    )
    assert created is True
    assert user.role is UserRole.admin
    assert user.is_active is True
    assert user.email == "owner@example.com"  # normalised
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password(user.password_hash, "a-long-passphrase-123")


def test_seed_admin_is_idempotent_on_email(db_session: Session) -> None:
    seed_admin(
        db_session, email="owner@example.com", display_name="Owner", password="pw-one-1234567"
    )
    user, created = seed_admin(
        db_session,
        email="owner@example.com",
        display_name="Owner Renamed",
        password="pw-two-1234567",
    )
    assert created is False
    assert _count_users(db_session) == 1
    assert user.display_name == "Owner Renamed"
    assert verify_password(user.password_hash, "pw-two-1234567")
    assert not verify_password(user.password_hash, "pw-one-1234567")


def test_seed_admin_allows_multiple_distinct_admins(db_session: Session) -> None:
    seed_admin(db_session, email="a@example.com", display_name="A", password="passphrase-aaaa-1")
    seed_admin(db_session, email="b@example.com", display_name="B", password="passphrase-bbbb-2")
    assert _count_users(db_session) == 2


def test_cli_parser_requires_email_and_name() -> None:
    parser = build_parser()
    ns = parser.parse_args(["seed-admin", "--email", "x@example.com", "--name", "X"])
    assert ns.command == "seed-admin"
    assert ns.password is None


def test_seed_demo_builds_a_reviewable_demo(db_session: Session) -> None:
    result = seed_demo(db_session)

    assert result.admin_created is True
    assert result.admin.role is UserRole.admin
    assert result.student_created is True
    assert result.student.role is UserRole.student

    # one fully published course, all six artifacts each
    assert result.published_course.status is CourseStatus.published
    module = result.published_course.modules[0]
    assert module.status is ModuleStatus.published
    assert {a.type for a in module.artifacts} == set(ArtifactType)
    assert all(a.published_version_id is not None for a in module.artifacts)

    # the other course is left for the admin review flow, not published
    assert result.review_course.status is not CourseStatus.published
    review_module = result.review_course.modules[0]
    assert {a.type for a in review_module.artifacts} == set(ArtifactType)
    assert all(a.published_version_id is None for a in review_module.artifacts)

    # demo student has real, partial (not 0%, not 100%) progress
    report = next(a for a in module.artifacts if a.type is ArtifactType.report)
    audio = next(a for a in module.artifacts if a.type is ArtifactType.audio_overview)
    quiz = next(a for a in module.artifacts if a.type is ArtifactType.quiz)
    progress_rows = db_session.scalars(
        sa.select(ArtifactProgress).where(ArtifactProgress.user_id == result.student.id)
    )
    progress_by_artifact = {p.artifact_id: p for p in progress_rows}
    assert progress_by_artifact[report.id].completed_at is not None
    assert progress_by_artifact[audio.id].viewed_at is not None
    assert progress_by_artifact[audio.id].completed_at is None
    assert quiz.id not in progress_by_artifact  # untouched — genuinely partial


def test_seed_demo_is_idempotent_for_courses(db_session: Session) -> None:
    seed_demo(db_session)
    second = seed_demo(db_session)
    assert second.admin_created is False
    assert second.student_created is False

    count = db_session.scalar(
        sa.select(sa.func.count())
        .select_from(Course)
        .where(Course.title == "Neural Networks Crash Course")
    )
    assert count == 1


STALE_HTML = "<p>old <code>E = mc^2</code></p>"


def _stored_report(db: Session, provider: FakeNotebookLm) -> ArtifactVersion:
    artifact = _artifact(db, ArtifactType.report)
    version = orchestrator.run_artifact_generation(db, provider, artifact.id)
    assert version is not None
    return version


def _make_stale(version: ArtifactVersion) -> dict[str, object]:
    fresh = dict(version.content_json or {})
    version.content_json = {**fresh, "title": "stale title"}
    version.content_html = STALE_HTML
    return fresh


def test_refresh_updates_report_html_in_place(db_session: Session) -> None:
    provider = FakeNotebookLm(_row("report_interactive.json"))
    version = _stored_report(db_session, provider)
    version_id, revision = version.id, version.revision
    fresh = _make_stale(version)
    db_session.flush()

    results = refresh_report_math(db_session, provider)

    assert [outcome for _, outcome in results] == ["updated"]
    db_session.refresh(version)
    assert version.id == version_id and version.revision == revision
    assert version.content_json == fresh
    assert version.content_html != STALE_HTML and "<h2" in (version.content_html or "")
    assert db_session.scalar(sa.select(sa.func.count()).select_from(ArtifactVersion)) == 1

    assert [o for _, o in refresh_report_math(db_session, provider)] == ["unchanged"]


class _MissingArtifact(FakeNotebookLm):
    def fetch_content(self, job: StudioJobRef) -> RawArtifact:
        raise ProviderError("MCP shim error 404: artifact not found")


def test_missing_artifact_is_skipped_and_listed(db_session: Session) -> None:
    version = _stored_report(db_session, FakeNotebookLm(_row("report_interactive.json")))
    _make_stale(version)
    db_session.flush()

    results = refresh_report_math(db_session, _MissingArtifact(None))

    assert len(results) == 1
    label, outcome = results[0]
    assert version.notebooklm_artifact_id in label
    assert outcome == "skipped (not found in the module's notebook)"
    db_session.refresh(version)
    assert version.content_html == STALE_HTML  # untouched
    assert version.content_json is not None and version.content_json["title"] == "stale title"


def test_unparseable_row_is_skipped_not_blanked(db_session: Session) -> None:
    version = _stored_report(db_session, FakeNotebookLm(_row("report_interactive.json")))
    _make_stale(version)
    db_session.flush()

    results = refresh_report_math(db_session, FakeNotebookLm([None]))

    assert results[0][1].startswith("skipped (")
    db_session.refresh(version)
    assert version.content_html == STALE_HTML


def test_dry_run_changes_nothing(db_session: Session) -> None:
    provider = FakeNotebookLm(_row("report_interactive.json"))
    version = _stored_report(db_session, provider)
    _make_stale(version)
    db_session.flush()

    results = refresh_report_math(db_session, provider, dry_run=True)

    assert [outcome for _, outcome in results] == ["updated"]
    db_session.refresh(version)
    assert version.content_html == STALE_HTML
    assert version.content_json is not None and version.content_json["title"] == "stale title"


def test_refresh_command_is_registered() -> None:
    ns = build_parser().parse_args(["refresh-report-math", "--dry-run"])
    assert ns.dry_run is True
