"""`FixtureProvider` — a deterministic `ContentProvider` backed by canned files.

Used for every dev run and all of CI (`CONTENT_PROVIDER=fixture`, the default),
so the whole pipeline is exercisable without a Google account or the MCP
container. Generation is instant: `poll` always returns `ready`.

Fault injection (worst-case E2E/integration tests)
--------------------------------------------------
Only with `CONTENT_PROVIDER=fixture` (this provider is never used otherwise; the
typeset hook checks the setting). Put a marker in the **module title**, e.g.
"Week 1 [fixture:slow=20]". The title becomes the notebook id
(`fixture-nb-<slug>`), so every later call of that module's jobs sees it, in any
worker process. Several markers may be combined. A module without markers
behaves exactly as before.

- `[fixture:fail-generate]`: generation is rejected (permanent `ProviderError`):
  every artifact errors, Retry fails again.
- `[fixture:transient-generate]`: generation fails as transient
  (`TransientProviderError`): Celery retries 3 times, then the artifact errors.
- `[fixture:studio-failed]`: NotebookLM reports the generation failed (Retry
  generates a new one).
- `[fixture:slow=N]`: artifacts stay "Generating…" for N seconds, then ready.
- `[fixture:stuck]`: artifacts stay pending until the job times out
  (`MCP_TIMEOUT_TEXT_SEC` / `_AUDIO_`): exercises Cancel and the reaper.
- `[fixture:malformed]`: NotebookLM's output can't be parsed
  (`ArtifactParseError`): the card errors, Retry generates again (decision 6).
- `[fixture:source-fail]`: NotebookLM reports the module's sources failed (§8
  "NotebookLM couldn't read …").
- `[fixture:chat-fail]`: quiz chat is rejected (permanent): a fresh retake set
  fails at once ("not available right now").
- `[fixture:quiz=N]`: the Studio quiz has N questions (1-30) and chat draws from
  a pool of 60 questions, skipping any it is told to avoid, so many retakes work
  (a link-only module: the pool's quotes aren't in an uploaded PDF). The questions are
  written in the language the prompt asks for (the quiz's language option).
- `[fixture:typeset-down]`: the typeset service counts as unavailable for this
  module's PDFs (retried with back-off, then "gave up"; the artifact stays ready).

Counted faults, for recovery scenarios: `[fixture:<fault>=N]` hits only the first
N attempts, then everything works. Attempts are counted in Redis (shared by every
worker, kept a day) per notebook and artifact type for `fail-generate`,
`transient-generate`, `studio-failed`, `stuck` and `malformed` (each `generate` is
an attempt; a resumed job keeps its attempt, so `stuck=1` stays stuck on Retry
but a Redo generates anew); per notebook for `chat-fail` (each chat call); per
artifact version for `typeset-down` (each PDF task attempt). E.g.
`[fixture:transient-generate=1]` recovers on Celery's first retry,
`[fixture:typeset-down=1]` builds the PDF on the task's first retry (30 s).
`source-fail` takes no count.
"""

from __future__ import annotations

import datetime as dt
import html as html_lib
import json
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.models.enums import ArtifactType
from app.pipeline.provider import (
    NotebookRef,
    ProviderError,
    ProviderHealth,
    RawArtifact,
    SourceRef,
    SourceState,
    StudioJobRef,
    StudioStatus,
    TransientProviderError,
)

log = get_logger("fixture")

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
DEFAULT_FIXTURE_ID = "sample-neural-nets"


_FIXTURE_FACTS = [
    "Paris is the capital and largest city of France.",
    "Mars is often called the Red Planet because of its iron oxide dust.",
    "A hexagon is a polygon that has exactly six sides.",
    "Plants absorb carbon dioxide from the air during photosynthesis.",
    "Water is a molecule made of two hydrogen atoms and one oxygen atom.",
    "The chemical symbol for the element gold is Au.",
    "A triangle is a polygon with three sides and three angles.",
]
#: stands in for a module's PDF text: every fixture source_quote is a sentence of it
FIXTURE_SOURCE_TEXT = "Fixture course notes. " + " ".join(_FIXTURE_FACTS) + " End of notes."


def _fixture_chat_answer() -> str:
    """A canned chat answer: prose around a JSON array of 4 MCQ + 3 fill-blank questions
    (7 distinct questions). Each `source_quote` is a sentence of `FIXTURE_SOURCE_TEXT`, so it
    validates fully with that text and with `source_text=None`."""
    mcq = [
        ("What is the capital of France?", ["Paris", "Lyon", "Nice", "Lille"], 0),
        ("Which planet is known as the Red Planet?", ["Venus", "Mars", "Jupiter", "Saturn"], 1),
        ("How many sides does a hexagon have?", ["Five", "Six", "Seven", "Eight"], 1),
        (
            "Which gas do plants absorb for photosynthesis?",
            ["Oxygen", "Nitrogen", "Carbon dioxide", "Helium"],
            2,
        ),
    ]
    blanks = [
        ("Water is made of hydrogen and ____.", "oxygen", ["Oxygen"]),
        ("The chemical symbol for gold is ____.", "Au", []),
        ("A triangle has ____ sides.", "three", ["3"]),
    ]
    items: list[dict[str, Any]] = [
        {
            "type": "mcq",
            "question": q,
            "options": opts,
            "correct_index": ci,
            "explanation": f"The answer is {opts[ci]}.",
            "source_quote": _FIXTURE_FACTS[i],
        }
        for i, (q, opts, ci) in enumerate(mcq)
    ]
    items += [
        {
            "type": "fill_blank",
            "question": q,
            "answer": a,
            "accepted_answers": acc,
            "explanation": f"The answer is {a}.",
            "source_quote": _FIXTURE_FACTS[len(mcq) + j],
        }
        for j, (q, a, acc) in enumerate(blanks)
    ]
    return "Here are your questions:\n" + json.dumps(items, indent=2)


FIXTURE_CHAT_ANSWER = _fixture_chat_answer()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "untitled"


# -- fault injection (see the module docstring) ---------------------------------------
_FLAGS = (
    "fail-generate",
    "transient-generate",
    "studio-failed",
    "stuck",
    "malformed",
    "source-fail",
    "chat-fail",
    "typeset-down",
)
#: a marker as it appears in a title, and once slugified into a notebook id
_TITLE_MARKER = re.compile(r"\[fixture:([a-z-]+)(?:=(\d+))?\]", re.IGNORECASE)
_SLUG_MARKER = re.compile(r"(?:^|-)fixture-(" + "|".join(_FLAGS) + r"|slow|quiz)(?:-(\d+))?(?=-|$)")
_MAX_QUIZ = 30


@dataclass(frozen=True)
class Faults:
    flags: frozenset[str] = frozenset()
    slow_sec: int = 0
    quiz: int = 0
    #: (flag, N) for counted faults `[fixture:<flag>=N]`
    counted: frozenset[tuple[str, int]] = frozenset()

    @property
    def any(self) -> bool:
        return bool(self.flags or self.slow_sec or self.quiz)

    def limit(self, flag: str) -> int | None:
        """N for `[fixture:<flag>=N]`; None when the fault always applies (or is absent)."""
        return next((n for f, n in self.counted if f == flag), None)

    def hits(self, flag: str, attempt: int | None) -> bool:
        """Whether `flag` applies to this attempt (1-based; None = not counted)."""
        if flag not in self.flags:
            return False
        n = self.limit(flag)
        return n is None or (attempt is not None and attempt <= n)


def _faults(pairs: list[tuple[str, str]]) -> Faults:
    flags: set[str] = set()
    counted: set[tuple[str, int]] = set()
    slow = quiz = 0
    for name, value in pairs:
        name = name.lower()
        if name in _FLAGS:
            flags.add(name)
            if value:
                counted.add((name, int(value)))
        elif name == "slow" and value:
            slow = int(value)
        elif name == "quiz" and value:
            quiz = max(1, min(_MAX_QUIZ, int(value)))
    return Faults(flags=frozenset(flags), slow_sec=slow, quiz=quiz, counted=frozenset(counted))


#: flags whose count follows the generation (`generate` → job id → poll/fetch)
_PER_GENERATION = ("fail-generate", "transient-generate", "studio-failed", "stuck", "malformed")
_ATTEMPT_IN_JOB = re.compile(r"-a(\d+)(?:-t\d+)?$")
_COUNT_TTL_SEC = 86400


@lru_cache(maxsize=1)
def _counter_client() -> Any:
    import redis

    from app.config import get_settings

    return redis.Redis.from_url(get_settings().redis_url)


def _count(key: str) -> int:
    """This attempt's number (1, 2, …) for `key`, shared by every worker process."""
    pipe = _counter_client().pipeline()
    pipe.incr(key)
    pipe.expire(key, _COUNT_TTL_SEC)
    n, _ = pipe.execute()
    return int(n)


def _job_attempt(job_id: str) -> int | None:
    m = _ATTEMPT_IN_JOB.search(job_id)
    return int(m.group(1)) if m else None


def faults_in_title(title: str) -> Faults:
    """The fault markers in a module title."""
    return _faults(_TITLE_MARKER.findall(title))


def faults_of(notebook_id: str) -> Faults:
    """The fault markers carried by a fixture notebook id (the slugified title)."""
    if not notebook_id.startswith("fixture-nb-"):
        return Faults()
    return _faults(_SLUG_MARKER.findall(notebook_id.removeprefix("fixture-nb-")))


def typeset_down(module_title: str, version_id: str = "") -> bool:
    """The `[fixture:typeset-down]` hook for the PDF task: only with the fixture
    provider. Each call is one attempt of `version_id`'s PDF task."""
    from app.config import get_settings

    if get_settings().content_provider != "fixture":
        return False
    faults = faults_in_title(module_title)
    if "typeset-down" not in faults.flags:
        return False
    attempt = None
    if faults.limit("typeset-down") is not None:
        attempt = _count(f"fixture:typeset:{_slug(module_title)}:{version_id}")
    return faults.hits("typeset-down", attempt)


#: chat questions for `[fixture:quiz=N]`: numbers 10-69 (two digits each, so no two are
#: near-duplicates); the Studio quiz uses 70-99
_POOL = range(10, 70)
_STUDIO = range(70, 100)


#: the pool's question texts in the quiz languages (mcq, fill-blank, explanation); the proof
#: quote stays the English fixture sentence, as the prompt asks (verbatim from the source)
_POOL_TEXTS: dict[str, tuple[str, str, str]] = {
    "English": (
        "What is {i} squared, per the fixture notes?",
        "In the fixture notes, {i} squared is ____.",
        "In the fixture notes, the number {i} squared is {sq}.",
    ),
    "Hindi": (
        "फ़िक्स्चर नोट्स के अनुसार {i} का वर्ग क्या है?",
        "फ़िक्स्चर नोट्स में {i} का वर्ग ____ है।",
        "फ़िक्स्चर नोट्स में {i} का वर्ग {sq} है।",
    ),
    "Marathi": (
        "फिक्स्चर नोट्सनुसार {i} चा वर्ग किती आहे?",
        "फिक्स्चर नोट्समध्ये {i} चा वर्ग ____ आहे.",
        "फिक्स्चर नोट्समध्ये {i} चा वर्ग {sq} आहे.",
    ),
    "Tamil": (
        "ஃபிக்ஸ்சர் குறிப்புகளின்படி {i} இன் வர்க்கம் என்ன?",
        "ஃபிக்ஸ்சர் குறிப்புகளில் {i} இன் வர்க்கம் ____ ஆகும்.",
        "ஃபிக்ஸ்சர் குறிப்புகளில் {i} இன் வர்க்கம் {sq} ஆகும்.",
    ),
    "Telugu": (
        "ఫిక్స్చర్ నోట్స్ ప్రకారం {i} యొక్క వర్గం ఎంత?",
        "ఫిక్స్చర్ నోట్స్‌లో {i} యొక్క వర్గం ____.",
        "ఫిక్స్చర్ నోట్స్‌లో {i} యొక్క వర్గం {sq}.",
    ),
    "Kannada": (
        "ಫಿಕ್ಸ್ಚರ್ ಟಿಪ್ಪಣಿಗಳ ಪ್ರಕಾರ {i} ರ ವರ್ಗ ಎಷ್ಟು?",
        "ಫಿಕ್ಸ್ಚರ್ ಟಿಪ್ಪಣಿಗಳಲ್ಲಿ {i} ರ ವರ್ಗ ____ ಆಗಿದೆ.",
        "ಫಿಕ್ಸ್ಚರ್ ಟಿಪ್ಪಣಿಗಳಲ್ಲಿ {i} ರ ವರ್ಗ {sq} ಆಗಿದೆ.",
    ),
}
_LANGUAGE_ASKED = re.compile(r"accepted answer and explanation in (\w+),")


def _pool_question(i: int, language: str = "English") -> dict[str, Any]:
    ask, blank, explain = _POOL_TEXTS.get(language, _POOL_TEXTS["English"])
    fact = f"In the fixture notes, the number {i} squared is {i * i}."
    explanation = explain.format(i=i, sq=i * i)
    if i % 5 == 0:
        return {
            "type": "fill_blank",
            "question": blank.format(i=i),
            "answer": str(i * i),
            "accepted_answers": [],
            "explanation": explanation,
            "source_quote": fact,
        }
    options = [str(i * i + d) for d in (0, 1, 2, 3)]
    shift = i % 4
    options = options[shift:] + options[:shift]
    return {
        "type": "mcq",
        "question": ask.format(i=i),
        "options": options,
        "correct_index": options.index(str(i * i)),
        "explanation": explanation,
        "source_quote": fact,
    }


def _chat_answer(prompt: str) -> str:
    """`[fixture:quiz=N]` chat: N pool questions not in the prompt's avoid list, written in
    the language the prompt asks for (English, Hindi, Marathi, Tamil, Telugu, Kannada)."""
    wanted = re.search(r"Create (\d+) NEW", prompt)
    n = int(wanted.group(1)) if wanted else 10
    asked = _LANGUAGE_ASKED.search(prompt)
    language = asked.group(1) if asked else "English"
    pool = (_pool_question(i, language) for i in _POOL)
    fresh = [q for q in pool if q["question"] not in prompt]
    return "Here are your questions:\n" + json.dumps(fresh[:n], ensure_ascii=False, indent=2)


def _studio_quiz_html(n: int) -> str:
    blocks = []
    for i in list(_STUDIO)[:n]:
        options = [str(2 * i + d) for d in (0, 1, 2, 3)]
        items = "".join(f"<li>{html_lib.escape(o)}</li>" for o in options)
        blocks.append(
            '<div class="question">'
            f'<p class="prompt">What is {i} doubled, per the fixture notes?</p>'
            f'<ol class="options">{items}</ol>'
            '<p class="answer" data-correct-index="0">1</p>'
            f'<p class="explanation">{i} doubled is {2 * i}.</p>'
            "</div>"
        )
    return f'<div class="studio-artifact" data-type="quiz">{"".join(blocks)}</div>'


_MALFORMED_HTML = '<div class="studio-artifact"></div>'


class _FailedStates(dict[str, SourceState]):
    """`[fixture:source-fail]`: every fixture source failed."""

    def get(self, key: str, default: Any = None) -> Any:
        return SourceState.failed if key.startswith("fixture-") else default


class _FixtureStates(dict[str, SourceState]):
    """Source states where any `fixture-` id counts as ready.

    Each job builds a fresh `FixtureProvider`, so a resumed run must still see
    ids an earlier instance handed out.
    """

    def get(self, key: str, default: Any = None) -> Any:
        if key in self:
            return self[key]
        return SourceState.ready if key.startswith("fixture-") else default


class FixtureProvider:
    def __init__(
        self,
        fixture_id: str = DEFAULT_FIXTURE_ID,
        *,
        fixtures_dir: Path | None = None,
    ) -> None:
        self.fixture_id = fixture_id
        self._dir = (fixtures_dir or _FIXTURES_DIR) / fixture_id
        if not self._dir.is_dir():
            raise FileNotFoundError(f"fixture set not found: {self._dir}")
        #: calls tests may assert on, e.g. ("add_file_source", notebook_id, path, name)
        self.calls: list[tuple[Any, ...]] = []
        self._source_ids: dict[str, list[str]] = {}

    # -- ContentProvider ---------------------------------------------------

    def create_notebook(self, title: str) -> NotebookRef:
        return NotebookRef(notebook_id=f"fixture-nb-{_slug(title)}")

    def add_source(self, nb: NotebookRef, url: str) -> SourceRef:
        ref = SourceRef(source_id=f"fixture-src-{_slug(url)[:40]}")
        self._remember(nb, ref)
        return ref

    def add_file_source(self, nb: NotebookRef, path: str, display_name: str) -> SourceRef:
        self.calls.append(("add_file_source", nb.notebook_id, path, display_name))
        ref = SourceRef(source_id=f"fixture-file-{_slug(display_name)}")
        self._remember(nb, ref)
        return ref

    def source_statuses(self, nb: NotebookRef) -> dict[str, SourceState]:
        if "source-fail" in faults_of(nb.notebook_id).flags:
            return _FailedStates()
        return _FixtureStates(
            {sid: SourceState.ready for sid in self._source_ids.get(nb.notebook_id, [])}
        )

    def generate(
        self,
        nb: NotebookRef,
        kind: ArtifactType,
        focus_prompt: str,
        options: dict[str, Any],
    ) -> StudioJobRef:
        faults = faults_of(nb.notebook_id)
        attempt = None
        if any(faults.limit(f) is not None for f in _PER_GENERATION):
            attempt = _count(f"fixture:generate:{nb.notebook_id}:{kind.value}")
        if faults.hits("fail-generate", attempt):
            raise ProviderError("fixture: NotebookLM rejected the generation")
        if faults.hits("transient-generate", attempt):
            raise TransientProviderError("fixture: NotebookLM is unavailable")
        job_id = f"fixture-job-{nb.notebook_id}-{kind.value}"
        if attempt is not None:
            job_id += f"-a{attempt}"
        if faults.slow_sec:
            job_id += f"-t{int(time.time())}"  # when it "started", for `poll`
        return StudioJobRef(job_id=job_id, notebook_id=nb.notebook_id, kind=kind)

    def poll(self, job: StudioJobRef) -> StudioStatus:
        faults = faults_of(job.notebook_id)
        attempt = _job_attempt(job.job_id)
        if faults.hits("studio-failed", attempt):
            return StudioStatus.failed
        if faults.hits("stuck", attempt):
            return StudioStatus.pending
        if faults.slow_sec:
            started = re.search(r"-t(\d+)$", job.job_id)
            if started and time.time() - int(started.group(1)) < faults.slow_sec:
                return StudioStatus.pending
        return StudioStatus.ready

    def fetch_content(self, job: StudioJobRef) -> RawArtifact:
        faults = faults_of(job.notebook_id)
        extras: dict[str, Any] = {"artifact_id": job.job_id}
        if faults.hits("malformed", _job_attempt(job.job_id)):
            return RawArtifact(html=_MALFORMED_HTML, extras=extras)
        if faults.quiz and job.kind is ArtifactType.quiz:
            return RawArtifact(html=_studio_quiz_html(faults.quiz), extras=extras)
        html = self._read_text(f"{job.kind.value}.html")
        if job.kind is ArtifactType.infographic:
            extras["mind_map_tree"] = json.loads(self._read_text("infographic.mind_map.json"))
        return RawArtifact(html=html, extras=extras)

    def fetch_binary(self, job: StudioJobRef, kind: ArtifactType) -> bytes | None:
        if kind is ArtifactType.audio_overview:
            return (self._dir / "audio_overview.mp3").read_bytes()
        # Infographic image is rendered by us from structure (D15); nothing to fetch.
        return None

    def download(self, url: str) -> tuple[bytes, str]:
        # Fixture content is self-contained; it never hands out media URLs.
        raise ProviderError(f"FixtureProvider has no remote media ({url})")

    def outline_action(self, job: StudioJobRef, feedback: str | None) -> None:
        # Fixture generations finish immediately; they never wait for an outline.
        raise ProviderError("FixtureProvider has no slide outline to review")

    def query(self, nb: NotebookRef, text: str) -> str:
        self.calls.append(("query", nb.notebook_id, text))
        faults = faults_of(nb.notebook_id)
        attempt = None
        if faults.limit("chat-fail") is not None:
            attempt = _count(f"fixture:chat:{nb.notebook_id}")
        if faults.hits("chat-fail", attempt):
            raise ProviderError("fixture: chat rejected the question")
        if faults.quiz:
            return _chat_answer(text)
        return FIXTURE_CHAT_ANSWER

    def delete_notebook(self, nb: NotebookRef) -> None:
        # recorded for tests; logged so an E2E run can see it happened
        self.calls.append(("delete_notebook", nb.notebook_id))
        log.info("fixture.notebook_deleted", notebook_id=nb.notebook_id)

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            healthy=True,
            account_email="fixture@localhost",
            last_ok_at=dt.datetime.now(tz=dt.UTC),
            detail=f"FixtureProvider[{self.fixture_id}]",
        )

    def refresh_auth(self) -> None:
        return None

    # -- helpers ---------------------------------------------------------

    def _remember(self, nb: NotebookRef, ref: SourceRef) -> None:
        ids = self._source_ids.setdefault(nb.notebook_id, [])
        if ref.source_id not in ids:
            ids.append(ref.source_id)

    def _read_text(self, name: str) -> str:
        path = self._dir / name
        if not path.is_file():
            raise FileNotFoundError(f"fixture file missing: {path}")
        return path.read_text(encoding="utf-8")
