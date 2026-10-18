"""scripts/exploratory/memory_proxy_check.py: what 0213's gate measured. Offline; invented."""

from pathlib import Path

import pytest
from scripts.exploratory import memory_proxy_check as pc

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import coverage
from ntsb_probable_cause.memory.lessons import Lesson, Prediction, Support
from ntsb_probable_cause.memory.pool import LearningCase

LOC, STALL = "550240", "500241"


def _lesson(lid: str, first: tuple[str, ...] = (), cats: tuple[str, ...] = ()) -> Lesson:
    return Lesson(
        lesson_id=lid,
        kind="convention" if first else "evidence",
        statement=f"lesson {lid}",
        scope="a scope",
        predicts=Prediction(first_occurrence=first, finding_categories=cats),
        written_in=2010,
        support=Support(applies=20, agrees=10),
    )


def _case(case_id: str, occ: str, findings: tuple[str, ...] = ()) -> LearningCase:
    return LearningCase(case_id, 0, "a cause", (occ,), findings)


CASES = {
    "A": _case("A", LOC, ("0101010101",)),
    "B": _case("B", STALL),
    "C": _case("C", LOC),
}
RIGHT = _lesson("L1", first=(LOC,))
WRONG = _lesson("L2", first=(STALL,), cats=("010101",))


def test_groups_split_cases_by_todays_lessons() -> None:
    found = pc.groups({"A": (RIGHT,), "B": (RIGHT, WRONG), "C": ()}, CASES)
    assert found == {
        pc.NONE_GROUP: frozenset({"C"}),
        pc.WRONG_GROUP: frozenset({"B"}),
        pc.RIGHT_GROUP: frozenset({"A"}),
    }


def test_rank_lines_count_cases_by_size_and_precision_by_rank() -> None:
    lines = pc.rank_lines({"A": (RIGHT, WRONG), "B": (WRONG,), "C": ()}, CASES)
    assert lines[0].endswith("1, 1, 1, 0, 0, 0")
    # rank 1: A's RIGHT agrees, B's WRONG (first STALL, category 010101 not flagged) does not;
    # rank 2: A's WRONG fails on its first code.
    assert lines[1].endswith("50.0% (1 of 2); 0.0% (0 of 1); -; -; -")


def test_part_lines_compare_the_finding_part_with_todays() -> None:
    chosen = {"A": (WRONG,), "B": (), "C": ()}
    _first, today = coverage.part_coverage({}, CASES)
    lines = pc.part_lines(chosen, CASES, today)
    assert "precision 0.0% (0 of 1)" in lines[0]  # as the gate read it: the first code fails
    assert "finding part: case hit 33.3%, precision 100.0% (1 of 1)" in lines[2]
    assert lines[3].startswith("  finding-part case hit minus today's: +33.3 points")
    assert len(pc.part_lines(chosen, CASES, None)) == 3


def test_spend_of_sums_a_run_folders_rows(tmp_path: Path) -> None:
    row = (
        '{"job_id":"j","kind":"learning","model":"m","started":"2026-10-17T18:27:02Z",'
        '"calls":3,"cost_usd":%s,"commit_sha":"abc1234","dirty":false}'
    )
    (tmp_path / "spend.jsonl").write_text(row % "1.25" + "\n" + row % "0.5" + "\n")
    assert pc.spend_of(tmp_path) == (1.75, 2, "learning")


def test_spend_of_refuses_a_folder_without_spend_rows(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="no readable spend rows"):
        pc.spend_of(tmp_path)
