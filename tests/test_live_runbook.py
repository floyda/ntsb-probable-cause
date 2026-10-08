"""The live-mornings runbook quotes refusals the program really prints (S3.3 Task 9, round 1)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "runbooks" / "live-shadow-mornings.md"


def _sources() -> str:
    paths = [
        *(ROOT / "src").rglob("*.py"),
        *(ROOT / "apps").rglob("*.py"),
        *(ROOT / "scripts").glob("*.py"),
        *(ROOT / "scripts").glob("*.sh"),
    ]
    return "\n".join(p.read_text() for p in paths)


def _refusal_rows() -> list[str]:
    text = RUNBOOK.read_text()
    section = text.split("## 6. When the command refuses", 1)[1].split("\n## 7.", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| `")]
    assert len(rows) >= 15
    return rows


def test_every_quoted_refusal_text_is_in_the_program() -> None:
    sources = _sources()
    for row in _refusal_rows():
        first = row.split("|")[1]
        for quoted in re.findall(r"`([^`]+)`", first):
            assert quoted in sources, quoted


def test_the_runbook_tells_andy_to_tell_claude_and_never_to_ask_or_report_to_andy() -> None:
    text = RUNBOOK.read_text()
    assert "ask Andy" not in text
    assert "report to Andy" not in text.lower()
    assert "Tell Claude" in text


def test_the_runbook_keeps_the_binding_rules() -> None:
    text = RUNBOOK.read_text()
    for needle in (
        "before any code is pushed to the branch",
        "LIMIT=1",
        "03:45 UTC",
        "09:00 UTC",
        "keep the lid open",
        "Do not start a second `paid_run.sh`",
        "no `run.jsonl` file at all",
        "`aws login`",
        "borrows the `default` login",
    ):
        assert needle in text, needle


def test_the_dry_run_goes_through_paid_run_and_the_runbook_says_where_to_run_from() -> None:
    text = RUNBOOK.read_text()
    assert "NTSB_PAID_BRANCH=s3-3-live-shadow scripts/paid_run.sh s33-dry-run" in text
    assert "`make s33-dry-run`" not in text  # make alone has no NTSB_API_KEY
    assert ".claude/worktrees/s3-3-live-shadow" in text
    assert "until S3.3 is merged" in text
