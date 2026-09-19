"""``ntsb_probable_cause.docket.title_vocab``: the committed vocabulary and its lookup."""

from pathlib import Path

from ntsb_probable_cause.docket.title_vocab import (
    capitalised_words,
    is_ordinary_word,
    known_title_words,
    load_title_vocabulary,
)


def test_capitalised_words_matches_strict_title_case_tokens_only() -> None:
    """Three letters or more, initial capital, the rest lowercase -- see the module docstring.

    "of" and "to" are lowercase (not matched); "NTSB" is all-caps (not matched either -- see
    the module docstring for why).
    """
    assert capitalised_words("Statement of Party Representatives to NTSB Investigation") == [
        "Statement",
        "Party",
        "Representatives",
        "Investigation",
    ]


def test_capitalised_words_excludes_all_caps_and_short_words() -> None:
    words = capitalised_words("NTSB FAA Of By Report")
    assert "NTSB" not in words
    assert "FAA" not in words
    assert "Of" not in words
    assert "By" not in words
    assert words == ["Report"]


def test_load_title_vocabulary_is_committed_and_lowercased() -> None:
    vocabulary = load_title_vocabulary()
    assert len(vocabulary) > 0
    assert all(word == word.lower() for word in vocabulary)
    # A word the module docstring and scripts/build_title_vocab.py's own docstring both name
    # as an example -- a stable member of the committed file, not an artefact of this test.
    assert "aircraft" in vocabulary


def test_known_title_words_combines_vocabulary_and_a_present_dictionary(tmp_path: Path) -> None:
    dictionary_path = tmp_path / "words"
    dictionary_path.write_text("zzzinventedword\n")
    known, found = known_title_words(dictionary_path=dictionary_path)
    assert found is True
    assert "zzzinventedword" in known
    assert "aircraft" in known  # still carries the committed vocabulary


def test_known_title_words_reports_a_missing_dictionary(tmp_path: Path) -> None:
    known, found = known_title_words(dictionary_path=tmp_path / "does-not-exist")
    assert found is False
    assert known == load_title_vocabulary()


def test_is_ordinary_word_is_plain_membership_case_insensitive() -> None:
    known = frozenset({"aircraft", "report"})
    assert is_ordinary_word("Aircraft", known)
    assert is_ordinary_word("REPORT", known)
    assert not is_ordinary_word("Thackerson", known)
