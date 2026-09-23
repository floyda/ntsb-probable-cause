"""The container-image jobs in `.github/workflows/ci.yml` (S2.5 Task 12).

Parses the workflow's own YAML rather than matching its text, so a harmless reformatting
(key order, quoting) does not break these tests -- only the properties that matter: the build
job runs on every pull request, the push job is gated on a merge to `main` and needs lint and
test to pass first, every `uses:` is pinned by a full commit SHA (not a tag or a branch),
`id-token: write` -- the permission the OIDC credential exchange needs -- appears on the push
job and nowhere else, pushes are serialized by a non-cancelling concurrency group (fix round
1), and every `docker build` step carries the commit identity build arg.
"""

from pathlib import Path
from typing import Any

import yaml

WORKFLOW_PATH = Path(".github/workflows/ci.yml")
FULL_SHA_LENGTH = 40


def _load_workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text())
    assert isinstance(loaded, dict)
    return loaded


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML's default (YAML 1.1) loader reads the unquoted key `on:` as the boolean `True`;
    # `raw` is typed loosely enough here to look that boolean key up without a mypy complaint.
    raw: dict[Any, Any] = workflow
    on = raw.get("on", raw.get(True))
    assert isinstance(on, dict), "workflow has no 'on' trigger mapping"
    return on


def _jobs(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps", [])
    assert isinstance(steps, list)
    return steps


def test_workflow_parses_and_has_the_image_jobs() -> None:
    jobs = _jobs(_load_workflow())
    assert "image-build" in jobs
    assert "image-push" in jobs


def test_top_level_triggers_include_pull_request_and_push() -> None:
    on = _triggers(_load_workflow())
    assert "push" in on
    assert "pull_request" in on


def test_image_build_job_runs_on_pull_requests() -> None:
    """The build job carries no restrictive `if:`, so the workflow's own top-level triggers --
    which include `pull_request` -- reach it unmodified."""
    jobs = _jobs(_load_workflow())
    build_job = jobs["image-build"]
    assert "if" not in build_job


def test_image_push_job_is_gated_on_main_push_only() -> None:
    jobs = _jobs(_load_workflow())
    condition = jobs["image-push"]["if"]
    assert "refs/heads/main" in condition
    assert "push" in condition


def test_image_push_job_needs_lint_and_test_to_pass_first() -> None:
    """Fix round 1, Minor 3: `needs` requires *every* listed job to succeed, not merely finish
    -- so a commit that fails lint or the test suite can still merge to `main`, but its image
    is never pushed."""
    jobs = _jobs(_load_workflow())
    needs = jobs["image-push"].get("needs")
    needs_list = [needs] if isinstance(needs, str) else needs
    assert needs_list is not None
    assert set(needs_list) == {"image-build", "lint", "test"}


def test_image_push_job_has_a_non_cancelling_concurrency_group() -> None:
    """Fix round 1, Minor 4: serializes pushes across quick back-to-back merges to `main`, so
    `:latest` always ends up as the most recent successful build -- `cancel-in-progress: false`
    because a half-finished push must never be interrupted mid-way and left as `:latest`."""
    jobs = _jobs(_load_workflow())
    concurrency = jobs["image-push"].get("concurrency")
    assert isinstance(concurrency, dict), "image-push has no concurrency group"
    assert concurrency.get("group") == "image-push"
    assert concurrency.get("cancel-in-progress") is False


def test_every_docker_build_passes_commit_sha() -> None:
    """Fix round 1, Minor 6: guards against a future edit to either build step -- the no-push
    validation build or the real push build -- silently dropping the commit identity that the
    Dockerfile's `ARG COMMIT_SHA` needs."""
    workflow = _load_workflow()
    docker_build_runs = [
        step["run"]
        for job in _jobs(workflow).values()
        for step in _steps(job)
        if "docker build" in step.get("run", "")
    ]
    assert docker_build_runs, "no `docker build` step found anywhere in the workflow"
    for run_text in docker_build_runs:
        has_build_arg = "--build-arg" in run_text
        has_commit_sha = "COMMIT_SHA=" in run_text
        assert has_build_arg, f"a docker build step is missing --build-arg: {run_text!r}"
        assert has_commit_sha, f"a docker build step is missing COMMIT_SHA=: {run_text!r}"


def _is_pinned_by_full_sha(ref: str) -> bool:
    return len(ref) == FULL_SHA_LENGTH and all(c in "0123456789abcdef" for c in ref)


def test_every_action_use_is_pinned_by_a_full_commit_sha() -> None:
    workflow = _load_workflow()
    for job_name, job in _jobs(workflow).items():
        for step in _steps(job):
            uses = step.get("uses")
            if uses is None:
                continue
            ref = uses.rsplit("@", 1)[-1]
            pinned = _is_pinned_by_full_sha(ref)
            assert pinned, f"{job_name}: {uses!r} is not pinned by a 40-hex commit SHA"


def test_id_token_write_appears_only_on_the_image_push_job() -> None:
    workflow = _load_workflow()
    for job_name, job in _jobs(workflow).items():
        permissions = job.get("permissions") or {}
        has_id_token_write = permissions.get("id-token") == "write"
        assert has_id_token_write == (job_name == "image-push"), (
            f"job {job_name}: id-token write is "
            f"{'set' if has_id_token_write else 'unset'}, expected the opposite"
        )
    # Also confirm the top-level (workflow-wide) permissions grant no id-token write, so a job
    # that declares no `permissions:` of its own cannot inherit one.
    top_level = workflow.get("permissions") or {}
    assert top_level.get("id-token") != "write"


def test_image_push_job_never_runs_without_configuring_aws_credentials_first() -> None:
    """A missing `AWS_DEPLOY_ROLE_ARN` repository variable (before Task 13 deploys the stack)
    must make the AWS/push steps skip cleanly, not fail the job -- so those steps carry a
    per-step `if:`, not a job-level one, on top of the job's own main-push gate."""
    jobs = _jobs(_load_workflow())
    push_job = jobs["image-push"]
    aws_steps = [
        step
        for step in _steps(push_job)
        if step.get("uses", "").startswith(("aws-actions/", "docker"))
        or "docker" in step.get("run", "")
    ]
    assert aws_steps
    for step in aws_steps:
        assert "if" in step, f"step {step.get('name', step.get('uses'))} has no guard"
