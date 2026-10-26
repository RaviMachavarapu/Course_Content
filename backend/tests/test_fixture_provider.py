"""T015 — FixtureProvider + provider factory."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.models.enums import ARTIFACT_TYPES, ArtifactType
from app.pipeline.factory import get_content_provider
from app.pipeline.fixture import FixtureProvider
from app.pipeline.provider import ContentProvider, StudioStatus


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
    from app.pipeline.provider import SourceState

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
