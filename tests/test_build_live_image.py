"""``scripts/build_live_image.sh`` (S4 Task 12), run with stub ``git``, ``docker`` and ``aws``."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_live_image.sh"
DIGEST = "sha256:" + "ab" * 32

_GIT = """#!/bin/sh
case "$1" in
  status) printf '%s' "$STUB_DIRTY" ;;
  rev-parse) echo abc1234 ;;
esac
"""
_AWS = """#!/bin/sh
echo "$@" >> "$STUB_AWS_LOG"
echo "123456789012.dkr.ecr.eu-west-2.amazonaws.com/ntsb-live"
"""
_DOCKER = """#!/bin/sh
echo "$@" >> "$STUB_LOG"
while [ $# -gt 0 ]; do
  if [ "$1" = "--metadata-file" ]; then
    printf '{"containerimage.digest": "%s"}' "$STUB_DIGEST" > "$2"
  fi
  shift
done
"""


def _run(
    tmp_path: Path, *, dirty: bool, digest: str = DIGEST
) -> tuple[subprocess.CompletedProcess[str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("git", _GIT), ("aws", _AWS), ("docker", _DOCKER)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "docker.log"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "STUB_DIRTY": " M file.py\n" if dirty else "",
        "STUB_LOG": str(log),
        "STUB_DIGEST": digest,
        "STUB_AWS_LOG": str(tmp_path / "aws.log"),
        "AWS_PROFILE": "ntsb-live",
    }
    done = subprocess.run(  # noqa: S603 -- fixed argv; stubs on PATH stand in for the tools
        [shutil.which("bash") or "bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return done, log


def test_a_dirty_tree_exits_1_before_docker(tmp_path: Path) -> None:
    done, log = _run(tmp_path, dirty=True)
    assert done.returncode == 1
    assert not log.exists()


def test_a_clean_tree_builds_for_amd64_with_the_sha_and_prints_the_digest(tmp_path: Path) -> None:
    done, log = _run(tmp_path, dirty=False)
    assert done.returncode == 0, done.stderr
    call = log.read_text()
    assert "buildx build --platform linux/amd64" in call
    assert "--build-arg COMMIT_SHA=abc1234" in call
    assert "-t 123456789012.dkr.ecr.eu-west-2.amazonaws.com/ntsb-live:live-abc1234" in call
    assert "--push" in call
    assert "latest" not in call
    assert done.stdout.strip() == DIGEST
    assert "--provenance=false --sbom=false" in call


def test_the_profile_is_fixed_whatever_aws_profile_holds(tmp_path: Path) -> None:
    done, _ = _run(tmp_path, dirty=False)
    assert done.returncode == 0, done.stderr
    aws_call = (tmp_path / "aws.log").read_text()
    assert "--profile ntsb " in aws_call
    assert "ntsb-live " not in aws_call.replace("/ntsb-live", "")


def test_an_empty_digest_exits_1_with_one_line(tmp_path: Path) -> None:
    done, _ = _run(tmp_path, dirty=False, digest="")
    assert done.returncode == 1
    assert done.stdout == ""
    assert len(done.stderr.strip().splitlines()) == 1
