"""Pure parts of the second pair of Jev dev-400 follow-ups (judge, findings). No socket."""

import csv
from itertools import pairwise
from pathlib import Path
from typing import cast, get_args

import pytest
from scripts.exploratory.jev_followups.findings import (
    THRESHOLDS,
    believed_categories,
    precision_recall,
    threshold_row,
)
from scripts.exploratory.jev_followups.judge import (
    CAUSE_LABELS,
    JoinedRow,
    build_state,
    judge_questions,
    load_joined_rows,
)

from ntsb_probable_cause.model.typesafe import NoulAnswer
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.judge import JudgeLabels

# --- judge.py -----------------------------------------------------------------------------

_WORKING_HEADER = [
    "row",
    "case_id",
    "judge_said",
    "codes_said",
    "model_probable_cause",
    "ntsb_probable_cause",
    "model_lay_explanation",
]
_MARKED_HEADER = ["row", "judge_said", "codes_said", "andy_mark"]


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _sample_row(row: int) -> JoinedRow:
    return JoinedRow(
        row=row,
        case_id=f"CASE{row}",
        judge_said="same cause",
        codes_said="wrong",
        andy_mark="judge_right",
        model_probable_cause="The pilot's failure to maintain control.",
        ntsb_probable_cause="The pilot's failure to maintain directional control.",
        model_lay_explanation="The pilot lost control of the airplane.",
    )


def test_cause_labels_are_exactly_judgelabels_causes_three_literals() -> None:
    expected = get_args(JudgeLabels.model_fields["cause"].annotation)
    assert expected == CAUSE_LABELS
    assert set(CAUSE_LABELS) == {"same_cause", "related", "different"}


def test_judge_questions_choice_criteria_match_cause_labels_exactly() -> None:
    questions = judge_questions()
    cause_criteria = cast("dict[str, str]", questions["cause"]["criteria"])
    agreement_criteria = cast("list[str]", questions["agreement"]["criteria"])
    assert questions["cause"]["type"] == "choice"
    assert set(cause_criteria) == set(CAUSE_LABELS)
    assert questions["agreement"]["type"] == "score"
    assert len(agreement_criteria) == 3
    # Both questions carry the same rubric sentence (0036 point 4: same rubric, both shapes).
    assert questions["cause"]["instructions"] == questions["agreement"]["instructions"]
    assert questions["cause"]["instructions"]


def test_build_state_carries_both_prose_causes_and_the_lay_explanation() -> None:
    row = _sample_row(1)
    state = build_state(row)
    assert row.model_probable_cause in state
    assert row.ntsb_probable_cause in state
    assert row.model_lay_explanation in state


def test_load_joined_rows_keeps_all_marked_rows_and_maps_fields_correctly(tmp_path: Path) -> None:
    working = tmp_path / "working.csv"
    marked = tmp_path / "marked.csv"
    _write_csv(
        working,
        _WORKING_HEADER,
        [
            ["1", "CASE1", "same cause", "wrong", "analyst cause A", "official cause A", "lay A"],
            ["2", "CASE2", "different", "right", "analyst cause B", "official cause B", "lay B"],
            ["3", "CASE3", "related", "right", "analyst cause C", "official cause C", "lay C"],
        ],
    )
    _write_csv(
        marked,
        _MARKED_HEADER,
        [
            ["1", "same cause", "wrong", "judge_right"],
            ["2", "different", "right", "both_defensible"],
            ["3", "related", "right", "codes_right"],
        ],
    )
    rows = load_joined_rows(working, marked)
    assert len(rows) == 3
    assert [r.row for r in rows] == [1, 2, 3]
    second = rows[1]
    assert second.case_id == "CASE2"
    assert second.andy_mark == "both_defensible"
    assert second.model_probable_cause == "analyst cause B"
    assert second.ntsb_probable_cause == "official cause B"
    assert second.model_lay_explanation == "lay B"


def test_load_joined_rows_refuses_a_marked_row_missing_from_the_working_sheet(
    tmp_path: Path,
) -> None:
    working = tmp_path / "working.csv"
    marked = tmp_path / "marked.csv"
    _write_csv(
        working,
        _WORKING_HEADER,
        [["1", "CASE1", "same cause", "wrong", "a", "b", "c"]],
    )
    _write_csv(marked, _MARKED_HEADER, [["2", "same cause", "wrong", "judge_right"]])
    with pytest.raises(ValueError, match="row 2"):
        load_joined_rows(working, marked)


# --- findings.py ----------------------------------------------------------------------------


def test_threshold_sweep_runs_from_005_to_050_in_005_steps() -> None:
    assert THRESHOLDS[0] == 0.05
    assert THRESHOLDS[-1] == 0.5
    assert len(THRESHOLDS) == 10
    diffs = [round(b - a, 2) for a, b in pairwise(THRESHOLDS)]
    assert all(d == 0.05 for d in diffs)


def test_believed_categories_keeps_only_nouls_at_or_above_threshold() -> None:
    reply_answers = {
        "category_010100": {"type": "noul", "noul": 0.8},
        "category_010105": {"type": "noul", "noul": 0.3},
        "category_010109": {"type": "noul", "noul": 0.5},
    }
    answers = {name: NoulAnswer.model_validate(value) for name, value in reply_answers.items()}
    believed = believed_categories(answers, 0.5)
    assert believed == frozenset({"010100", "010109"})


def test_precision_recall_arithmetic_on_a_hand_made_example() -> None:
    predicted = frozenset({"010100", "010109", "020000"})
    truth = ("0101000001", "0201000002")  # truncates to {"010100", "020100"} at 6 digits
    result = precision_recall(predicted, truth)
    # intersection at 6 digits: {"010100"} only -- "020000" != "020100", "010109" not in truth.
    assert result.precision == 1 / 3
    assert result.recall == 1 / 2


def test_precision_recall_is_none_when_predicted_or_truth_is_empty() -> None:
    assert precision_recall(frozenset(), ("0101000001",)).precision is None
    assert precision_recall(frozenset(), ("0101000001",)).recall == 0.0
    assert precision_recall(frozenset({"010100"}), ()).recall is None
    assert precision_recall(frozenset({"010100"}), ()).precision == 0.0


def _verdict(finding_codes_in_cause: tuple[str, ...], finding_codes: tuple[str, ...]) -> Verdict:
    return Verdict(
        probable_cause=None,
        occurrence_codes=(),
        finding_codes=finding_codes,
        finding_codes_in_cause=finding_codes_in_cause,
    )


def test_threshold_row_aggregates_mean_believed_and_precision_recall_across_cases() -> None:
    believed_sets = [frozenset({"010100"}), frozenset({"010100", "020000"}), frozenset()]
    verdicts = [
        _verdict(("0101000001",), ("0101000001",)),
        # Strict truth (finding_codes_in_cause) has only "010100" here -- "020000" is in the
        # looser "all findings" set (finding_codes) but not in the strict one.
        _verdict(("0101000001",), ("0101000001", "0200000001")),
        _verdict((), ()),
    ]
    row = threshold_row(0.5, believed_sets, verdicts)
    assert row.threshold == 0.5
    assert row.mean_believed == (1 + 2 + 0) / 3
    # Case 1: p={010100}, strict t={010100} -> precision 1.0, recall 1.0.
    # Case 2: p={010100,020000}, strict t={010100} -> precision 0.5, recall 1.0.
    # Case 3: p={}, strict t={} -> both None, excluded from both averages.
    assert row.precision_strict == (1.0 + 0.5) / 2
    assert row.recall_strict == 1.0
    assert row.n_precision_strict == 2
    assert row.n_recall_strict == 2
    # "All findings" truth for case 2 includes "020000" too, so precision there is 1.0.
    assert row.precision_all == 1.0
    assert row.recall_all == 1.0
