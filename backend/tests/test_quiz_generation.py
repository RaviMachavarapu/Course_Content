"""Adaptive quiz — chat prompt, answer parsing and question validation."""

# ruff: noqa: RUF001

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.models import Course, Module, ModuleSourceFile
from app.models.enums import ModuleSourceType
from app.pipeline.fixture import FIXTURE_CHAT_ANSWER, FIXTURE_SOURCE_TEXT, FixtureProvider
from app.pipeline.provider import NotebookRef
from app.services import quiz_generation as qg
from app.storage.keys import source_key
from app.storage.service import Storage
from tests.test_pdf_split import _make_pdf

FIX = Path(__file__).parent / "fixtures"
ANSWER = (FIX / "quiz_chat_answer.txt").read_text(encoding="utf-8")
SOURCE = (FIX / "quiz_chat_source.txt").read_text(encoding="utf-8")


def mcq(**over: Any) -> dict[str, Any]:
    q: dict[str, Any] = {
        "type": "mcq",
        "question": "Which planet is the Red Planet?",
        "options": ["Venus", "Mars", "Jupiter", "Saturn"],
        "correct_index": 1,
        "explanation": "Mars.",
        "source_quote": "",
    }
    q.update(over)
    return q


def blank(**over: Any) -> dict[str, Any]:
    q: dict[str, Any] = {
        "type": "fill_blank",
        "question": "Water is made of hydrogen and ____.",
        "answer": "oxygen",
        "accepted_answers": ["O"],
        "explanation": "H2O.",
        "source_quote": "",
    }
    q.update(over)
    return q


def reasons(dropped: list[dict[str, Any]]) -> list[str]:
    return [d["reason"] for d in dropped]


# -- prompt -----------------------------------------------------------------


def test_prompt_mix_and_avoid_list() -> None:
    p = qg.build_prompt(10, ["What is X?", "Name the Y"])
    assert "6 multiple-choice" in p and "4 fill-in-the-blank" in p
    assert "What is X?" in p and "Name the Y" in p
    assert "JSON array" in p and "____" in p
    assert "6 multiple-choice" in qg.build_prompt(10, [])
    assert "7 multiple-choice" in qg.build_prompt(12, [])  # round(7.2)
    assert "What is X?" not in qg.build_prompt(10, [])


def test_prompt_example_does_not_put_the_answer_first() -> None:
    p = qg.build_prompt(10, [])
    assert '"correct_index":0' not in p
    assert '"correct_index":2' in p


def test_prompt_caps_avoid_list_at_60() -> None:
    p = qg.build_prompt(10, [f"seen question number {i}" for i in range(100)])
    assert "seen question number 59" in p
    assert "seen question number 60" not in p


# -- parse ------------------------------------------------------------------


def test_parse_real_chat_answer() -> None:
    qs = qg.parse_questions(ANSWER)
    assert len(qs) == 10
    assert [q["type"] for q in qs].count("mcq") == 6
    assert "\\(" in qs[0]["question"]


def test_parse_prose_around_json_and_fences() -> None:
    wrapped = (
        f"Sure! Here are the questions [see below]:\n```json\n{ANSWER}\n```\nHope that helps [1]."
    )
    assert qg.parse_questions(wrapped) == qg.parse_questions(ANSWER)


def test_parse_skips_non_question_brackets_before_array() -> None:
    assert qg.parse_questions('Note [1] and [2, 3]. [{"type": "mcq"}] done') == [{"type": "mcq"}]


def test_parse_repairs_unescaped_latex_backslashes() -> None:
    raw = r'[{"type": "fill_blank", "question": "x \(S_N2\) ____", "answer": "a"}]'
    assert "\\(" in raw and "\\\\(" not in raw
    assert qg.parse_questions(raw)[0]["question"] == "x \\(S_N2\\) ____"


@pytest.mark.parametrize("answer", ["", "no json here", "[1, 2, 3]", "[{broken", "{}"])
def test_parse_no_array_returns_empty(answer: str) -> None:
    assert qg.parse_questions(answer) == []


def test_fixture_answer_validates_fully_with_fixture_source_text() -> None:
    qs = qg.parse_questions(FIXTURE_CHAT_ANSWER)
    kept, dropped = qg.validate(qs, seen=[], source_text=FIXTURE_SOURCE_TEXT)
    assert len(kept) == 7 and dropped == []


def test_fixture_provider_answer_parses_and_validates() -> None:
    nb = NotebookRef("fixture-nb")
    p = FixtureProvider()
    assert p.query(nb, "hi") == FIXTURE_CHAT_ANSWER
    kept, dropped = qg.validate(qg.parse_questions(FIXTURE_CHAT_ANSWER), seen=[], source_text=None)
    assert len(kept) == 7 and dropped == []


# -- validate: shape --------------------------------------------------------


def test_valid_questions_are_kept_and_normalised() -> None:
    kept, dropped = qg.validate(
        [mcq(extra="x"), blank(accepted_answers=None, explanation=None)], seen=[], source_text=None
    )
    assert dropped == []
    assert kept[0] == {
        "type": "mcq",
        "question": "Which planet is the Red Planet?",
        "options": ["Venus", "Mars", "Jupiter", "Saturn"],
        "correct_index": 1,
        "explanation": "Mars.",
        "source_quote": "",
    }
    assert kept[1]["accepted_answers"] == [] and kept[1]["explanation"] == ""


@pytest.mark.parametrize(
    ("q", "reason"),
    [
        (mcq(options=["a", "b", "c"]), "options"),
        (mcq(options=["a", "b", "c", "d", "e"]), "options"),
        (mcq(options="abcd"), "options"),
        (mcq(options=["a", "b", "c", ""]), "options"),
        (mcq(options=["a", "b", "c", "  "]), "options"),
        (mcq(options=["a", "b", "c", 4]), "options"),
        # two correct-looking options: identical once normalised
        (mcq(options=["Mars", "mars.", "Venus", "Saturn"]), "options"),
        (mcq(options=["\\(3\\)", "$3$", "4", "5"]), "options"),
        (mcq(correct_index=4), "correct_index"),
        (mcq(correct_index=-1), "correct_index"),
        (mcq(correct_index="1"), "correct_index"),
        (mcq(correct_index=True), "correct_index"),
        (mcq(correct_index=None), "correct_index"),
        (mcq(question=""), "question"),
        (mcq(question=5), "question"),
        (blank(question="no blank here"), "blank"),
        (blank(question="two ____ blanks ____"), "blank"),
        (blank(answer=""), "answer"),
        (blank(answer="  "), "answer"),
        (blank(answer=3), "answer"),
        (blank(accepted_answers="O"), "accepted_answers"),
        (blank(accepted_answers=[1]), "accepted_answers"),
        ({"type": "essay", "question": "q"}, "type"),
        ("not a dict", "shape"),
    ],
)
def test_invalid_shape_is_dropped_with_reason(q: Any, reason: str) -> None:
    kept, dropped = qg.validate([q], seen=[], source_text=None)
    assert kept == []
    assert len(dropped) == 1 and reason in dropped[0]["reason"]
    assert "question" in dropped[0] and "index" in dropped[0]


def test_dropped_entries_keep_position_in_input() -> None:
    kept, dropped = qg.validate(
        [mcq(), blank(answer=""), mcq(question="Another one?")], seen=[], source_text=None
    )
    assert [d["index"] for d in dropped] == [1]
    assert len(kept) == 2


def test_blank_marker_longer_underscores_counts_once() -> None:
    kept, _ = qg.validate([blank(question="Water is H and ________.")], seen=[], source_text=None)
    assert len(kept) == 1


# -- validate: duplicates ---------------------------------------------------


def test_near_duplicate_of_seen_is_dropped() -> None:
    seen = ["Which planet is the Red Planet??"]
    kept, dropped = qg.validate(
        [
            mcq(question="Which planet is the red planet?"),
            mcq(question="How many moons does Mars have?"),
        ],
        seen=seen,
        source_text=None,
    )
    assert [k["question"] for k in kept] == ["How many moons does Mars have?"]
    assert "duplicate" in dropped[0]["reason"]


def test_ratio_threshold_is_085() -> None:
    base = "abcdefghijklmnopqrst"  # 20 chars
    near = base[:-3] + "xyz"  # ratio 0.85 -> dropped
    far = base[:-4] + "wxyz"  # ratio 0.80 -> kept
    from difflib import SequenceMatcher

    assert (
        SequenceMatcher(None, base, near).ratio() >= 0.85 > SequenceMatcher(None, base, far).ratio()
    )
    kept, _ = qg.validate([mcq(question=near), mcq(question=far)], seen=[base], source_text=None)
    assert [k["question"] for k in kept] == [far]


def test_duplicates_within_the_batch_keep_first() -> None:
    kept, dropped = qg.validate(
        [mcq(), mcq(question="Which planet is the Red Planet ?")], seen=[], source_text=None
    )
    assert len(kept) == 1 and "duplicate" in dropped[0]["reason"]


# -- validate: source quotes ------------------------------------------------


def test_quote_exact_substring_after_normalisation() -> None:
    src = "The  Quick brown-fox jumps, over the lazy dog."
    q = mcq(source_quote="quick BROWN fox jumps over the lazy dog")
    kept, _ = qg.validate([q], seen=[], source_text=src)
    assert len(kept) == 1


def test_quote_must_match_whole_words() -> None:
    kept, dropped = qg.validate([mcq(source_quote="quic")], seen=[], source_text="the quick fox")
    assert kept == [] and "quote" in dropped[0]["reason"]


def test_quote_words_in_order_within_window() -> None:
    src = "carbon is S N 1 bonded to five atoms simultaneously"
    # "sn1" never appears; but words in order with gaps: carbon ... five atoms
    q = mcq(source_quote="carbon bonded five atoms")  # 4 words, span 7 words <= 12
    assert len(qg.validate([q], seen=[], source_text=src)[0]) == 1
    far = "carbon " + "x " * 20 + "bonded five atoms"
    kept, dropped = qg.validate([q], seen=[], source_text=far)
    assert kept == [] and "quote" in dropped[0]["reason"]


def test_quote_words_out_of_order_rejected() -> None:
    kept, _ = qg.validate(
        [mcq(source_quote="atoms five")], seen=[], source_text="five atoms are here"
    )
    assert kept == []


def test_missing_quote_dropped_only_when_source_present() -> None:
    assert len(qg.validate([mcq(source_quote="")], seen=[], source_text=None)[0]) == 1
    kept, dropped = qg.validate([mcq(source_quote="")], seen=[], source_text="some text")
    assert kept == [] and "quote" in dropped[0]["reason"]


def test_quote_not_checked_without_pdf_sources() -> None:
    assert len(qg.validate([mcq(source_quote="made up")], seen=[], source_text=None)[0]) == 1


def test_real_chat_answer_against_real_source() -> None:
    qs = qg.parse_questions(ANSWER)
    kept, dropped = qg.validate(qs, seen=[], source_text=SOURCE)
    # 7/10 verbatim; 3/10 only after LaTeX stripping / spaceless matching
    # the 4 fill-blanks: sp2-hybridised-style answers are formulas and now dropped
    assert len(kept) + len(dropped) == 10
    assert all(d["reason"] == qg.FORMULA_REASON for d in dropped)
    assert len([k for k in kept if k["type"] == "mcq"]) == 6
    kept_none, dropped_none = qg.validate(qs, seen=[], source_text=None)
    assert len(kept_none) == 9
    assert [d["reason"] for d in dropped_none] == [qg.FORMULA_REASON]  # sp2-hybridised


def test_validate_does_not_mutate_input() -> None:
    qs = qg.parse_questions(ANSWER)
    before = copy.deepcopy(qs)
    qg.validate(qs, seen=[], source_text=SOURCE)
    assert qs == before


# -- normalize_answer / grading: see "fix round 3" below ---------------------


# -- module_source_text ------------------------------------------------------


def _module_with_pdfs(db: Session, storage: Storage, tmp_path: Path, pdfs: list[bytes]) -> Module:
    course = Course(title="C", slug=f"c-{uuid.uuid4()}")
    module = Module(course=course, order_index=0, title="M", source_type=ModuleSourceType.pdf)
    db.add(module)
    db.flush()
    for i, data in enumerate(pdfs):
        key = source_key(course.id, module.id, i, f"f{i}")
        storage.put(key, data, "application/pdf")
        db.add(
            ModuleSourceFile(
                module_id=module.id,
                order_index=i,
                file_name=f"f{i}.pdf",
                size_bytes=len(data),
                checksum_sha256=f"{i}" * 64,
                storage_key=key,
                page_count=1,
                parts=[],
            )
        )
    db.flush()
    db.refresh(module)
    return module


def test_module_source_text_none_without_pdfs(
    db_session: Session, media_storage: Storage, tmp_path: Path
) -> None:
    assert qg.module_source_text(_module_with_pdfs(db_session, media_storage, tmp_path, [])) is None


def test_module_source_text_extracts_and_caches(
    db_session: Session, media_storage: Storage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = _make_pdf(tmp_path / "a.pdf", [(3, 0), (2, 0)]).read_bytes()
    b = _make_pdf(tmp_path / "b.pdf", [(4, 0)]).read_bytes()
    module = _module_with_pdfs(db_session, media_storage, tmp_path, [a, b])
    text = qg.module_source_text(module)
    assert text is not None and text.split().count("word") == 9

    calls: list[Path] = []
    real = qg._extract_pdf_text
    monkeypatch.setattr(qg, "_extract_pdf_text", lambda p: calls.append(p) or real(p))
    assert qg.module_source_text(module) == text
    assert calls == []  # cached


def test_module_source_text_cache_busts_on_new_checksum(
    db_session: Session, media_storage: Storage, tmp_path: Path
) -> None:
    a = _make_pdf(tmp_path / "a.pdf", [(3, 0)]).read_bytes()
    module = _module_with_pdfs(db_session, media_storage, tmp_path, [a])
    first = qg.module_source_text(module)
    b = _make_pdf(tmp_path / "b.pdf", [(5, 0)]).read_bytes()
    module.source_files[0].storage_key = (
        _module_with_pdfs(db_session, media_storage, tmp_path, [b]).source_files[0].storage_key
    )
    module.source_files[0].checksum_sha256 = "f" * 64
    second = qg.module_source_text(module)
    assert first is not None and second is not None
    assert second.split().count("word") == 5


def test_module_source_text_none_when_no_text_layer(
    db_session: Session, media_storage: Storage, tmp_path: Path
) -> None:
    blank_pdf = _make_pdf(tmp_path / "a.pdf", [(0, 0)]).read_bytes()
    assert (
        qg.module_source_text(_module_with_pdfs(db_session, media_storage, tmp_path, [blank_pdf]))
        is None
    )


def test_module_source_text_skips_unreadable_file(
    db_session: Session, media_storage: Storage, tmp_path: Path
) -> None:
    good = _make_pdf(tmp_path / "a.pdf", [(3, 0)]).read_bytes()
    module = _module_with_pdfs(db_session, media_storage, tmp_path, [b"not a pdf", good])
    text = qg.module_source_text(module)
    assert text is not None and text.split().count("word") == 3


# keep json import used (answers are JSON text)
def test_answer_fixture_is_json_text() -> None:
    assert isinstance(json.loads(ANSWER), list)


# -- fix round 1 -------------------------------------------------------------


def _one(question_fields: str) -> dict[str, Any]:
    qs = qg.parse_questions(f"[{{{question_fields}}}]")
    assert len(qs) == 1
    return qs[0]


def test_parse_single_backslash_latex_that_forms_valid_escapes() -> None:
    raw = (
        r'[{"type":"fill_blank","question":"Rate = ____","answer":"$\frac{1}{2}k$",'
        r'"accepted_answers":["$\beta$","$\nu$","$\text{S}_\text{N}2$","$\neq$"]}]'
    ).replace("\\\\", "\\")
    assert "\\\\" not in raw
    q = qg.parse_questions(raw)[0]
    assert q["answer"] == "$\\frac{1}{2}k$"
    assert q["accepted_answers"] == ["$\\beta$", "$\\nu$", "$\\text{S}_\\text{N}2$", "$\\neq$"]


def test_parse_properly_escaped_latex_is_untouched() -> None:
    raw = (
        r'[{"type":"mcq","question":"\\(\\text{S}_\\text{N}2\\) and \\nu and \\beta","options":[]}]'
    )
    assert (
        qg.parse_questions(raw)[0]["question"] == "\\(\\text{S}_\\text{N}2\\) and \\nu and \\beta"
    )


def test_parse_ordinary_newline_kept() -> None:
    q = qg.parse_questions('[{"type":"mcq","question":"a\\n2) B?"}]')[0]
    assert q["question"] == "a\n2) B?"


def test_parse_drops_questions_with_control_characters() -> None:
    assert qg.parse_questions('[{"type":"mcq","question":"a\\u0001b"}]') == []


def test_parse_objects_fallback_citations_and_trailing_comma() -> None:
    raw = (
        '[{"type":"mcq","question":"Q1?"} [1], {"type":"mcq","question":"Q2?"} [2,3], '
        '{"type":"mcq","question":"Q3?"},]'
    )
    assert [q["question"] for q in qg.parse_questions(raw)] == ["Q1?", "Q2?", "Q3?"]


def test_parse_objects_fallback_with_single_backslashes() -> None:
    raw = r'[{"type":"mcq","question":"\(x\)?"} [1], {"type":"mcq","question":"b?"}]'.replace(
        "\\\\", "\\"
    )
    assert [q["question"] for q in qg.parse_questions(raw)] == ["\\(x\\)?", "b?"]


def test_prompt_tells_model_to_escape_backslashes() -> None:
    assert "doubled" in qg.build_prompt(10, []) and "\\\\(" in qg.build_prompt(10, [])


def test_underscore_runs_rewritten_to_four() -> None:
    kept, dropped = qg.validate(
        [blank(question="A ___ b"), blank(question="Other ________ c")], seen=[], source_text=None
    )
    assert [k["question"] for k in kept] == ["A ____ b", "Other ____ c"] and dropped == []
    kept, dropped = qg.validate([blank(question="A ___ and ____")], seen=[], source_text=None)
    assert kept == [] and "blank" in dropped[0]["reason"]


def test_quote_latex_stripped_and_spaceless_fallback() -> None:
    src = "Actually the carbocation formed in the slow step being sp2 hybridised is planar. SN1 reactions are generally carried out in polar protic solvents."
    split = "S N 1 reactions are generally carried out in polar protic solvents. sp 2 stuff"
    for quote in (
        r"Actually the carbocation formed in the slow step being \(\text{sp}^2\) hybridised is planar",
        r"\(\text{S}_\text{N}1\) reactions are generally carried out in polar protic solvents",
    ):
        assert len(qg.validate([mcq(source_quote=quote)], seen=[], source_text=src)[0]) == 1
    quote = "SN1 reactions are generally carried out in polar protic solvents"
    assert len(qg.validate([mcq(source_quote=quote)], seen=[], source_text=split)[0]) == 1


# ruff: noqa: E501
FABRICATED = [
    "Thus, in the transition state, carbon is simultaneously bonded to six atoms.",
    "Thus, in the transition state, carbon is simultaneously bonded to four atoms.",
    "SN1 reactions are generally carried out in polar aprotic solvents.",
    "SN2 reactions are generally carried out in polar protic solvents (like water, alcohol, acetic acid, etc.).",
    "the carbocation formed in the slow step being sp3 hybridised is planar",
    "no effect on reactivity of haloarenes is observed by the presence of electron withdrawing group at para-position.",
    "C-Cl bond length in haloarene is 177 pm",
    "chlorobenzene is converted to phenol at 523 K and 300 atmospheres",
    r"\(\text{S}_\text{N}2\) reactions are generally carried out in polar protic solvents",
]


@pytest.mark.parametrize("quote", FABRICATED)
def test_fabricated_quotes_rejected_against_real_source(quote: str) -> None:
    kept, dropped = qg.validate([mcq(source_quote=quote)], seen=[], source_text=SOURCE)
    assert kept == [] and "quote" in dropped[0]["reason"]


@pytest.mark.parametrize("quote", ["", "the", "carbon", "carbon is bonded", "a b c d"])
def test_short_quotes_dropped(quote: str) -> None:
    kept, dropped = qg.validate(
        [mcq(source_quote=quote)], seen=[], source_text="carbon is bonded a b c d"
    )
    assert kept == [] and "quote" in dropped[0]["reason"]
    if quote:
        assert "too short" in dropped[0]["reason"]


def test_short_but_long_enough_in_characters_is_accepted() -> None:
    src = "Racemisation happens readily."
    assert (
        len(
            qg.validate(
                [mcq(source_quote="Racemisation happens readily")], seen=[], source_text=src
            )[0]
        )
        == 1
    )


def test_latex_variants_are_near_duplicates() -> None:
    seen = ["Which solvent is used for SN1 reactions?"]
    kept, dropped = qg.validate(
        [mcq(question="Which solvent is used for \\(\\text{S}_\\text{N}1\\) reactions?")],
        seen=seen,
        source_text=None,
    )
    assert kept == [] and "duplicate" in dropped[0]["reason"]


def test_module_source_text_raises_when_every_pdf_unreadable(
    db_session: Session, media_storage: Storage, tmp_path: Path
) -> None:
    module = _module_with_pdfs(db_session, media_storage, tmp_path, [b"nope", b"also nope"])
    with pytest.raises(qg.SourceTextUnavailable):
        qg.module_source_text(module)
    with pytest.raises(qg.SourceTextUnavailable):  # failures are not cached as "no PDFs"
        qg.module_source_text(module)


def test_module_source_text_warns_for_scans(
    db_session: Session, media_storage: Storage, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(qg.log, "warning", lambda msg, *a, **k: warnings.append(msg % a))
    scan = _make_pdf(tmp_path / "a.pdf", [(0, 0)]).read_bytes()
    module = _module_with_pdfs(db_session, media_storage, tmp_path, [scan])
    assert qg.module_source_text(module) is None
    assert any("no text layer" in w for w in warnings)


# -- fix round 2: translation, not deletion ----------------------------------


def test_mcq_options_with_commands_stay_distinct() -> None:
    for opts in (
        [r"\(\alpha\)-helix", r"\(\beta\)-helix", "sheet", "coil"],
        [r"\(x^2\)", r"\(x_2\)", "x", "2x"],
        [r"\(\leq 5\)", r"\(\geq 5\)", "5 only", "none"],
        [r"\(\Delta G < 0\)", r"\(\Delta G > 0\)", r"\(\Delta H < 0\)", "none"],
        [r"\(\hbar\)", r"\(\hslash\)", "a", "b"],
    ):
        kept, dropped = qg.validate([mcq(options=opts)], seen=[], source_text=None)
        assert len(kept) == 1, (opts, dropped)


def test_negated_latex_quote_rejected() -> None:
    quote = r"\(\text{S}_\text{N}1\) reactions are \(\neg\) generally carried out in polar protic solvents"
    kept, dropped = qg.validate([mcq(source_quote=quote)], seen=[], source_text=SOURCE)
    assert kept == [] and "quote" in dropped[0]["reason"]


def test_comparison_questions_are_not_duplicates() -> None:
    seen = [r"Which statement is true when \(\Delta G < 0\) for a reaction at constant T?"]
    kept, _ = qg.validate(
        [
            mcq(
                question=r"Which statement is true when \(\Delta G > 0\) for a reaction at constant T?"
            )
        ],
        seen=seen,
        source_text=None,
    )
    assert len(kept) == 1
    kept, _ = qg.validate(
        [
            mcq(
                question=r"Which statement is true when \(\Delta G < 0\) for a reaction at constant T?"
            )
        ],
        seen=seen,
        source_text=None,
    )
    assert kept == []


def test_superscript_vs_subscript_questions_are_not_duplicates() -> None:
    kept, _ = qg.validate(
        [mcq(question=r"What is \(x^2\) here?")], seen=[r"What is \(x_2\) here?"], source_text=None
    )
    assert len(kept) == 1


# -- fix round 3: words and plain numbers only (spec 4.4) ----------------------

#: reviewer probe pairs: each must be dropped at validation (formula answer) or graded wrong
PROBE_PAIRS = [
    (r"\(\text{H}_2\text{O}\)", "H^2O"),
    (r"\(10^{-3}\)", r"10^{3}"),
    (r"\(\text{Fe}^{3+}\)", r"\(\text{Fe}^{2+}\)"),
    (r"\(\Delta\)", r"\(\delta\)"),
    (r"\(\le\)", "<"),
    (r"\(\approx\)", "="),
    (r"\(\to\)", r"\(\leftarrow\)"),
    (r"\(\frac{\frac{1}{2}}{3}\)", "1/2/3"),
    (r"\(\frac{1}{\frac{2}{3}}\)", "1/2/3"),
    (r"\(\frac{a+b}{c}\)", "a+b/c"),
    (r"\(\frac{1}{2x}\)", "1/2x"),
    (r"\(\frac{1}{2}x\)", "1/2x"),
    (r"\(\sqrt[3]{x}\)", r"\(\sqrt{x}\)"),
    (r"\(\sqrt{x+1}\)", "√x+1"),
    (r"\(\sqrt{x}+1\)", "√x+1"),
    (r"\(\vec{F}\)", "F"),
    (r"\(\bar{x}\)", "x"),
    (r"\(\hat{H}\)", "H"),
    (r"\(\ce{Na+}\)", "Na"),
    (r"\(\ce{Na+}\)", "Na+"),
    (r"\(x^{2+1}\)", "x^2+1"),
    (r"\(e^{x+1}\)", "e^x+1"),
    (r"\(x_{n+1}\)", "x_n+1"),
    (r"\(x_{n+1}\)", "xn+1"),
    (r"\(-3\)", "3"),
    ("-3", "3"),
    (r"\(\text{CO}_3^{2-}\)", "CO3^2"),
    (r"\(\text{Cl}^-\)", "Cl^"),
    (r"\(e^-\)", "e^"),
    (r"\(\text{CO}\)", "Co"),
    ("NO", "No"),
    (r"\(-40^\circ\text{C}\)", "40°C"),
    ("−3", "3"),
    (r"\(\neq\)", "="),
    (r"\(\not=\)", "="),
    (r"\(\mathbf{F}\)", "F"),
    (r"\(\pm\)", "+"),
    (r"\(\cdot\)", "."),
    (r"\(\Delta H < 0\)", "ΔH < 0"),
    (r"\(\Delta H < 0\)", "ΔH<0"),
    (r"\(a^{b^c}\)", "a^b^c"),
    (r"\((a^b)^c\)", "a^b^c"),
    (r"\(2^{10}\)", "2^1 0"),
    (r"\(1.5\)", "15"),
    (r"\(1,5\)", "15"),
    (r"\(0.5\)", ".5"),
    (r"\(5.\)", "5"),
    (r"\(\%\)", "%"),
    (r"50\%", "50"),
    ("50%", "50"),
    (r"\(\text{sp}^3\text{d}\)", "sp^3d"),
    (r"\(\text{sp}^3\text{d}\)", "sp3d"),
    (r"\(\text{Ca}^{2+}\)", "Ca2+"),
    (r"\(\text{CH}_3\)", "CH^3"),
]


def _graded(answer: str, typed: str) -> str | bool:
    q = {"type": "fill_blank", "question": "A ____", "answer": answer, "accepted_answers": []}
    kept, dropped = qg.validate([q], seen=[], source_text=None)
    if not kept:
        return "dropped: " + dropped[0]["reason"]
    return qg.fill_blank_correct(kept[0], typed)


@pytest.mark.parametrize(("answer", "typed"), PROBE_PAIRS)
def test_probe_pairs_dropped_or_graded_wrong(answer: str, typed: str) -> None:
    assert _graded(answer, typed) in (False, "dropped: " + qg.FORMULA_REASON)


@pytest.mark.parametrize(
    ("answer", "typed", "expected"),
    [
        ("-3", "3", False),
        ("3", "-3", False),
        ("-3", "\u22123", True),
        ("\u22123", "-3", True),
        ("50%", "50", False),
        ("50%", "50 %", False),
        ("50%", "50%", True),
        ("CO", "Co", False),
        ("CO", "CO", True),
        ("pH", "PH", False),
        ("pH", "pH", True),
        ("NaCl", "nacl", False),
        ("mRNA", "MRNA", False),
        ("0.5", ".5", True),
        (".5", "0.5", True),
        ("1.5", "15", False),
        ("Racemic mixture.", "racemic mixture", True),
        ("racemic mixture", "  Racemic   Mixture! ", True),
        ("racemic mixture", "racemic", False),
        ("Paris", "paris", True),
        ("40 \u00b0C", "40 \u00b0C", True),
        ("40 \u00b0C", "40 C", False),
        ("+5", "5", False),
        ("\u201cracemic\u201d", "racemic", True),
        ("\uff33odium", "Sodium", True),  # NFKC
        # spec 4.4 symmetric case rule (fix round 4)
        ("Co", "CO", False),
        ("No", "NO", False),
        ("Na", "NA", False),
        ("C", "c", False),
        ("H", "h", False),
        ("c", "C", False),
        ("Na+", "na+", False),
        ("\u03b4", "\u0394", False),
        ("\u03b4+", "\u0394+", False),
        ("\u03c3", "\u03a3", False),
        ("\u03c0", "\u03a0", False),
        ("\u0394", "\u0394", True),
        ("Co", "Co", True),
        ("C", "C", True),
        ("Paris", "PARIS", False),
        ("racemic mixture", "Racemic Mixture", True),
        ("Racemic Mixture", "racemic mixture", True),
        # primes, curly quotes, en dash
        ("3'", "3", False),
        ("3", "3'", False),
        ("3\u2019", "3'", True),
        ("3\u2032", "3'", True),
        ("3''", "3'", False),
        ("3'.", "3'", True),
        ("'5'", "5", True),
        ("Zaitsev\u2019s rule", "Zaitsev's rule", True),
        ("Zaitsev's rule", "Zaitsev\u2019s rule", True),
        ("Zaitsev's rule", "Zaitsevs rule", False),
        ("2\u20133", "2-3", True),
        ("2-3", "2\u20133", True),
    ],
)
def test_grading_per_spec(answer: str, typed: str, expected: bool) -> None:
    assert qg.fill_blank_correct({"answer": answer, "accepted_answers": []}, typed) is expected


def test_grading_accepted_answers_and_empty_response() -> None:
    q = {"answer": "oxygen", "accepted_answers": ["O2gas", "dioxygen"]}
    assert qg.fill_blank_correct(q, "Dioxygen.")
    assert not qg.fill_blank_correct(q, "")
    assert not qg.fill_blank_correct(q, "  ")


@pytest.mark.parametrize(
    "answer",
    [
        "H2O", "CO2", "Fe3", "SN2", "sp2", "NaCl2", r"\(x\)", "$5$", r"\alpha", "x^2", "x_2", "{a}",
        "\u221a2", "1/2", "a/b", "a = b", "x < 5", "(aq)", "\u00d7", "\u0394H<0", "10^-3", r"\frac{1}{2}",
    ],
)  # fmt: skip
def test_formula_answers_dropped_at_validation(answer: str) -> None:
    kept, dropped = qg.validate([blank(answer=answer)], seen=[], source_text=None)
    assert kept == [] and dropped[0]["reason"] == qg.FORMULA_REASON
    kept, dropped = qg.validate([blank(accepted_answers=[answer])], seen=[], source_text=None)
    assert kept == [] and dropped[0]["reason"] == qg.FORMULA_REASON


@pytest.mark.parametrize(
    "answer",
    [
        "racemic mixture", "5", "-3", "+3", "0.5", "1,5", "50%", "40 \u00b0C", "Paris", "NaCl",
        "mRNA", "pH", "don't", "d\u00e9j\u00e0 vu", "\u03b1-helix", "\u0394", "\u5c71", "Zaitsev's rule", "2-3",
        "carbon-carbon bond",
    ],
)  # fmt: skip
def test_word_and_number_answers_are_kept(answer: str) -> None:
    kept, dropped = qg.validate([blank(answer=answer)], seen=[], source_text=None)
    assert len(kept) == 1, dropped


def test_empty_after_normalisation_dropped_and_empty_accepted_removed() -> None:
    kept, dropped = qg.validate([blank(answer="...")], seen=[], source_text=None)
    assert kept == [] and "answer" in dropped[0]["reason"]
    kept, _ = qg.validate([blank(accepted_answers=["O", " ", "..."])], seen=[], source_text=None)
    assert kept[0]["accepted_answers"] == ["O"]


@pytest.mark.parametrize("answer", ["2\u00a0000", "2\u202f000", "3\u2032", "2\u20133"])
def test_nfkc_and_dash_answers_are_not_formulas(answer: str) -> None:
    assert not qg.is_formula_answer(answer)
    kept, dropped = qg.validate([blank(answer=answer)], seen=[], source_text=None)
    assert len(kept) == 1, dropped


def test_prompt_asks_for_accepted_variants() -> None:
    p = qg.build_prompt(10, [])
    assert "accepted_answers" in p and "plural" in p and "spellings" in p and "hyphenated" in p


def test_prompt_forbids_formula_blank_answers() -> None:
    p = qg.build_prompt(10, [])
    assert "never a formula" in p and "must be multiple-choice" in p


def test_extra_item_question_is_still_a_duplicate() -> None:
    seen = ["In the transition state of an SN2 reaction, how many atoms bond to carbon?"]
    q = mcq(
        question="In the transition state of an SN2 reaction, how many atoms bond to carbon (5)?"
    )
    kept, dropped = qg.validate([q], seen=seen, source_text=None)
    assert kept == [] and "duplicate" in dropped[0]["reason"]


def test_substituted_item_question_is_not_a_duplicate() -> None:
    seen = ["In the transition state of an SN2 reaction, how many atoms bond to carbon (5)?"]
    q = mcq(
        question="In the transition state of an SN2 reaction, how many atoms bond to carbon (4)?"
    )
    assert len(qg.validate([q], seen=seen, source_text=None)[0]) == 1


def test_live_sample_fill_blanks_and_mcqs() -> None:
    qs = qg.parse_questions(ANSWER)
    kept, dropped = qg.validate(qs, seen=[], source_text=SOURCE)
    blanks = [q for q in qs if q["type"] == "fill_blank"]
    assert len(blanks) == 4
    kept_blank = [k for k in kept if k["type"] == "fill_blank"]
    assert [k["type"] for k in kept].count("mcq") == 6  # MCQs unaffected
    assert len(kept_blank) + len(dropped) == 4
    assert all(d["reason"] == qg.FORMULA_REASON for d in dropped)


# -- mixed link + PDF modules (owner decision 2026-10-28) ---------------------------------
def test_link_and_pdf_module_keeps_a_quote_not_found_in_the_pdfs_and_flags_it() -> None:
    flagged: list[dict[str, Any]] = []
    kept, dropped = qg.validate(
        [
            mcq(source_quote="a sentence that was only said in the video"),
            mcq(question="Q2?", source_quote="the quick brown fox jumps over the lazy dog"),
        ],
        seen=[],
        source_text="so the quick brown fox jumps over the lazy dog today",
        link_source=True,
        unverified=flagged,
    )
    assert len(kept) == 2 and dropped == []
    assert flagged == [
        {"index": 0, "question": "Which planet is the Red Planet?", "reason": qg.UNVERIFIED_REASON}
    ]
    assert qg.UNVERIFIED_REASON == "quote not verified (link source)"


def test_link_and_pdf_module_still_applies_format_duplicate_and_missing_quote_checks() -> None:
    flagged: list[dict[str, Any]] = []
    kept, dropped = qg.validate(
        [
            mcq(options=["a", "b"]),  # format
            mcq(source_quote="a sentence that was only said in the video"),
            mcq(
                source_quote="another sentence that was only said in the video"
            ),  # duplicate question
            mcq(question="No quote at all?", source_quote=""),
        ],
        seen=[],
        source_text="so the quick brown fox jumps over the lazy dog today",
        link_source=True,
        unverified=flagged,
    )
    assert len(kept) == 1
    reasons = [d["reason"] for d in dropped]
    assert any(r.startswith("duplicate") for r in reasons)
    assert "quote: missing" in reasons
    assert len(dropped) == 3 and len(flagged) == 1


def test_pdf_only_module_still_drops_a_quote_not_in_the_pdfs() -> None:
    kept, dropped = qg.validate(
        [mcq(source_quote="a sentence that was only said in the video")],
        seen=[],
        source_text="the quick fox",
    )
    assert kept == [] and dropped[0]["reason"] == "quote: not found in the sources"
