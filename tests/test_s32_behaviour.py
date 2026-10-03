"""scripts/s32_behaviour.py: results 1 and 4 counted from the noise-floor trails (Task 9, §9).

Made-up trails and run folders; no real data. Offline.
"""

from pathlib import Path

import pytest
from scripts import s32_behaviour as sb
from tests.test_s3_noise_floor import (
    _IDS,
    _RUN_A,
    _RUN_B,
    _call,
    _choose,
    _failed,
    _scored,
    _write,
)

from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.records import CaseResult

_ORDER = ("describe_codes", "occurrence_usage", "past_findings", "suggest_codes")


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The runs folder, with ``dev-400`` taken to be the made-up ids ``_IDS``."""
    folder = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(folder))
    monkeypatch.setattr(samples, "sample_ids", lambda name: _IDS if name == "dev-400" else ())
    return folder


def _choice(
    case_id: str, offered: tuple[int, ...], read: tuple[int, ...], **kw: object
) -> AgentCall:
    decisions = {n: n in read for n in offered}
    row = _choose(case_id, decisions, offered=offered, **kw)  # type: ignore[arg-type]
    return row.model_copy(update={"step": "choice1"})


def _tools(case_id: str, tools: tuple[str, ...], start: int = 10) -> list[AgentCall]:
    return [_call(case_id, tool, index=start + i) for i, tool in enumerate(tools)]


def _case(case_id: str, *, fatal: bool = False) -> CaseResult:
    return _scored(case_id, fatal=fatal)


def test_offered_three_read_three_reads_everything() -> None:
    calls = [_choice("c1", (1, 2, 3), (1, 2, 3))]
    counts = sb.read_counts(calls, [_case("c1")])
    assert (counts.counted, counts.with_offer, counts.read_everything) == (1, 1, 1)


def test_offered_three_read_two_does_not() -> None:
    calls = [_choice("c1", (1, 2, 3), (1, 2))]
    counts = sb.read_counts(calls, [_case("c1")])
    assert (counts.with_offer, counts.read_everything) == (1, 0)


def test_both_choices_together_count() -> None:
    calls = [_choice("c1", (1, 2, 3), (1,), index=1), _choice("c1", (2, 3), (2, 3), index=3)]
    assert sb.read_counts(calls, [_case("c1")]).read_everything == 1


def test_a_decision_on_a_document_not_offered_is_ignored() -> None:
    one = _choice("c1", (1, 2), (1,))
    # the model also said "read" about document 9, which was never on offer
    arguments = {
        "decisions": [
            {"document": 1, "read": True, "expected_effect": "e"},
            {"document": 2, "read": False, "expected_effect": "e"},
            {"document": 9, "read": True, "expected_effect": "e"},
        ],
        "reason": "r",
    }
    row = one.model_copy(update={"arguments": arguments})
    assert sb.read_counts([row], [_case("c1")]).read_everything == 0


def test_a_rejected_read_choice_reads_nothing() -> None:
    row = _choice("c1", (1,), (1,)).model_copy(update={"protocol_error": "bad"})
    assert sb.read_counts([row], [_case("c1")]).read_everything == 0


def test_a_case_with_nothing_on_offer_leaves_the_read_count_but_not_the_order_count() -> None:
    calls = _tools("c1", _ORDER)
    counts = sb.read_counts(calls, [_case("c1")])
    assert (counts.counted, counts.with_offer, counts.read_everything) == (1, 0, 0)
    assert counts.fixed_order == 1


@pytest.mark.parametrize(
    ("tools", "fixed"),
    [
        (_ORDER, True),
        (
            (
                "describe_codes",
                "describe_codes",
                "occurrence_usage",
                "past_findings",
                "suggest_codes",
            ),
            True,
        ),
        (("occurrence_usage", "describe_codes", "past_findings", "suggest_codes"), False),
        (_ORDER[:3], False),
        ((), False),
    ],
)
def test_the_order_rule(tools: tuple[str, ...], fixed: bool) -> None:
    calls = [*_tools("c1", tools), _choice("c1", (1,), (1,))]
    assert sb.read_counts(calls, [_case("c1")]).fixed_order == int(fixed)


def test_counts_by_fatal_and_by_documents_offered() -> None:
    calls = [
        _choice("c1", (1,), (1,)),
        _choice("c2", (1, 2, 3), (1,)),
        _choice("c3", tuple(range(1, 7)), tuple(range(1, 7))),
        _choice("c4", (1, 2), (1, 2)),
    ]
    cases = [_case("c1", fatal=True), _case("c2"), _case("c3", fatal=True), _case("c4")]
    counts = sb.read_counts(calls, cases)
    assert counts.by_fatal["fatal"].read_everything == 2
    assert counts.by_fatal["non-fatal"].read_everything == 1
    assert counts.by_offered["1"].counted == 1
    assert counts.by_offered["2-4"].counted == 2
    assert counts.by_offered["2-4"].read_everything == 1
    assert counts.by_offered["5 or more"].read_everything == 1


def test_a_case_with_no_trail_is_not_counted() -> None:
    counts = sb.read_counts([_choice("c1", (1,), (1,))], [_case("c1"), _failed("c2", "cap")])
    assert counts.counted == 1


def test_effects_naming_an_event_label_or_code() -> None:
    tables = load_tables()

    def decide(effect: str, read: bool = True) -> AgentCall:
        arguments = {
            "decisions": [{"document": 1, "read": read, "expected_effect": effect}],
            "reason": "r",
        }
        return _choice("c1", (1,), (1,)).model_copy(update={"arguments": arguments})

    calls = [
        decide("May show loss of control in flight or not"),
        decide("may establish wind, visibility and conditions"),
        decide("Likely the event was 240 and not another"),
        decide("number 2400 is not a code"),
        decide(
            "Loss of control in flight", read=False
        ),  # skipped: not an effect on a read document
    ]
    assert sb.effects_naming_codes(calls, tables) == (2, 4)


def _decide(*effects: str) -> list[AgentCall]:
    """One accepted read choice per effect, each on a read document."""
    calls = []
    for effect in effects:
        arguments = {
            "decisions": [{"document": 1, "read": True, "expected_effect": effect}],
            "reason": "r",
        }
        calls.append(_choice("c1", (1,), (1,)).model_copy(update={"arguments": arguments}))
    return calls


def test_the_category_leaf_is_what_is_searched_for() -> None:
    tables = load_tables()
    full = "Aircraft — Aircraft systems — Fuel system"
    assert full in tables.categories.values()  # a real label, a three-part path
    leaves = sb.category_leaves(tables)
    assert "fuel system" in leaves
    assert "aircraft" not in leaves  # a first or middle segment is not a leaf
    assert "(general)" not in leaves
    assert "wind" not in leaves  # shorter than 6 characters
    assert all(len(leaf) >= 6 for leaf in leaves)
    assert len(leaves) == len(set(leaves))


def test_an_effect_naming_a_category_leaf_counts_and_a_middle_segment_does_not() -> None:
    tables = load_tables()
    calls = _decide(
        "Maintenance records may show a fuel system fault",  # the leaf of a real label
        "The aircraft records may show what happened",  # "aircraft" is a middle segment
        "Will show the pilot's account of the flight",
    )
    routes = sb.effect_routes(calls, tables)
    assert (routes.total, routes.naming) == (3, 1)
    assert (routes.event_label, routes.category_leaf, routes.event_code) == (0, 1, 0)
    assert sb.effects_naming_codes(calls, tables) == (1, 3)


def test_routes_are_counted_apart_and_an_effect_is_named_once() -> None:
    tables = load_tables()
    calls = _decide(
        "Shows loss of control in flight",  # event label only
        "Shows a fuel system fault",  # category leaf only
        "Event 240 is likely",  # event code only
        "Loss of control in flight with a fuel system fault, code 240",  # all three
    )
    routes = sb.effect_routes(calls, tables)
    assert routes == sb.Routes(total=4, naming=4, event_label=2, category_leaf=2, event_code=2)


def test_main_prints_each_run_without_a_case_id(
    runs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = [_scored(i, fatal=n < 2) for n, i in enumerate(_IDS)]
    calls = [_choice(i, (1, 2), (1, 2)) for i in _IDS[:12]] + [_choice(_IDS[12], (1, 2), (1,))]
    _write(runs, _RUN_A, a, calls)
    _write(runs, _RUN_B, a, [])
    out_path = tmp_path / "o" / "b.txt"
    assert sb.main([_RUN_A, _RUN_B, "--out", str(out_path)]) == 0
    out = capsys.readouterr().out
    assert "run a: 13 cases counted" in out
    assert (
        "read every document on offer: 12 of 13 (92.3%) of the cases with documents on offer" in out
    )
    assert "result 1: holds" in out
    assert "run b: 0 cases counted" in out
    assert "by documents offered" in out
    assert "result 4's measure: " in out
    assert "by route (an effect can match more than one): event label 0, category leaf 0" in out
    assert out_path.read_text().strip() == out.strip()
    assert "ZQX" not in out


def test_result_one_does_not_hold_when_neither_half_is_met(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = [_scored(i) for i in _IDS]
    calls = [_choice(i, (1, 2), (1,)) for i in _IDS]
    _write(runs, _RUN_A, a, calls)
    _write(runs, _RUN_B, a, calls)
    sb.main([_RUN_A, _RUN_B])
    assert "result 1: does not hold" in capsys.readouterr().out


def test_one_run_is_enough(runs: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(runs, _RUN_A, [_scored(i) for i in _IDS], [])
    assert sb.main([_RUN_A]) == 0
    assert "run a:" in capsys.readouterr().out


def _counts(
    *, counted: int = 10, with_offer: int = 8, read_everything: int = 0, fixed_order: int = 0
) -> sb.ReadCounts:
    return sb.ReadCounts(counted, with_offer, read_everything, fixed_order)


@pytest.mark.parametrize(
    ("changes", "holds"),
    [
        ({"read_everything": 5}, True),  # 5 of 8 with documents on offer
        ({"read_everything": 4}, False),  # exactly half of 8: not more than half
        ({"read_everything": 5, "with_offer": 10}, False),  # exactly half of 10
        ({"fixed_order": 6}, True),  # 6 of the 10 counted
        ({"fixed_order": 5}, False),  # exactly half of 10
        ({"read_everything": 4, "fixed_order": 4}, False),  # neither
        ({"read_everything": 0, "with_offer": 0, "counted": 0}, False),  # nothing counted
    ],
)
def test_result_one_holds_on_more_than_half_of_either(changes: dict[str, int], holds: bool) -> None:
    assert sb.result1_holds(_counts(**changes)) is holds
