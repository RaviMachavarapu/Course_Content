from __future__ import annotations

from typing import TypeVar

from bs4 import BeautifulSoup
from pydantic import BaseModel, ValidationError

M = TypeVar("M", bound=BaseModel)


class ArtifactParseError(Exception):
    """Studio HTML could not be turned into valid content_json."""


def soup(html: str) -> BeautifulSoup:
    if not html or not html.strip():
        raise ArtifactParseError("empty HTML")
    return BeautifulSoup(html, "lxml")


def text_of(node: object, *, strip: bool = True) -> str:
    if node is None:
        return ""
    value = node.get_text(" ") if hasattr(node, "get_text") else str(node)
    return " ".join(value.split()) if strip else value


def validate(model_cls: type[M], data: dict[str, object]) -> M:
    try:
        return model_cls.model_validate(data)
    except ValidationError as exc:
        raise ArtifactParseError(
            f"{model_cls.__name__} validation failed: {exc.errors()[0]['msg']} "
            f"at {list(exc.errors()[0]['loc'])}"
        ) from exc
