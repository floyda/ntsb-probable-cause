"""scripts/miss_kinds.py: how an answer's first code differs from the NTSB's defining event.

S3.1 Task 15. Pure: synthetic codes and synthetic ``CaseResult`` objects, no file.
"""

from collections.abc import Sequence

import pytest
from scripts import miss_kinds as mk
from tests.test_occurrence_misses import _case

from ntsb_probable_cause.scoring.records import CaseResult

# Phases 552 (landing roll), 500 (approach), 450 (maneuvering). Events 240 loss of control in
# flight, 241 aerodynamic stall/spin, 341 / 342 loss of engine power (total / partial), 120
# controlled flight into terrain, 192 fuel exhaustion, 470 collision with terrain.


def _kind(ntsb: Sequence[str], answer: Sequence[str] | None) -> str:
    return mk.classify(ntsb, answer).kind


def _patterns(
    ntsb: Sequence[str],
    answer: Sequence[str],
    *,
    abstained: bool = False,
    flagged: Sequence[str] = (),
) -> tuple[str, ...]:
    return mk.classify(ntsb, answer, abstained=abstained, flagged=flagged).patterns


class TestKind:
    def test_the_first_code_right(self) -> None:
        assert _kind(("552240", "552241"), ("552240", "552241")) == "first code right"

    @pytest.mark.parametrize("answer", [("552241", "552240"), ("552241", "500120", "552240")])
    def test_order_the_ntsbs_first_is_the_answers_second_or_third(
        self, answer: tuple[str, ...]
    ) -> None:
        assert _kind(("552240",), answer) == "order"

    def test_order_wins_over_a_shared_phase_or_event(self) -> None:
        # The first code shares the phase (552) and the NTSB's first is the answer's second.
        assert _kind(("552240",), ("552241", "552240")) == "order"
        # The first code shares the event (240) and the NTSB's first is the answer's third.
        assert _kind(("552240",), ("500240", "500120", "552240")) == "order"

    def test_the_same_phase_a_different_event(self) -> None:
        assert _kind(("552240",), ("552241",)) == "same phase, different event"

    def test_the_same_event_a_different_phase(self) -> None:
        assert _kind(("552240",), ("500240", "552241")) == "same event, different phase"

    def test_different_phase_and_event(self) -> None:
        assert _kind(("552240",), ("500241", "450470")) == "different phase and event"

    def test_only_the_first_code_decides_phase_and_event(self) -> None:
        # The answer's second code shares the phase; the first shares nothing.
        assert _kind(("552240",), ("500241", "552120")) == "different phase and event"

    def test_a_later_ntsb_code_does_not_count_as_order(self) -> None:
        # The NTSB's *second* code is the answer's second: still not order.
        assert _kind(("552240", "500120"), ("450470", "500120")) == "different phase and event"

    def test_no_answer_is_failed_or_not_scored_with_no_pattern(self) -> None:
        difference = mk.classify(("990000",), None, flagged=("0500000000",))
        assert difference == mk.Difference("failed or not scored", ())

    def test_an_ntsb_verdict_with_no_occurrence_code_is_not_classified(self) -> None:
        with pytest.raises(ValueError, match="no occurrence code"):
            mk.classify((), ("552240",))

    def test_an_answer_with_no_code_is_not_classified(self) -> None:
        with pytest.raises(ValueError, match="no occurrence code"):
            mk.classify(("552240",), ())

    def test_kinds_lists_every_kind_once_each_with_its_meaning(self) -> None:
        assert len(set(mk.KINDS)) == len(mk.KINDS) == 6
        assert set(mk.KIND_MEANINGS) == set(mk.KINDS)


class TestPatterns:
    def test_none(self) -> None:
        assert _patterns(("552240",), ("500120",)) == ()

    def test_ntsb_stall_spin_first_loop_loss_of_control_first(self) -> None:
        assert _patterns(("552241",), ("500240", "500120")) == (
            "NTSB stall/spin first, loop loss of control first",
            "generic consequence",
        )

    def test_ntsb_loss_of_control_first_loop_stall_spin_first(self) -> None:
        assert _patterns(("552240",), ("500241",)) == (
            "NTSB loss of control first, loop stall/spin first",
        )

    def test_stall_spin_against_loss_of_control_reads_the_first_codes_only(self) -> None:
        # Loss of control second in the answer: no pattern.
        assert _patterns(("552241",), ("500120", "500240")) == ()
        # The NTSB's stall/spin is its second code; its first is fuel exhaustion.
        assert _patterns(("552192", "552241"), ("500240",)) == ("generic consequence",)

    @pytest.mark.parametrize("generic", ["240", "341", "342"])
    def test_generic_consequence(self, generic: str) -> None:
        assert _patterns(("552192",), (f"500{generic}", "500120")) == ("generic consequence",)

    def test_not_generic_when_the_ntsbs_first_event_is_generic_too(self) -> None:
        assert _patterns(("552342",), ("500341",)) == ()
        assert _patterns(("552341",), ("552240",)) == ()

    def test_not_generic_when_the_answer_holds_the_ntsbs_first_code(self) -> None:
        assert _patterns(("552192",), ("500240", "552192")) == ()
        # The same holds for stall/spin, which is then order, not a missed event.
        assert _patterns(("552241",), ("552240", "552241")) == (
            "NTSB stall/spin first, loop loss of control first",
        )

    def test_generic_when_the_answer_holds_the_ntsbs_event_under_another_phase(self) -> None:
        assert _patterns(("552192",), ("500240", "500192")) == ("generic consequence",)

    def test_not_generic_when_the_answers_first_event_is_specific(self) -> None:
        assert _patterns(("552192",), ("500120", "500240")) == ()

    def test_ntsb_cause_undetermined_by_the_flagged_finding(self) -> None:
        patterns = _patterns(("552240",), ("500120",), flagged=("0106201220", "0500000000"))
        assert patterns == ("NTSB cause undetermined",)

    def test_another_flagged_finding_is_not_undetermined(self) -> None:
        assert _patterns(("552240",), ("500120",), flagged=("0106201220",)) == ()

    def test_ntsb_cause_undetermined_by_the_unknown_occurrence(self) -> None:
        assert _patterns(("990000",), ("500120",)) == ("NTSB cause undetermined",)
        assert _patterns(("990000",), ("990000",)) == ("NTSB cause undetermined",)

    def test_an_unknown_phase_or_event_alone_is_not_undetermined(self) -> None:
        assert _patterns(("990240",), ("500120",)) == ()
        assert _patterns(("552000",), ("500120",)) == ()

    def test_undetermined_is_not_flagged_when_the_loop_abstained(self) -> None:
        assert _patterns(("990000",), ("500120",), abstained=True) == ("abstained",)

    def test_abstained(self) -> None:
        difference = mk.classify(("552240",), ("552240",), abstained=True)
        assert difference == mk.Difference("first code right", ("abstained",))

    def test_patterns_come_in_the_order_of_patterns(self) -> None:
        patterns = _patterns(("552241",), ("500240",), flagged=("0500000000",))
        assert patterns == (
            "NTSB stall/spin first, loop loss of control first",
            "generic consequence",
            "NTSB cause undetermined",
        )
        assert list(mk.PATTERNS).index(patterns[0]) < list(mk.PATTERNS).index(patterns[1])
        assert set(mk.PATTERN_MEANINGS) == set(mk.PATTERNS)


class TestCase:
    def test_a_scored_case_reads_its_last_checkpoint(self) -> None:
        case = _case("ZQX001", ("552241", "552240"), ("552240", "500120"))
        assert mk.case_difference(case) == mk.Difference(
            "same phase, different event",
            ("NTSB stall/spin first, loop loss of control first", "generic consequence"),
        )
        answer = mk.scored_answer(case)
        assert answer is not None
        assert mk.answer_codes(answer) == ("552240", "500120")

    def test_the_flagged_findings_are_the_cause_ones(self) -> None:
        case = _case("ZQX001", ("552240",), ("500120",)).model_copy(
            update={"verdict_findings_in_cause": ("0500000000",)}
        )
        assert mk.case_difference(case).patterns == ("NTSB cause undetermined",)
        unflagged = case.model_copy(
            update={"verdict_findings_in_cause": (), "verdict_findings": ("0500000000",)}
        )
        assert mk.case_difference(unflagged).patterns == ()

    def test_an_abstained_case(self) -> None:
        case = _case("ZQX001", ("552240",), ("552240",), abstain=True)
        assert mk.case_difference(case) == mk.Difference("first code right", ("abstained",))

    def test_a_failed_case(self) -> None:
        case = _case("ZQX001", ("552240",), (), scored=False)
        assert mk.scored_answer(case) is None
        assert mk.case_difference(case) == mk.Difference("failed or not scored", ())

    def test_a_failed_case_with_checkpoints_is_still_failed(self) -> None:
        # Arm C keeps the checkpoints of a case that failed later (at its refinement, say).
        case = _case("ZQX001", ("552240",), ("552240",)).model_copy(
            update={"failure": "failed: coding", "scores": None}
        )
        assert mk.scored_answer(case) is None
        assert mk.case_difference(case).kind == "failed or not scored"

    def test_a_case_with_no_score_is_not_scored(self) -> None:
        case: CaseResult = _case("ZQX001", ("552240",), ("552240",)).model_copy(
            update={"scores": None}
        )
        assert mk.case_difference(case).kind == "failed or not scored"
