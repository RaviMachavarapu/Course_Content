"""T019 — infographic renderer (D15: render our own structure, not the MCP image)."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from app.render import RenderError
from app.render.infographic import (
    ensure_infographic_toolchain,
    mermaid_flowchart_to_dot,
    render_infographic,
)
from app.schemas.content import InfographicContent

MERMAID_SOURCE = (
    "flowchart TD\n"
    '    nn["Neural Network"]\n'
    '    neuron["Neuron"]\n'
    "    nn -->|part of| neuron\n"
    '    activation["Activation"]\n'
    "    neuron -->|uses| activation\n"
)

CONTENT = InfographicContent(
    caption="How a neural network learns",
    diagram_kind="mermaid",
    diagram_source=MERMAID_SOURCE,
)

_needs_toolchain = pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz not installed")


def test_mermaid_flowchart_translates_to_valid_dot() -> None:
    dot = mermaid_flowchart_to_dot(MERMAID_SOURCE)
    assert dot.startswith("digraph G {")
    assert '"Neural Network"' in dot
    assert "nn -> neuron" in dot
    assert '"part of"' in dot


def test_unsupported_mermaid_syntax_raises_render_error() -> None:
    with pytest.raises(RenderError, match="unsupported"):
        mermaid_flowchart_to_dot("pie title not a flowchart\n")


def test_edge_to_unknown_node_raises_render_error() -> None:
    with pytest.raises(RenderError, match="unknown node"):
        mermaid_flowchart_to_dot('flowchart TD\n    a["A"]\n    a --> b\n')


def test_unparseable_line_inside_a_flowchart_raises_render_error() -> None:
    with pytest.raises(RenderError, match="unsupported mermaid syntax"):
        mermaid_flowchart_to_dot('flowchart TD\n    a["A"]\n    subgraph cluster\n')


def test_flowchart_with_no_nodes_raises_render_error() -> None:
    with pytest.raises(RenderError, match="no nodes"):
        mermaid_flowchart_to_dot("flowchart TD\n")


@_needs_toolchain
def test_dot_process_failure_raises_render_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.CalledProcessError(1, cmd, stderr=b"syntax error in line 1")

    monkeypatch.setattr("app.render.infographic.subprocess.run", _boom)
    with pytest.raises(RenderError, match="syntax error"):
        render_infographic(CONTENT.model_dump())


@_needs_toolchain
def test_dot_process_timeout_raises_render_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _hang(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd, 30)

    monkeypatch.setattr("app.render.infographic.subprocess.run", _hang)
    with pytest.raises(RenderError, match="timed out"):
        render_infographic(CONTENT.model_dump())


@_needs_toolchain
def test_empty_dot_output_raises_render_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _empty(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr("app.render.infographic.subprocess.run", _empty)
    with pytest.raises(RenderError, match="empty output"):
        render_infographic(CONTENT.model_dump())


def test_missing_toolchain_raises_render_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.render.infographic.shutil.which", lambda _name: None)
    with pytest.raises(RenderError, match="Graphviz"):
        ensure_infographic_toolchain()
    with pytest.raises(RenderError, match="Graphviz"):
        render_infographic(CONTENT.model_dump())


@_needs_toolchain
def test_render_infographic_produces_svg_and_png() -> None:
    rendered = render_infographic(CONTENT.model_dump())
    assert b"<svg" in rendered.svg
    assert rendered.png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(rendered.png) > 500


@_needs_toolchain
def test_graphviz_source_passes_through_unchanged() -> None:
    dot_content = InfographicContent(
        caption="direct dot",
        diagram_kind="graphviz",
        diagram_source="digraph G { a -> b; }",
    )
    rendered = render_infographic(dot_content.model_dump())
    assert b"<svg" in rendered.svg
