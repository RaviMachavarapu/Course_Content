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
- ``add-math-prompt-line`` — append the two LaTeX instruction lines to the active
  Flashcards, Quiz and Report templates (one new version each; idempotent).
- ``refresh-report-math`` — one-time: re-read every stored report from
  NotebookLM and rebuild its text/HTML with the formula-aware parser, in place.
- ``rebuild-pdfs`` — typeset the PDF of every current and published version of
  the report, flashcards, quiz, infographic and slide-deck artifacts (replacing
  each version's previous PDF); ``--dry-run`` writes nothing.
"""

from __future__ import annotations

import argparse
import getpass
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.hashing import hash_password
from app.db.session import session_scope
from app.models.artifact import Artifact
from app.models.artifact_version import ArtifactVersion
from app.models.course import Course
from app.models.enums import ArtifactType
from app.models.module import Module
from app.models.user import User, UserRole, normalize_email
from app.pipeline import artifact_pdf, orchestrator
from app.pipeline.factory import get_content_provider
from app.pipeline.fixture import FixtureProvider
from app.pipeline.provider import ContentProvider, ProviderError, StudioJobRef
from app.render.typeset_client import TypesetError, TypesetUnavailable
from app.services.ingestion import detect_source_type
from app.services.progress import record_artifact_progress
from app.services.prompts import (
    get_active_body,
    seed_prompt_templates,
    update_prompt,
)
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


MATH_PROMPT_LINE = (
    "Write every mathematical expression, equation, chemical formula and scientific symbol "
    "in LaTeX between $ signs (e.g. $S_N2$, $\\frac{1}{2}mv^2$, $\\ce{H2O}$), copied exactly "
    "from the source, never paraphrased or invented."
)
NOTATION_PROMPT_LINE = (
    "Use standard LaTeX (e.g. \\frac{dx}{dt}, \\mathrm{m/s^2}, \\mathbf{F}) "
    "rather than package shorthand such as \\dv, \\SI or \\qty."
)
PROMPT_LINES = (MATH_PROMPT_LINE, NOTATION_PROMPT_LINE)
_MATH_PROMPT_TYPES = (ArtifactType.flashcards, ArtifactType.quiz, ArtifactType.report)


def add_math_prompt_line(session: Session) -> dict[ArtifactType, str]:
    """Ensure each active template ends with the LaTeX lines (formula format, then
    notation), appending whichever are missing as one new version each."""
    result: dict[ArtifactType, str] = {}
    for artifact_type in _MATH_PROMPT_TYPES:
        body = get_active_body(session, artifact_type)
        missing = [line for line in PROMPT_LINES if line not in body]
        if not missing:
            result[artifact_type] = "already present"
            continue
        new_body = "\n\n".join([body.rstrip(), *missing])
        row = update_prompt(session, artifact_type, new_body)
        result[artifact_type] = f"added v{row.version}"
    return result


def _cmd_add_math_prompt_line(_: argparse.Namespace) -> int:
    with session_scope() as session:
        result = add_math_prompt_line(session)
    for artifact_type, status in result.items():
        print(f"{artifact_type.value}: {status}")
    return 0


REBUILD_REPORT_PDFS = "run: python -m app.cli rebuild-pdfs --type report"


def refresh_report_math(
    session: Session, provider: ContentProvider, *, dry_run: bool = False
) -> list[tuple[str, str]]:
    """Rebuild every report version's content from its NotebookLM artifact.

    Updates ``content_json``/``content_html`` in place (same revision, same
    media). Returns ``(label, outcome)`` per version, outcome being ``updated``,
    ``unchanged`` or ``skipped (<reason>)``. Any fetch/parse error skips the
    version and leaves its row untouched. With ``dry_run`` nothing is written
    (``updated`` then means "would be updated").
    """
    versions = session.scalars(
        select(ArtifactVersion)
        .join(Artifact, Artifact.id == ArtifactVersion.artifact_id)
        .where(
            Artifact.type == ArtifactType.report,
            ArtifactVersion.notebooklm_artifact_id.is_not(None),
        )
        .order_by(ArtifactVersion.created_at)
    ).all()

    results: list[tuple[str, str]] = []
    for version in versions:
        module = version.artifact.module
        label = (
            f"{module.title} / report r{version.revision} " f"[{version.notebooklm_artifact_id}]"
        )
        notebook_id = module.notebooklm_notebook_id
        if not notebook_id or not version.notebooklm_artifact_id:
            results.append((label, "skipped (module has no NotebookLM notebook)"))
            continue
        job = StudioJobRef(
            job_id=version.notebooklm_artifact_id,
            notebook_id=notebook_id,
            kind=ArtifactType.report,
        )
        try:
            raw = provider.fetch_content(job)
        except ProviderError as exc:
            text = str(exc)
            if "404" in text or "not found" in text.lower():
                reason = "not found in the module's notebook"
            else:
                reason = f"fetch failed: {text[:200]}"
            results.append((label, f"skipped ({reason})"))
            continue
        except Exception as exc:
            results.append((label, f"skipped (fetch failed: {exc!s:.200})"))
            continue
        try:
            content_json, _blobs, content_html = orchestrator._content_and_media(
                provider, ArtifactType.report, raw, job
            )
        except Exception as exc:
            results.append((label, f"skipped (parse failed: {exc!s:.200})"))
            continue
        if not content_json or not content_html:
            results.append((label, "skipped (rebuilt content is empty)"))
            continue
        if content_json == version.content_json and content_html == version.content_html:
            results.append((label, "unchanged"))
            continue
        if not dry_run:
            version.content_json = content_json
            version.content_html = content_html
            session.flush()
        results.append((label, "updated"))
    return results


def _cmd_refresh_report_math(args: argparse.Namespace) -> int:
    provider = get_content_provider()
    with session_scope() as session:
        results = refresh_report_math(session, provider, dry_run=args.dry_run)
    for label, outcome in results:
        print(f"{label}: {outcome}")
    counts = {"updated": 0, "unchanged": 0, "skipped": 0}
    for _, outcome in results:
        counts[outcome.split(" ")[0]] += 1
    prefix = "DRY RUN - nothing written. " if args.dry_run else ""
    print(
        f"{prefix}refresh-report-math: {counts['updated']} updated, "
        f"{counts['unchanged']} unchanged, {counts['skipped']} skipped"
    )
    if counts["updated"] and not args.dry_run:
        # the reports' PDFs were typeset from the old content
        print(REBUILD_REPORT_PDFS)
    return 0


def _pdf_versions(session: Session, types: Sequence[ArtifactType] | None) -> list[uuid.UUID]:
    """The current and published version of every artifact with a PDF type."""
    wanted = [t for t in (types or artifact_pdf.PDF_KINDS) if t in artifact_pdf.PDF_KINDS]
    artifacts = session.scalars(
        select(Artifact)
        .join(Module, Module.id == Artifact.module_id)
        .where(Artifact.type.in_(wanted))
        .order_by(Module.course_id, Module.order_index, Artifact.type)
    ).all()
    ids: list[uuid.UUID] = []
    for artifact in artifacts:
        for vid in (artifact.current_version_id, artifact.published_version_id):
            if vid is not None and vid not in ids:
                ids.append(vid)
    return ids


def rebuild_pdfs(
    session: Session,
    *,
    dry_run: bool = False,
    types: Sequence[ArtifactType] | None = None,
    version_id: uuid.UUID | None = None,
    render: artifact_pdf.Render | None = None,
) -> list[tuple[str, str]]:
    """Typeset the PDF of each current/published version (or just `version_id`)
    synchronously, with the same steps as the `build_artifact_pdf` task.

    Returns ``(label, outcome)`` per version: ``built (fallback X)``,
    ``skipped (reason)`` or ``failed (reason)``; with ``dry_run`` the document
    is prepared (content checked) but nothing is typeset or written, and the
    outcome is ``would build``. Each built PDF is committed on its own.
    """
    ids = [version_id] if version_id is not None else _pdf_versions(session, types)
    results: list[tuple[str, str]] = []
    for vid in ids:
        version = session.get(ArtifactVersion, vid)
        if version is None:
            results.append((str(vid), "skipped (version not found)"))
            continue
        module = version.artifact.module
        label = f"{module.title} / {version.artifact.type.value} r{version.revision} [{version.id}]"
        try:
            if dry_run:
                artifact_pdf.prepare_pdf(session, vid)
                results.append((label, "would build"))
                continue
            built: artifact_pdf.BuiltPdf | None = None
            try:
                with session.begin_nested():
                    built = artifact_pdf.build_version_pdf(session, vid, render=render)
                session.commit()
            except Exception:
                if built is not None:  # the commit failed: don't orphan the new file
                    session.rollback()
                    artifact_pdf.discard_new_file(built.stored)
                raise
            artifact_pdf.delete_files(built.stored.stale_keys)
            results.append((label, f"built (fallback {built.fallback})"))
        except artifact_pdf.PdfSkipped as exc:
            results.append((label, f"skipped ({exc})"))
        except TypesetUnavailable as exc:
            results.append((label, f"failed (typeset service unavailable: {exc!s:.200})"))
        except TypesetError as exc:
            results.append((label, f"failed ({exc!s:.200})"))
        except Exception as exc:
            results.append((label, f"failed ({type(exc).__name__}: {exc!s:.200})"))
    return results


def _cmd_rebuild_pdfs(args: argparse.Namespace) -> int:
    types = [ArtifactType(args.type)] if args.type else None
    version_id = uuid.UUID(args.version) if args.version else None
    with session_scope() as session:
        results = rebuild_pdfs(session, dry_run=args.dry_run, types=types, version_id=version_id)
    for label, outcome in results:
        print(f"{label}: {outcome}")
    counts: dict[str, int] = {}
    for _, outcome in results:
        word = outcome.split(" (")[0]
        counts[word] = counts.get(word, 0) + 1
    summary = ", ".join(f"{n} {word}" for word, n in sorted(counts.items())) or "no versions"
    prefix = "DRY RUN - nothing written. " if args.dry_run else ""
    print(f"{prefix}rebuild-pdfs: {summary}")
    return 1 if counts.get("failed") else 0


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

    math_line = sub.add_parser(
        "add-math-prompt-line",
        help="append the LaTeX formula and notation lines to the flashcards, quiz, report prompts",
    )
    math_line.set_defaults(func=_cmd_add_math_prompt_line)

    demo = sub.add_parser(
        "seed-demo",
        help="build a reviewable demo: admin + student + two courses via FixtureProvider",
    )
    demo.set_defaults(func=_cmd_seed_demo)

    refresh = sub.add_parser(
        "refresh-report-math",
        help="re-read existing reports from NotebookLM and rebuild them (formula-aware)",
    )
    refresh.add_argument(
        "--dry-run", action="store_true", help="report what would change without writing"
    )
    refresh.set_defaults(func=_cmd_refresh_report_math)

    pdfs = sub.add_parser(
        "rebuild-pdfs",
        help="typeset the PDF of every current/published report, flashcards, quiz, "
        "infographic and slide-deck version",
    )
    pdfs.add_argument(
        "--dry-run", action="store_true", help="list what would be built without writing"
    )
    pdfs.add_argument(
        "--type",
        choices=[t.value for t in artifact_pdf.PDF_KINDS],
        help="only this artifact type",
    )
    pdfs.add_argument("--version", help="only this artifact version id")
    pdfs.set_defaults(func=_cmd_rebuild_pdfs)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
