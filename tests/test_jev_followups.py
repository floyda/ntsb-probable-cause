"""The three Jev dev-400 follow-ups' pure parts (2026-09-17-typesafe-jev-dev400 follow-ups)."""

import json
from pathlib import Path

from scripts.exploratory.jev_dev400 import JevCase
from scripts.exploratory.jev_followups.confidence_gating import (
    GATING_MIN_ANSWERED_SHARE,
    GATING_MIN_TOP1,
    NOT_USEFUL_READING,
    USEFUL_READING,
    gating_reading,
    gating_table,
)
from scripts.exploratory.jev_followups.hierarchical_events import (
    FLAT_AS_GOOD_READING,
    HIERARCHY_HELPS_READING,
    beam_candidates,
    choose_event,
    combine_replies,
    family_description,
    family_label,
    flat_event_accuracy,
    group_events_by_family,
    hierarchy_reading,
    top_family,
)
from scripts.exploratory.jev_followups.state_hygiene import LEAN_EXCLUSIONS, arm_spec

from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.model.typesafe import (
    ChoiceAnswer,
    Exchange,
    SystemOneReply,
    SystemOneUsage,
)
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.metrics import CaseScores
from ntsb_probable_cause.scoring.runner import RunSpec, case_payload

TABLES = load_tables()
FIXTURE = Path("tests/fixtures/records/ANC09CA020.json")


def _choice(probabilities: dict[str, float], confidence: float = 0.5) -> ChoiceAnswer:
    best = max(probabilities, key=probabilities.__getitem__)
    return ChoiceAnswer(
        type="choice", choice=best, confidence=confidence, probabilities=probabilities
    )


def _scores(*, top1: bool, event: bool, confidence: float) -> CaseScores:
    return CaseScores(
        occurrence_top1=top1,
        occurrence_top3=top1,
        event_match=event,
        pair_unseen=False,
        finding_precision_10=None,
        finding_recall_10=None,
        finding_precision_8=None,
        finding_recall_8=None,
        finding_precision_6=None,
        finding_recall_6=None,
        finding_precision_all_10=None,
        finding_recall_all_10=None,
        abstained=False,
        confidence=confidence,
    )


def _jev_case(case_id: str, *, confidence: float, top1: bool, event: bool) -> JevCase:
    return JevCase(
        case_id=case_id,
        fatal=False,
        scores=_scores(top1=top1, event=event, confidence=confidence),
        event_confidence=confidence,
        event_top_probability=confidence,
        top1_probability=confidence,
        true_occurrence="550240",
        true_event_probability=confidence,
        top_events=(("240", confidence),),
        phase_match=None,
    )


# --- Experiment 1: confidence gating ---------------------------------------------------


def test_gating_table_arithmetic_at_a_known_threshold() -> None:
    # At t=0.5: three cases at/above (two right on top-1), two below (none right).
    cases = [
        _jev_case("A", confidence=0.9, top1=True, event=True),
        _jev_case("B", confidence=0.6, top1=True, event=True),
        _jev_case("C", confidence=0.5, top1=False, event=True),
        _jev_case("D", confidence=0.4, top1=False, event=False),
        _jev_case("E", confidence=0.1, top1=False, event=False),
    ]
    rows = gating_table(cases, thresholds=(0.5,))
    row = rows[0]
    assert row.t == 0.5
    assert row.answered_share.n == 5
    assert row.answered_share.value == 3 / 5
    assert row.answered_top1.n == 3
    assert row.answered_top1.value == 2 / 3
    assert row.answered_event.n == 3
    assert row.answered_event.value == 1.0
    assert row.below_top1.n == 2
    assert row.below_top1.value == 0.0
    assert row.below_event.n == 2
    assert row.below_event.value == 0.0


def test_gating_reading_useful_when_some_threshold_clears_both_bars() -> None:
    # 80% of cases answered at t, all of them right: well above both bars.
    cases = [_jev_case(f"R{i}", confidence=0.8, top1=True, event=True) for i in range(8)] + [
        _jev_case(f"W{i}", confidence=0.1, top1=False, event=False) for i in range(2)
    ]
    rows = gating_table(cases, thresholds=(0.5,))
    assert rows[0].answered_top1.value >= GATING_MIN_TOP1
    assert rows[0].answered_share.value >= GATING_MIN_ANSWERED_SHARE
    assert gating_reading(rows) == USEFUL_READING


def test_gating_reading_not_useful_when_no_threshold_clears_both_bars() -> None:
    # High accuracy above threshold, but too few cases answered there.
    cases = [_jev_case(f"R{i}", confidence=0.9, top1=True, event=True) for i in range(2)] + [
        _jev_case(f"W{i}", confidence=0.1, top1=False, event=False) for i in range(8)
    ]
    rows = gating_table(cases, thresholds=(0.5,))
    assert rows[0].answered_share.value < GATING_MIN_ANSWERED_SHARE
    assert gating_reading(rows) == NOT_USEFUL_READING


# --- Experiment 3: state hygiene --------------------------------------------------------


def test_lean_exclusions_remove_exactly_the_named_roles_from_a_payload() -> None:
    raw = json.loads(FIXTURE.read_text())["record"]
    full_payload, _, _, _ = case_payload(raw, RunSpec(sample="dev-400", arm="ceiling"), TABLES)
    lean_payload, _, _, _ = case_payload(raw, arm_spec("lean"), TABLES)

    full_fields = set(full_payload.fields())
    lean_fields = set(lean_payload.fields())

    excluded_names = {role.value for role in LEAN_EXCLUSIONS}
    # Every excluded role that was present in the full payload is gone from the lean one.
    assert full_fields & excluded_names
    assert not lean_fields & excluded_names
    # Nothing else was removed: the lean payload is the full one minus exactly those roles.
    assert lean_fields == full_fields - excluded_names


def test_arm_spec_full_excludes_nothing() -> None:
    assert arm_spec("full").exclusions == frozenset()
    assert arm_spec("lean").exclusions == LEAN_EXCLUSIONS


# --- Experiment 5: hierarchical events --------------------------------------------------


def test_family_grouping_is_a_partition_of_all_93_events() -> None:
    families = group_events_by_family(TABLES)
    all_members = [code for members in families.values() for code in members]
    assert len(all_members) == len(TABLES.events) == 93
    assert set(all_members) == set(TABLES.events)
    # Every code appears in exactly one family, keyed by its own leading digit.
    for digit, members in families.items():
        assert all(code[0] == digit for code in members)
    # The counts fixed by the task description.
    assert {digit: len(members) for digit, members in families.items()} == {
        "0": 19,
        "1": 14,
        "2": 18,
        "3": 23,
        "4": 13,
        "5": 2,
        "6": 1,
        "9": 3,
    }


def test_family_description_is_derived_from_member_labels_not_authored() -> None:
    families = group_events_by_family(TABLES)
    members = families["2"]
    description = family_description("2", members, TABLES)
    assert description == "; ".join(TABLES.events[code] for code in members[:3])
    assert family_label("2") == "Family 2"


def _member_answer(choice: str, probabilities: dict[str, float]) -> ChoiceAnswer:
    return ChoiceAnswer(type="choice", choice=choice, confidence=0.5, probabilities=probabilities)


def test_geometric_mean_scoring_picks_the_right_candidate() -> None:
    # Family call: family "2" is most probable (0.6), "0" and "3" trail.
    family_answer = _choice({"2": 0.6, "0": 0.3, "3": 0.1})
    # Member call for family "2": top choice "092" at 0.5 -> score sqrt(0.6*0.5)=0.5477
    # Member call for family "0": top choice "010" at 0.9 -> score sqrt(0.3*0.9)=0.5196
    # Member call for family "3": top choice "310" at 0.99 -> score sqrt(0.1*0.99)=0.3146
    # Family "2" wins here (0.5477 is the highest score): the winner matches call 1's top
    # family, so this fixture has no repair. The next test builds one that does.
    reply = SystemOneReply(
        model="jev-1.13.0",
        usage=SystemOneUsage(input_tokens=40, output_tokens=10),
        answers={
            "family": family_answer,
            "member_2": _member_answer("092", {"092": 0.5, "240": 0.5}),
            "member_0": _member_answer("010", {"010": 0.9, "020": 0.1}),
            "member_3": _member_answer("310", {"310": 0.99, "320": 0.01}),
        },
    )
    candidates = beam_candidates(reply)
    assert len(candidates) == 3
    winner = choose_event(reply)
    assert winner.family == "2"
    assert winner.event == "092"
    # Sanity: family "2"'s candidate score is exactly sqrt(0.6*0.5).
    by_family = {c.family: c for c in candidates}
    assert abs(by_family["2"].score - (0.6 * 0.5) ** 0.5) < 1e-12
    assert abs(by_family["0"].score - (0.3 * 0.9) ** 0.5) < 1e-12
    assert top_family(reply) == "2"
    # The winner *is* the top family here, so this reply shows no repair; a different fixture
    # (below) checks a case where the winner comes from a different family.
    assert winner.family == top_family(reply)


def test_geometric_mean_scoring_can_repair_the_top_family_choice() -> None:
    # Family "2" is the most probable family (0.55), but its member call is unconvincing
    # (0.3), while family "0" (0.45) has a near-certain member call (0.95):
    # sqrt(0.55*0.3)=0.406 vs sqrt(0.45*0.95)=0.654 -- family "0" wins overall.
    family_answer = _choice({"2": 0.55, "0": 0.45})
    reply = SystemOneReply(
        model="jev-1.13.0",
        usage=SystemOneUsage(input_tokens=20, output_tokens=5),
        answers={
            "family": family_answer,
            "member_2": _member_answer("092", {"092": 0.3, "240": 0.7}),
            "member_0": _member_answer("010", {"010": 0.95, "020": 0.05}),
        },
    )
    assert top_family(reply) == "2"
    winner = choose_event(reply)
    assert winner.family == "0"
    assert winner.event == "010"
    assert winner.family != top_family(reply)


def test_combine_replies_sums_tokens_and_folds_answers() -> None:
    family_exchange = Exchange(
        reply=SystemOneReply(
            model="jev-1.13.0",
            usage=SystemOneUsage(input_tokens=100, output_tokens=20),
            answers={"family": _choice({"2": 0.7, "0": 0.3})},
        ),
        attempts=1,
        retried_statuses=(),
        seconds=0.1,
    )
    member_exchanges = [
        (
            "2",
            Exchange(
                reply=SystemOneReply(
                    model="jev-1.13.0",
                    usage=SystemOneUsage(input_tokens=50, output_tokens=10),
                    answers={"member": _member_answer("092", {"092": 0.6, "240": 0.4})},
                ),
                attempts=2,
                retried_statuses=("429",),
                seconds=0.2,
            ),
        ),
        (
            "0",
            Exchange(
                reply=SystemOneReply(
                    model="jev-1.13.0",
                    usage=SystemOneUsage(input_tokens=30, output_tokens=5),
                    answers={"member": _member_answer("010", {"010": 0.9})},
                ),
                attempts=1,
                retried_statuses=(),
                seconds=0.15,
            ),
        ),
    ]
    combined = combine_replies(family_exchange, member_exchanges)
    assert combined.reply.usage.input_tokens == 180
    assert combined.reply.usage.output_tokens == 35
    assert combined.attempts == 4
    assert combined.retried_statuses == ("429",)
    assert abs(combined.seconds - 0.45) < 1e-12
    assert set(combined.reply.answers) == {"family", "member_2", "member_0"}
    winner = choose_event(combined.reply)
    assert winner.event == "092"


def _replies_row(case_id: str, event_choice: str) -> dict[str, object]:
    """One row in the shape ``jev_dev400.py run`` writes to ``replies.jsonl`` (not ``cases.jsonl``,
    which only an S1 evaluation run produces)."""
    return {
        "case_id": case_id,
        "ok": True,
        "error": None,
        "attempts": 1,
        "retried_statuses": [],
        "seconds": 0.3,
        "cost_usd": 0.0001,
        "reply": {
            "model": "jev-1.13.0",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "answers": {
                "phase": {
                    "type": "choice",
                    "choice": "450",
                    "confidence": 0.5,
                    "probabilities": {"450": 0.5},
                },
                "event": {
                    "type": "choice",
                    "choice": event_choice,
                    "confidence": 0.5,
                    "probabilities": {event_choice: 0.5},
                },
            },
        },
    }


def test_flat_event_accuracy_reads_repliesjsonl_not_casesjsonl(tmp_path: Path) -> None:
    # ANC09CA020's true occurrence is 550402 (true event "402"); ANC09CA024's is 552230
    # (true event "230"). One row answers right, one wrong.
    flat_folder = tmp_path / "flat_run"
    flat_folder.mkdir()
    raw_right = json.loads(FIXTURE.read_text())["record"]
    raw_wrong = json.loads(Path("tests/fixtures/records/ANC09CA024.json").read_text())["record"]
    rows = [_replies_row("ANC09CA020", "402"), _replies_row("ANC09CA024", "999")]
    (flat_folder / "replies.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    accuracy, n = flat_event_accuracy(
        flat_folder, ["ANC09CA020", "ANC09CA024"], [raw_right, raw_wrong], TABLES
    )
    assert n == 2
    assert accuracy == 0.5


def test_hierarchy_reading_helps_branch() -> None:
    assert hierarchy_reading(0.30, 0.20) == HIERARCHY_HELPS_READING


def test_hierarchy_reading_as_good_branch_within_three_points_either_way() -> None:
    assert hierarchy_reading(0.20, 0.21) == FLAT_AS_GOOD_READING
    assert hierarchy_reading(0.21, 0.20) == FLAT_AS_GOOD_READING


def test_hierarchy_reading_third_branch_names_the_measured_gap_when_far_worse() -> None:
    # The real experiment 5 result: hierarchical 5.5% against flat 17.7%, a -12.2pp gap.
    reading = hierarchy_reading(0.055, 0.177)
    assert reading not in (HIERARCHY_HELPS_READING, FLAT_AS_GOOD_READING)
    assert "5.5%" in reading
    assert "17.7%" in reading
    assert "-12.2%" in reading
    assert "neither fixed reading applies" in reading


def test_lean_payload_still_passes_the_leakage_guard() -> None:
    """The lean payload is built only via case_payload/RunSpec.exclusions -- never hand-edited."""
    raw = json.loads(FIXTURE.read_text())["record"]
    evidence, _, verdict = split_record(raw, exclude=LEAN_EXCLUSIONS)
    payload = Payload.from_evidence(evidence)
    assert not set(payload.fields()) & {r.value for r in LEAN_EXCLUSIONS}
    assert verdict.occurrence_codes  # verdict itself is untouched by evidence exclusions
