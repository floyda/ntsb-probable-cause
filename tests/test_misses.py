"""scoring/misses.py: where a first guess lands, and how deep a finding miss goes."""

import pytest

from ntsb_probable_cause.scoring.misses import (
    GROUPS,
    MISS_GROUPS,
    FindingDepth,
    finding_depth,
    miss_group,
    names_event,
)

TRUTH = ("452240", "452241")


@pytest.mark.parametrize(
    ("guesses", "group"),
    [
        (("452240",), "exact"),
        (("450240", "452241"), "right event, wrong phase"),
        (("452241",), "in sequence, not defining"),
        (("470470", "452241"), "a later guess in sequence"),
        (("450241",), "event under another phase"),
        (("552300",), "nothing in common"),
    ],
)
def test_each_case_lands_in_one_group(guesses: tuple[str, ...], group: str) -> None:
    assert miss_group(guesses, TRUTH, abstain=False) == group


def test_abstained_and_empty_truth() -> None:
    assert miss_group(("452240",), TRUTH, abstain=True) == "abstained"
    assert miss_group(("452240",), (), abstain=False) == "nothing in common"


def test_the_group_lists() -> None:
    assert GROUPS[0] == "exact"
    assert "exact" not in MISS_GROUPS
    assert "abstained" not in MISS_GROUPS
    assert len(MISS_GROUPS) == 5


def test_finding_depth_counts_each_flagged_finding_once_at_its_deepest_match() -> None:
    flagged = ("0106201220", "0206304044", "0303403591", "0204152044")
    predicted = ("0106201220", "0206304099", "0303403000")
    assert finding_depth(predicted, flagged) == FindingDepth(
        flagged=4,
        found=1,
        item_right_modifier_wrong=1,
        category_right_item_wrong=1,
        category_wrong=1,
    )
    assert finding_depth((), ()) + finding_depth((), ("0106201220",)) == FindingDepth(
        flagged=1,
        found=0,
        item_right_modifier_wrong=0,
        category_right_item_wrong=0,
        category_wrong=1,
    )


def test_names_event_is_a_fixed_phrase_list() -> None:
    assert names_event("The pilot LOST CONTROL of the airplane.", "240") is True
    assert names_event("The airplane stalled.", "240") is False
    assert names_event("anything", "999") is None
