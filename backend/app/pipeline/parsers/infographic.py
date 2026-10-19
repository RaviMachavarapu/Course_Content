from __future__ import annotations

from typing import Any

from app.pipeline.parsers.base import ArtifactParseError, soup, text_of, validate
from app.schemas.content import InfographicContent

_REL_LABEL = {
    "part-of": "part of",
    "uses": "uses",
    "requires": "requires",
    "minimises": "minimises",
    "leads-to": "leads to",
    "contrasts-with": "contrasts with",
}


def _node_id(raw: str, seen: dict[str, str]) -> str:
    """A mermaid-safe node id, stable per source id."""
    if raw in seen:
        return seen[raw]
    safe = "".join(c if c.isalnum() else "_" for c in raw) or f"n{len(seen)}"
    seen[raw] = safe
    return safe


def _mermaid_from_tree(tree: dict[str, Any]) -> str:
    lines = ["flowchart TD"]
    seen: dict[str, str] = {}

    def walk(node: dict[str, Any], parent: dict[str, Any] | None) -> None:
        nid = _node_id(str(node.get("id") or node.get("label", "")), seen)
        lines.append(f'    {nid}["{node.get("label", "").strip() or nid}"]')
        if parent is not None:
            pid = _node_id(str(parent.get("id") or parent.get("label", "")), seen)
            rel = _REL_LABEL.get(str(node.get("rel", "")), "")
            edge = f"-->|{rel}|" if rel else "-->"
            lines.append(f"    {pid} {edge} {nid}")
        for child in node.get("children", []):
            walk(child, node)

    walk(tree, None)
    if len(lines) == 1:
        raise ArtifactParseError("mind-map tree produced no nodes")
    return "\n".join(lines)


def _mermaid_from_html(html_root: Any) -> str:
    nodes = html_root.select(".node")
    if not nodes:
        raise ArtifactParseError("no .node elements and no mind_map_tree")
    lines = ["flowchart TD"]
    seen: dict[str, str] = {}
    for node in nodes:
        raw_id = node.get("data-id") or text_of(node.select_one(".label"))
        nid = _node_id(str(raw_id), seen)
        label = text_of(node.select_one(".label")) or nid
        lines.append(f'    {nid}["{label}"]')
        parent = node.get("data-parent")
        if parent:
            pid = _node_id(str(parent), seen)
            rel = _REL_LABEL.get(str(node.get("data-rel", "")), "")
            edge = f"-->|{rel}|" if rel else "-->"
            lines.append(f"    {pid} {edge} {nid}")
    return "\n".join(lines)


def parse_infographic(html: str, extras: dict[str, Any]) -> InfographicContent:
    doc = soup(html)
    root = doc.select_one(".studio-artifact") or doc

    kind = str(extras.get("diagram_kind") or "mermaid")
    if kind not in ("mermaid", "graphviz"):
        kind = "mermaid"

    tree = extras.get("mind_map_tree")
    diagram_source = (
        _mermaid_from_tree(tree) if isinstance(tree, dict) else _mermaid_from_html(root)
    )

    central = root.select_one(".node.central .desc, .node.central .label")
    caption = text_of(central) or text_of(root.select_one("figcaption, .caption"))

    return validate(
        InfographicContent,
        {"caption": caption, "diagram_kind": kind, "diagram_source": diagram_source},
    )
