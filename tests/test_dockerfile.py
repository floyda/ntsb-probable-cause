"""The recorder's `Dockerfile` (S2.5 Task 12).

A `docker build` was not exercised here -- the Docker daemon is not running in this
environment (see the Task 12 report); the CI `image-build` job (`.github/workflows/ci.yml`,
`tests/test_ci_workflow.py`) is the substitute, running the real build on every pull request.
These are the structural properties controller note 7 asks for, checked without a daemon:
the commit identity comes in as a build arg with no baked-in default, the entrypoint runs
`ntsb-record`, no NTSB API key ever appears in the image definition, and the process drops
root before it runs.
"""

import json
import re
from pathlib import Path

DOCKERFILE = Path("Dockerfile").read_text()


def _last_instruction(instruction: str) -> str:
    """The argument text of the last line starting with `instruction`, e.g. `"ENTRYPOINT"`."""
    lines = [
        line.strip() for line in DOCKERFILE.splitlines() if re.match(rf"^\s*{instruction}\s", line)
    ]
    assert lines, f"no {instruction} instruction found in Dockerfile"
    return lines[-1][len(instruction) :].strip()


def test_commit_sha_is_a_build_arg_with_no_baked_in_default() -> None:
    arg_lines = [
        line.strip() for line in DOCKERFILE.splitlines() if line.strip().startswith("ARG ")
    ]
    assert "ARG COMMIT_SHA" in arg_lines, (
        "COMMIT_SHA must be declared as `ARG COMMIT_SHA` with no default value, so an image "
        "built without --build-arg gets an empty NTSB_COMMIT_SHA rather than a fabricated one"
    )


def test_commit_sha_env_var_is_derived_from_the_build_arg() -> None:
    assert "ENV NTSB_COMMIT_SHA=${COMMIT_SHA}" in DOCKERFILE


def test_entrypoint_runs_ntsb_record() -> None:
    args = json.loads(_last_instruction("ENTRYPOINT"))
    assert "ntsb-record" in args


def test_cmd_defaults_to_the_run_subcommand() -> None:
    args = json.loads(_last_instruction("CMD"))
    assert args == ["run"]


def test_no_api_key_appears_anywhere_in_the_dockerfile() -> None:
    assert "NTSB_API_KEY" not in DOCKERFILE


def test_image_runs_as_a_non_root_user() -> None:
    user_lines = [
        line.strip() for line in DOCKERFILE.splitlines() if line.strip().startswith("USER ")
    ]
    assert user_lines, "Dockerfile never switches to a non-root USER"
    last_user = user_lines[-1].removeprefix("USER").strip()
    assert last_user not in {"root", "0"}
