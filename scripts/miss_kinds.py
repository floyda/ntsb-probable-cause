"""How an arm C answer differs from the NTSB's defining event: one kind, and patterns, per case.

Status
    Live helper for S3.1 Task 15, free and pure: no file, no model call. It is the classifier
    behind ``scripts/exploratory/s3_miss_kinds.py``'s counts and ``scripts/s3_trail_pages.py``'s
    "Differences at a glance", so the counts and the page name a case's miss the same way. It
    sets no bar and tunes nothing.

Why
    Before a tuning round is registered, Andy reads where the loop went wrong. Two questions
    come first for a case: did the loop's first code come near the NTSB's defining event (the
    first code of the NTSB's ordered occurrence sequence), and does the miss follow a pattern
    seen across many cases? A rule written once answers both the same way on the page and in
    the counts.

The codes
    An occurrence code is six digits: a three-digit phase and a three-digit event. The loop's
    answer is the last checkpoint of a case that ``scripts/round_result.py`` does not count as
    failed (decision 0136 item 1), its codes in the loop's ranked order.

The kinds (exactly one per case; ``KINDS``, ``KIND_MEANINGS``)
    Tested in this order: failed or not scored; first code right; order; same phase, different
    event; same event, different phase; different phase and event. "First code right" is scored
    right unless the loop abstained, so in an "always wrong" group it marks an abstention.

The patterns (none, one or several per scored case; ``PATTERNS``, ``PATTERN_MEANINGS``)
    Stall/spin against loss of control, each way round, on the two first codes; a generic
    consequence (the loop's first event is 240, 341 or 342, the NTSB's first event is none of
    them, and the NTSB's first code is not among the loop's codes); the NTSB's cause
    undetermined (``0500000000`` flagged as cause, or the NTSB's first code ``990000``) while the
    loop did not abstain; the loop abstained. A failed case has no answer and so no pattern.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from ntsb_probable_cause.scoring.hypothesis import Hypothesis
from ntsb_probable_cause.scoring.records import CaseResult
from scripts.round_result import counted_failed

type Kind = Literal[
    "first code right",
    "order",
    "same phase, different event",
    "same event, different phase",
    "different phase and event",
    "failed or not scored",
]
type Pattern = Literal[
    "NTSB stall/spin first, loop loss of control first",
    "NTSB loss of control first, loop stall/spin first",
    "generic consequence",
    "NTSB cause undetermined",
    "abstained",
]

KINDS: Final[tuple[Kind, ...]] = (
    "first code right",
    "order",
    "same phase, different event",
    "same event, different phase",
    "different phase and event",
    "failed or not scored",
)
PATTERNS: Final[tuple[Pattern, ...]] = (
    "NTSB stall/spin first, loop loss of control first",
    "NTSB loss of control first, loop stall/spin first",
    "generic consequence",
    "NTSB cause undetermined",
    "abstained",
)

LOSS_OF_CONTROL: Final = "240"  # Loss of control in flight
STALL_SPIN: Final = "241"  # Aerodynamic stall/spin
# Loss of control in flight; loss of engine power, total and partial: events that follow many
# different causes.
GENERIC_EVENTS: Final = ("240", "341", "342")
NOT_DETERMINED_FINDING: Final = "0500000000"
UNKNOWN_OCCURRENCE: Final = "990000"

KIND_MEANINGS: Final[Mapping[Kind, str]] = {
    "first code right": (
        "the loop's first code is the NTSB's first (scored right unless the loop abstained)"
    ),
    "order": "the NTSB's first code is the loop's second or third code",
    "same phase, different event": (
        "the loop's first code has the NTSB's first's phase, not its event"
    ),
    "same event, different phase": (
        "the loop's first code has the NTSB's first's event, not its phase"
    ),
    "different phase and event": (
        "the loop's first code shares neither, and the NTSB's first is not among its codes"
    ),
    "failed or not scored": (
        "the case failed, or holds no score: no answer to compare (decision 0136 item 1)"
    ),
}
PATTERN_MEANINGS: Final[Mapping[Pattern, str]] = {
    "NTSB stall/spin first, loop loss of control first": (
        f"the NTSB's first event is {STALL_SPIN}, the loop's first event {LOSS_OF_CONTROL}"
    ),
    "NTSB loss of control first, loop stall/spin first": (
        f"the NTSB's first event is {LOSS_OF_CONTROL}, the loop's first event {STALL_SPIN}"
    ),
    "generic consequence": (
        f"the loop's first event is {', '.join(GENERIC_EVENTS[:-1])} or {GENERIC_EVENTS[-1]}, "
        "the NTSB's first event is none of these, and the NTSB's first code is not among the "
        "loop's codes"
    ),
    "NTSB cause undetermined": (
        f"{NOT_DETERMINED_FINDING} is flagged as cause, or the NTSB's first code is "
        f"{UNKNOWN_OCCURRENCE}, and the loop did not abstain"
    ),
    "abstained": "the loop abstained",
}


@dataclass(frozen=True)
class Difference:
    """How one case's answer differs from the NTSB's defining event."""

    kind: Kind
    patterns: tuple[Pattern, ...]


def answer_codes(hypothesis: Hypothesis) -> tuple[str, ...]:
    """The six-digit occurrence codes of an answer, in the loop's ranked order."""
    return tuple(guess.phase + guess.event for guess in hypothesis.occurrence)


def scored_answer(case: CaseResult) -> Hypothesis | None:
    """The answer a case was scored on, its last checkpoint; None when counted as failed."""
    return None if counted_failed(case) else case.steps[-1].hypothesis


def _kind(first: str, answer: Sequence[str]) -> Kind:
    top = answer[0]
    if top == first:
        return "first code right"
    if first in answer[1:]:
        return "order"
    if top[:3] == first[:3]:
        return "same phase, different event"
    if top[3:] == first[3:]:
        return "same event, different phase"
    return "different phase and event"


def _patterns(
    first: str, answer: Sequence[str], *, abstained: bool, flagged: Sequence[str]
) -> tuple[Pattern, ...]:
    event, top = first[3:], answer[0][3:]
    found: list[Pattern] = []
    if event == STALL_SPIN and top == LOSS_OF_CONTROL:
        found.append("NTSB stall/spin first, loop loss of control first")
    if event == LOSS_OF_CONTROL and top == STALL_SPIN:
        found.append("NTSB loss of control first, loop stall/spin first")
    if top in GENERIC_EVENTS and event not in GENERIC_EVENTS and first not in answer:
        found.append("generic consequence")
    undetermined = NOT_DETERMINED_FINDING in flagged or first == UNKNOWN_OCCURRENCE
    if undetermined and not abstained:
        found.append("NTSB cause undetermined")
    if abstained:
        found.append("abstained")
    return tuple(found)


def classify(
    ntsb: Sequence[str],
    answer: Sequence[str] | None,
    *,
    abstained: bool = False,
    flagged: Sequence[str] = (),
) -> Difference:
    """The kind and the patterns of one case.

    Args:
        ntsb: the NTSB's occurrence codes, in its order; the first is the defining event.
        answer: the loop's occurrence codes, ranked; None when the case failed or holds no score.
        abstained: whether the loop abstained.
        flagged: the NTSB's findings flagged as in the probable cause (ten digits each).

    Returns:
        The case's difference; a failed case has its kind and no pattern.

    Raises:
        ValueError: the NTSB's verdict or the answer holds no occurrence code.
    """
    if not ntsb:
        raise ValueError("the NTSB's verdict holds no occurrence code: no defining event")
    if answer is None:
        return Difference("failed or not scored", ())
    if not answer:
        raise ValueError("the answer holds no occurrence code")
    first = ntsb[0]
    return Difference(
        _kind(first, answer), _patterns(first, answer, abstained=abstained, flagged=flagged)
    )


def case_difference(case: CaseResult) -> Difference:
    """:func:`classify` on one case of a run, from its verdict and the answer it was scored on.

    Args:
        case: one case of a run's ``cases.jsonl``.

    Returns:
        The case's difference.
    """
    answer = scored_answer(case)
    if answer is None:
        return classify(case.verdict_occurrence, None)
    return classify(
        case.verdict_occurrence,
        answer_codes(answer),
        abstained=answer.abstain,
        flagged=case.verdict_findings_in_cause,
    )
