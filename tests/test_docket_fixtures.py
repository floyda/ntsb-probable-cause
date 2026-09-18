"""Docket fixtures: development cases only, listing pages as received (decision 0037)."""

import json
from datetime import date
from pathlib import Path

import pytest
from scripts.make_docket_fixture import (  # noqa: F401 -- interface import, exercised by Step 4.
    first_dev_400_case,
    write_listing_fixture,
)

from ntsb_probable_cause.errors import FixtureError
from ntsb_probable_cause.splits import Split, split_of

DOCKET_FIXTURES = Path("tests/fixtures/docket")


def docket_fixture_dirs() -> list[Path]:
    return sorted(p for p in DOCKET_FIXTURES.iterdir() if p.is_dir())


def test_at_least_one_listing_fixture_exists() -> None:
    assert docket_fixture_dirs(), "Task 6 commits the first listing fixture"


def test_every_docket_fixture_has_a_listing_and_a_manifest() -> None:
    for folder in docket_fixture_dirs():
        assert (folder / "listing.html").is_file(), folder
        manifest = json.loads((folder / "manifest.json").read_text())
        assert manifest["fixture"]["case_id"] == folder.name
        assert split_of(date.fromisoformat(manifest["fixture"]["event_date"])) is Split.DEV


def test_write_listing_fixture_refuses_a_held_out_case(tmp_path: Path) -> None:
    with pytest.raises(FixtureError, match="2021"):
        write_listing_fixture(
            "X", 1, "2021-05-01", "<html/>", "2026-09-18T00:00:00+00:00", "test", root=tmp_path
        )


def test_write_listing_fixture_writes_the_page_as_received(tmp_path: Path) -> None:
    folder = write_listing_fixture(
        "X", 1, "2016-05-01", "<html>x</html>", "2026-09-18T00:00:00+00:00", "test", root=tmp_path
    )
    assert (folder / "listing.html").read_text() == "<html>x</html>"
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["fixture"]["mkey"] == 1
    assert manifest["documents"] == []
