"""Infographic renderer (T019, D15): `content_json` -> `.svg` + `.png`.

D15 (PROJECT_FRAME.md — owner decision, not gated on the still-open O1 MCP
spike): the backend renders its own diagram from the structure NotebookLM
returned, rather than depending on retrieving a NotebookLM-generated image.

`diagram_kind` is one of:
  - "graphviz" — `diagram_source` is already Graphviz DOT; rendered as-is.
  - "mermaid"  — `diagram_source` is the small `flowchart TD` subset our own
    parser (`app/pipeline/parsers/infographic.py`) emits: one node per line
    (`id["label"]`) and one edge per line (`a --> b` or `a -->|rel| b`).
    Rather than pull in `@mermaid-js/mermaid-cli` (a full headless-Chromium
    dependency, comparable in weight to LibreOffice, just to render a diagram
    shape we generate ourselves), that controlled subset is translated
    directly to Graphviz DOT and rendered with `dot` — the same toolchain,
    no browser. Content from outside our parser that uses other Mermaid
    syntax is rejected with a clear `RenderError`, matching the AC.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from app.render import RenderError
from app.schemas.content import InfographicContent

_NODE_RE = re.compile(r'^(\w+)\["(.*)"\]$')
_EDGE_RE = re.compile(r"^(\w+)\s*-->\s*(?:\|([^|]*)\|)?\s*(\w+)$")
_SUBPROCESS_TIMEOUT = 30


@dataclass(frozen=True)
class RenderedInfographic:
    svg: bytes
    png: bytes


def _dot() -> str:
    exe = shutil.which("dot")
    if exe is None:
        raise RenderError("Graphviz (dot) not found — infographic rendering unavailable")
    return exe


def ensure_infographic_toolchain() -> None:
    """Startup probe, mirroring T018's `ensure_slide_toolchain`."""
    _dot()


def mermaid_flowchart_to_dot(source: str) -> str:
    lines = [line.strip() for line in source.strip().splitlines() if line.strip()]
    if not lines or not lines[0].lower().startswith("flowchart"):
        raise RenderError("unsupported diagram: expected a mermaid 'flowchart TD'")

    nodes: dict[str, str] = {}
    edges: list[tuple[str, str, str]] = []
    for line in lines[1:]:
        if m := _NODE_RE.match(line):
            nodes[m.group(1)] = m.group(2)
            continue
        if m := _EDGE_RE.match(line):
            edges.append((m.group(1), m.group(3), m.group(2) or ""))
            continue
        raise RenderError(f"unsupported mermaid syntax: {line!r}")

    if not nodes:
        raise RenderError("diagram has no nodes")

    dot = [
        "digraph G {",
        "  rankdir=TB;",
        '  bgcolor="transparent";',
        '  node [shape=box, style="rounded,filled", fillcolor="#EEF1FB", '
        'color="#2B4CA8", fontname="Helvetica", fontsize=12, margin="0.18,0.12"];',
        '  edge [color="#5F5F5F", fontname="Helvetica", fontsize=10];',
    ]
    for node_id, label in nodes.items():
        dot.append(f'  {node_id} [label="{_escape(label)}"];')
    for src, dst, rel in edges:
        if src not in nodes or dst not in nodes:
            raise RenderError(f"edge references an unknown node: {src} -> {dst}")
        attrs = f' [label="{_escape(rel)}"]' if rel else ""
        dot.append(f"  {src} -> {dst}{attrs};")
    dot.append("}")
    return "\n".join(dot)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _run_capture(cmd: list[str]) -> bytes:
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, timeout=_SUBPROCESS_TIMEOUT)
        return result.stdout
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace")[:400]
        raise RenderError(f"{Path(cmd[0]).name} failed: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"{Path(cmd[0]).name} timed out") from exc


def render_infographic(content_json: dict[str, object]) -> RenderedInfographic:
    content = InfographicContent.model_validate(content_json)
    dot_exe = _dot()

    dot_source = (
        mermaid_flowchart_to_dot(content.diagram_source)
        if content.diagram_kind == "mermaid"
        else content.diagram_source
    )

    with TemporaryDirectory() as td:
        src = Path(td) / "diagram.dot"
        src.write_text(dot_source, encoding="utf-8")
        svg = _run_capture([dot_exe, "-Tsvg", str(src)])
        png = _run_capture([dot_exe, "-Tpng", str(src)])

    if not svg or not png:
        raise RenderError("dot produced empty output")
    return RenderedInfographic(svg=svg, png=png)
