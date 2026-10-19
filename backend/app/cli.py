"""Administrative CLI: ``python -m app.cli <command>``.

- ``seed-admin`` — create or update the platform admin account. There is no
  self-service admin signup; this command (or admin-only user management) is
  the only way an admin is created.
- ``seed-prompts`` — insert the default prompt template for any artifact type
  missing one.
- ``seed-demo`` (T044) — build a reviewable demo: an admin, a student with
  partial progress, and two courses generated via `FixtureProvider` (no
  Google/MCP session needed), one fully published and one left in review so
  both the ingest→review→publish and the student-facing flows are visible
  immediately.
"""

from __future__ import annotations

import argparse
import getpass
import sys
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.hashing import hash_password
from app.db.session import session_scope
from app.models.course import Course
from app.models.enums import ArtifactType
from app.models.module import Module
from app.models.user import User, UserRole, normalize_email
from app.pipeline import orchestrator
from app.pipeline.fixture import FixtureProvider
from app.services.ingestion import detect_source_type
from app.services.progress import record_artifact_progress
from app.services.prompts import seed_prompt_templates
from app.services.publish import publish_course, publish_module
from app.services.slugs import unique_course_slug

MIN_ADMIN_PASSWORD_LEN = 12

DEMO_ADMIN_EMAIL = "admin@example.com"
DEMO_ADMIN_PASSWORD = "dev-admin-password-123"
DEMO_STUDENT_EMAIL = "student@example.com"
DEMO_STUDENT_PASSWORD = "dev-student-pw-1234"


def seed_admin(
    session: Session, *, email: str, display_name: str, password: str
) -> tuple[User, bool]:
    """Idempotent upsert of an admin, keyed on the unique email.

    Returns ``(user, created)``. An existing account with this email is updated
    in place (password, name, role→admin, reactivated) — never duplicated.
    """
    normalized = normalize_email(email)
    user = session.scalar(select(User).where(User.email == normalized))
    created = user is None

    if user is None:
        user = User(
            email=normalized,
            role=UserRole.admin,
            display_name=display_name,
            password_hash="",
        )
        session.add(user)

    user.display_name = display_name
    user.role = UserRole.admin
    user.is_active = True
    user.password_hash = hash_password(password)
    session.flush()
    return user, created


def seed_student(
    session: Session, *, email: str, display_name: str, password: str
) -> tuple[User, bool]:
    """Idempotent upsert of a student, keyed on the unique email — the
    ``seed_admin`` pattern, for T044's demo student."""
    normalized = normalize_email(email)
    user = session.scalar(select(User).where(User.email == normalized))
    created = user is None

    if user is None:
        user = User(
            email=normalized,
            role=UserRole.student,
            display_name=display_name,
            password_hash="",
        )
        session.add(user)

    user.display_name = display_name
    user.role = UserRole.student
    user.is_active = True
    user.password_hash = hash_password(password)
    session.flush()
    return user, created


def _seed_module(
    session: Session,
    provider: FixtureProvider,
    *,
    course_id: uuid.UUID,
    order_index: int,
    title: str,
    source_url: str,
    requested_by: uuid.UUID,
) -> Module:
    """Create a module and generate all six artifacts for it synchronously,
    via `FixtureProvider` — no Celery, no Google/MCP session needed."""
    source_type = detect_source_type(source_url)
    assert source_type is not None, f"bad demo source url: {source_url}"
    module = Module(
        course_id=course_id,
        order_index=order_index,
        title=title,
        source_url=source_url,
        source_type=source_type,
    )
    session.add(module)
    session.flush()

    jobs = orchestrator.start_module_generation(
        session, provider, module.id, list(ArtifactType), requested_by=requested_by
    )
    session.flush()
    for job in jobs:
        orchestrator.run_artifact_generation(
            session, provider, job.artifact_id, job_id=job.job_id, requested_by=requested_by
        )
    session.refresh(module)
    return module


def _get_or_seed_course(
    session: Session,
    provider: FixtureProvider,
    *,
    title: str,
    description: str,
    category: str,
    created_by: uuid.UUID,
    module_title: str,
    source_url: str,
) -> tuple[Course, Module, bool]:
    """Idempotent like `seed_admin`/`seed_student`: re-running `seed-demo`
    finds the course by title and leaves it alone rather than piling up
    duplicates. Returns `(course, first_module, created)`."""
    course = session.scalar(select(Course).where(Course.title == title))
    if course is not None:
        return course, course.modules[0], False

    course = Course(
        title=title,
        slug=unique_course_slug(session, title),
        description=description,
        category=category,
        created_by=created_by,
    )
    session.add(course)
    session.flush()
    module = _seed_module(
        session,
        provider,
        course_id=course.id,
        order_index=0,
        title=module_title,
        source_url=source_url,
        requested_by=created_by,
    )
    return course, module, True


@dataclass(frozen=True)
class DemoResult:
    admin: User
    admin_created: bool
    student: User
    student_created: bool
    published_course: Course
    review_course: Course


def seed_demo(session: Session, provider: FixtureProvider | None = None) -> DemoResult:
    """The `seed-demo` logic (T044), session-scoped like `seed_admin` so it's
    directly testable (and re-runnable in one transaction) without going
    through `session_scope()`'s own connection."""
    provider = provider or FixtureProvider()

    admin, admin_created = seed_admin(
        session, email=DEMO_ADMIN_EMAIL, display_name="Demo Admin", password=DEMO_ADMIN_PASSWORD
    )
    student, student_created = seed_student(
        session,
        email=DEMO_STUDENT_EMAIL,
        display_name="Demo Student",
        password=DEMO_STUDENT_PASSWORD,
    )
    seed_prompt_templates(session)

    # Course 1 — fully published: the student-facing flow is immediately
    # explorable (catalog, workspace, all six artifact viewers).
    course1, module1, course1_created = _get_or_seed_course(
        session,
        provider,
        title="Neural Networks Crash Course",
        description="An intuition-first tour of how neural networks learn.",
        category="AI & Machine Learning",
        created_by=admin.id,
        module_title="How Neural Networks Learn",
        source_url="https://www.youtube.com/watch?v=demo-nn-1",
    )
    if course1_created:
        publish_module(session, module1)
        publish_course(session, course1)

    # Course 2 — left in review: demonstrates the admin ingest/staging flow
    # (six generated cards, redo, publish) without spoiling course 1.
    course2, _module2, _course2_created = _get_or_seed_course(
        session,
        provider,
        title="Effective Study Techniques",
        description="Evidence-based methods for learning anything faster.",
        category="Study Skills",
        created_by=admin.id,
        module_title="Spaced Repetition and Active Recall",
        source_url="https://www.youtube.com/watch?v=demo-study-1",
    )

    # Demo student: partial progress on course 1 (viewed some artifacts,
    # completed the report) — the progress dashboard shows a real,
    # in-between percentage rather than 0% or 100%.
    session.refresh(module1)
    report = next(a for a in module1.artifacts if a.type is ArtifactType.report)
    audio = next(a for a in module1.artifacts if a.type is ArtifactType.audio_overview)
    record_artifact_progress(session, user_id=student.id, artifact=audio)
    record_artifact_progress(session, user_id=student.id, artifact=report, completed=True)

    return DemoResult(
        admin=admin,
        admin_created=admin_created,
        student=student,
        student_created=student_created,
        published_course=course1,
        review_course=course2,
    )


def _cmd_seed_demo(_: argparse.Namespace) -> int:
    with session_scope() as session:
        result = seed_demo(session)
        print(f"{'Created' if result.admin_created else 'Updated'} admin {result.admin.email}")
        print(
            f"{'Created' if result.student_created else 'Updated'} student {result.student.email}"
        )
        print(f"Course (published): {result.published_course.title}")
        print(f"Course (in review):  {result.review_course.title}")
    return 0


def _prompt_password() -> str:
    while True:
        pw = getpass.getpass("New admin password: ")
        if len(pw) < MIN_ADMIN_PASSWORD_LEN:
            print(
                f"  Too short — need at least {MIN_ADMIN_PASSWORD_LEN} characters.",
                file=sys.stderr,
            )
            continue
        if pw != getpass.getpass("Confirm password: "):
            print("  Passwords did not match.", file=sys.stderr)
            continue
        return pw


def _cmd_seed_admin(args: argparse.Namespace) -> int:
    password = args.password or _prompt_password()
    with session_scope() as session:
        user, created = seed_admin(
            session, email=args.email, display_name=args.name, password=password
        )
        verb = "Created" if created else "Updated"
        print(f"{verb} admin {user.email} (id={user.id})")
    return 0


def _cmd_seed_prompts(_: argparse.Namespace) -> int:
    with session_scope() as session:
        inserted = seed_prompt_templates(session)
    print(f"seed-prompts: {inserted} template(s) inserted")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="Shikshak Dp admin CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed-admin", help="create or update an admin account")
    seed.add_argument("--email", required=True)
    seed.add_argument("--name", required=True, help="display name")
    seed.add_argument(
        "--password",
        help="password (omit to be prompted; prefer the prompt so it is not in shell history)",
    )
    seed.set_defaults(func=_cmd_seed_admin)

    prompts = sub.add_parser(
        "seed-prompts", help="insert the default prompt template for any artifact type missing one"
    )
    prompts.set_defaults(func=_cmd_seed_prompts)

    demo = sub.add_parser(
        "seed-demo",
        help="build a reviewable demo: admin + student + two courses via FixtureProvider",
    )
    demo.set_defaults(func=_cmd_seed_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
