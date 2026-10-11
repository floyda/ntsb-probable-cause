"""`.github/workflows/ledger.yml` (S4 Task 13, decision 0178), read as YAML like CI's."""

import re
from pathlib import Path
from typing import Any

import yaml

WORKFLOW_PATH = Path(".github/workflows/ledger.yml")
FULL_SHA = re.compile(r"[0-9a-f]{40}")
S4_BRANCH = "s4-predictions-and-resolution"


def _load() -> dict[Any, Any]:
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text())
    assert isinstance(loaded, dict)
    return loaded


def _job() -> dict[str, Any]:
    jobs: dict[str, dict[str, Any]] = _load()["jobs"]
    assert list(jobs) == ["append"]
    return jobs["append"]


def _steps() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = _job()["steps"]
    return steps


def test_top_level_permissions_are_empty() -> None:
    assert _load()["permissions"] == {}


def test_the_job_has_exactly_contents_write_and_id_token_write() -> None:
    assert _job()["permissions"] == {"contents": "write", "id-token": "write"}


def test_triggers_are_schedule_push_to_the_s4_branch_and_dispatch() -> None:
    workflow = _load()
    on: dict[str, Any] = workflow.get("on", workflow.get(True)) or {}
    assert set(on) == {"schedule", "push", "workflow_dispatch"}
    assert on["push"]["branches"] == [S4_BRANCH]
    assert on["schedule"] == [{"cron": "0 10 * * *"}]


def test_every_use_is_pinned_by_a_full_sha() -> None:
    uses = [s["uses"] for s in _steps() if "uses" in s]
    assert uses
    for ref in uses:
        assert FULL_SHA.fullmatch(ref.rsplit("@", 1)[-1]), ref


def test_no_step_prints_a_downloaded_file() -> None:
    for step in _steps():
        run = step.get("run", "")
        assert not re.search(r"\b(cat|head|tail|jq)\b", run), run


def test_the_job_does_nothing_until_the_role_and_bucket_are_set() -> None:
    condition = _job()["if"]
    assert "vars.LEDGER_ROLE_ARN != ''" in condition
    assert "vars.LIVE_BUCKET != ''" in condition
    assert "&&" in condition


def test_no_environment_is_used() -> None:
    """An environment would change the OIDC subject, which the role's trust refuses."""
    assert "environment" not in _job()
    assert "environment:" not in WORKFLOW_PATH.read_text().replace("`environment:`", "")


def test_only_the_ledger_checkout_keeps_credentials_and_it_never_creates_the_branch() -> None:
    checkouts = [s for s in _steps() if s.get("uses", "").startswith("actions/checkout")]
    assert [c["with"]["persist-credentials"] for c in checkouts] == [False, True]
    assert checkouts[1]["with"]["ref"] == "ledger"
    text = WORKFLOW_PATH.read_text()
    assert "git checkout -b" not in text
    assert "git branch" not in text
    assert "--orphan" not in text


def test_the_bucket_name_reaches_the_script_through_the_environment() -> None:
    step = next(s for s in _steps() if "ledger_append" in s.get("run", ""))
    assert step["env"] == {"LIVE_BUCKET": "${{ vars.LIVE_BUCKET }}"}
    assert "${{" not in step["run"]
    assert "uv run --locked --extra aws" in step["run"]
