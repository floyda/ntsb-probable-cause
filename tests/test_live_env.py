"""``scripts/live_env.sh``: the AWS settings a live morning needs, by behaviour (stub ``aws``)."""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "live_env.sh"
_STUB_AWS = """#!/bin/bash
echo "aws $*" >> "$STUB_LOG"
if [[ -n "${STUB_AWS_STDERR:-}" ]]; then echo "$STUB_AWS_STDERR" >&2; fi
if [[ "${STUB_AWS_FAIL:-}" == "1" ]]; then exit 255; fi
echo "${STUB_BUCKET:-}"
"""


def _run(tmp_path: Path, **extra: str) -> tuple[int, str, str, list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "aws"
    stub.write_text(_STUB_AWS)
    stub.chmod(0o755)
    log = tmp_path / "calls.log"
    log.unlink(missing_ok=True)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "STUB_LOG": str(log), **extra}
    done = subprocess.run(  # noqa: S603 -- fixed argv; `aws` is a stand-in
        ["/bin/bash", str(SCRIPT)], env=env, capture_output=True, text=True, check=False
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return done.returncode, done.stdout, done.stderr, calls


def test_it_resolves_the_store_from_the_stacks_bucket_output(tmp_path: Path) -> None:
    code, out, _, calls = _run(tmp_path, STUB_BUCKET="the-bucket")
    assert code == 0
    assert "export AWS_PROFILE='ntsb'" in out
    assert "export NTSB_STORE='s3://the-bucket/recorder.sqlite'" in out
    (call,) = calls
    assert "--profile ntsb" in call
    assert "--stack-name NtsbRecorderStack" in call
    assert "BucketName" in call


def test_an_explicit_store_wins_and_no_lookup_is_made(tmp_path: Path) -> None:
    code, out, _, calls = _run(tmp_path, NTSB_STORE="s3://mine/x.sqlite", AWS_PROFILE="other")
    assert code == 0
    assert "export AWS_PROFILE='other'" in out
    assert "NTSB_STORE" not in out
    assert calls == []


def test_a_failed_or_empty_lookup_refuses_plainly_and_prints_no_store(tmp_path: Path) -> None:
    for extra in ({"STUB_AWS_FAIL": "1"}, {"STUB_BUCKET": ""}, {"STUB_BUCKET": "None"}):
        code, out, err, _ = _run(tmp_path, **extra)
        assert code == 1
        assert "NTSB_STORE" not in out
        assert "aws login'" in err
        assert "--profile" not in err


def test_awss_own_error_is_shown_after_the_plain_message_and_nothing_is_exported(
    tmp_path: Path,
) -> None:
    code, out, err, _ = _run(
        tmp_path, STUB_AWS_FAIL="1", STUB_AWS_STDERR="Unable to locate profile"
    )
    assert code == 1
    assert "NTSB_STORE" not in out
    assert "Unable to locate profile" in err
    assert err.index("aws login'") < err.index("Unable to locate profile")
