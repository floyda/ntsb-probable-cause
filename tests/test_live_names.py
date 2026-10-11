"""``live.names``: the names step for the board (decision 0182)."""

import subprocess
import sys
from pathlib import Path

from ntsb_probable_cause.docket.title_vocab import known_title_words
from ntsb_probable_cause.live.names import NAME_MARKER, board_text, board_title, case_names

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
