"""``scripts/build_title_vocab.py``: the committed docket-title vocabulary generator."""

from pathlib import Path

from scripts.build_title_vocab import build_vocabulary, main

from ntsb_probable_cause.docket.title_vocab import VENDORED_DICTIONARY_PATH, known_title_words

_ROW_TEMPLATE = (
    "<tr><td><b>{index}</b></td><td>{title}</td><td><b>3</b></td><td>0</td>"
    "<td>Report</td><td></td></tr>"
)


def _listing_html(titles: list[str]) -> str:
    rows = "".join(_ROW_TEMPLATE.format(index=i, title=t) for i, t in enumerate(titles, start=1))
    return f"<html><body>Docket Items: {len(titles)}<table>{rows}</table></body></html>"


def _write_docket(docket_dir: Path, mkey: str, titles: list[str]) -> None:
    folder = docket_dir / mkey
    folder.mkdir(parents=True)
    (folder / "listing.html").write_text(_listing_html(titles), encoding="utf-8")


def test_build_vocabulary_keeps_only_words_meeting_the_docket_threshold(tmp_path: Path) -> None:
    # "Common" appears in four dockets (below a threshold of 5); "Report" appears in five.
    for i in range(4):
        _write_docket(tmp_path, f"{i}", ["Common Word Report"])
    _write_docket(tmp_path, "4", ["Report Only"])
    words = build_vocabulary(tmp_path, min_dockets=5)
    assert "report" in words
    assert "common" not in words
    assert "word" not in words


def test_build_vocabulary_counts_distinct_dockets_not_occurrences(tmp_path: Path) -> None:
    """A word repeated many times in one docket's titles counts once, not once per title."""
    _write_docket(tmp_path, "0", ["Repeated Item"] * 10)
    words = build_vocabulary(tmp_path, min_dockets=1)
    assert "repeated" in words
    words_at_two = build_vocabulary(tmp_path, min_dockets=2)
    assert "repeated" not in words_at_two


def test_build_vocabulary_excludes_all_caps_and_short_words(tmp_path: Path) -> None:
    for i in range(5):
        _write_docket(tmp_path, f"{i}", ["NTSB Of Report"])
    words = build_vocabulary(tmp_path, min_dockets=5)
    assert "ntsb" not in words
    assert "of" not in words
    assert "report" in words


def test_build_vocabulary_skips_a_non_numeric_folder_name(tmp_path: Path) -> None:
    """A folder whose name is not an ``mkey`` (an integer) is skipped, not raised past."""
    not_a_docket = tmp_path / "not-a-mkey"
    not_a_docket.mkdir()
    (not_a_docket / "listing.html").write_text(_listing_html(["Some Title"]), encoding="utf-8")
    assert build_vocabulary(tmp_path, min_dockets=1) == []


def test_build_vocabulary_skips_a_listing_that_will_not_parse(tmp_path: Path) -> None:
    """A listing whose declared item count disagrees with its rows raises ``DocketError``
    inside ``parse_listing``; that docket contributes nothing rather than aborting the run.
    """
    folder = tmp_path / "0"
    folder.mkdir()
    (folder / "listing.html").write_text(
        "<html><body>Docket Items: 99<table></table></body></html>", encoding="utf-8"
    )
    assert build_vocabulary(tmp_path, min_dockets=1) == []


def test_main_writes_the_vocabulary_file(tmp_path: Path) -> None:
    docket_dir = tmp_path / "docket"
    for i in range(5):
        _write_docket(docket_dir, f"{i}", ["Report Alone"])
    out = tmp_path / "out" / "title_words.txt"
    code = main(["--docket-dir", str(docket_dir), "--out", str(out), "--min-dockets", "5"])
    assert code == 0
    assert out.read_text().strip() == "Alone\nReport"


def test_main_reports_a_missing_docket_cache(tmp_path: Path) -> None:
    out = tmp_path / "title_words.txt"
    code = main(["--docket-dir", str(tmp_path / "no-such-cache"), "--out", str(out)])
    assert code == 1
    assert not out.exists()


def test_default_dictionary_is_the_vendored_file() -> None:
    assert Path("tests/fixtures/words.txt") == VENDORED_DICTIONARY_PATH
    words, found = known_title_words()
    assert found is True
    assert "examination" in words
