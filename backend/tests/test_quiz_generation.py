"""Adaptive quiz — chat prompt, answer parsing and question validation."""

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


def test_blank_drops_empty_accepted_entries() -> None:
    kept, _ = qg.validate([blank(accepted_answers=["O", " ", "o2"])], seen=[], source_text=None)
    assert kept[0]["accepted_answers"] == ["O", "o2"]


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
    assert (len(kept), dropped) == (10, [])
    kept_none, dropped_none = qg.validate(qs, seen=[], source_text=None)
    assert len(kept_none) == 10 and dropped_none == []


def test_validate_does_not_mutate_input() -> None:
    qs = qg.parse_questions(ANSWER)
    before = copy.deepcopy(qs)
    qg.validate(qs, seen=[], source_text=SOURCE)
    assert qs == before


# -- normalize_answer -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Racemic   Mixture. ", "racemic mixture"),
        ("\\(\\text{sp}^2\\)", "sp2"),  # edge punctuation, backslash too, is stripped
        ("$sp^2$", "sp2"),
        ("“Quoted”", "quoted"),
        ("\uff33\uff2e\uff11", "sn1"),  # NFKC full-width
        ("(Hello)", "hello"),
        ("a\tb\nc", "a b c"),
        ("", ""),
        ("...", ""),
    ],
)
def test_normalize_answer(raw: str, expected: str) -> None:
    assert qg.normalize_answer(raw) == expected


def test_is_correct_blank_matches_answer_or_accepted() -> None:
    q = blank(answer="Oxygen", accepted_answers=["O", "O2"])
    assert qg.fill_blank_correct(q, " oxygen. ")
    assert qg.fill_blank_correct(q, "$O_2$")
    assert qg.fill_blank_correct(q, "o")
    assert not qg.fill_blank_correct(q, "oxygen gas")
    assert not qg.fill_blank_correct(q, "")


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


def test_blank_answer_must_survive_normalisation() -> None:
    kept, dropped = qg.validate([blank(answer="\\(\\)")], seen=[], source_text=None)
    assert kept == [] and "answer" in dropped[0]["reason"]
    kept, _ = qg.validate([blank(accepted_answers=["$$", "ok"])], seen=[], source_text=None)
    assert kept[0]["accepted_answers"] == ["ok"]


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


def test_grading_matches_latex_and_plain() -> None:
    q = blank(answer="\\(\\text{sp}^2\\) hybridised", accepted_answers=[])
    assert qg.fill_blank_correct(q, "sp^2 hybridised")
    assert qg.fill_blank_correct(q, "SP2 Hybridised.")
    assert not qg.fill_blank_correct(q, "sp3 hybridised")


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
