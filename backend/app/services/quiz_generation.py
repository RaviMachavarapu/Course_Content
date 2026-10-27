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

_BLANK_RE = re.compile(r"_{3,}")
BLANK = "____"
MIN_QUOTE_WORDS = 5
MIN_QUOTE_CHARS = 20
_NON_ALNUM_RE = re.compile(r"[\W_]+")
_WS_RE = re.compile(r"\s+")
_DELIMITERS = ("\\(", "\\)", "\\[", "\\]", "$")
_LTX_WRAP_RE = re.compile(
    r"\\(?:text|textrm|textbf|textit|mathrm|mathbf|mathit|operatorname|ce)\s*\{([^{}]*)\}"
)
_LTX_CMD_RE = re.compile(r"\\[A-Za-z]+")
_LTX_PUNCT_RE = re.compile(r"[\^_{}]")
_CONTROL_RE = re.compile(r"[\x00-\x09\x0b-\x1f]")
#: a JSON `\n` escape directly followed by a letter: LaTeX `\nu`, `\neq`, `\nabla`
_NEWLINE_LETTER_RE = re.compile(r"(?<!\\)(?:\\\\)*\\n[A-Za-z]")
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
        "copied exactly from the source. Because the answer is JSON, write every backslash "
        'inside a JSON string doubled, e.g. "\\\\(\\\\text{sp}^2\\\\)" for \\(\\text{sp}^2\\).',
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


def _first_array(text: str) -> list[dict[str, Any]] | None:
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


def _objects(text: str) -> list[dict[str, Any]]:
    """Every top-level `{...}` question object, decoded one by one (an array broken by
    citation markers or trailing commas)."""
    decoder = json.JSONDecoder()
    out: list[dict[str, Any]] = []
    pos = text.find("{")
    while pos != -1:
        try:
            value, end = decoder.raw_decode(text, pos)
        except ValueError:
            pos = text.find("{", pos + 1)
            continue
        if isinstance(value, dict) and "question" in value:
            out.append(value)
        pos = text.find("{", end if isinstance(value, dict) else pos + 1)
    return out


def _repair(text: str) -> str:
    """Double every backslash that is not part of `\\"`, `\\\\`, `\\/` or `\\uXXXX`, so LaTeX
    written with single backslashes (`\\frac`, `\\beta`, `\\nu`, `\\(`) survives."""
    return _BAD_ESCAPE_RE.sub(lambda m: m.group(0) if m.group(1) else "\\\\", text)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [t for v in value.values() for t in _strings(v)]
    if isinstance(value, list):
        return [t for v in value for t in _strings(v)]
    return []


def _corrupted(text: str, found: list[dict[str, Any]]) -> bool:
    """A parse that succeeded but turned single-backslash LaTeX (`\\frac`, `\\beta`, `\\text`,
    `\\nu`) into form feed, backspace, tab or newline characters."""
    if _NEWLINE_LETTER_RE.search(text):
        return True
    return any(c in t for t in _strings(found) for c in "\t\b\f\r")


def parse_questions(answer: str) -> list[dict[str, Any]]:
    """The question objects in a chat answer: the first JSON array of objects (prose and code
    fences around it are ignored), or, when no array parses, each `{...}` object on its own.
    Single-backslash LaTeX is repaired. Questions whose text still holds control characters
    are dropped. `[]` when nothing parses."""
    has_bs = "\\" in answer
    found = _first_array(answer)
    if has_bs and (found is None or _corrupted(answer, found)):
        repaired = _first_array(_repair(answer))
        if repaired is not None:
            found = repaired
    if found is None:
        found = _objects(answer)
        if has_bs:
            repaired_objects = _objects(_repair(answer))
            if len(repaired_objects) >= len(found):
                found = repaired_objects
    return [q for q in found if not any(_CONTROL_RE.search(t) for t in _strings(q))]


# -- normalisation --------------------------------------------------------------


def strip_latex(s: str) -> str:
    """Drop LaTeX markup: delimiters, `\\text{X}`-style wrappers unwrapped to X, other
    `\\commands`, and `^ _ { }`."""
    for d in _DELIMITERS:
        s = s.replace(d, " ")
    prev = None
    while prev != s:
        prev = s
        s = _LTX_WRAP_RE.sub(r"\1", s)
    return _LTX_PUNCT_RE.sub("", _LTX_CMD_RE.sub(" ", s))


def normalize_text(s: str) -> str:
    """LaTeX stripped, lowercase, every run of non-alphanumerics -> one space (quote and
    duplicate matching)."""
    return _NON_ALNUM_RE.sub(" ", strip_latex(unicodedata.normalize("NFKC", s)).lower()).strip()


def normalize_answer(s: str) -> str:
    """Fill-blank comparison form: NFKC, lowercase, LaTeX markup removed, whitespace
    collapsed, surrounding punctuation stripped."""
    t = _WS_RE.sub(" ", strip_latex(unicodedata.normalize("NFKC", s).lower())).strip()
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
        out["question"] = _BLANK_RE.sub(BLANK, question)
        answer = _text(q.get("answer"))
        if not answer:
            return None, "answer: missing or empty"
        if not normalize_answer(answer):
            return None, "answer: empty after normalisation"
        accepted = q.get("accepted_answers")
        if accepted is None:
            accepted = []
        if not isinstance(accepted, list) or not all(isinstance(a, str) for a in accepted):
            return None, "accepted_answers: need a list of strings"
        out["answer"] = answer
        out["accepted_answers"] = [a.strip() for a in accepted if normalize_answer(a)]
    out["explanation"] = _text(q.get("explanation"))
    out["source_quote"] = _text(q.get("source_quote"))
    return out, ""


class _SourceIndex:
    """Normalised source words, for exact, in-order-window and spaceless quote matching."""

    def __init__(self, source_text: str) -> None:
        norm = normalize_text(source_text)
        self.padded = f" {norm} "
        self.squashed = norm.replace(" ", "")
        self.positions: dict[str, list[int]] = {}
        for i, word in enumerate(norm.split()):
            self.positions.setdefault(word, []).append(i)

    def quote_problem(self, quote: str) -> str | None:
        """None when the quote is acceptable, else why not."""
        words = normalize_text(quote).split()
        squashed = "".join(words)
        if not words:
            return "quote: missing"
        if len(words) < MIN_QUOTE_WORDS and len(squashed) < MIN_QUOTE_CHARS:
            return "quote: too short"
        if self._found(words, squashed):
            return None
        return "quote: not found in the sources"

    def _found(self, words: list[str], squashed: str) -> bool:
        if f" {' '.join(words)} " in self.padded:
            return True
        window = len(words) * QUOTE_WINDOW_FACTOR
        if all(w in self.positions for w in words):
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
        # PDF extraction splits sub/superscripts into separate words ("S N 1"): compare with
        # every space removed
        return squashed in self.squashed


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
        problem = index.quote_problem(q["source_quote"]) if index is not None else None
        if problem:
            dropped.append({"index": i, "question": shown, "reason": problem})
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


class SourceTextUnavailable(Exception):
    """The module has PDF sources but none could be read; validation must not proceed as if
    the module had no PDFs (the caller retries or fails the set)."""


def module_source_text(module: Module) -> str | None:
    """Extracted text of the module's PDF sources. None only when the module has no PDFs, or
    its PDFs have no text layer (scans; logged as a warning). Raises `SourceTextUnavailable`
    when it has PDFs and every one fails to load. Cached in-process per module + files'
    storage keys and checksums."""
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
    if not texts:
        raise SourceTextUnavailable(f"none of the module's {len(files)} PDF(s) could be read")
    text = "\n".join(texts)
    result = text if text.strip() else None
    if result is None:
        log.warning("module %s: PDF sources have no text layer; quotes are not checked", module.id)
    if complete:
        if len(_text_cache) >= _CACHE_MAX:
            _text_cache.pop(next(iter(_text_cache)))
        _text_cache[key] = result
    return result
