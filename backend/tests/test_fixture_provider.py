"""T015 — FixtureProvider + provider factory."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.models.enums import ARTIFACT_TYPES, ArtifactType
from app.pipeline.factory import get_content_provider
from app.pipeline.fixture import FixtureProvider
from app.pipeline.provider import ContentProvider, SourceState, StudioStatus


@pytest.fixture
def provider() -> FixtureProvider:
    return FixtureProvider()


def test_satisfies_the_protocol(provider: FixtureProvider) -> None:
    assert isinstance(provider, ContentProvider)


def test_create_notebook_and_add_source_are_deterministic(provider: FixtureProvider) -> None:
    nb = provider.create_notebook("Neural Networks 101")
    assert nb == provider.create_notebook("Neural Networks 101")
    assert nb.notebook_id == "fixture-nb-neural-networks-101"
    src = provider.add_source(nb, "https://youtu.be/abc")
    assert src.source_id.startswith("fixture-src-")


def test_generate_then_poll_is_ready(provider: FixtureProvider) -> None:
    nb = provider.create_notebook("t")
    job = provider.generate(nb, ArtifactType.quiz, "focus", {})
    assert job.kind is ArtifactType.quiz
    assert job.notebook_id == nb.notebook_id
    assert provider.poll(job) is StudioStatus.ready


@pytest.mark.parametrize("kind", ARTIFACT_TYPES)
def test_fetch_content_returns_html_for_every_type(
    provider: FixtureProvider, kind: ArtifactType
) -> None:
    nb = provider.create_notebook("t")
    raw = provider.fetch_content(provider.generate(nb, kind, "", {}))
    assert f'data-type="{kind.value}"' in raw.html
    assert raw.extras["artifact_id"]
    if kind is ArtifactType.infographic:
        assert raw.extras["mind_map_tree"]["label"] == "Neural Network"


def test_fetch_binary_only_for_audio(provider: FixtureProvider) -> None:
    nb = provider.create_notebook("t")
    audio_job = provider.generate(nb, ArtifactType.audio_overview, "", {})
    mp3 = provider.fetch_binary(audio_job, ArtifactType.audio_overview)
    assert mp3 is not None and mp3[:3] == b"ID3" and len(mp3) > 1000

    info_job = provider.generate(nb, ArtifactType.infographic, "", {})
    assert provider.fetch_binary(info_job, ArtifactType.infographic) is None


def test_health_and_refresh_auth(provider: FixtureProvider) -> None:
    health = provider.health()
    assert health.healthy is True
    assert health.account_email == "fixture@localhost"
    assert health.last_ok_at is not None
    assert provider.refresh_auth() is None


def test_missing_fixture_set_raises() -> None:
    with pytest.raises(FileNotFoundError):
        FixtureProvider("does-not-exist")


def test_factory_selects_fixture_by_default() -> None:
    assert isinstance(get_content_provider(Settings(content_provider="fixture")), FixtureProvider)


def test_factory_selects_notebooklm_mcp_provider() -> None:
    from app.pipeline.notebooklm_mcp import NotebookLmMcpProvider

    provider = get_content_provider(Settings(content_provider="notebooklm"))
    assert isinstance(provider, NotebookLmMcpProvider)


def test_fixture_file_sources_are_ready(provider: FixtureProvider) -> None:
    nb = provider.create_notebook("Mixed")
    link = provider.add_source(nb, "https://youtu.be/abc")
    f = provider.add_file_source(nb, "/data/media/u/a.pdf", "My File.pdf")
    assert f.source_id == "fixture-file-my-file-pdf"
    assert provider.calls == [
        ("add_file_source", nb.notebook_id, "/data/media/u/a.pdf", "My File.pdf")
    ]
    assert provider.source_statuses(nb) == {
        link.source_id: SourceState.ready,
        f.source_id: SourceState.ready,
    }
    assert provider.source_statuses(provider.create_notebook("Other")) == {}


def test_fresh_provider_reports_ids_issued_by_another_instance_as_ready() -> None:
    issuer = FixtureProvider()
    nb = issuer.create_notebook("Resumed")
    ids = [
        issuer.add_source(nb, "https://youtu.be/abc").source_id,
        issuer.add_file_source(nb, "/tmp/book.pdf", "book.pdf (part 1 of 2)").source_id,
    ]
    fresh = FixtureProvider()
    states = fresh.source_statuses(nb)
    # the same lookup the source step uses
    assert [states.get(sid, SourceState.pending) for sid in ids] == [SourceState.ready] * 2
    assert states.get("not-a-fixture-id", SourceState.pending) is SourceState.pending


# -- fault injection (only CONTENT_PROVIDER=fixture) ---------------------------------
from app.pipeline import fixture as fx  # noqa: E402
from app.pipeline.provider import (  # noqa: E402
    NotebookRef,
    ProviderError,
    StudioJobRef,
    TransientProviderError,
)


def _nb(title: str) -> NotebookRef:
    return FixtureProvider().create_notebook(title)


def test_markers_survive_the_title_to_notebook_id_round_trip() -> None:
    nb = _nb("Week 1 [fixture:slow=20] [fixture:stuck] notes [fixture:quiz=12]")
    faults = fx.faults_of(nb.notebook_id)
    assert faults.flags == {"stuck"}
    assert (faults.slow_sec, faults.quiz) == (20, 12)
    assert fx.faults_in_title("Week 1 [fixture:slow=20] [fixture:stuck]") == fx.Faults(
        flags=frozenset({"stuck"}), slow_sec=20
    )
    assert not fx.faults_of(_nb("Week 1 about fixtures, slow learning").notebook_id).any
    assert not fx.faults_of("nb-real-notebooklm-id-fixture-stuck").any  # fixture ids only


def test_a_module_without_markers_behaves_as_before() -> None:
    p = FixtureProvider()
    nb = p.create_notebook("Plain module")
    job = p.generate(nb, ArtifactType.quiz, "", {})
    assert job.job_id == f"fixture-job-{nb.notebook_id}-quiz"
    assert p.poll(job) is StudioStatus.ready
    assert p.query(nb, "Create 3 NEW quiz questions") == fx.FIXTURE_CHAT_ANSWER


def test_fail_generate_and_transient_generate() -> None:
    p = FixtureProvider()
    with pytest.raises(ProviderError) as err:
        p.generate(_nb("M [fixture:fail-generate]"), ArtifactType.report, "", {})
    assert not isinstance(err.value, TransientProviderError)
    with pytest.raises(TransientProviderError):
        p.generate(_nb("M [fixture:transient-generate]"), ArtifactType.report, "", {})


def test_studio_failed_and_stuck() -> None:
    p = FixtureProvider()
    failed = p.generate(_nb("M [fixture:studio-failed]"), ArtifactType.report, "", {})
    assert p.poll(failed) is StudioStatus.failed
    stuck = p.generate(_nb("M [fixture:stuck]"), ArtifactType.report, "", {})
    assert p.poll(stuck) is StudioStatus.pending


def test_slow_is_pending_until_n_seconds_after_generate(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1_000_000.0]
    monkeypatch.setattr(fx.time, "time", lambda: now[0])
    p = FixtureProvider()
    job = p.generate(_nb("M [fixture:slow=20]"), ArtifactType.report, "", {})
    assert p.poll(job) is StudioStatus.pending
    now[0] += 19
    assert FixtureProvider().poll(job) is StudioStatus.pending  # another worker, same id
    now[0] += 2
    assert FixtureProvider().poll(job) is StudioStatus.ready


@pytest.mark.parametrize("kind", ARTIFACT_TYPES)
def test_malformed_output_is_a_parse_error_for_every_type(kind: ArtifactType) -> None:
    from app.pipeline.parsers import parse_artifact
    from app.pipeline.parsers.base import ArtifactParseError

    p = FixtureProvider()
    raw = p.fetch_content(
        StudioJobRef(job_id="j", notebook_id=_nb("M [fixture:malformed]").notebook_id, kind=kind)
    )
    with pytest.raises(ArtifactParseError):
        parse_artifact(kind, raw.html, raw.extras)


def test_source_fail_reports_every_source_failed() -> None:
    p = FixtureProvider()
    nb = p.create_notebook("M [fixture:source-fail]")
    src = p.add_source(nb, "https://youtu.be/x")
    assert p.source_statuses(nb).get(src.source_id) is SourceState.failed


def test_chat_fail_is_a_permanent_error() -> None:
    with pytest.raises(ProviderError) as err:
        FixtureProvider().query(_nb("M [fixture:chat-fail]"), "Create 3 NEW quiz questions")
    assert not isinstance(err.value, TransientProviderError)


def test_quiz_n_sizes_the_studio_quiz_and_chat_skips_what_to_avoid() -> None:
    from app.pipeline.parsers import parse_artifact
    from app.services import quiz_generation as qg

    p = FixtureProvider()
    nb = _nb("M [fixture:quiz=12]")
    raw = p.fetch_content(
        StudioJobRef(job_id="j", notebook_id=nb.notebook_id, kind=ArtifactType.quiz)
    )
    studio = parse_artifact(ArtifactType.quiz, raw.html, raw.extras)["questions"]
    assert len(studio) == 12

    seen = [q["question"] for q in studio]
    first = qg.parse_questions(p.query(nb, qg.build_prompt(12, seen)))
    kept, dropped = qg.validate(first, seen=seen, source_text=None)
    assert len(kept) == 12 and dropped == []
    seen = [q["question"] for q in kept] + seen
    second = qg.parse_questions(p.query(nb, qg.build_prompt(12, seen)))
    kept2, dropped2 = qg.validate(second, seen=seen, source_text=None)
    assert len(kept2) == 12 and dropped2 == []  # attempt 3 works too


def test_typeset_down_only_with_the_fixture_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.config.get_settings", lambda: Settings(content_provider="fixture"))
    assert fx.typeset_down("Week 1 [fixture:typeset-down]")
    assert not fx.typeset_down("Week 1")
    monkeypatch.setattr("app.config.get_settings", lambda: Settings(content_provider="notebooklm"))
    assert not fx.typeset_down("Week 1 [fixture:typeset-down]")
