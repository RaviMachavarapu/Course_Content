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

    def unreadable(_: Module) -> str | None:
        raise SourceTextUnavailable("none of the module's 1 PDF(s) could be read")

    monkeypatch.setattr(qg, "module_source_text", unreadable)
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
    quote = "the reaction proceeds through a planar carbocation intermediate"
    monkeypatch.setattr(qg, "module_source_text", lambda _m: f"Notes. {quote}. End.")
    good = [{**mcq(), "source_quote": quote} for _ in range(5)]
    fabricated = {**mcq(), "source_quote": "a sentence that is nowhere in the module notes"}
    chat = FakeChat(answer([*good, fabricated]), answer([]))

    assert _run(monkeypatch, chat, artifact, user) == "ready"

    [qs] = _sets(db_session, artifact, user)
    assert len(qs.questions) == 5
    [dropped] = qs.validation_report["rounds"][0]["dropped"]
    assert dropped["reason"].startswith("quote:")


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
        assert quiz._insert_preparing(first, artifact.id, user.id) is not None

        def claim() -> None:
            got["second"] = quiz._insert_preparing(second, artifact.id, user.id)
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
