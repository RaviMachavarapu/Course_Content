from __future__ import annotations

import re
from typing import Any

from app.pipeline.parsers.base import ArtifactParseError, soup, text_of, validate
from app.schemas.content import QuizContent


def _correct_index(answer_el: object, option_count: int) -> int:
    """Resolve the 0-based correct option index from an `.answer` element.

    Accepts `data-correct-index` (0-based) or an inner "1"-"4" (1-based).
    """
    if answer_el is None:
        raise ArtifactParseError("question has no marked answer")
    raw_attr = answer_el.get("data-correct-index") if hasattr(answer_el, "get") else None
    if raw_attr is not None and raw_attr.strip().isdigit():
        idx = int(raw_attr)
    else:
        m = re.search(r"\d+", text_of(answer_el))
        if not m:
            raise ArtifactParseError("could not read the marked answer")
        idx = int(m.group()) - 1
    if not 0 <= idx < option_count:
        raise ArtifactParseError(f"marked answer {idx} is out of range")
    return idx


def parse_quiz(html: str, extras: dict[str, Any]) -> QuizContent:
    doc = soup(html)
    blocks = doc.select(".question") or doc.select("li.question")
    if not blocks:
        raise ArtifactParseError("no .question blocks found")

    questions = []
    for i, block in enumerate(blocks):
        prompt = text_of(block.select_one(".prompt, .stem, p"))
        options = [text_of(li) for li in block.select(".options li, ol li")]
        if len(options) != 4:
            raise ArtifactParseError(
                f"question {i + 1} has {len(options)} options; exactly 4 are required"
            )
        correct = _correct_index(block.select_one(".answer"), len(options))
        explanation = text_of(block.select_one(".explanation, .rationale"))
        questions.append(
            {
                "question": prompt,
                "options": options,
                "correct_index": correct,
                "explanation": explanation,
            }
        )

    return validate(QuizContent, {"questions": questions})
