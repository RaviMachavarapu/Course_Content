"""Adaptive quiz — ask NotebookLM chat for fresh questions, parse and validate them.

Pure functions plus `module_source_text` (PDF text for proof-quote checks). The
Celery task (`app/tasks/quiz.py`) owns the provider call, the re-ask and storage.

Question shapes kept by `validate` (extra keys are dropped):

    {"type": "mcq", "question", "options": [4 str], "correct_index": 0-3,
     "explanation", "source_quote"}
    {"type": "fill_blank", "question" (one ____), "answer", "accepted_answers": [str],
     "explanation", "source_quote"}
"""

# ruff: noqa: RUF001, RUF002, RUF003 (Greek letters and math symbols are intentional)

from __future__ import annotations

import bisect
import functools
import json
import logging
import re
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pypdf import PdfReader

from app.schemas.content_options import LANGUAGE_NAMES
from app.storage import service as storage_service

if TYPE_CHECKING:
    from app.models.module import Module

log = logging.getLogger(__name__)

MAX_AVOID = 60
DUPLICATE_RATIO = 0.85
QUOTE_WINDOW_FACTOR = 3
MIN_SERVED = 5


def min_served(n: int) -> int:
    """The fewest questions a fresh set may have: 5, or all N when the Studio quiz has
    fewer (a retake is as long as the reviewed quiz; owner decision 2026-10-29)."""
    return max(1, min(MIN_SERVED, n))


MCQ_SHARE = 0.6

_BLANK_RE = re.compile(r"_{3,}")
BLANK = "____"
FORMULA_REASON = "answer: formula — ask as multiple-choice"
MIN_QUOTE_WORDS = 5
MIN_QUOTE_CHARS = 20


def _mark_ranges() -> str:
    """A regex class body of every combining mark (Unicode category M) in the BMP: the
    vowel signs and viramas of Indic scripts. `re`'s `\\w` does not match them, so
    without these "தமிழ்" would split into "தம ழ" (spec §4.3, non-Latin languages)."""
    ranges: list[str] = []
    start = prev = -2
    for cp in range(0x300, 0x10000):
        if unicodedata.category(chr(cp)).startswith("M"):
            if cp != prev + 1:
                if start >= 0:
                    ranges.append(f"\\u{start:04x}-\\u{prev:04x}")
                start = cp
            prev = cp
    ranges.append(f"\\u{start:04x}-\\u{prev:04x}")
    return "".join(ranges)


_MARKS = _mark_ranges()
#: a run of characters that are neither word characters nor combining marks (or `_`)
_NON_ALNUM_RE = re.compile(f"(?:[^\\w{_MARKS}]|_)+")
#: zero-width characters typed (or not) inside Indic words: ZWSP, ZWNJ, ZWJ, word joiner,
#: BOM — dropped before any comparison
_ZERO_WIDTH_RE = re.compile("[\u200b-\u200d\u2060\ufeff]")
#: sentence punctuation of Indic scripts: danda and double danda
_DANDAS = "\u0964\u0965"
_WS_RE = re.compile(r"\s+")
_DELIMITERS = ("\\(", "\\)", "\\[", "\\]", "$")
_LTX_WRAP_RE = re.compile(
    r"\\(text|textrm|textbf|textit|mathrm|mathbf|mathit|operatorname|ce)\s*\{([^{}]*)\}"
)
_LTX_FRAC_RE = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_LTX_SQRT_RE = re.compile(r"\\sqrt\s*\{([^{}]*)\}")
_LTX_DEGREE_RE = re.compile(r"\^\s*\{?\s*\\circ\s*\}?")
_LTX_CMD_RE = re.compile(r"\\([A-Za-z]+) ?")
_LTX_ESCAPED_RE = re.compile(r"\\([%&#])")
_LTX_SPACING_RE = re.compile(r"\\[,;:! ]")
_SCRIPT_RUN_RE = re.compile("[\u2070\u00b9\u00b2\u00b3\u2074-\u207e\u207f]+")
_SUBSCRIPT_RUN_RE = re.compile("[\u2080-\u208e]+")
_SYMBOL_WS_RE = re.compile(
    r"\s*([\u00b1\u2213\u2264\u2265\u2260\u2248\u00d7\u00b7\u00f7\u2192\u2190\u21cc\u221e\u00b0\u2202\u2207\u2211\u222b\u221a=<>+/^-])\s*"
)
_SIGNATURE_RE = re.compile(
    r"[\d<>=+^_\u00b1\u2213\u2264\u2265\u2260\u2248\u00d7\u00b7\u00f7\u2192\u2190\u21cc\u221e\u00b0\u2202\u2207\u2211\u222b\u221a\u0370-\u03ff]"
)
_CONTROL_RE = re.compile(r"[\x00-\x09\x0b-\x1f]")
#: a JSON `\n` escape directly followed by a letter: LaTeX `\nu`, `\neq`, `\nabla`
_NEWLINE_LETTER_RE = re.compile(r"(?<!\\)(?:\\\\)*\\n[A-Za-z]")
#: a backslash that is not part of a valid JSON escape (LaTeX written unescaped)
_BAD_ESCAPE_RE = re.compile(r'\\(["\\/]|u[0-9a-fA-F]{4})|\\')


_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ϵ",
    "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "varpi": "ϖ", "rho": "ρ",
    "varrho": "ϱ", "sigma": "σ", "varsigma": "ς", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "varphi": "ϕ", "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ",
    "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ",
    "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}  # fmt: skip
_SYMBOLS = {
    "pm": "±", "mp": "∓", "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠",
    "approx": "≈", "times": "×", "cdot": "·", "div": "÷", "to": "→", "rightarrow": "→",
    "leftarrow": "←", "rightleftharpoons": "⇌", "leftrightharpoons": "⇌", "infty": "∞",
    "circ": "°", "degree": "°", "partial": "∂", "nabla": "∇", "sum": "∑", "int": "∫",
    "neg": " not ", "lnot": " not ", "not": " not ", "quad": " ", "qquad": " ",
}  # fmt: skip
_IGNORED = frozenset({"left", "right", "displaystyle", "big", "Big", "bigg", "Bigg", "limits"})
_SUPER = dict(zip("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ", "0123456789+-=()n", strict=True))
_SUB = dict(zip("₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎", "0123456789+-=()", strict=True))


# -- prompt ---------------------------------------------------------------------


#: what each admin-chosen quiz difficulty asks of the questions (QuizOptions.difficulty)
DIFFICULTY_GUIDE = {
    "easy": "easy: recall of facts, terms and definitions stated directly in the sources",
    "medium": "medium: understanding and applying the ideas in the sources",
    "hard": (
        "hard: multi-step reasoning, analysis, and connecting ideas from different parts "
        "of the sources"
    ),
}


def prepared_for(options: dict[str, Any] | None) -> dict[str, str]:
    """The language and difficulty a quiz's fresh sets are written in: the admin's choice
    for the quiz (QuizOptions, as recorded on the published version), defaults en / medium."""
    options = options or {}
    language = options.get("language")
    difficulty = options.get("difficulty")
    return {
        "language": language if language in LANGUAGE_NAMES else "en",
        "difficulty": difficulty if difficulty in DIFFICULTY_GUIDE else "medium",
    }


def build_prompt(
    n: int, avoid: list[str], *, language: str = "en", difficulty: str = "medium"
) -> str:
    """The chat query for `n` new questions (~60% MCQ) written in `language` (a `Language`
    code) at `difficulty` (easy / medium / hard; the quiz's admin-chosen options). `avoid`:
    the student's seen question texts, most recent first (at most `MAX_AVOID` are listed)."""
    n_mcq = round(n * MCQ_SHARE)
    n_blank = n - n_mcq
    name = LANGUAGE_NAMES.get(language, "English")
    parts = [
        f"Create {n} NEW quiz questions strictly from the sources: {n_mcq} multiple-choice "
        "(exactly 4 distinct options, exactly one correct) and "
        f"{n_blank} fill-in-the-blank (one blank written as ____; the answer is a single word, a "
        "short phrase or a plain number stated in the source, never a formula, equation, "
        "chemical formula or symbol). Any question whose answer is a formula, equation, "
        "chemical formula or symbol must be multiple-choice instead. In accepted_answers list the "
        "common acceptable variants of a fill-in-the-blank answer (plural or singular, alternative "
        "spellings, hyphenated or spaced forms, a number with or without a space before its unit).",
        "Write every formula, chemical formula and symbol in LaTeX between \\( and \\), "
        "copied exactly from the source. Because the answer is JSON, write every backslash "
        'inside a JSON string doubled, e.g. "\\\\(\\\\text{sp}^2\\\\)" for \\(\\text{sp}^2\\).',
        f"Write every question, option, answer, accepted answer and explanation in {name}, "
        f"at this difficulty: {DIFFICULTY_GUIDE.get(difficulty, DIFFICULTY_GUIDE['medium'])}.",
        "For each question include a short verbatim quote from the source that proves the answer; "
        f"copy the quote exactly as it is written in the source, in the source's own language "
        f"(never translate it into {name}).",
    ]
    seen = [_WS_RE.sub(" ", a).strip()[:300] for a in avoid[:MAX_AVOID] if a.strip()]
    if seen:
        parts.append(
            "The student has already seen these questions; do not repeat or paraphrase them:\n"
            + "\n".join(f"- {a}" for a in seen)
        )
    parts.append(
        "Return ONLY a JSON array, no prose, using this shape: "
        '[{"type":"mcq","question":"...","options":["...","...","...","..."],"correct_index":2,'
        '"explanation":"...","source_quote":"..."},'
        '{"type":"fill_blank","question":"... ____ ...","answer":"...","accepted_answers":["..."],'
        '"explanation":"...","source_quote":"..."}]'
    )
    return " ".join(parts[:4]) + "\n\n" + "\n\n".join(parts[4:])


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


def _translate(s: str, unknown: str) -> tuple[str, bool]:
    """LaTeX -> plain text by translation: Greek letters and operators become Unicode,
    `\\frac{a}{b}` -> a/b, `\\sqrt{x}` -> √x, `\\text{X}`-style wrappers unwrap to X, negations
    become "not", delimiters go. A command not known: dropped (`unknown="drop"`) or kept as
    its bare name (`"keep"`). Returns (text, saw_unknown_command). `^` and `_` stay."""
    for d in _DELIMITERS:
        s = s.replace(d, " ")
    s = _LTX_DEGREE_RE.sub("°", s)
    s = _LTX_SPACING_RE.sub(" ", s)
    s = _LTX_ESCAPED_RE.sub(r"\1", s)
    prev = None
    while prev != s:
        prev = s
        s = _LTX_FRAC_RE.sub(r"\1/\2", s)
        s = _LTX_SQRT_RE.sub(r"√\1", s)

        def wrap(m: re.Match[str]) -> str:
            body: str = m.group(2)
            if m.group(1) == "ce":
                body = body.replace("<=>", "⇌").replace("->", "→").replace("<-", "←")
            return body

        s = _LTX_WRAP_RE.sub(wrap, s)
    saw_unknown = False

    def command(m: re.Match[str]) -> str:
        nonlocal saw_unknown
        name = m.group(1)
        if name in _GREEK:
            return _GREEK[name]
        if name in _SYMBOLS:
            return _SYMBOLS[name]
        if name in _IGNORED:
            return ""
        saw_unknown = True
        return f" {name} " if unknown == "keep" else " "

    return _LTX_CMD_RE.sub(command, s), saw_unknown


def _lower(s: str) -> str:
    """Lowercase except capital Greek letters (so ΔG and δG stay different)."""
    return "".join(c if "Α" <= c <= "Ω" else c.lower() for c in s)


def normalize_text(s: str) -> str:
    """LaTeX translated (unknown commands dropped), lowercase, every run of non-alphanumerics
    -> one space (quote matching)."""
    text = _translate(_fold(s), "drop")[0]
    return _NON_ALNUM_RE.sub(" ", _lower(text)).strip()


@functools.lru_cache(maxsize=8192)
def _dup_key(s: str) -> tuple[str, str]:
    """(text key, signature) for duplicate detection. The key keeps ^ and comparison
    symbols; the signature is just digits, symbols and Greek letters in order, so
    `\\Delta G < 0` and `\\Delta G > 0` are never duplicates."""
    text = _translate(_fold(s), "drop")[0]
    text = _lower(text).replace("{", "").replace("}", "")
    text = re.sub(
        f"[^\\w{_MARKS}"
        r"<>=+^\u00b1\u2213\u2264\u2265\u2260\u2248\u00d7\u00b7\u00f7\u2192\u2190\u21cc\u221e\u00b0\u2202\u2207\u2211\u222b\u221a]+",
        " ",
        text,
    )
    text = text.strip()
    return text, "".join(_SIGNATURE_RE.findall(text))


def normalize_formula(s: str) -> str:
    """Comparison key for MCQ options (not grading): Unicode super/subscripts mapped,
    NFKC, LaTeX translated (`\\alpha` -> α, `\\leq` -> ≤, `\\frac{1}{2}` -> 1/2), lowercase
    (capital Greek kept), `_` and braces dropped but `^` kept, whitespace collapsed (and removed
    around operators), surrounding punctuation stripped."""
    t = _SCRIPT_RUN_RE.sub(lambda m: "^" + "".join(_SUPER[c] for c in m.group(0)), s)
    t = _SUBSCRIPT_RUN_RE.sub(lambda m: "".join(_SUB[c] for c in m.group(0)), t)
    t = unicodedata.normalize("NFKC", t)
    t = _lower(_translate(t, "keep")[0])
    t = t.replace("<=>", "⇌").replace("->", "→").replace(">=", "≥").replace("<=", "≤")
    t = t.replace("!=", "≠")
    t = re.sub(r"[_{}]", "", t)
    t = _SYMBOL_WS_RE.sub(r"\1", _WS_RE.sub(" ", t).strip())
    start, end = 0, len(t)
    while start < end and unicodedata.category(t[start]).startswith("P"):
        start += 1
    while end > start and unicodedata.category(t[end - 1]).startswith("P"):
        end -= 1
    return t[start:end].strip()


_CHAR_MAP = str.maketrans(
    {
        "\u2212": "-",  # minus sign
        "\u2013": "-",  # en dash
        "\u2018": "'",
        "\u2019": "'",
        "\u2032": "'",  # prime
        "\u201c": '"',
        "\u201d": '"',
    }
)
_QUOTES = "\"'«»"
_TRAILING_PUNCT = ".,;:!?" + _DANDAS + _QUOTES
_LEADING_DOT_RE = re.compile(r"(?<![\w.])\.(?=\d)")
_LETTER_DIGIT_RE = re.compile(r"[^\W\d_]\d")
_FORMULA_CHARS = frozenset("$\\^_{}√/")
_PLAIN_PUNCT = frozenset(" -+.,%°'" + _DANDAS)


def _fold(s: str) -> str:
    """NFKC, zero-width characters dropped, every decimal digit (Devanagari ५, Tamil ௫,
    Telugu ౫ ...) -> its ASCII digit."""
    t = _ZERO_WIDTH_RE.sub("", unicodedata.normalize("NFKC", s))
    if t.isascii():
        return t
    return "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in t)


def _canonical(s: str) -> str:
    """`_fold`, then curly quotes/apostrophes and primes -> straight, minus and en dash
    -> `-`."""
    return _fold(s).translate(_CHAR_MAP)


def _strip_trailing(t: str) -> str:
    """Strip trailing sentence punctuation and quotes, but keep a run of `'` right after a
    digit (a prime: 3', 3'')."""
    while t and t[-1] in _TRAILING_PUNCT + " ":
        if t[-1] == "'" and t.rstrip("'")[-1:].isdigit():
            break
        t = t[:-1]
    return t


def normalize_answer(s: str) -> str:
    """Typed fill-blank answer, case preserved (spec 4.4): NFKC, curly quotes -> straight,
    minus sign and en dash -> `-`, whitespace collapsed and trimmed, surrounding quotes and
    trailing sentence punctuation (`. , ; : ! ?`) stripped (signs, `%`, `°` and a prime
    right after a digit kept), a leading `.` before a digit -> `0.`."""
    t = _WS_RE.sub(" ", _canonical(s)).strip()
    while len(t) >= 2 and t[0] in _QUOTES and t[0] == t[-1]:
        t = t[1:-1].strip()
    t = _strip_trailing(t.lstrip(_QUOTES + " ")).strip()
    return _LEADING_DOT_RE.sub("0.", t)


def is_formula_answer(s: str) -> bool:
    """True if `s` (NFKC-normalised) is not words or a plain number: formula notation
    (`$ \\ ^ _ { } √ /`), a chemical-formula-like token (a letter right before a digit: H2O,
    CO2, Fe3), or any character outside letters, digits, spaces and `- + . , % ° '`."""
    s = _canonical(s)
    if _FORMULA_CHARS & set(s) or _LETTER_DIGIT_RE.search(s):
        return True
    for c in s:
        if c in _PLAIN_PUNCT or c.isspace():
            continue
        cat = unicodedata.category(c)
        if not (cat[0] in "LM" or cat == "Nd"):
            return True
    return False


def _inner_upper(t: str) -> bool:
    """An uppercase letter that does not start a word (CO, NaCl, pH, mRNA)."""
    return any(c.isupper() and i > 0 and t[i - 1].isalpha() for i, c in enumerate(t))


def _has_greek(t: str) -> bool:
    return any(c.isalpha() and unicodedata.name(c, "").startswith("GREEK") for c in t)


def _symbol_shape(t: str) -> bool:
    """A single 1-2 letter token starting with a capital, signs allowed (C, Co, Na, Na+)."""
    letters = [c for c in t if c.isalpha()]
    return (
        1 <= len(letters) <= 2 and letters[0].isupper() and all(c.isalpha() or c in "+-" for c in t)
    )


def _case_sensitive(want: str, got: str) -> bool:
    """Spec 4.4: case matters when the stored or typed answer has a non-word-initial capital,
    the stored answer has a Greek letter, or either side is element-symbol shaped (the typed
    side too, so `C` never matches a stored `c`)."""
    return (
        _inner_upper(want)
        or _inner_upper(got)
        or _has_greek(want)
        or _symbol_shape(want)
        or _symbol_shape(got)
    )


def fill_blank_correct(question: dict[str, Any], response: str) -> bool:
    """Grade a typed fill-blank response: exact match after `normalize_answer` against the
    answer or any accepted answer; case-insensitive unless `_case_sensitive` (spec 4.4)."""
    got = normalize_answer(response)
    if not got:
        return False
    for a in [question.get("answer", ""), *question.get("accepted_answers", [])]:
        if not isinstance(a, str):
            continue
        want = normalize_answer(a)
        if not want:
            continue
        if want == got or (not _case_sensitive(want, got) and want.casefold() == got.casefold()):
            return True
    return False


def _option_key(option: str) -> str:
    return normalize_formula(option) or option.strip().lower()


# -- validate -------------------------------------------------------------------


def blank_key(question: str) -> str:
    """A question's text with its blank normalised to `BLANK` (as served)."""
    return _BLANK_RE.sub(BLANK, question.strip())


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
        if is_formula_answer(answer):
            return None, FORMULA_REASON
        if not normalize_answer(answer):
            return None, "answer: empty after normalisation"
        accepted = q.get("accepted_answers")
        if accepted is None:
            accepted = []
        if not isinstance(accepted, list) or not all(isinstance(a, str) for a in accepted):
            return None, "accepted_answers: need a list of strings"
        out["answer"] = answer
        if any(is_formula_answer(a) for a in accepted):
            return None, FORMULA_REASON
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
        return _QUOTE_NOT_FOUND

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


class _SeenIndex:
    """Duplicate keys (`_dup_key`) sorted by text length, for the near-duplicate rule: two
    questions are near-duplicates when their signatures don't differ at equal length and
    `SequenceMatcher(None, new, seen).ratio() >= DUPLICATE_RATIO`. The ratio is at most
    2*min(la, lb)/(la + lb), so only seen texts within the matching length window can
    reach it; within it, `quick_ratio` (another upper bound) rules most out before the
    full `ratio`. Exactly the same rule, without comparing against every seen question."""

    def __init__(self, keys: Iterable[tuple[str, str]] = ()) -> None:
        self._keys = sorted(keys, key=lambda k: len(k[0]))
        self._lens = [len(k[0]) for k in self._keys]

    def add(self, key: tuple[str, str]) -> None:
        at = bisect.bisect_right(self._lens, len(key[0]))
        self._lens.insert(at, len(key[0]))
        self._keys.insert(at, key)

    def has_near_duplicate(self, norm: tuple[str, str]) -> bool:
        la, r = len(norm[0]), DUPLICATE_RATIO
        # 2*min(la, lb)/(la + lb) >= r  <=>  la*r/(2-r) <= lb <= la*(2-r)/r (a hair of slack
        # for float rounding: a wider window only costs a comparison)
        lo = bisect.bisect_left(self._lens, la * r / (2 - r) - 1e-6)
        hi = bisect.bisect_right(self._lens, la * (2 - r) / r + 1e-6)
        for text, sig in self._keys[lo:hi]:
            if len(norm[1]) == len(sig) and norm[1] != sig:
                continue
            sm = SequenceMatcher(None, norm[0], text)
            if sm.quick_ratio() >= r and sm.ratio() >= r:
                return True
        return False


#: validation_report flag on a kept question whose quote isn't in the module's PDFs
UNVERIFIED_REASON = "quote not verified (link source)"
#: the same, when some of the module's PDFs could not be read (the quote may be in one)
UNVERIFIED_UNREADABLE_REASON = "quote not verified (some PDFs could not be read)"
_QUOTE_NOT_FOUND = "quote: not found in the sources"


def validate(
    questions: list[Any],
    *,
    seen: list[str],
    source_text: str | None,
    link_source: bool = False,
    unverified: list[dict[str, Any]] | None = None,
    unverified_reason: str = UNVERIFIED_REASON,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split chat questions into (kept, dropped). Dropped entries are
    `{"index", "question", "reason"}`; kept ones are normalised copies (input untouched).

    `seen`: question texts the student has already seen (near-duplicates are dropped, as
    are repeats within `questions`). `source_text`: the module's PDF text; when given, each
    question's `source_quote` must be found in it (None = module has no PDFs, not checked).
    `link_source`: the module also has a link (owner decision 2026-10-28): a quote not
    found in the PDFs may come from the link, so the question is kept and appended to
    `unverified` (same entry shape, reason `UNVERIFIED_REASON`); a missing or too-short
    quote is still dropped, as are format problems and duplicates. A module some of whose
    PDFs could not be read is treated the same way (`unverified_reason` then says so).
    """
    index = _SourceIndex(source_text) if source_text is not None else None
    taken = _SeenIndex(_dup_key(s) for s in seen)
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
        norm = _dup_key(q["question"])
        if taken.has_near_duplicate(norm):
            dropped.append(
                {
                    "index": i,
                    "question": shown,
                    "reason": "duplicate: near-duplicate of a seen question",
                }
            )
            continue
        problem = index.quote_problem(q["source_quote"]) if index is not None else None
        if problem == _QUOTE_NOT_FOUND and link_source:
            if unverified is not None:
                # the text as served (a fill-blank's blank normalised), so it can be matched
                unverified.append(
                    {"index": i, "question": q["question"], "reason": unverified_reason}
                )
            problem = None
        if problem:
            dropped.append({"index": i, "question": shown, "reason": problem})
            continue
        taken.add(norm)
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


@dataclass(frozen=True)
class SourceText:
    """The module's PDF text and the PDFs it is missing."""

    #: None: no PDFs, or none with a text layer (quotes are not checked)
    text: str | None
    #: file names of the PDFs that could not be read: `text` is then incomplete, so a quote
    #: not found in it is not proof the question was made up
    unreadable: tuple[str, ...] = field(default=())


def read_module_source_text(module: Module) -> SourceText:
    """Extracted text of the module's PDF sources, and which PDFs could not be read. `text`
    is None only when the module has no PDFs, or its PDFs have no text layer (scans; logged
    as a warning). Raises `SourceTextUnavailable` when it has PDFs and every one fails to
    load. A complete read is cached in-process per module + files' storage keys and
    checksums (a partial one is not: the next run tries the failed files again)."""
    files = sorted(module.source_files, key=lambda f: f.order_index)
    if not files:
        return SourceText(None)
    key = (module.id, tuple((f.storage_key, f.checksum_sha256) for f in files))
    if key in _text_cache:
        return SourceText(_text_cache[key])
    storage = storage_service.get_storage()
    texts: list[str] = []
    unreadable: list[str] = []
    for f in files:
        try:
            texts.append(_extract_pdf_text(storage.path_for(f.storage_key)))
        except Exception:  # pypdf raises many error types on damaged input
            log.warning("could not read PDF text of %s", f.file_name, exc_info=True)
            unreadable.append(f.file_name)
    if not texts:
        raise SourceTextUnavailable(f"none of the module's {len(files)} PDF(s) could be read")
    text = "\n".join(texts)
    result = text if text.strip() else None
    if result is None:
        log.warning("module %s: PDF sources have no text layer; quotes are not checked", module.id)
    if not unreadable:
        if len(_text_cache) >= _CACHE_MAX:
            _text_cache.pop(next(iter(_text_cache)))
        _text_cache[key] = result
    return SourceText(result, tuple(unreadable))


def module_source_text(module: Module) -> str | None:
    """`read_module_source_text(module).text` (possibly incomplete: see `SourceText`)."""
    return read_module_source_text(module).text
