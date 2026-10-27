"""Adaptive quiz — ask NotebookLM chat for fresh questions, parse and validate them.

Pure functions plus `module_source_text` (PDF text for proof-quote checks). The
Celery task (`app/tasks/quiz.py`) owns the provider call, the re-ask and storage.

Question shapes kept by `validate` (extra keys are dropped):

    {"type": "mcq", "question", "options": [4 str], "correct_index": 0-3,
     "explanation", "source_quote"}
    {"type": "fill_blank", "question" (one ____), "answer", "accepted_answers": [str],
     "explanation", "source_quote"}
"""

from __future__ import annotations

import bisect
import json
import logging
import re
import unicodedata
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pypdf import PdfReader

from app.storage import service as storage_service

if TYPE_CHECKING:
    from app.models.module import Module

log = logging.getLogger(__name__)

MAX_AVOID = 60
DUPLICATE_RATIO = 0.85
QUOTE_WINDOW_FACTOR = 3
MIN_SERVED = 5
MCQ_SHARE = 0.6

_BLANK_RE = re.compile(r"_{4,}")
_NON_ALNUM_RE = re.compile(r"[\W_]+")
_WS_RE = re.compile(r"\s+")
_DELIMITERS = ("\\(", "\\)", "\\[", "\\]", "$")
#: a backslash that is not part of a valid JSON escape (LaTeX written unescaped)
_BAD_ESCAPE_RE = re.compile(r'\\(["\\/]|u[0-9a-fA-F]{4})|\\')


# -- prompt ---------------------------------------------------------------------


def build_prompt(n: int, avoid: list[str]) -> str:
    """The chat query for `n` new questions (~60% MCQ). `avoid`: the student's seen
    question texts, most recent first (at most `MAX_AVOID` are listed)."""
    n_mcq = round(n * MCQ_SHARE)
    n_blank = n - n_mcq
    parts = [
        f"Create {n} NEW quiz questions strictly from the sources: {n_mcq} multiple-choice "
        "(exactly 4 distinct options, exactly one correct) and "
        f"{n_blank} fill-in-the-blank (one blank written as ____, the answer is a short "
        "exact phrase from the source).",
        "Write every formula, chemical formula and symbol in LaTeX between \\( and \\), "
        "copied exactly from the source.",
        "For each question include a short verbatim quote from the source that proves the answer.",
    ]
    seen = [_WS_RE.sub(" ", a).strip()[:300] for a in avoid[:MAX_AVOID] if a.strip()]
    if seen:
        parts.append(
            "The student has already seen these questions; do not repeat or paraphrase them:\n"
            + "\n".join(f"- {a}" for a in seen)
        )
    parts.append(
        "Return ONLY a JSON array, no prose, using this shape: "
        '[{"type":"mcq","question":"...","options":["...","...","...","..."],"correct_index":0,'
        '"explanation":"...","source_quote":"..."},'
        '{"type":"fill_blank","question":"... ____ ...","answer":"...","accepted_answers":["..."],'
        '"explanation":"...","source_quote":"..."}]'
    )
    return " ".join(parts[:3]) + "\n\n" + "\n\n".join(parts[3:])


# -- parse ----------------------------------------------------------------------


def _first_question_array(text: str) -> list[dict[str, Any]] | None:
    decoder = json.JSONDecoder()
    pos = text.find("[")
    while pos != -1:
        try:
            value, _ = decoder.raw_decode(text, pos)
        except ValueError:
            value = None
        if isinstance(value, list) and any(isinstance(v, dict) for v in value):
            return [v for v in value if isinstance(v, dict)]
        pos = text.find("[", pos + 1)
    return None


def parse_questions(answer: str) -> list[dict[str, Any]]:
    """The first JSON array of objects in a chat answer (prose and code fences around it are
    ignored). `[]` when there is none."""
    found = _first_question_array(answer)
    if found is None and "\\" in answer:
        repaired = _BAD_ESCAPE_RE.sub(lambda m: m.group(0) if m.group(1) else "\\\\", answer)
        found = _first_question_array(repaired)
    return found or []


# -- normalisation --------------------------------------------------------------


def normalize_text(s: str) -> str:
    """Lowercase, every run of non-alphanumerics -> one space (quote and duplicate matching)."""
    return _NON_ALNUM_RE.sub(" ", unicodedata.normalize("NFKC", s).lower()).strip()


def normalize_answer(s: str) -> str:
    """Fill-blank comparison form: NFKC, lowercase, formula delimiters removed, whitespace
    collapsed, surrounding punctuation stripped."""
    t = unicodedata.normalize("NFKC", s).lower()
    for d in _DELIMITERS:
        t = t.replace(d, "")
    t = _WS_RE.sub(" ", t).strip()
    start, end = 0, len(t)
    while start < end and unicodedata.category(t[start]).startswith("P"):
        start += 1
    while end > start and unicodedata.category(t[end - 1]).startswith("P"):
        end -= 1
    return t[start:end].strip()


def fill_blank_correct(question: dict[str, Any], response: str) -> bool:
    """Grade a typed fill-blank response: exact match after `normalize_answer` against the
    answer or any accepted answer."""
    got = normalize_answer(response)
    if not got:
        return False
    accepted = [question.get("answer", ""), *question.get("accepted_answers", [])]
    return any(normalize_answer(a) == got for a in accepted if isinstance(a, str) and a.strip())


def _option_key(option: str) -> str:
    return normalize_answer(option) or option.strip().lower()


# -- validate -------------------------------------------------------------------


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _shape(q: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    kind = q.get("type")
    question = _text(q.get("question"))
    if kind not in ("mcq", "fill_blank"):
        return None, f"type: unsupported {kind!r}"
    if not question:
        return None, "question: missing or empty"
    out: dict[str, Any] = {"type": kind, "question": question}
    if kind == "mcq":
        options = q.get("options")
        if not isinstance(options, list) or len(options) != 4:
            return None, "options: need exactly 4"
        if not all(isinstance(o, str) and o.strip() for o in options):
            return None, "options: need 4 non-empty strings"
        clean = [o.strip() for o in options]
        if len({_option_key(o) for o in clean}) != 4:
            return None, "options: not 4 distinct options"
        idx = q.get("correct_index")
        if isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx <= 3:
            return None, "correct_index: need an integer 0-3"
        out["options"] = clean
        out["correct_index"] = idx
    else:
        if len(_BLANK_RE.findall(question)) != 1:
            return None, "blank: need exactly one ____"
        answer = _text(q.get("answer"))
        if not answer:
            return None, "answer: missing or empty"
        accepted = q.get("accepted_answers")
        if accepted is None:
            accepted = []
        if not isinstance(accepted, list) or not all(isinstance(a, str) for a in accepted):
            return None, "accepted_answers: need a list of strings"
        out["answer"] = answer
        out["accepted_answers"] = [a.strip() for a in accepted if a.strip()]
    out["explanation"] = _text(q.get("explanation"))
    out["source_quote"] = _text(q.get("source_quote"))
    return out, ""


class _SourceIndex:
    """Normalised source words, for exact and in-order-window quote matching."""

    def __init__(self, source_text: str) -> None:
        norm = normalize_text(source_text)
        self.padded = f" {norm} "
        self.positions: dict[str, list[int]] = {}
        for i, word in enumerate(norm.split()):
            self.positions.setdefault(word, []).append(i)

    def has_quote(self, quote: str) -> bool:
        words = normalize_text(quote).split()
        if not words:
            return False
        if f" {' '.join(words)} " in self.padded:
            return True
        window = len(words) * QUOTE_WINDOW_FACTOR
        if any(w not in self.positions for w in words):
            return False
        for start in self.positions[words[0]]:
            pos = start
            for w in words[1:]:
                where = self.positions[w]
                k = bisect.bisect_right(where, pos)
                if k == len(where) or where[k] - start >= window:
                    break
                pos = where[k]
            else:
                return True
        return False


def validate(
    questions: list[Any], *, seen: list[str], source_text: str | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split chat questions into (kept, dropped). Dropped entries are
    `{"index", "question", "reason"}`; kept ones are normalised copies (input untouched).

    `seen`: question texts the student has already seen (near-duplicates are dropped, as
    are repeats within `questions`). `source_text`: the module's PDF text; when given, each
    question's `source_quote` must be found in it (None = module has no PDFs, not checked).
    """
    index = _SourceIndex(source_text) if source_text is not None else None
    taken = [normalize_text(s) for s in seen]
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    for i, raw in enumerate(questions):
        shown = _text(raw.get("question")) if isinstance(raw, dict) else str(raw)[:200]
        if not isinstance(raw, dict):
            dropped.append({"index": i, "question": shown, "reason": "shape: not an object"})
            continue
        q, reason = _shape(raw)
        if q is None:
            dropped.append({"index": i, "question": shown, "reason": reason})
            continue
        norm = normalize_text(q["question"])
        if any(SequenceMatcher(None, norm, t).ratio() >= DUPLICATE_RATIO for t in taken):
            dropped.append(
                {
                    "index": i,
                    "question": shown,
                    "reason": "duplicate: near-duplicate of a seen question",
                }
            )
            continue
        if index is not None and not index.has_quote(q["source_quote"]):
            dropped.append(
                {"index": i, "question": shown, "reason": "quote: not found in the sources"}
            )
            continue
        taken.append(norm)
        kept.append(q)
    return kept, dropped


# -- PDF text -------------------------------------------------------------------

_CACHE_MAX = 16
_text_cache: dict[tuple[uuid.UUID, tuple[tuple[str, str], ...]], str | None] = {}


def _extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def module_source_text(module: Module) -> str | None:
    """Extracted text of the module's PDF sources, or None when it has none (or none with a
    text layer). Cached in-process per module + files' storage keys and checksums."""
    files = sorted(module.source_files, key=lambda f: f.order_index)
    if not files:
        return None
    key = (module.id, tuple((f.storage_key, f.checksum_sha256) for f in files))
    if key in _text_cache:
        return _text_cache[key]
    storage = storage_service.get_storage()
    texts: list[str] = []
    complete = True
    for f in files:
        try:
            texts.append(_extract_pdf_text(storage.path_for(f.storage_key)))
        except Exception:  # pypdf raises many error types on damaged input
            log.warning("could not read PDF text of %s", f.file_name, exc_info=True)
            complete = False
    text = "\n".join(texts)
    result = text if text.strip() else None
    if complete:
        if len(_text_cache) >= _CACHE_MAX:
            _text_cache.pop(next(iter(_text_cache)))
        _text_cache[key] = result
    return result
