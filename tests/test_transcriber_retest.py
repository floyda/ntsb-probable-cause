"""S2.7 track 2, Tasks 8-10: the re-test against Qwen."""

import hashlib
import json
from fractions import Fraction
from pathlib import Path

import pytest
from scripts import transcriber_retest as tr
from scripts import transcriber_test as tt
from scripts.transcriber_test import CandidateResult
from tests.test_transcriber_test import _offline_docs, _put, _seed, _text_pdf, _write_csv

from ntsb_probable_cause.docket.documents import CachedDocuments
from ntsb_probable_cause.docket.pages import page_text
from ntsb_probable_cause.docket.transcribe import TranscriptionCache
from ntsb_probable_cause.settings import Settings


def _result(model: str, **over: object) -> CandidateResult:
    fields: dict[str, object] = {
        "model": model,
        "cost_per_page": 0.0005,
        "hw_lines": 1548,
        "hw_right": 1036,
        "hw_inventing": 54,
        "photo_pages": 50,
        "photo_invented": 2,
        "typed_chars": 164464,
        "typed_errors": 20219,
        "mixed_pages": 25,
        "mixed_invented": 0,
        "hw_pages": 25,
        "hw_format_failed": 2,
    }
    fields.update(over)
    return CandidateResult(**fields)  # type: ignore[arg-type]


def test_a_candidate_equal_to_qwen_and_cheaper_replaces_it() -> None:
    chosen, _ = tr.choose_against_qwen([_result("a/m")])
    assert chosen == "a/m"


@pytest.mark.parametrize(
    "over",
    [
        {"hw_inventing": 55},  # 55 in 1548 lines is over 3.5 per 100
        {"photo_invented": 3},
        {"mixed_invented": 1},
        {"hw_format_failed": 3},
        {"hw_right": 958},  # 958/1548 = 61.89%, under 61.9%
        {"typed_errors": 21858},  # 13.29..., over 13.29 per 100 by one character
        {"cost_per_page": 0.00154},  # not below Qwen's
    ],
)
def test_each_measure_alone_keeps_qwen(over: dict[str, object]) -> None:
    chosen, notes = tr.choose_against_qwen([_result("a/m", **over)])
    assert chosen is None
    assert any("a/m: out" in n for n in notes)
    assert notes[-1] == "no candidate meets all seven: Qwen stays (decision 0100 item 3)"


def test_the_boundary_values_are_the_first_integers_past_each_limit() -> None:
    # The arithmetic behind the parametrised cases above, checked exactly.
    assert Fraction(100 * 54, 1548) <= Fraction(7, 2) < Fraction(100 * 55, 1548)
    assert Fraction(958, 1548) < Fraction(619, 1000) <= Fraction(959, 1548)
    limit = Fraction(1329, 100)
    assert Fraction(100 * 21857, 164464) <= limit < Fraction(100 * 21858, 164464)


def test_of_the_candidates_that_meet_all_seven_the_cheapest_wins() -> None:
    chosen, notes = tr.choose_against_qwen(
        [_result("a/dear", cost_per_page=0.0009), _result("b/cheap", cost_per_page=0.0003)]
    )
    assert chosen == "b/cheap"
    assert notes[-1] == "chosen: b/cheap, the cheapest of 2 meeting all seven"


def test_a_cost_tie_goes_to_the_first_model_id() -> None:
    chosen, _ = tr.choose_against_qwen([_result("b/m"), _result("a/m")])
    assert chosen == "a/m"


def test_the_limits_are_decision_0100s() -> None:
    assert tr.QWEN_LIMITS.inventing_per_100 == Fraction(7, 2)
    assert tr.QWEN_LIMITS.photo_invented == 2
    assert tr.QWEN_LIMITS.mixed_invented == 0
    assert tr.QWEN_LIMITS.format_failed == 2
    assert tr.QWEN_LIMITS.hw_accuracy == Fraction(619, 1000)
    assert tr.QWEN_LIMITS.typed_errors_per_100 == Fraction(1329, 100)
    assert tr.QWEN_LIMITS.cost_per_page == 0.00154


def test_absolute_notes_print_0080s_limits_beside_a_candidate() -> None:
    notes = tr.absolute_notes(_result("a/m", hw_inventing=40))
    assert any("0080" in n for n in notes)


def test_absolute_notes_say_within_or_over_and_decide_nothing() -> None:
    notes = tr.absolute_notes(_result("a/m", photo_invented=1, mixed_invented=2))
    by_name = {n.split(":")[0].strip(): n for n in notes}
    assert "(over)" in by_name["0080's limit, inventing lines per 100"]  # 3.5 against 2
    assert "(within)" in by_name["0080's limit, photographs with invented words"]  # 1 in 50
    assert "(over)" in by_name["0080's limit, scans with invented added words"]  # 2 in 25
    assert "(over)" in by_name["0080's limit, format-failed handwriting pages"]  # 2 in 25
    # Exactly 1 in 20 is within 0080's "1 in 20" (the gate is "more than").
    exact = tr.absolute_notes(_result("a/m", photo_pages=20, photo_invented=1))
    assert any("photographs" in n and "(within)" in n for n in exact)


def test_verify_accepts_only_qwens_published_counts() -> None:
    assert tr.matches_qwen_pass2(_result(tr.QWEN, cost_per_page=0.00154)) == []
    assert tr.matches_qwen_pass2(_result(tr.QWEN, hw_right=1035)) == [
        "hw_right 1035, published 1036"
    ]


# ---------------------------------------------------------------------------------------
# verify, over a tmp_path data directory laid out as S2.6 left it (no network).
# ---------------------------------------------------------------------------------------

_DRAFT = ["Fuel BOTH", "Mixture RICH", "Engine OK"]
_LUNA = "openai/gpt-6-luna"


def _s26_folder(tmp_path: Path) -> tuple[Settings, CachedDocuments, tt.Recheck, int]:
    """S2.6's keys, pass1/ CSVs and a recheck pair; returns the typed page's character count.

    Qwen reads the handwriting page as the draft, whose last line the recheck corrects
    ("Engine OK" to "Engine ROUGH"): 2 of 3 lines right, 1 inventing line. Of Qwen's two
    photograph cards first marked "some invented", the recheck clears one; Luna's card stays
    invented and is not Qwen's. One of Qwen's full-page scans was marked "some invented".
    """
    settings = Settings(data_dir=tmp_path)
    folder = settings.data_dir / tt.FOLDER
    (folder / "pass1").mkdir(parents=True)
    typed_doc = _text_pdf("FUEL SELECTOR BOTH. MIXTURE RICH.")
    _seed(settings.docket_dir, 1, typed_doc)
    docs = _offline_docs(settings)
    typed_row = {
        "set": "typed",
        "k": 1,
        "mkey": 1,
        "document": 1,
        "page": 1,
        "document_sha256": hashlib.sha256(typed_doc).hexdigest(),
    }
    hw_row = {"set": "handwriting", "k": 1, "document_sha256": "a" * 64, "page": 1}
    photo_rows = [
        {"set": "photo", "k": k, "document_sha256": c * 64, "page": 1}
        for k, c in ((1, "b"), (2, "d"))
    ]
    mixed_row = {"set": "mixed", "k": 1, "document_sha256": "c" * 64, "page": 1}
    keys = [typed_row, hw_row, *photo_rows, mixed_row]
    (folder / "keys.jsonl").write_text("".join(json.dumps(r) + "\n" for r in keys))
    cache = TranscriptionCache(settings.transcription_dir)
    typed_answer = page_text(typed_doc, 1)
    _put(cache, typed_row, tr.QWEN, typed_answer)
    _put(cache, hw_row, tr.QWEN, "\n".join(_DRAFT))
    for row in [*photo_rows, mixed_row]:
        _put(cache, row, tr.QWEN, "")
    (folder / "handwriting.json").write_text(
        json.dumps({"1": {"versions": {"A": _DRAFT}, "draft": "A", "agreed": _DRAFT}})
    )
    (folder / "photos.json").write_text(
        json.dumps(
            {
                "11": {"k": 1, "model": tr.QWEN},
                "12": {"k": 2, "model": tr.QWEN},
                "13": {"k": 1, "model": _LUNA},
            }
        )
    )
    (folder / "mixed.json").write_text(
        json.dumps({"21": {"k": 1, "model": tr.QWEN}, "22": {"k": 1, "model": _LUNA}})
    )
    _write_csv(
        folder / "pass1" / "handwriting-key.csv",
        ["row", "spot check", "key"],
        [["1", "", "\n".join(_DRAFT)]],
    )
    _write_csv(
        folder / "pass1" / "photo-words.csv",
        ["row", "words"],
        [["11", "some invented"], ["12", "some invented"], ["13", "some invented"]],
    )
    _write_csv(
        folder / "pass1" / "mixed-words.csv",
        ["row", "added words"],
        [["21", "some invented"], ["22", "some invented"]],
    )
    hw2, photos2 = tmp_path / "hw2.csv", tmp_path / "photos2.csv"
    _write_csv(
        hw2,
        ["row", "checked", "key"],
        [["1", "key corrected in the box", "Fuel BOTH\nMixture RICH\nEngine ROUGH"]],
    )
    _write_csv(
        photos2,
        ["row", "words"],
        [["11", "all on the page"], ["12", "some invented"], ["13", "some invented"]],
    )
    return settings, docs, tt.Recheck(handwriting_csv=hw2, photos_csv=photos2), len(typed_answer)


def _fixture_counts(typed_chars: int) -> dict[str, int]:
    return {
        "hw_lines": 3,
        "hw_right": 2,
        "hw_inventing": 1,
        "photo_pages": 2,
        "photo_invented": 1,
        "mixed_pages": 1,
        "mixed_invented": 1,
        "hw_pages": 1,
        "hw_format_failed": 0,
        "typed_chars": typed_chars,
        "typed_errors": 0,
    }


def test_key_material_applies_the_recheck_and_counts_only_qwens_marks(tmp_path: Path) -> None:
    settings, docs, recheck, _ = _s26_folder(tmp_path)
    material = tr.key_material(settings, docs, recheck)
    assert material.key_texts == {1: "Fuel BOTH\nMixture RICH\nEngine ROUGH"}
    assert material.qwen_photo_invented == 1
    assert material.qwen_mixed_invented == 1
    assert list(material.typed_answers) == [1]
    assert len(material.keys) == 5


def test_verify_passes_when_qwens_counts_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, docs, recheck, typed_chars = _s26_folder(tmp_path)
    monkeypatch.setattr(tr, "QWEN_PASS2", _fixture_counts(typed_chars))
    text = tr.cmd_verify(settings, docs, recheck)
    assert text.startswith("verified: Qwen's second pass reproduced exactly from the cache")
    assert str(recheck.handwriting_csv) in text


def test_verify_refuses_and_names_every_count_that_differs(tmp_path: Path) -> None:
    settings, docs, recheck, _ = _s26_folder(tmp_path)
    with pytest.raises(SystemExit) as refused:
        tr.cmd_verify(settings, docs, recheck)
    message = str(refused.value)
    assert "with the recheck CSVs hw2.csv, photos2.csv" in message
    assert "hw_lines 3, published 1548" in message
    assert "hw_right 2, published 1036" in message


def test_main_verify_reads_the_data_dir_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, _, recheck, typed_chars = _s26_folder(tmp_path)
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(tr, "QWEN_PASS2", _fixture_counts(typed_chars))
    argv = [
        "verify",
        "--handwriting-recheck",
        str(recheck.handwriting_csv),
        "--photos-recheck",
        str(recheck.photos_csv),
    ]
    assert tr.main(argv) == 0
    assert capsys.readouterr().out.startswith("verified: ")
