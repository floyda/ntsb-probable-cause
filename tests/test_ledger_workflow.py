"""`.github/workflows/ledger.yml` (S4 Task 13, decision 0178), read as YAML like CI's."""

import re
from pathlib import Path
from typing import Any

import yaml

WORKFLOW_PATH = Path(".github/workflows/ledger.yml")
FULL_SHA = re.compile(r"[0-9a-f]{40}")


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


def test_triggers_are_schedule_and_dispatch_only() -> None:
    workflow = _load()
    on: dict[str, Any] = workflow.get("on", workflow.get(True)) or {}
    assert set(on) == {"schedule", "workflow_dispatch"}
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


def test_the_job_does_nothing_until_the_enabling_variable_is_set() -> None:
    assert _job()["if"] == "vars.LEDGER_ENABLED == 'true'"


def test_no_variable_but_the_enabling_one_is_read() -> None:
    """Variables are not masked in the public log; the role ARN and bucket are secrets."""
    text = WORKFLOW_PATH.read_text()
    assert set(re.findall(r"vars\.(\w+)", text)) == {"LEDGER_ENABLED"}
    assert set(re.findall(r"secrets\.(\w+)", text)) == {"LEDGER_ROLE_ARN", "LIVE_BUCKET"}


def test_secrets_are_read_only_through_with_or_env() -> None:
    for step in _steps():
        assert "secrets." not in step.get("run", ""), step.get("name")
        assert "github.token" not in step.get("run", ""), step.get("name")
    for step in _steps():
        for section in ("with", "env"):
            for value in step.get(section, {}).values():
                assert "vars." not in str(value) or "LEDGER_ENABLED" in str(value)


def test_no_environment_is_used() -> None:
    """An environment would change the OIDC subject, which the role's trust refuses."""
    assert "environment" not in _job()
    assert "environment:" not in WORKFLOW_PATH.read_text().replace("`environment:`", "")


def test_no_checkout_keeps_the_token_and_the_ledger_branch_is_never_created() -> None:
    checkouts = [s for s in _steps() if s.get("uses", "").startswith("actions/checkout")]
    assert len(checkouts) == 2
    for checkout in checkouts:
        assert checkout["with"]["persist-credentials"] is False
    assert checkouts[1]["with"]["ref"] == "ledger"
    text = WORKFLOW_PATH.read_text()
    assert "git checkout -b" not in text
    assert "git branch" not in text
    assert "--orphan" not in text


def test_only_the_commit_step_holds_the_token() -> None:
    holders = [s for s in _steps() if "github.token" in str(s)]
    assert [s["name"] for s in holders] == ["Commit the ledger"]
    assert holders[0]["env"] == {"GH_TOKEN": "${{ github.token }}"}
    assert "extraheader" not in WORKFLOW_PATH.read_text()


def test_setup_uv_caching_is_off() -> None:
    step = next(s for s in _steps() if s.get("uses", "").startswith("astral-sh/setup-uv"))
    assert step["with"]["enable-cache"] is False


def test_the_bucket_name_reaches_the_script_through_the_environment() -> None:
    step = next(s for s in _steps() if "ledger_append" in s.get("run", ""))
    assert step["env"] == {"LIVE_BUCKET": "${{ secrets.LIVE_BUCKET }}"}
    assert "${{" not in step["run"]
    assert "uv run --locked --no-dev --extra aws" in step["run"]
