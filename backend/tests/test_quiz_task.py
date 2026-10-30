"""Adaptive quiz: `prepare_quiz_set` prepares a student's next fresh question set from
NotebookLM chat (spec §4.3). A fake chat provider only; never the live connector."""

from __future__ import annotations

import datetime as dt
import json
import random
import string
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from celery.exceptions import Retry
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import (
    Artifact,
    ArtifactStatus,
    ArtifactType,
    Course,
    Module,
    ModuleSourceType,
    QuizQuestionSet,
    QuizSetSource,
    QuizSetStatus,
    User,
    UserRole,
)
from app.models.artifact_version import ArtifactVersion
from app.pipeline.provider import GenerationTimeout, NotebookRef, TransientProviderError
from app.services import quiz_generation as qg
from app.services.quiz_generation import SourceTextUnavailable
from app.tasks import quiz

_rng = random.Random(7)
#: what a quiz with default options (and the `setup` quiz) has its sets prepared for
EN = {"prepared_for": {"language": "en", "difficulty": "medium"}}


def _word() -> str:
    return "".join(_rng.choice(string.ascii_lowercase) for _ in range(9))


def _text() -> str:
    """A question text unlike any other (random words: never a near-duplicate)."""
    return " ".join(_word() for _ in range(6)) + "?"


def mcq(question: str | None = None) -> dict[str, Any]:
    return {
        "type": "mcq",
        "question": question or _text(),
        "options": [_word(), _word(), _word(), _word()],
        "correct_index": 1,
        "explanation": "because",
        "source_quote": "",
    }


def blank() -> dict[str, Any]:
    return {
        "type": "fill_blank",
        "question": f"{_word()} {_word()} is ____ {_word()}.",
        "answer": _word(),
        "accepted_answers": [],
        "explanation": "because",
        "source_quote": "",
    }


def bad() -> dict[str, Any]:
    return {**mcq(), "options": ["a", "a", "b", "c"]}  # options not distinct


def answer(questions: list[dict[str, Any]]) -> str:
    return "Here are your questions:\n```json\n" + json.dumps(questions) + "\n```"


class FakeChat:
    """Answers queries from a script: each item is an answer string or an exception."""

    def __init__(self, *script: str | Exception) -> None:
        self.script = list(script)
        self.prompts: list[str] = []
        self.on_query: Callable[[], None] | None = None

    def query(self, nb: NotebookRef, text: str) -> str:
        assert nb.notebook_id == "nb-1"
        self.prompts.append(text)
        if self.on_query is not None:
            hook, self.on_query = self.on_query, None
            hook()
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# -- fixtures --------------------------------------------------------------------


@pytest.fixture
def scope(
    monkeypatch: pytest.MonkeyPatch,
    source_step_sessions: Callable[[], AbstractContextManager[Session]],
) -> Callable[[], AbstractContextManager[Session]]:
    monkeypatch.setattr(quiz, "session_scope", source_step_sessions)
    return source_step_sessions


@pytest.fixture
def setup(db_session: Session) -> tuple[Artifact, User]:
    course = Course(title="Chem", slug=f"chem-{uuid.uuid4().hex[:8]}", description="d")
    module = Module(
        course=course,
        order_index=0,
        title="Organic",
        source_url="https://youtu.be/x",
        source_type=ModuleSourceType.youtube,
        notebooklm_notebook_id="nb-1",
    )
    artifact = Artifact(module=module, type=ArtifactType.quiz, status=ArtifactStatus.published)
    student = User(
        email=f"s-{uuid.uuid4().hex[:8]}@x.org",
        role=UserRole.student,
        password_hash="x",
        display_name="S",
    )
    db_session.add_all([course, artifact, student])
    db_session.flush()
    studio = [mcq() for _ in range(10)]
    version = ArtifactVersion(
        artifact_id=artifact.id, revision=1, content_json={"questions": studio}
    )
    db_session.add(version)
    db_session.flush()
    artifact.published_version_id = version.id
    db_session.commit()
    return artifact, student


def _run(
    monkeypatch: pytest.MonkeyPatch,
    chat: FakeChat,
    artifact: Artifact,
    user: User,
    *,
    set_id: str | None = None,
    retries: int = 0,
) -> str:
    monkeypatch.setattr(quiz, "get_content_provider", lambda: chat)
    task = quiz.prepare_quiz_set
    task.push_request(retries=retries)
    try:
        return task.run(  # type: ignore[no-any-return]
            artifact_id=str(artifact.id), user_id=str(user.id), set_id=set_id
        )
    finally:
        task.pop_request()


def _sets(db: Session, artifact: Artifact, user: User) -> list[QuizQuestionSet]:
    db.expire_all()
    return list(
        db.scalars(
            sa.select(QuizQuestionSet).where(
                QuizQuestionSet.artifact_id == artifact.id, QuizQuestionSet.user_id == user.id
            )
        )
    )


@pytest.fixture
def retries(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """Capture `self.retry(...)` calls instead of scheduling them."""
    calls: list[dict[str, Any]] = []

    def fake_retry(**kwargs: Any) -> Retry:
        calls.append(kwargs)
        return Retry("retry", exc=kwargs.get("exc"))

    monkeypatch.setattr(quiz.prepare_quiz_set, "retry", fake_retry)
    yield calls


# -- tests -----------------------------------------------------------------------


def test_success_stores_a_ready_set_of_n_questions(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    questions = [mcq() for _ in range(6)] + [blank() for _ in range(4)]
    chat = FakeChat(answer(questions))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    [qs] = _sets(db_session, artifact, user)
    assert qs.source is QuizSetSource.chat
    assert qs.status is QuizSetStatus.ready
    assert [q["question"] for q in qs.questions] == [q["question"] for q in questions]
    assert len(chat.prompts) == 1
    assert "Create 10 NEW quiz questions" in chat.prompts[0]
    report = qs.validation_report
    assert report["requested"] == 10
    assert report["served"] == 10
    assert len(report["rounds"]) == 1
    assert report["rounds"][0]["kept"] == [q["question"] for q in questions]
    assert report["rounds"][0]["dropped"] == []
    db_session.refresh(artifact)
    assert artifact.status is ArtifactStatus.published  # never touched


def test_n_is_the_studio_question_count_and_extra_questions_are_capped(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    version = db_session.get(ArtifactVersion, artifact.published_version_id)
    assert version is not None
    version.content_json = {"questions": [mcq() for _ in range(6)]}
    db_session.commit()
    chat = FakeChat(answer([mcq() for _ in range(8)]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    [qs] = _sets(db_session, artifact, user)
    assert "Create 6 NEW quiz questions" in chat.prompts[0]
    assert len(qs.questions) == 6


def test_shortfall_is_asked_for_once_more(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    first = [mcq() for _ in range(7)]
    again = [mcq(first[0]["question"]), mcq(), mcq(), mcq(), bad()]  # 1 duplicate, 1 invalid
    chat = FakeChat(answer([*first, bad(), bad()]), answer(again))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.ready
    assert [q["question"] for q in qs.questions] == [q["question"] for q in first + again[1:4]]
    assert len(chat.prompts) == 2
    assert "Create 3 NEW quiz questions" in chat.prompts[1]
    assert first[0]["question"] in chat.prompts[1]  # kept questions are in the avoid list
    rounds = qs.validation_report["rounds"]
    assert [len(r["dropped"]) for r in rounds] == [2, 2]
    reasons = [d["reason"] for d in rounds[1]["dropped"]]
    assert any(r.startswith("duplicate:") for r in reasons)
    assert any(r.startswith("options:") for r in reasons)
    assert qs.validation_report["served"] == 10


def test_still_short_but_at_least_five_is_served(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    chat = FakeChat(answer([mcq() for _ in range(4)]), answer([mcq(), bad()]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    [qs] = _sets(db_session, artifact, user)
    assert len(qs.questions) == 5
    assert qs.validation_report["served"] == 5


def test_a_failed_re_ask_serves_round_one_when_it_has_five(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    chat = FakeChat(answer([mcq() for _ in range(6)]), TransientProviderError("rate limited"))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    [qs] = _sets(db_session, artifact, user)
    assert len(qs.questions) == 6
    assert "rate limited" in qs.validation_report["reask_error"]


def test_a_failed_re_ask_with_fewer_than_five_retries(
    db_session: Session,
    scope: Any,
    setup: tuple[Artifact, User],
    monkeypatch: pytest.MonkeyPatch,
    retries: list[dict[str, Any]],
) -> None:
    artifact, user = setup
    chat = FakeChat(answer([mcq() for _ in range(3)]), TransientProviderError("rate limited"))
    with pytest.raises(Retry):
        _run(monkeypatch, chat, artifact, user)
    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.preparing


def test_fewer_than_five_valid_questions_fails_the_set(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    chat = FakeChat(answer([mcq(), mcq(), bad()]), "Sorry, I can't help with that.")

    assert _run(monkeypatch, chat, artifact, user) == "failed"

    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.failed
    assert qs.questions == []
    report = qs.validation_report
    assert len(report["rounds"]) == 2
    assert report["rounds"][1]["parsed"] == 0
    assert "fewer than 5" in report["error"]
    db_session.refresh(artifact)
    assert artifact.status is ArtifactStatus.published


def _studio_count(db: Session, artifact: Artifact, n: int) -> None:
    version = db.get(ArtifactVersion, artifact.published_version_id)
    assert version is not None
    version.content_json = {"questions": [mcq() for _ in range(n)]}
    db.commit()


def test_a_short_studio_quiz_serves_retakes_of_its_own_size(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner decision 2026-10-29: a retake has as many questions as the Studio quiz; the
    minimum served is min(5, N), so a 3-question quiz gets 3-question retakes."""
    artifact, user = setup
    _studio_count(db_session, artifact, 3)
    chat = FakeChat(answer([mcq() for _ in range(7)]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.ready
    assert len(qs.questions) == 3
    assert "Create 3 NEW quiz questions" in chat.prompts[0]


def test_a_short_studio_quiz_needs_all_of_its_questions(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    _studio_count(db_session, artifact, 3)
    chat = FakeChat(answer([mcq(), mcq(), bad()]), answer([bad()]))

    assert _run(monkeypatch, chat, artifact, user) == "failed"

    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.failed
    assert "fewer than 3 needed" in qs.validation_report["error"]


def test_a_failed_re_ask_serves_round_one_when_it_covers_a_short_quiz(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    _studio_count(db_session, artifact, 4)
    chat = FakeChat(answer([mcq() for _ in range(4)]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"
    assert len(chat.prompts) == 1  # nothing short: no re-ask


def test_min_served_is_five_or_the_studio_count() -> None:
    assert [qg.min_served(n) for n in (1, 3, 5, 10)] == [1, 3, 5, 5]


def test_a_redis_outage_during_preparation_is_retried(
    db_session: Session,
    scope: Any,
    setup: tuple[Artifact, User],
    monkeypatch: pytest.MonkeyPatch,
    retries: list[dict[str, Any]],
) -> None:
    """Redis restarting (the NotebookLM session lock lives there) is chat unavailable."""
    import redis.exceptions

    artifact, user = setup
    with pytest.raises(Retry):
        _run(monkeypatch, FakeChat(redis.exceptions.ConnectionError("restarting")), artifact, user)
    assert len(retries) == 1
    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.preparing


def test_unverified_fill_blank_is_recorded_with_its_served_text(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unverified flag carries the question as served (blank normalised to ____), so
    the admin panel can match it."""
    artifact, user = setup
    quote = "the reaction proceeds through a planar carbocation intermediate"
    monkeypatch.setattr(
        qg, "read_module_source_text", lambda _m: qg.SourceText(f"Notes. {quote}. End.")
    )
    from_pdf = [{**mcq(), "source_quote": quote} for _ in range(4)]
    video_blank = {
        **blank(),
        "question": "The video says the ______ is red.",
        "source_quote": "a sentence only spoken in the video",
    }
    chat = FakeChat(answer([*from_pdf, video_blank]), answer([]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    [qs] = _sets(db_session, artifact, user)
    [flag] = qs.validation_report["rounds"][0]["unverified"]
    assert flag["question"] == "The video says the ____ is red."
    assert flag["question"] in [q["question"] for q in qs.questions]


def test_transient_error_retries_with_back_off_then_succeeds(
    db_session: Session,
    scope: Any,
    setup: tuple[Artifact, User],
    monkeypatch: pytest.MonkeyPatch,
    retries: list[dict[str, Any]],
) -> None:
    artifact, user = setup
    chat = FakeChat(TransientProviderError("rate limited"), answer([mcq() for _ in range(10)]))

    with pytest.raises(Retry):
        _run(monkeypatch, chat, artifact, user)

    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.preparing  # stays pending for the retry
    [call] = retries
    assert call["countdown"] == quiz.RETRY_BASE_SEC
    assert call["kwargs"] == {
        "artifact_id": str(artifact.id),
        "user_id": str(user.id),
        "set_id": str(qs.id),
    }

    assert _run(monkeypatch, chat, artifact, user, retries=1, **_set(call)) == "ready"
    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.ready
    assert len(qs.questions) == 10


def _set(call: dict[str, Any]) -> dict[str, Any]:
    return {"set_id": call["kwargs"]["set_id"]}


def test_back_off_doubles_per_retry(
    db_session: Session,
    scope: Any,
    setup: tuple[Artifact, User],
    monkeypatch: pytest.MonkeyPatch,
    retries: list[dict[str, Any]],
) -> None:
    artifact, user = setup
    chat = FakeChat(TransientProviderError("x"), TransientProviderError("x"))
    with pytest.raises(Retry):
        _run(monkeypatch, chat, artifact, user)
    with pytest.raises(Retry):
        _run(monkeypatch, chat, artifact, user, retries=2, **_set(retries[0]))
    assert [c["countdown"] for c in retries] == [quiz.RETRY_BASE_SEC, quiz.RETRY_BASE_SEC * 4]


def test_giving_up_after_the_last_retry_fails_the_set(
    db_session: Session,
    scope: Any,
    setup: tuple[Artifact, User],
    monkeypatch: pytest.MonkeyPatch,
    retries: list[dict[str, Any]],
) -> None:
    artifact, user = setup
    chat = FakeChat(TransientProviderError("x"), TransientProviderError("still limited"))
    with pytest.raises(Retry):
        _run(monkeypatch, chat, artifact, user)

    outcome = _run(monkeypatch, chat, artifact, user, retries=quiz.MAX_RETRIES, **_set(retries[0]))

    assert outcome == "gave up"
    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.failed
    assert "still limited" in qs.validation_report["error"]


def test_unreadable_source_pdfs_retry_without_asking_chat(
    db_session: Session,
    scope: Any,
    setup: tuple[Artifact, User],
    monkeypatch: pytest.MonkeyPatch,
    retries: list[dict[str, Any]],
) -> None:
    artifact, user = setup

    def unreadable(_: Module) -> qg.SourceText:
        raise SourceTextUnavailable("none of the module's 1 PDF(s) could be read")

    monkeypatch.setattr(qg, "read_module_source_text", unreadable)
    chat = FakeChat()

    with pytest.raises(Retry):
        _run(monkeypatch, chat, artifact, user)

    assert chat.prompts == []
    assert len(retries) == 1
    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.preparing


def test_source_text_is_used_for_quote_checks(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    artifact.module.source_url = None  # PDF-only module
    artifact.module.source_type = ModuleSourceType.pdf
    db_session.commit()
    quote = "the reaction proceeds through a planar carbocation intermediate"
    monkeypatch.setattr(
        qg, "read_module_source_text", lambda _m: qg.SourceText(f"Notes. {quote}. End.")
    )
    good = [{**mcq(), "source_quote": quote} for _ in range(5)]
    fabricated = {**mcq(), "source_quote": "a sentence that is nowhere in the module notes"}
    chat = FakeChat(answer([*good, fabricated]), answer([]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    [qs] = _sets(db_session, artifact, user)
    assert len(qs.questions) == 5
    [dropped] = qs.validation_report["rounds"][0]["dropped"]
    assert dropped["reason"].startswith("quote:")


def test_a_link_and_pdf_module_keeps_link_quotes_and_flags_them(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup  # the module has a YouTube link
    quote = "the reaction proceeds through a planar carbocation intermediate"
    monkeypatch.setattr(
        qg, "read_module_source_text", lambda _m: qg.SourceText(f"Notes. {quote}. End.")
    )
    from_pdf = [{**mcq(), "source_quote": quote} for _ in range(4)]
    from_video = {**mcq(), "source_quote": "a sentence only spoken in the video"}
    chat = FakeChat(answer([*from_pdf, from_video]), answer([]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    [qs] = _sets(db_session, artifact, user)
    assert len(qs.questions) == 5
    first = qs.validation_report["rounds"][0]
    assert first["dropped"] == []
    [flag] = first["unverified"]
    assert flag["question"] == from_video["question"]
    assert flag["reason"] == "quote not verified (link source)"


def test_switch_off_prepares_nothing(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    artifact.module.quiz_fresh_retakes = False
    db_session.commit()
    chat = FakeChat()

    assert _run(monkeypatch, chat, artifact, user) == "off"

    assert _sets(db_session, artifact, user) == []
    assert chat.prompts == []


def test_a_non_quiz_artifact_is_skipped(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    artifact.type = ArtifactType.flashcards
    db_session.commit()
    chat = FakeChat()
    assert _run(monkeypatch, chat, artifact, user) == "skipped"
    assert _sets(db_session, artifact, user) == []


def test_a_module_without_a_notebook_fails_the_set(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    artifact.module.notebooklm_notebook_id = None
    db_session.commit()
    chat = FakeChat()

    assert _run(monkeypatch, chat, artifact, user) == "failed"

    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.failed
    assert "notebook" in qs.validation_report["error"]
    assert chat.prompts == []


def test_prepare_is_idempotent(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two concurrent calls (the second starts while the first is asking chat) → one row,
    one chat query; a later call while the set is ready does nothing either."""
    artifact, user = setup
    chat = FakeChat(answer([mcq() for _ in range(10)]))
    inner: list[str] = []
    chat.on_query = lambda: inner.append(_run(monkeypatch, chat, artifact, user))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    assert inner == ["exists"]
    assert len(chat.prompts) == 1
    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.ready

    assert _run(monkeypatch, FakeChat(), artifact, user) == "exists"
    assert len(_sets(db_session, artifact, user)) == 1


def test_a_new_set_is_prepared_once_the_previous_one_is_used_or_failed(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    for status in (QuizSetStatus.used, QuizSetStatus.failed):
        db_session.add(
            QuizQuestionSet(
                artifact_id=artifact.id, user_id=user.id, source=QuizSetSource.chat, status=status
            )
        )
    db_session.commit()
    chat = FakeChat(answer([mcq() for _ in range(10)]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"
    assert len(_sets(db_session, artifact, user)) == 3


def test_an_abandoned_preparing_set_is_replaced(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker that died mid-preparation leaves a `preparing` row behind; once it is older
    than STALE_AFTER the redelivered task fails it and prepares a new set."""
    artifact, user = setup
    old = QuizQuestionSet(
        artifact_id=artifact.id,
        user_id=user.id,
        source=QuizSetSource.chat,
        status=QuizSetStatus.preparing,
        validation_report=EN,
        created_at=dt.datetime.now(tz=dt.UTC) - quiz.STALE_AFTER - dt.timedelta(minutes=1),
    )
    db_session.add(old)
    db_session.commit()
    chat = FakeChat(answer([mcq() for _ in range(10)]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    by_status = {qs.status: qs for qs in _sets(db_session, artifact, user)}
    assert set(by_status) == {QuizSetStatus.failed, QuizSetStatus.ready}
    assert by_status[QuizSetStatus.failed].id == old.id


def test_a_recent_preparing_set_is_left_alone(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    db_session.add(
        QuizQuestionSet(
            artifact_id=artifact.id,
            user_id=user.id,
            source=QuizSetSource.chat,
            status=QuizSetStatus.preparing,
            validation_report=EN,
        )
    )
    db_session.commit()
    chat = FakeChat()
    assert _run(monkeypatch, chat, artifact, user) == "exists"
    assert chat.prompts == []


def test_a_retry_for_a_set_no_longer_preparing_does_nothing(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    qs = QuizQuestionSet(
        artifact_id=artifact.id,
        user_id=user.id,
        source=QuizSetSource.chat,
        status=QuizSetStatus.ready,
    )
    db_session.add(qs)
    db_session.commit()
    chat = FakeChat()
    assert _run(monkeypatch, chat, artifact, user, set_id=str(qs.id), retries=1) == "exists"
    assert chat.prompts == []


def test_avoid_list_is_built_from_previous_sets(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    version = db_session.get(ArtifactVersion, artifact.published_version_id)
    assert version is not None
    studio_texts = [q["question"] for q in version.content_json["questions"]]  # type: ignore[index]
    now = dt.datetime.now(tz=dt.UTC)
    older = [mcq() for _ in range(10)]
    newer = [mcq() for _ in range(10)]
    other_user = User(
        email=f"o-{uuid.uuid4().hex[:8]}@x.org",
        role=UserRole.student,
        password_hash="x",
        display_name="O",
    )
    db_session.add(other_user)
    db_session.flush()
    others = [mcq() for _ in range(10)]
    db_session.add_all(
        [
            QuizQuestionSet(
                artifact_id=artifact.id,
                user_id=user.id,
                source=QuizSetSource.chat,
                status=QuizSetStatus.used,
                questions=older,
                created_at=now - dt.timedelta(days=2),
            ),
            QuizQuestionSet(
                artifact_id=artifact.id,
                user_id=user.id,
                source=QuizSetSource.chat,
                status=QuizSetStatus.used,
                questions=newer,
                created_at=now - dt.timedelta(days=1),
            ),
            QuizQuestionSet(  # another student's set is not this student's history
                artifact_id=artifact.id,
                user_id=other_user.id,
                source=QuizSetSource.chat,
                status=QuizSetStatus.used,
                questions=others,
            ),
        ]
    )
    db_session.commit()

    seen = quiz.seen_questions(db_session, artifact, user.id)
    assert seen == [q["question"] for q in newer + older] + studio_texts

    repeat = mcq(newer[3]["question"])
    studio_repeat = mcq(studio_texts[0])
    fresh = [mcq() for _ in range(10)]
    chat = FakeChat(answer([repeat, studio_repeat, *fresh]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    prompt = chat.prompts[0]
    assert newer[0]["question"] in prompt
    assert studio_texts[0] in prompt
    assert others[0]["question"] not in prompt
    qs = next(s for s in _sets(db_session, artifact, user) if s.status is QuizSetStatus.ready)
    assert [q["question"] for q in qs.questions] == [q["question"] for q in fresh]
    reasons = [d["reason"] for d in qs.validation_report["rounds"][0]["dropped"]]
    assert len(reasons) == 2
    assert all(r.startswith("duplicate:") for r in reasons)


def _used_sets(
    db: Session, artifact: Artifact, user: User, count: int
) -> list[list[dict[str, Any]]]:
    now = dt.datetime.now(tz=dt.UTC)
    sets = [[mcq() for _ in range(10)] for _ in range(count)]
    for i, questions in enumerate(sets):
        db.add(
            QuizQuestionSet(
                artifact_id=artifact.id,
                user_id=user.id,
                source=QuizSetSource.chat,
                status=QuizSetStatus.used,
                questions=questions,
                created_at=now - dt.timedelta(days=10 - i),
            )
        )
    db.commit()
    return sets


def test_seen_questions_lists_all_and_limit_keeps_the_most_recent(
    db_session: Session, setup: tuple[Artifact, User]
) -> None:
    artifact, user = setup
    sets = _used_sets(db_session, artifact, user, 7)

    seen = quiz.seen_questions(db_session, artifact, user.id)
    assert len(seen) == 80  # 7 used sets + the 10 Studio questions
    assert seen[:10] == [q["question"] for q in sets[6]]

    recent = quiz.seen_questions(db_session, artifact, user.id, limit=60)
    assert len(recent) == 60
    assert recent[-10:] == [q["question"] for q in sets[1]]


def test_an_old_seen_question_beyond_the_avoid_list_is_still_dropped(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the prompt's avoid list is capped at 60; validation checks every seen question."""
    artifact, user = setup
    version = db_session.get(ArtifactVersion, artifact.published_version_id)
    assert version is not None
    studio_text = version.content_json["questions"][0]["question"]  # type: ignore[index]
    sets = _used_sets(db_session, artifact, user, 7)
    oldest_chat = sets[0][0]["question"]
    fresh = [mcq() for _ in range(10)]
    chat = FakeChat(answer([mcq(studio_text), mcq(oldest_chat), *fresh]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    assert studio_text not in chat.prompts[0]  # beyond the 60 most recent
    assert oldest_chat not in chat.prompts[0]
    qs = next(s for s in _sets(db_session, artifact, user) if s.status is QuizSetStatus.ready)
    assert [q["question"] for q in qs.questions] == [q["question"] for q in fresh]
    reasons = [d["reason"] for d in qs.validation_report["rounds"][0]["dropped"]]
    assert len(reasons) == 2
    assert all(r.startswith("duplicate:") for r in reasons)
    assert qs.validation_report["seen"] == 80


@pytest.mark.parametrize(
    "error",
    [
        TransientProviderError("timeout"),
        GenerationTimeout("503 Service Unavailable"),
        httpx.ConnectError("connection refused"),
        httpx.ReadError("connection reset"),
    ],
    ids=["transient", "5xx", "connect", "read"],
)
def test_chat_unavailable_is_retried(
    error: Exception,
    db_session: Session,
    scope: Any,
    setup: tuple[Artifact, User],
    monkeypatch: pytest.MonkeyPatch,
    retries: list[dict[str, Any]],
) -> None:
    artifact, user = setup
    with pytest.raises(Retry):
        _run(monkeypatch, FakeChat(error), artifact, user)
    assert len(retries) == 1
    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.preparing


def test_connector_unreachable_on_the_re_ask_with_fewer_than_five_retries(
    db_session: Session,
    scope: Any,
    setup: tuple[Artifact, User],
    monkeypatch: pytest.MonkeyPatch,
    retries: list[dict[str, Any]],
) -> None:
    artifact, user = setup
    chat = FakeChat(answer([mcq()]), httpx.ConnectError("refused"))
    with pytest.raises(Retry):
        _run(monkeypatch, chat, artifact, user)
    assert len(retries) == 1


def test_a_set_no_longer_preparing_when_done_is_superseded(
    db_session: Session,
    scope: Any,
    setup: tuple[Artifact, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, user = setup
    chat = FakeChat(answer([mcq() for _ in range(10)]))

    def fail_it() -> None:  # e.g. replaced as abandoned while chat was answering
        [qs] = _sets(db_session, artifact, user)
        qs.status = QuizSetStatus.failed
        qs.validation_report = {"error": "abandoned"}
        db_session.commit()

    chat.on_query = fail_it

    assert _run(monkeypatch, chat, artifact, user) == "superseded"

    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.failed
    assert qs.questions == []
    assert qs.validation_report == {"error": "abandoned"}


def test_finish_on_a_failed_set_writes_nothing(
    db_session: Session, scope: Any, setup: tuple[Artifact, User]
) -> None:
    artifact, user = setup
    qs = QuizQuestionSet(
        artifact_id=artifact.id,
        user_id=user.id,
        source=QuizSetSource.chat,
        status=QuizSetStatus.failed,
        validation_report={"error": "x"},
    )
    db_session.add(qs)
    db_session.commit()

    written = quiz._finish(qs.id, quiz._Result(questions=[mcq() for _ in range(5)], report={}))

    assert written is False
    db_session.refresh(qs)
    assert qs.status is QuizSetStatus.failed
    assert qs.validation_report == {"error": "x"}


def test_a_database_blip_when_storing_keeps_the_questions(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    real_write = quiz._write
    calls: list[int] = []
    sleeps: list[float] = []

    def flaky(set_id: uuid.UUID, result: Any) -> bool:
        calls.append(1)
        if len(calls) < 3:
            raise OperationalError("UPDATE", {}, Exception("server closed the connection"))
        return real_write(set_id, result)

    monkeypatch.setattr(quiz, "_write", flaky)
    monkeypatch.setattr("app.tasks.quiz.time.sleep", sleeps.append)
    chat = FakeChat(answer([mcq() for _ in range(10)]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    assert len(calls) == 3
    assert sleeps == [quiz.FINISH_BACKOFF_SEC, quiz.FINISH_BACKOFF_SEC * 2]
    assert len(chat.prompts) == 1
    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.ready
    assert len(qs.questions) == 10


def test_a_database_outage_when_storing_raises_after_the_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def down(*_: Any) -> bool:
        raise OperationalError("UPDATE", {}, Exception("down"))

    monkeypatch.setattr(quiz, "_write", down)
    monkeypatch.setattr("app.tasks.quiz.time.sleep", lambda _s: None)
    with pytest.raises(OperationalError):
        quiz._finish(uuid.uuid4(), quiz._Result())


def test_studio_set_rows_are_not_listed_twice(
    db_session: Session, setup: tuple[Artifact, User]
) -> None:
    artifact, user = setup
    version = db_session.get(ArtifactVersion, artifact.published_version_id)
    assert version is not None
    studio = version.content_json["questions"]  # type: ignore[index]
    db_session.add(
        QuizQuestionSet(
            artifact_id=artifact.id,
            user_id=user.id,
            source=QuizSetSource.studio,
            status=QuizSetStatus.used,
            questions=studio,
        )
    )
    db_session.commit()
    seen = quiz.seen_questions(db_session, artifact, user.id)
    assert seen == [q["question"] for q in studio]


# -- enqueue ---------------------------------------------------------------------


def test_enqueue_prepare_sends_to_the_quiz_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(quiz.prepare_quiz_set, "apply_async", lambda **kw: sent.append(kw))
    aid, uid = uuid.uuid4(), uuid.uuid4()

    quiz.enqueue_prepare(aid, uid)

    assert sent == [{"kwargs": {"artifact_id": str(aid), "user_id": str(uid)}, "queue": "quiz"}]


def test_enqueue_prepare_swallows_broker_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def down(**_: Any) -> None:
        raise ConnectionError("redis down")

    monkeypatch.setattr(quiz.prepare_quiz_set, "apply_async", down)
    quiz.enqueue_prepare(uuid.uuid4(), uuid.uuid4())  # no exception


def test_task_is_routed_to_the_quiz_queue() -> None:
    assert quiz.prepare_quiz_set.queue == "quiz"
    assert quiz.prepare_quiz_set.name == "app.tasks.prepare_quiz_set"


def test_concurrent_claims_on_separate_connections_insert_one_set(db_engine: sa.Engine) -> None:
    """Real concurrency: two transactions insert at once; the second waits for the first
    and then inserts nothing (ON CONFLICT on the partial unique index)."""
    import threading

    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with factory() as db:  # committed for real: other connections must see it
        course = Course(title="C", slug=f"conc-{uuid.uuid4().hex[:8]}", description="d")
        module = Module(
            course=course, order_index=0, title="M", source_type=ModuleSourceType.youtube
        )
        artifact = Artifact(module=module, type=ArtifactType.quiz)
        user = User(
            email=f"c-{uuid.uuid4().hex[:8]}@x.org",
            role=UserRole.student,
            password_hash="x",
            display_name="C",
        )
        db.add_all([course, artifact, user])
        db.commit()
    try:
        first, second = factory(), factory()
        got: dict[str, uuid.UUID | None] = {}
        assert quiz._insert_preparing(first, artifact.id, user.id, EN["prepared_for"]) is not None

        def claim() -> None:
            got["second"] = quiz._insert_preparing(second, artifact.id, user.id, EN["prepared_for"])
            second.commit()

        thread = threading.Thread(target=claim)
        thread.start()
        thread.join(timeout=1)
        assert thread.is_alive()  # blocked on the first transaction's uncommitted row
        first.commit()
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert got["second"] is None
        first.close()
        second.close()
        with factory() as db:
            count = db.scalar(
                sa.select(sa.func.count())
                .select_from(QuizQuestionSet)
                .where(QuizQuestionSet.artifact_id == artifact.id)
            )
            assert count == 1
    finally:
        with factory() as db:
            db.execute(sa.delete(Course).where(Course.id == course.id))
            db.execute(sa.delete(User).where(User.id == user.id))
            db.commit()


# -- heartbeat: a crashed preparation is replaced after STALE_AFTER of silence ------


def _ago(minutes: float) -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC) - dt.timedelta(minutes=minutes)


def _stale_minutes() -> float:
    return quiz.STALE_AFTER.total_seconds() / 60 + 1


def _preparing(
    db: Session,
    artifact: Artifact,
    user: User,
    *,
    created_at: dt.datetime | None = None,
    heartbeat_at: dt.datetime | None = None,
) -> QuizQuestionSet:
    qs = QuizQuestionSet(
        artifact_id=artifact.id,
        user_id=user.id,
        source=QuizSetSource.chat,
        status=QuizSetStatus.preparing,
        heartbeat_at=heartbeat_at,
        validation_report=EN,
    )
    if created_at is not None:
        qs.created_at = created_at
    db.add(qs)
    db.commit()
    return qs


def _heartbeat_of(db: Session, set_id: uuid.UUID) -> dt.datetime | None:
    db.expire_all()
    qs = db.get(QuizQuestionSet, set_id)
    assert qs is not None
    return qs.heartbeat_at


def _age_heartbeat(db: Session, set_id: uuid.UUID, minutes: float) -> None:
    db.execute(
        sa.update(QuizQuestionSet)
        .where(QuizQuestionSet.id == set_id)
        .values(heartbeat_at=_ago(minutes))
    )
    db.commit()


def test_stale_after_leaves_room_for_the_longest_back_off() -> None:
    longest_countdown = quiz.RETRY_BASE_SEC * 2 ** (quiz.MAX_RETRIES - 1)
    assert dt.timedelta(seconds=longest_countdown) < quiz.STALE_AFTER
    assert dt.timedelta(minutes=15) <= quiz.STALE_AFTER <= dt.timedelta(minutes=30)


def test_a_new_set_starts_with_a_heartbeat(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    assert (
        _run(monkeypatch, FakeChat(answer([mcq() for _ in range(10)])), artifact, user) == "ready"
    )
    [qs] = _sets(db_session, artifact, user)
    assert qs.heartbeat_at is not None
    assert qs.heartbeat_at > _ago(1)


def test_a_crashed_preparation_is_replaced_once_its_heartbeat_is_stale(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    old = _preparing(
        db_session,
        artifact,
        user,
        created_at=_ago(_stale_minutes() + 5),
        heartbeat_at=_ago(_stale_minutes()),
    )
    chat = FakeChat(answer([mcq() for _ in range(10)]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    by_status = {qs.status: qs for qs in _sets(db_session, artifact, user)}
    assert set(by_status) == {QuizSetStatus.failed, QuizSetStatus.ready}
    assert by_status[QuizSetStatus.failed].id == old.id
    assert "abandoned" in by_status[QuizSetStatus.failed].validation_report["error"]


def test_a_live_preparation_with_a_fresh_heartbeat_is_not_replaced(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Created hours ago (a long back-off) but its task beat a minute ago: alive."""
    artifact, user = setup
    live = _preparing(db_session, artifact, user, created_at=_ago(180), heartbeat_at=_ago(1))
    chat = FakeChat()

    assert _run(monkeypatch, chat, artifact, user) == "exists"

    assert chat.prompts == []
    [qs] = _sets(db_session, artifact, user)
    assert qs.id == live.id
    assert qs.status is QuizSetStatus.preparing


@pytest.mark.parametrize(
    ("created_minutes_ago", "replaced"), [(1, False), (None, True)], ids=["recent", "stale"]
)
def test_without_a_heartbeat_liveness_falls_back_to_created_at(
    created_minutes_ago: float | None,
    replaced: bool,
    db_session: Session,
    scope: Any,
    setup: tuple[Artifact, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sets made before the heartbeat column existed have heartbeat_at NULL."""
    artifact, user = setup
    minutes = _stale_minutes() if created_minutes_ago is None else created_minutes_ago
    old = _preparing(db_session, artifact, user, created_at=_ago(minutes))
    assert old.heartbeat_at is None
    chat = FakeChat(answer([mcq() for _ in range(10)]))

    outcome = _run(monkeypatch, chat, artifact, user)

    assert outcome == ("ready" if replaced else "exists")
    db_session.refresh(old)
    assert old.status is (QuizSetStatus.failed if replaced else QuizSetStatus.preparing)


def test_a_retry_bumps_the_heartbeat_before_it_is_scheduled(
    db_session: Session,
    scope: Any,
    setup: tuple[Artifact, User],
    monkeypatch: pytest.MonkeyPatch,
    retries: list[dict[str, Any]],
) -> None:
    artifact, user = setup
    chat = FakeChat(TransientProviderError("rate limited"))

    def age_it() -> None:  # the chat call took a long time
        [qs] = _sets(db_session, artifact, user)
        _age_heartbeat(db_session, qs.id, 6)

    chat.on_query = age_it

    with pytest.raises(Retry):
        _run(monkeypatch, chat, artifact, user)

    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.preparing
    assert qs.heartbeat_at is not None and qs.heartbeat_at > _ago(1)
    assert len(retries) == 1


def test_a_resumed_retry_bumps_the_heartbeat(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    qs = _preparing(db_session, artifact, user, created_at=_ago(30), heartbeat_at=_ago(9))
    beats: list[dt.datetime | None] = []
    chat = FakeChat(answer([mcq() for _ in range(10)]))
    chat.on_query = lambda: beats.append(_heartbeat_of(db_session, qs.id))

    assert _run(monkeypatch, chat, artifact, user, set_id=str(qs.id), retries=3) == "ready"

    [beat] = beats
    assert beat is not None and beat > _ago(1)


def test_each_chat_round_bumps_the_heartbeat(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    chat = FakeChat(answer([mcq() for _ in range(6)]), answer([mcq() for _ in range(4)]))
    beats: list[dt.datetime | None] = []

    def round_one() -> None:
        [qs] = _sets(db_session, artifact, user)
        beats.append(qs.heartbeat_at)
        _age_heartbeat(db_session, qs.id, 6)  # round 1 took a while
        chat.on_query = lambda: beats.append(_heartbeat_of(db_session, qs.id))

    chat.on_query = round_one

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    assert len(beats) == 2
    assert all(b is not None and b > _ago(1) for b in beats)


def test_a_live_task_whose_set_was_replaced_does_not_touch_the_replacement(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow task's set goes silent past STALE_AFTER and the next enqueue replaces it;
    when the slow task wakes up it stops without asking chat again or writing anything."""
    artifact, user = setup
    replacement = [mcq() for _ in range(10)]
    slow = FakeChat(answer([mcq() for _ in range(6)]), answer([mcq() for _ in range(4)]))
    inner: list[str] = []

    def replaced_meanwhile() -> None:
        [qs] = _sets(db_session, artifact, user)
        _age_heartbeat(db_session, qs.id, _stale_minutes())
        inner.append(_run(monkeypatch, FakeChat(answer(replacement)), artifact, user))

    slow.on_query = replaced_meanwhile

    assert _run(monkeypatch, slow, artifact, user) == "superseded"

    assert inner == ["ready"]
    assert len(slow.prompts) == 1  # the re-ask was never sent
    by_status = {qs.status: qs for qs in _sets(db_session, artifact, user)}
    assert set(by_status) == {QuizSetStatus.failed, QuizSetStatus.ready}
    assert [q["question"] for q in by_status[QuizSetStatus.ready].questions] == [
        q["question"] for q in replacement
    ]
    assert "abandoned" in by_status[QuizSetStatus.failed].validation_report["error"]


def test_a_live_task_whose_set_was_replaced_does_not_retry(
    db_session: Session,
    scope: Any,
    setup: tuple[Artifact, User],
    monkeypatch: pytest.MonkeyPatch,
    retries: list[dict[str, Any]],
) -> None:
    artifact, user = setup
    chat = FakeChat(TransientProviderError("rate limited"))
    inner: list[str] = []

    def replaced_meanwhile() -> None:
        [qs] = _sets(db_session, artifact, user)
        _age_heartbeat(db_session, qs.id, _stale_minutes())
        inner.append(
            _run(monkeypatch, FakeChat(answer([mcq() for _ in range(10)])), artifact, user)
        )

    chat.on_query = replaced_meanwhile

    assert _run(monkeypatch, chat, artifact, user) == "superseded"

    assert inner == ["ready"]
    assert retries == []
    statuses = sorted(qs.status.value for qs in _sets(db_session, artifact, user))
    assert statuses == ["failed", "ready"]


# -- worst cases (review 2026-10-29, section B 28/29) --------------------------------
def test_a_redelivered_message_while_the_set_is_preparing_does_nothing(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """worker-quiz killed mid-preparation: the broker redelivers the original message
    (no set id). The set still beats (or isn't stale yet): "exists", no chat query."""
    artifact, user = setup
    chat = FakeChat(answer([mcq() for _ in range(10)]))

    def redelivered() -> None:
        assert _run(monkeypatch, FakeChat(), artifact, user) == "exists"

    chat.on_query = redelivered
    assert _run(monkeypatch, chat, artifact, user) == "ready"
    assert len(chat.prompts) == 1
    assert [s.status for s in _sets(db_session, artifact, user)] == [QuizSetStatus.ready]


def test_after_a_republish_the_next_preparation_follows_the_new_studio_count(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The admin redoes and republishes the quiz while a student retakes: the ready set
    is still served; the next preparation asks for the new Studio count."""
    artifact, user = setup
    assert (
        _run(monkeypatch, FakeChat(answer([mcq() for _ in range(10)])), artifact, user) == "ready"
    )
    [ready] = _sets(db_session, artifact, user)

    v2 = ArtifactVersion(
        artifact_id=artifact.id, revision=2, content_json={"questions": [mcq() for _ in range(4)]}
    )
    db_session.add(v2)
    db_session.flush()
    artifact.published_version_id = v2.id
    ready.status = QuizSetStatus.used  # the student took it
    db_session.commit()

    chat = FakeChat(answer([mcq() for _ in range(6)]))
    assert _run(monkeypatch, chat, artifact, user) == "ready"
    assert "Create 4 NEW quiz questions" in chat.prompts[0]
    newest = [s for s in _sets(db_session, artifact, user) if s.status is QuizSetStatus.ready]
    assert len(newest) == 1 and len(newest[0].questions) == 4


# -- language and difficulty: the admin's choice for the quiz (owner decision 2026-10-29) --


def _set_options(db: Session, artifact: Artifact, **options: str) -> None:
    artifact.generation_options = {"quantity": "standard", **options}
    db.commit()


def test_the_prompt_asks_for_the_quiz_language_and_difficulty(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    _set_options(db_session, artifact, language="ta", difficulty="hard")
    chat = FakeChat(answer([bad(), *[mcq() for _ in range(9)]]), answer([mcq()]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    assert len(chat.prompts) == 2  # the re-ask is in the same language and difficulty
    for prompt in chat.prompts:
        assert "explanation in Tamil" in prompt
        assert "difficulty: hard" in prompt
        assert "never translate it into Tamil" in prompt
    [qs] = _sets(db_session, artifact, user)
    assert qs.validation_report["prepared_for"] == {"language": "ta", "difficulty": "hard"}


def test_default_options_prepare_english_medium(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    assert artifact.generation_options == {}
    chat = FakeChat(answer([mcq() for _ in range(10)]))
    assert _run(monkeypatch, chat, artifact, user) == "ready"
    assert "explanation in English" in chat.prompts[0]
    assert "difficulty: medium" in chat.prompts[0]
    [qs] = _sets(db_session, artifact, user)
    assert qs.validation_report["prepared_for"] == EN["prepared_for"]


@pytest.mark.parametrize("status", [QuizSetStatus.ready, QuizSetStatus.preparing])
@pytest.mark.parametrize(
    "report",
    [{}, EN, {"prepared_for": {"language": "ta", "difficulty": "medium"}}],
    ids=["unrecorded", "english", "tamil-medium"],
)
def test_a_pending_set_for_another_language_or_difficulty_is_replaced(
    status: QuizSetStatus,
    report: dict[str, Any],
    db_session: Session,
    scope: Any,
    setup: tuple[Artifact, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sets prepared before the admin chose Tamil / hard (or before sets recorded what they
    were prepared for) are discarded and a new one is prepared."""
    artifact, user = setup
    _set_options(db_session, artifact, language="ta", difficulty="hard")
    old = QuizQuestionSet(
        artifact_id=artifact.id,
        user_id=user.id,
        source=QuizSetSource.chat,
        status=status,
        questions=[mcq() for _ in range(10)] if status is QuizSetStatus.ready else [],
        validation_report=report,
        heartbeat_at=_ago(0),
    )
    db_session.add(old)
    db_session.commit()
    chat = FakeChat(answer([mcq() for _ in range(10)]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    by_status = {qs.status: qs for qs in _sets(db_session, artifact, user)}
    assert set(by_status) == {QuizSetStatus.failed, QuizSetStatus.ready}
    discarded = by_status[QuizSetStatus.failed]
    assert discarded.id == old.id
    assert discarded.validation_report["discarded"] is True
    assert "the quiz is now ta/hard" in discarded.validation_report["error"]
    assert by_status[QuizSetStatus.ready].validation_report["prepared_for"] == {
        "language": "ta",
        "difficulty": "hard",
    }
    assert "explanation in Tamil" in chat.prompts[0]


def test_a_matching_pending_set_is_kept(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    _set_options(db_session, artifact, language="hi", difficulty="easy")
    db_session.add(
        QuizQuestionSet(
            artifact_id=artifact.id,
            user_id=user.id,
            source=QuizSetSource.chat,
            status=QuizSetStatus.ready,
            questions=[mcq() for _ in range(10)],
            validation_report={"prepared_for": {"language": "hi", "difficulty": "easy"}},
        )
    )
    db_session.commit()
    chat = FakeChat()
    assert _run(monkeypatch, chat, artifact, user) == "exists"
    assert chat.prompts == []


def test_a_retry_after_the_language_changed_prepares_a_new_set(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact, user = setup
    old = _preparing(db_session, artifact, user, heartbeat_at=_ago(0))
    _set_options(db_session, artifact, language="te", difficulty="medium")
    chat = FakeChat(answer([mcq() for _ in range(10)]))

    assert _run(monkeypatch, chat, artifact, user, set_id=str(old.id), retries=1) == "ready"

    db_session.refresh(old)
    assert old.status is QuizSetStatus.failed and old.validation_report["discarded"] is True
    assert "explanation in Telugu" in chat.prompts[0]


def test_a_live_task_whose_set_was_discarded_for_a_new_language_writes_nothing(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The admin switches the quiz to Marathi while chat is answering in English: the
    student API discards the set; the task's result is thrown away ("superseded")."""
    artifact, user = setup
    chat = FakeChat(answer([mcq() for _ in range(10)]))

    def switch() -> None:
        with scope() as db:
            a = db.get(Artifact, artifact.id)
            assert a is not None
            a.generation_options = {"language": "mr", "difficulty": "medium"}
            db.flush()
            assert quiz.discard_stale_sets(db, a, user.id) == 1

    chat.on_query = switch
    assert _run(monkeypatch, chat, artifact, user) == "superseded"
    [qs] = _sets(db_session, artifact, user)
    assert qs.status is QuizSetStatus.failed and qs.questions == []
    assert qs.validation_report["discarded"] is True


def test_fixture_chat_answers_in_the_quiz_language(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end with the fixture provider's `[fixture:quiz=N]` chat: a Tamil quiz's
    fresh set is in Tamil, its proof quotes stay the English source sentences."""
    from app.pipeline.fixture import FixtureProvider

    artifact, user = setup
    artifact.module.notebooklm_notebook_id = "fixture-nb-m-fixture-quiz-10"
    _set_options(db_session, artifact, language="ta", difficulty="easy")
    provider = FixtureProvider()
    monkeypatch.setattr(quiz, "get_content_provider", lambda: provider)
    task = quiz.prepare_quiz_set
    task.push_request(retries=0)
    try:
        assert task.run(artifact_id=str(artifact.id), user_id=str(user.id)) == "ready"
    finally:
        task.pop_request()
    [qs] = _sets(db_session, artifact, user)
    assert len(qs.questions) == 10
    for q in qs.questions:
        assert "வர்க்கம்" in q["question"]
        assert q["source_quote"].startswith("In the fixture notes")


def test_a_queued_redo_in_another_language_does_not_change_the_prepared_set(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retakes follow the PUBLISHED version's options (owner decision 2026-10-30): the
    artifact's options already say Tamil (a Redo is queued), the published version was
    made in English, so the set is prepared in English."""
    artifact, user = setup
    published = db_session.get(ArtifactVersion, artifact.published_version_id)
    assert published is not None
    published.generation_options = {"quantity": "standard", "language": "en", "difficulty": "easy"}
    _set_options(db_session, artifact, language="ta", difficulty="hard")
    chat = FakeChat(answer([mcq() for _ in range(10)]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    assert "explanation in English" in chat.prompts[0]
    assert "difficulty: easy" in chat.prompts[0]
    [qs] = _sets(db_session, artifact, user)
    assert qs.validation_report["prepared_for"] == {"language": "en", "difficulty": "easy"}


def test_a_pdf_module_with_an_unreadable_pdf_keeps_unfound_quotes_and_flags_them(
    db_session: Session, scope: Any, setup: tuple[Artifact, User], monkeypatch: pytest.MonkeyPatch
) -> None:
    """PR #2 review finding 2: one of the module's PDFs could not be read, so the text is
    incomplete. A quote not found in it may be in the unreadable PDF: the question is kept,
    flagged "quote not verified", and the report names the unreadable file."""
    artifact, user = setup
    artifact.module.source_url = None  # PDF-only module
    artifact.module.source_type = ModuleSourceType.pdf
    db_session.commit()
    quote = "the reaction proceeds through a planar carbocation intermediate"
    monkeypatch.setattr(
        qg,
        "read_module_source_text",
        lambda _m: qg.SourceText(f"Notes. {quote}. End.", ("chapter-2.pdf",)),
    )
    from_readable = [{**mcq(), "source_quote": quote} for _ in range(4)]
    from_unreadable = {**mcq(), "source_quote": "a sentence only in the second chapter"}
    no_quote = {**mcq(), "source_quote": ""}
    chat = FakeChat(answer([*from_readable, from_unreadable, no_quote]), answer([]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    [qs] = _sets(db_session, artifact, user)
    assert len(qs.questions) == 5
    assert qs.validation_report["unreadable_pdfs"] == ["chapter-2.pdf"]
    first = qs.validation_report["rounds"][0]
    [flag] = first["unverified"]
    assert flag["question"] == from_unreadable["question"]
    assert flag["reason"] == "quote not verified (some PDFs could not be read)"
    [dropped] = first["dropped"]  # a missing quote is still dropped
    assert dropped["reason"] == "quote: missing"


def test_seen_questions_dedup_keeps_order_on_a_large_history(
    db_session: Session, setup: tuple[Artifact, User]
) -> None:
    """PR #2 review finding 10: order-preserving dedup with a set (a long history with
    repeats is listed once each, most recent first, quickly)."""
    import time

    artifact, user = setup
    now = dt.datetime.now(tz=dt.UTC)
    pool = [mcq() for _ in range(3000)]
    newer, older = pool[:2000], pool[1000:]  # 1000 questions repeated across the two
    for i, questions in enumerate([older, newer]):
        db_session.add(
            QuizQuestionSet(
                artifact_id=artifact.id,
                user_id=user.id,
                source=QuizSetSource.chat,
                status=QuizSetStatus.used,
                questions=questions,
                created_at=now - dt.timedelta(days=2 - i),
            )
        )
    db_session.commit()

    start = time.perf_counter()
    seen = quiz.seen_questions(db_session, artifact, user.id)
    elapsed = time.perf_counter() - start

    studio = [q["question"] for q in quiz.studio_questions(artifact)]
    assert seen == [q["question"] for q in pool] + studio
    assert elapsed < 1.0
