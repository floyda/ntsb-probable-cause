"""``live.names``: the names step for the board (decision 0182)."""

import subprocess
import sys
from pathlib import Path

from ntsb_probable_cause.docket.title_vocab import known_title_words
from ntsb_probable_cause.live.names import (
    NAME_MARKER,
    NAMES_LIMIT,
    board_text,
    board_title,
    case_names,
)

_RAW = {
    "aircrafts": [
        {
            "ownerOperators": [
                {"registeredOwner": "Invented Aviation LLC", "operatorName": "Zed Air"}
            ]
        }
    ]
}


def test_title_surname_becomes_the_marker() -> None:
    known, _ = known_title_words()
    assert board_title("Statement of Smithers", known) == "Statement of [name]"
    assert NAME_MARKER == "[name]"


def test_title_keeps_a_word_in_the_list() -> None:
    known, _ = known_title_words()
    assert board_title("Cessna Engine Examination", known) == "Cessna Engine Examination"


def test_owner_replaced_in_each_kind_of_prose() -> None:
    names = case_names(_RAW)
    for kind in ("cause", "account", "note", "reason"):
        text = f"The {kind} says invented aviation llc, then Zed Air."
        assert board_text(text, names) == f"The {kind} says [name], then [name]."


def test_capitalised_word_in_prose_is_kept() -> None:
    """Pins 0182: the step never guesses at a name in prose."""
    assert board_text("Smithers reported a gust", case_names(_RAW)) == "Smithers reported a gust"


def test_no_owner_strings_changes_nothing() -> None:
    assert board_text("Plain text.", case_names({})) == "Plain text."


def test_import_works_with_no_tests_folder(tmp_path: Path) -> None:
    code = (
        "from ntsb_probable_cause.live.names import board_title;"
        "from ntsb_probable_cause.docket.title_vocab import known_title_words;"
        "k, found = known_title_words(); assert found;"
        "print(board_title('Cessna Statement of Smithers', k))"
    )
    done = subprocess.run(  # noqa: S603 -- fixed argv, invented code
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == "Cessna Statement of [name]"


_RAW_REG = {
    "aircrafts": [
        {
            "aircraftRegistrationNumber": "N123XX",
            "ownerOperators": [{"registeredOwner": "Invented Aviation LLC"}],
        }
    ]
}


def test_registration_is_replaced_in_each_kind_of_prose() -> None:
    names = case_names(_RAW_REG)
    assert names.registrations == ("N123XX",)
    for kind in ("cause", "account", "note", "reason"):
        text = f"The {kind} says n123xx, and Invented Aviation LLC flew N123XX."
        assert board_text(text, names) == f"The {kind} says [name], and [name] flew [name]."


def test_registration_is_replaced_in_a_title() -> None:
    """The title rule alone never matches an N-number; the case's own registration is replaced."""
    known, _ = known_title_words()
    names = case_names(_RAW_REG)
    assert board_title("Maintenance records N123XX", known) == "Maintenance records N123XX"
    assert board_title("Maintenance records N123XX", known, names) == "Maintenance records [name]"


def test_a_case_without_a_registration_replaces_none() -> None:
    names = case_names({"aircrafts": [{"aircraftRegistrationNumber": "  "}]})
    assert names.registrations == ()
    assert board_text("N123XX stays", names) == "N123XX stays"


_TWO_AIRCRAFT = {
    "aircrafts": [
        {
            "aircraftRegistrationNumber": "N123XX",
            "ownerOperators": [{"registeredOwner": "Blue Sky Flying", "operatorName": "Zed Air"}],
        },
        {
            "aircraftRegistrationNumber": " N456YY ",
            "ownerOperators": [{"registeredOwner": "Second Owner Group"}],
        },
        {"aircraftRegistrationNumber": "N1"},
        {"aircraftRegistrationNumber": "N123XX"},
        "not an aircraft",
    ]
}


def test_every_aircrafts_registration_is_replaced_once_and_a_short_one_never() -> None:
    """Decision 0184 (item A6): every aircraft, not only the first; "N1" would hit tokens."""
    names = case_names(_TWO_AIRCRAFT)
    assert names.registrations == ("N123XX", "N456YY")
    text = "N123XX hit n456yy; the N1 gauge read low, and Second Owner Group was told."
    assert board_text(text, names) == (
        "[name] hit [name]; the N1 gauge read low, and [name] was told."
    )


def test_a_titles_owner_and_operator_strings_are_replaced_any_case() -> None:
    """Item A6: the exact parts go first; an owner made of ordinary words passes the title rule."""
    known, _ = known_title_words()
    names = case_names(_TWO_AIRCRAFT)
    title = "Letter from BLUE SKY FLYING to zed air about N456YY"
    assert board_title(title, known) == title  # ordinary words: the title rule keeps them
    assert board_title(title, known, names) == "Letter from [name] to [name] about [name]"


def test_the_published_limit_names_titles_prose_and_short_registrations() -> None:
    assert NAMES_LIMIT.startswith("A name the rules cannot recognise is not replaced: in prose,")
    assert "in titles, also a name made only of ordinary words" in NAMES_LIMIT
    assert "shorter than 3 characters" in NAMES_LIMIT


def test_a_common_given_name_and_surname_in_a_title_is_the_published_limit() -> None:
    """The limit, pinned: a name made only of ordinary words is not caught by the title rule."""
    known, _ = known_title_words()
    assert board_title("Witness statement - John Smith", known) == (
        "Witness statement - John Smith"
    )
