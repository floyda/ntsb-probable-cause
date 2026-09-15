"""The held-out ledger and the commit state every run records (decisions 0018, 0026)."""

from pathlib import Path

import pytest

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring import ledger
from ntsb_probable_cause.scoring.records import RunRecord


def test_heldout_refused_when_dirty() -> None:
    with pytest.raises(ConfigurationError, match="uncommitted"):
        ledger.refuse_if_heldout_and_dirty("heldout-400", dirty=True)
    ledger.refuse_if_heldout_and_dirty("dev-400", dirty=True)
    ledger.refuse_if_heldout_and_dirty("heldout-400", dirty=False)


def test_append_row_creates_header_once(tmp_path: Path, run_record: RunRecord) -> None:
    path = tmp_path / "heldout-ledger.md"
    ledger.append_row(path, run_record, "docs/results/x.txt")
    ledger.append_row(path, run_record, "docs/results/y.txt")
    lines = path.read_text().splitlines()
    rows = sum(row.startswith("| 20") for row in lines)
    assert lines[0].startswith("# Held-out ledger")
    assert rows == 2


def test_append_row_marks_a_dirty_commit(tmp_path: Path, run_record: RunRecord) -> None:
    dirty = run_record.model_copy(update={"dirty": True})
    path = tmp_path / "heldout-ledger.md"
    ledger.append_row(path, dirty, "docs/results/x.txt")
    assert f"{dirty.commit_sha}*" in path.read_text()


def test_commit_state_returns_a_short_sha_and_a_dirty_flag() -> None:
    sha, dirty = ledger.commit_state()
    assert len(sha) >= 7
    assert isinstance(dirty, bool)
