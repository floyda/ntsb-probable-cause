"""scripts/round0_handread.py: the cards, and the narrative-label validation (decision 0099)."""

import csv
from pathlib import Path

import pytest
from scripts import round0_handread as rh
from tests.test_occurrence_misses import _case, _write_run

from ntsb_probable_cause.scoring.judge import JudgeLabels
from ntsb_probable_cause.scoring.records import CaseResult, write_jsonl


def _cases() -> list[CaseResult]:
    cases = [_case(f"X{i:02d}", ("452240",), ("452240",)) for i in range(12)]  # hits
    cases += [
        _case(f"W{i:02d}", ("452240",), ("450240",)) for i in range(9)
    ]  # right event, wrong phase
    cases += [
        _case(f"S{i:02d}", ("452240", "452241"), ("452241",)) for i in range(3)
    ]  # in sequence
    return cases


def test_draw_cards_takes_eight_per_miss_group_or_all_and_ten_hits() -> None:
    drawn = rh.draw_cards(_cases(), seed=1)
    groups = [g for _id, g in drawn]
    assert groups.count("exact") == 10
    assert groups.count("right event, wrong phase") == 8
    assert groups.count("in sequence, not defining") == 3  # fewer than 8: all (plan W7)
    assert rh.draw_cards(_cases(), seed=1) == drawn


def _sheet(rows: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"row": str(n), "case_id": c, "group": g} for n, (c, g) in enumerate(rows, start=1)]


def _labels(narratives: dict[str, str]) -> dict[str, JudgeLabels]:
    return {
        c: JudgeLabels(narrative=n, cause="related", lay="does_not") for c, n in narratives.items()
    }


def test_score_validates_at_75_percent_with_errors_both_ways() -> None:
    sheet = _sheet([(f"C{i}", "nothing in common") for i in range(8)])
    # Andy: yes on C0-C3, no on C4-C7. Judge: consistent on C0-C2 and C4 (one generous error),
    # not consistent on C3 (one harsh error) and C5-C7: 6 of 8 agree = 75%.
    marks = {
        n: {"key fact": "yes" if n <= 4 else "no", "why": "coding convention"} for n in range(1, 9)
    }
    labels = _labels(
        {
            "C0": "consistent",
            "C1": "consistent",
            "C2": "consistent",
            "C3": "contradicts",
            "C4": "consistent",
            "C5": "less_detailed",
            "C6": "contradicts",
            "C7": "contradicts",
        }
    )
    text = rh.score(sheet, marks, labels)
    assert "agreement: 6 of 8" in text
    assert "outcome: validated" in text


def test_score_is_not_validated_when_errors_run_one_way() -> None:
    sheet = _sheet([(f"C{i}", "nothing in common") for i in range(4)])
    marks = {n: {"key fact": "yes", "why": "other"} for n in range(1, 5)}
    labels = _labels(
        {"C0": "consistent", "C1": "consistent", "C2": "consistent", "C3": "contradicts"}
    )
    text = rh.score(sheet, marks, labels)
    assert "outcome: not validated" in text


def test_score_prints_why_by_miss_group() -> None:
    sheet = _sheet(
        [
            ("C0", "right event, wrong phase"),
            ("C1", "right event, wrong phase"),
            ("C2", "nothing in common"),
        ]
    )
    marks = {
        1: {"key fact": "yes", "why": "coding convention"},
        2: {"key fact": "yes", "why": "wrong phase"},
        3: {"key fact": "no", "why": "other"},
    }
    labels = _labels({"C0": "consistent", "C1": "consistent", "C2": "consistent"})
    text = rh.score(sheet, marks, labels)
    lines = text.splitlines()
    assert (
        "why by group -- right event, wrong phase (2 cards): coding convention 1, "
        "wrong phase 1, misread or missing fact 0, NTSB code arguable 0, other 0"
    ) in lines
    assert (
        "why by group -- nothing in common (1 cards): coding convention 0, wrong phase 0, "
        "misread or missing fact 0, NTSB code arguable 0, other 1"
    ) in lines


def test_score_refuses_an_unmarked_card() -> None:
    sheet = _sheet([("C0", "nothing in common")])
    with pytest.raises(SystemExit, match="unmarked"):
        rh.score(sheet, {1: {"key fact": "", "why": ""}}, _labels({"C0": "consistent"}))


def test_score_refuses_a_case_missing_from_the_judge_labels() -> None:
    sheet = _sheet([("C0", "nothing in common")])
    with pytest.raises(SystemExit, match="row 1"):
        rh.score(sheet, {1: {"key fact": "yes", "why": "other"}}, {})


def test_cards_refuses_a_held_out_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    with pytest.raises(SystemExit, match="development"):
        rh.main(["cards", "--run", "20260926T000000-abc1234-heldout-400-B"])


def test_cards_refuses_a_run_recorded_as_held_out_before_cases_are_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run id says development, but run.jsonl's recorded sample says otherwise: refused
    before cases.jsonl is even opened (review fix round 1, item 1). No cases.jsonl is written,
    so the test would fail with a missing-file error, not a clean SystemExit, if the run.jsonl
    check ran after (or not at all)."""
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    runs_dir = tmp_path / "runs"
    _write_run(runs_dir, "20260926T000000-abc1234-dev-400-B", sample="heldout-400")
    with pytest.raises(SystemExit, match="held-out run"):
        rh.main(["cards", "--run", "20260926T000000-abc1234-dev-400-B"])


def test_cards_refuses_a_run_holding_a_case_outside_the_dev_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    runs_dir = tmp_path / "runs"
    run_id = "20260926T000000-abc1234-dev-400-B"
    folder = _write_run(runs_dir, run_id)
    write_jsonl(
        folder / "cases.jsonl",
        [
            _case("C1", ("452240",), ("452240",)),
            _case("C2", ("452240",), ("452240",), split="heldout"),
        ],
    )
    with pytest.raises(SystemExit, match="outside the dev split"):
        rh.main(["cards", "--run", run_id])


def test_score_refuses_a_sheet_drawn_from_a_different_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    runs_dir = tmp_path / "runs"
    run_id = "20260927T120000-abc1234-dev-400-B"
    other_run_id = "20260926T000000-abc1234-dev-400-B"
    folder = _write_run(runs_dir, run_id)
    write_jsonl(folder / "cases.jsonl", [_case("C1", ("452240",), ("452240",))])
    sheet_dir = tmp_path / rh.FOLDER
    sheet_dir.mkdir(parents=True)
    with (sheet_dir / "sheet.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["row", "case_id", "group", "run_id"])
        writer.writerow([1, "C1", "exact", other_run_id])
    with pytest.raises(SystemExit, match=other_run_id):
        rh.main(["score", "unused.csv", "--run", run_id])
