"""Question 6's sentence (S5 step 4b, Task 3): the rule picks one group, whatever the row order."""

from datetime import date

import pytest
from scripts.exploratory import s3_precedent_probe as pp
from scripts.exploratory import s5_one_sentence as one

from ntsb_probable_cause.scoring.codes import load_tables


def _case(n: int, text: str, first: str) -> pp.PoolText:
    return pp.PoolText(
        case_id=f"CEN15LA{n:03d}",
        event_date=date(2015, 1, 1),
        text=text,
        sequence=(first, "999999"),
    )


# Three groups of exact twins, invented:
# - "a": 4 cases, 2 different first codes;
# - "b": 3 cases, 3 different first codes (the rule's pick: most different first codes);
# - "c": 6 cases, 1 first code (the largest, which the rule does not prefer).
_POOL = [
    *(
        _case(i, "The pilot's failure to maintain control.", f)
        for i, f in enumerate(["240220", "240220", "240220", "550402"])
    ),
    *(
        _case(10 + i, "The pilot's improper flare.", f)
        for i, f in enumerate(["551094", "550402", "500250"])
    ),
    *(
        _case(20 + i, "The loss of engine power for undetermined reasons.", "300000")
        for i in range(6)
    ),
    _case(30, "A sentence no other case shares.", "240220"),
]


def test_the_rule_takes_the_group_with_the_most_different_first_codes() -> None:
    chosen = one.choose(_POOL)
    assert chosen.sentence == "The pilot's improper flare."
    assert chosen.cases == 3
    assert [code for code, _ in chosen.codes] == ["500250", "550402", "551094"]  # ties by code
    assert chosen.groups == 3


def test_a_tie_on_codes_goes_to_the_larger_group() -> None:
    extra = [_case(40 + i, "The pilot's improper flare.", "551094") for i in range(3)]
    rival = [
        _case(50 + i, "A second three-code sentence.", f)
        for i, f in enumerate(["111111", "222222", "333333"])
    ]
    chosen = one.choose([*_POOL, *extra, *rival])
    assert chosen.sentence == "The pilot's improper flare."
    assert chosen.cases == 6
    assert chosen.codes[0] == ("551094", 4)


def test_a_full_tie_goes_to_the_sentence_that_sorts_first() -> None:
    rival = [
        _case(50 + i, "A second three-code sentence.", f)
        for i, f in enumerate(["111111", "222222", "333333"])
    ]
    assert one.choose([*_POOL, *rival]).sentence == "A second three-code sentence."


def test_row_order_never_changes_the_pick() -> None:
    first = one.choose(_POOL)
    orders = [_POOL[i:] + _POOL[:i] for i in range(len(_POOL))] + [_POOL[::-1]]
    for rows in orders:
        assert one.choose(rows) == first


def test_the_shown_text_is_the_groups_commonest_spelling() -> None:
    # Exact twins ignore case and punctuation, so a group can hold two spellings.
    spelled = [_case(60, "the pilot's improper flare", "999990")]
    chosen = one.choose([*_POOL, *spelled])
    assert chosen.sentence == "The pilot's improper flare."
    assert chosen.cases == 4


def test_a_capitalised_word_mid_sentence_stops_it() -> None:
    named = [
        _case(70 + i, "The pilot, Smith, lost control.", f)
        for i, f in enumerate(["1", "2", "3", "4"])
    ]
    with pytest.raises(SystemExit, match="capitalised"):
        one.choose([*_POOL, *named])


def test_the_report_states_the_rule_first_and_labels_codes() -> None:
    text = one.report(one.choose(_POOL), load_tables())
    assert text.index(one.RULE) < text.index("sentence:")
    assert "550402  Landing / Loss of visual reference" in text
