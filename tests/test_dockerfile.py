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


def test_entrypoint_does_not_depend_on_uv_run() -> None:
    """Fix round 1, Minor 2: the entrypoint runs the venv's own installed script directly
    (`ENV PATH=/app/.venv/bin:$PATH`), not `uv run`, so the running container depends on
    nothing but that venv -- no `uv` binary, no `uv` cache, no writable `HOME`."""
    args = json.loads(_last_instruction("ENTRYPOINT"))
    assert "uv" not in args
    assert "run" not in args


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


def test_base_image_is_pinned_by_digest() -> None:
    """Fix round 1, Minor 7: a tag alone can be repointed by the publisher; a digest cannot."""
    from_line = _last_instruction("FROM")
    assert "@sha256:" in from_line, f"FROM line has no digest pin: {from_line!r}"


def test_chown_does_not_recurse_into_app() -> None:
    """Fix round 1, Minor 1: only `NTSB_DATA_DIR` is handed to the non-root user -- a recursive
    `chown` of `/app` would duplicate the whole venv into a new image layer on every build."""
    chown_lines = [
        line
        for line in DOCKERFILE.splitlines()
        if "chown" in line and not line.strip().startswith("#")
    ]
    assert chown_lines, "no chown instruction found"
    for line in chown_lines:
        assert "-R" not in line.split(), f"a chown here must not recurse: {line!r}"
        assert "/app" not in line, f"a chown here must not touch /app: {line!r}"


def test_bytecode_is_compiled_at_build_time() -> None:
    """Fix round 1, Minor 1: `UV_COMPILE_BYTECODE=1` set before the first `uv sync`, so
    compilation happens once at build time rather than on every nightly container start."""
    lines = DOCKERFILE.splitlines()
    env_index = next(
        i for i, line in enumerate(lines) if line.strip() == "ENV UV_COMPILE_BYTECODE=1"
    )
    first_sync_index = next(i for i, line in enumerate(lines) if "uv sync" in line)
    assert env_index < first_sync_index
