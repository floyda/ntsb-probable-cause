"""scripts/round1_jev2_report.py: the second, registered Jev check's report (decision 0103)."""

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from scripts import round1_jev2_report as r2
from scripts.round1_report import Paired, derived_id
from tests.test_occurrence_misses import _SCORES, _case, _write_run  # shared builders

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.model.typesafe import TypeSafeClient
from ntsb_probable_cause.scoring import checkpass
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import PoolCase, build
from ntsb_probable_cause.scoring.ordering import NONE_OF_THESE
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl, write_jsonl

LOC, STALL = "452240", "452241"


def _p(low: float) -> Paired:
    return Paired(mean=low + 0.03, low=low, high=low + 0.06, n=399, fixes=20, breaks=5)


def _against(none: float, rule: float, luna: float) -> dict[str, Paired | None]:
    return {"no check": _p(none), "the plain rule": _p(rule), "GPT-6 Luna": _p(luna)}


def test_jev2_wins_only_when_all_three_lower_bounds_are_above_zero_on_both_sets() -> None:
    both = {"A": _against(0.01, 0.01, 0.01), "B": _against(0.02, 0.01, 0.005)}
    assert r2.jev2_wins(both)
    assert "replaces GPT-6 Luna" in r2.outcome(both)


@pytest.mark.parametrize(
    "second",
    [
        _against(0.01, 0.01, 0.0),  # a lower bound at zero is not above it
        _against(0.01, -0.01, 0.02),  # beats Luna but not the rule
        _against(-0.01, 0.01, 0.02),
        {"no check": _p(0.01), "the plain rule": _p(0.01), "GPT-6 Luna": None},  # Luna not run
    ],
)
def test_luna_stays_unless_every_bound_holds_on_both_sets(second: dict[str, Paired | None]) -> None:
    results = {"A": _against(0.05, 0.05, 0.05), "B": second}
    assert not r2.jev2_wins(results)
    assert r2.outcome(results).endswith("luna stays (CHECK=luna)")


def test_luna_stays_when_an_answer_set_has_no_jev2_result() -> None:
    assert not r2.jev2_wins({"A": _against(0.05, 0.05, 0.05)})


def _checked(  # noqa: PLR0913 -- a test-only builder, one keyword per varied field.
    case: CaseResult,
    first: str,
    *,
    top1: bool,
    probabilities: dict[str, float],
    confidence: float,
    jev_order: list[str] | None = None,
) -> CaseResult:
    last = case.steps[-1]
    guess = last.hypothesis.occurrence[0].model_copy(
        update={"phase": first[:3], "event": first[3:]}
    )
    step = last.model_copy(
        update={
            "step": 1,
            "tool": "ordering_check",
            "arguments": {
                "ranking": [first],
                "toward_more_common": first == LOC,
                "choice": max(probabilities, key=lambda k: probabilities[k]),
                "confidence": confidence,
                "jev_order": jev_order or list(probabilities),
                "probabilities": probabilities,
            },
            "hypothesis": last.hypothesis.model_copy(update={"occurrence": (guess,)}),
        }
    )
    return case.model_copy(
        update={"steps": (last, step), "scores": replace(_SCORES, occurrence_top1=top1)}
    )


def test_none_first_reads_the_recorded_jev_order_not_the_probabilities_order() -> None:
    base = _case("C1", (LOC,), (STALL,))
    # A tie at the top: none_of_these ranks first (registration, Andy: option A), whatever order
    # the probabilities happen to be stored in.
    tied = _checked(
        base,
        STALL,
        top1=False,
        probabilities={STALL: 0.5, NONE_OF_THESE: 0.5},
        confidence=0.4,
        jev_order=[NONE_OF_THESE, STALL],
    )
    code_first = _checked(
        base,
        STALL,
        top1=False,
        probabilities={NONE_OF_THESE: 0.4, STALL: 0.6},
        confidence=0.4,
        jev_order=[STALL, NONE_OF_THESE],
    )
    assert r2.none_first(tied) is True
    assert r2.none_first(code_first) is False
    assert r2.none_first(base) is False  # not a checked case


@respx.mock
def test_a_tie_at_the_top_survives_the_round_trip_through_cases_jsonl(tmp_path: Path) -> None:
    """jev2_checker -> check_run -> cases.jsonl on disk -> the report reads none_of_these first."""
    respx.post("https://api.typesafe.ai/v1/systemone").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "usage": {"input_tokens": 100, "output_tokens": 0},
                "answers": {
                    "defining": {
                        "type": "choice",
                        "choice": STALL,  # Jev's own pick on the tie; the rule decides
                        "confidence": 0.3,
                        "probabilities": {STALL: 0.45, LOC: 0.1, NONE_OF_THESE: 0.45},
                    }
                },
            },
        )
    )
    runs = tmp_path / "runs"
    source = "20260926T000000-abc1234-dev-400-B"
    folder = _write_run(runs, source)
    write_jsonl(folder / "cases.jsonl", [_case("C1", (LOC, STALL), (STALL,))])
    stats = build(
        [PoolCase(2012, "Maneuvering", (LOC, STALL))] * 30
        + [PoolCase(2016, "Maneuvering", (STALL, LOC))] * 5,
        built_from="test",
    )
    with TypeSafeClient("k", base_url="https://api.typesafe.ai") as client:
        record = checkpass.check_run(
            folder,
            "jev2",
            checkpass.jev2_checker(client, stats, load_tables()),
            runs_dir=runs,
            groups={"C1": "Maneuvering"},
            seen_pairs=frozenset(),
            commit=("def5678", False),
            now=lambda: datetime(2026, 9, 28, tzinfo=UTC),
        )
    (case,) = read_jsonl(runs / record.run_id / "cases.jsonl", CaseResult)
    assert case.steps[-1].arguments["jev_order"] == [NONE_OF_THESE, STALL, LOC]
    assert [g.phase + g.event for g in case.steps[-1].hypothesis.occurrence] == [STALL]
    assert r2.none_first(case) is True


def _source_cases() -> list[CaseResult]:
    # No check: C1 right, C2 wrong, C3 right, C4 wrong.
    return [
        _case("C1", (STALL,), (STALL,)).model_copy(
            update={"scores": replace(_SCORES, occurrence_top1=True)}
        ),
        _case("C2", (LOC,), (STALL,)),
        _case("C3", (STALL,), (STALL,)).model_copy(
            update={"scores": replace(_SCORES, occurrence_top1=True)}
        ),
        _case("C4", ("552230",), (STALL,)),
    ]


def _jev2_cases(source: list[CaseResult]) -> list[CaseResult]:
    c1, c2, c3, c4 = source
    return [
        # broken: moved to LOC, now wrong
        _checked(c1, LOC, top1=False, probabilities={LOC: 0.7, STALL: 0.3}, confidence=0.2),
        # fixed: moved to LOC, now right
        _checked(c2, LOC, top1=True, probabilities={LOC: 0.8, STALL: 0.2}, confidence=0.9),
        # unchanged: none_of_these first, answer left as it was (still right)
        _checked(
            c3,
            STALL,
            top1=True,
            probabilities={NONE_OF_THESE: 0.6, STALL: 0.4},
            confidence=0.5,
        ),
        # unchanged: kept, still wrong
        _checked(c4, STALL, top1=False, probabilities={STALL: 0.9, LOC: 0.1}, confidence=0.7),
    ]


def _write(runs: Path, run_id: str, cases: list[CaseResult]) -> None:
    folder = _write_run(runs, run_id)
    write_jsonl(folder / "cases.jsonl", cases)


def test_main_prints_every_comparison_the_counts_and_the_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    out_file = tmp_path / "out.txt"
    for source in ("source-a", "source-b"):
        cases = _source_cases()
        _write(runs, source, cases)
        for way in ("rule", "luna", "jev"):
            _write(runs, derived_id(source, way), cases)
        _write(runs, f"{source}-check-jev2", _jev2_cases(cases))
    assert r2.main(["--answers", "source-a", "source-b", "--out", str(out_file)]) == 0
    out = capsys.readouterr().out
    assert out_file.read_text() == out
    assert "second, registered comparison (decision 0103)" in out.splitlines()[0]
    assert "## answer set source-a" in out
    for label in ("no check", "the plain rule", "GPT-6 Luna", "Round 1's Jev"):
        assert f"- jev2 against {label}: +0.0% " in out
    assert "on n=4; fixes 1, breaks 1" in out
    assert "first codes changed: 2; toward a more common option (decision 0101): 2" in out
    assert "none_of_these ranked first (answer left unchanged): 1 of 4 checked cases" in out
    assert (
        "median Jev confidence: fixed 0.90 (n=1), broken 0.20 (n=1), "
        "unchanged (top-1 the same as no check) 0.60 (n=2)"
    ) in out
    assert out.rstrip().endswith("luna stays (CHECK=luna)")


def test_main_says_not_run_for_a_missing_folder_and_luna_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    for source in ("source-a", "source-b"):
        cases = _source_cases()
        _write(runs, source, cases)
        _write(runs, derived_id(source, "rule"), cases)
    _write(runs, "source-a-check-jev2", _jev2_cases(_source_cases()))
    assert r2.main(["--answers", "source-a", "source-b"]) == 0
    out = capsys.readouterr().out
    assert "- jev2 against GPT-6 Luna: not run" in out
    assert "- jev2: not run" in out  # source-b has no jev2 folder
    assert out.rstrip().endswith("luna stays (CHECK=luna)")


def test_a_source_recorded_on_a_held_out_sample_is_refused_before_its_cases_are_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    _write_run(runs, "renamed-run", sample="heldout-400")  # no cases.jsonl written
    with pytest.raises(SystemExit, match="held-out run"):
        r2.main(["--answers", "renamed-run", "other-run"])


def test_a_held_out_run_id_and_a_case_outside_the_dev_split_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    with pytest.raises(SystemExit, match="held-out run"):
        r2.main(["--answers", "x-heldout-400-B", "other-run"])
    _write(runs, "mixed", [*_source_cases(), _case("H1", (LOC,), (LOC,), split="heldout")])
    _write(runs, "other-run", _source_cases())
    with pytest.raises(SystemExit, match="outside the development split"):
        r2.main(["--answers", "mixed", "other-run"])


def test_a_sealed_source_is_refused_before_any_run_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``dev-seal-400`` is refused until its registration is committed (decision 0095), and both
    sources' records are checked before either's cases are read: the first source here has no
    cases.jsonl, so reading it first would fail with a missing file, not this refusal."""
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): False)
    _write_run(runs, "dev-run")  # no cases.jsonl
    _write_run(runs, "sealed-run", sample="dev-seal-400")  # no cases.jsonl
    with pytest.raises(SystemExit, match="sealed"):
        r2.main(["--answers", "dev-run", "sealed-run"])


def test_a_source_that_has_not_finished_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    folder = _write_run(runs, "dead-run")
    record = read_jsonl(folder / "run.jsonl", RunRecord)[0]
    (folder / "run.jsonl").unlink()  # write_jsonl appends; replace, not add, the row
    write_jsonl(folder / "run.jsonl", [record.model_copy(update={"finished": None})])
    with pytest.raises(SystemExit, match="has not finished"):
        r2.main(["--answers", "dead-run", "other-run"])


def test_main_refuses_answer_sets_on_different_arms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    _write_run(runs, "source-a", arm="B")
    _write_run(runs, "source-b", arm="ceiling")
    with pytest.raises(SystemExit, match="arm"):
        r2.main(["--answers", "source-a", "source-b"])
