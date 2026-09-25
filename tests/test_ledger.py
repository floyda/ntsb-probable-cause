"""The held-out ledger and the commit state every run records (decisions 0018, 0026)."""

from pathlib import Path

import pytest

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.gitinfo import commits_since
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


def test_append_row_never_writes_an_absolute_path(tmp_path: Path, run_record: RunRecord) -> None:
    """The ledger is committed, so a row must not carry the running machine's filesystem.

    The first held-out rows recorded `/Users/<name>/Workspace/.../cases.jsonl`, because both
    call sites pass `str(folder / ...)` and `folder` comes from an absolute setting.
    """
    path = tmp_path / "heldout-ledger.md"
    ledger.append_row(path, run_record, str(tmp_path / "20260917T061527-x-heldout-400" / "c.jsonl"))
    row = next(line for line in path.read_text().splitlines() if line.startswith("| 20"))
    assert str(tmp_path) not in row
    assert "| 20260917T061527-x-heldout-400/c.jsonl |" in row


def test_results_ref_keeps_a_bare_file_name() -> None:
    assert ledger.results_ref("cases.jsonl") == "cases.jsonl"


def test_commit_state_returns_a_short_sha_and_a_dirty_flag() -> None:
    sha, dirty = ledger.commit_state()
    assert len(sha) >= 7
    assert isinstance(dirty, bool)


def test_commits_since_head_is_empty() -> None:
    """`HEAD..HEAD` holds no commit; this reads no history, only proves the call's shape."""
    assert commits_since("HEAD") == ()


def test_a_new_ledger_carries_the_version_column(tmp_path: Path, run_record: RunRecord) -> None:
    ledger_path = tmp_path / "ledger.md"
    ledger.append_row(
        ledger_path, run_record.model_copy(update={"sample": "heldout-400"}), "r/cases.jsonl"
    )
    text = ledger_path.read_text()
    assert "| evidence |" in text
    assert "| v1 |" in text


def test_an_old_ledger_gains_a_versioned_table_below_it(
    tmp_path: Path, run_record: RunRecord
) -> None:
    ledger_path = tmp_path / "ledger.md"
    ledger_path.write_text(
        "# Held-out ledger\n\n| date | sample | arm | exclusions | includes | model | commit "
        "| cost USD | results |\n|---|---|---|---|---|---|---|---|---|\n| old row |\n"
    )
    held = run_record.model_copy(update={"sample": "heldout-400", "evidence_version": "v2"})
    ledger.append_row(ledger_path, held, "r/cases.jsonl")
    ledger.append_row(ledger_path, held, "r/cases.jsonl")
    text = ledger_path.read_text()
    assert text.count("| evidence |") == 1
    assert text.index("| old row |") < text.index("From S2.6")
    assert text.count("| v2 |") == 2
