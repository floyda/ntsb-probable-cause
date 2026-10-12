"""``scripts/live_env.sh``: the AWS settings a live morning needs, by behaviour (stub ``aws``)."""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "live_env.sh"
_STUB_AWS = """#!/bin/bash
echo "aws $*" >> "$STUB_LOG"
if [[ -n "${STUB_AWS_STDERR:-}" ]]; then echo "$STUB_AWS_STDERR" >&2; fi
if [[ "${STUB_AWS_FAIL:-}" == "1" ]]; then exit 255; fi
if [[ "$*" == *NtsbLiveStack* ]]; then
  echo "${STUB_LIVE_BUCKET:-None}"
  if [[ "${STUB_LIVE_FAIL:-}" == "1" ]]; then exit 254; fi
  exit 0
fi
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
    assert out.splitlines() == [
        "export AWS_PROFILE=ntsb",
        "export NTSB_STORE=s3://the-bucket/recorder.sqlite",
    ]
    assert len(calls) == 2
    assert all("--profile ntsb " in call for call in calls)
    assert "--stack-name NtsbRecorderStack" in calls[0]
    assert "BucketName" in calls[0]


def test_it_adds_the_live_bucket_when_the_live_stack_exists(tmp_path: Path) -> None:
    code, out, _, calls = _run(tmp_path, STUB_BUCKET="the-bucket", STUB_LIVE_BUCKET="live-bkt")
    assert code == 0
    assert out.splitlines() == [
        "export AWS_PROFILE=ntsb",
        "export NTSB_STORE=s3://the-bucket/recorder.sqlite",
        "export NTSB_LIVE_BUCKET=live-bkt",
    ]
    assert "--stack-name NtsbLiveStack" in calls[1]
    assert "LiveBucketName" in calls[1]


_MISSING = "An error occurred (ValidationError): Stack with id NtsbLiveStack does not exist"


def test_a_missing_live_stack_is_not_an_error(tmp_path: Path) -> None:
    for extra in (
        {"STUB_LIVE_FAIL": "1", "STUB_AWS_STDERR": _MISSING},
        {"STUB_LIVE_BUCKET": "None"},
        {"STUB_LIVE_BUCKET": ""},
    ):
        code, out, _, _ = _run(tmp_path, STUB_BUCKET="the-bucket", **extra)
        assert code == 0
        assert "NTSB_LIVE_BUCKET" not in out


def test_any_other_live_lookup_failure_names_its_kind_and_is_never_not_deployed(
    tmp_path: Path,
) -> None:
    """Item A15: only "does not exist" means the stack is not deployed."""
    for stderr, kind in (
        ("An error occurred (AccessDenied): User is not authorized", "access denied"),
        ("Unable to locate credentials", "access denied or no credentials"),
        ("An error occurred (Throttling): Rate exceeded", "throttled"),
        ('Could not connect to the endpoint URL: "https://cloudformation..."', "network"),
        ("", "other (exit 254)"),
        ("something unforeseen", "other (exit 254)"),
    ):
        code, out, err, _ = _run(
            tmp_path, STUB_BUCKET="the-bucket", STUB_LIVE_FAIL="1", STUB_AWS_STDERR=stderr
        )
        assert code == 1, stderr
        assert out == ""
        assert kind in err, (stderr, err)
        assert "not deployed" not in err
        assert "does not exist" not in err
        assert err.count("\n") == 1, err


def test_an_expired_login_on_the_live_lookup_says_so_in_one_line(tmp_path: Path) -> None:
    for extra in ({"STUB_BUCKET": "the-bucket"}, {"NTSB_STORE": "s3://mine/x.sqlite"}):
        code, out, err, _ = _run(
            tmp_path,
            STUB_LIVE_FAIL="1",
            STUB_AWS_STDERR="Error loading SSO Token: the token has expired",
            **extra,
        )
        assert code == 1
        assert out == ""  # no export, so the caller does not go on as if the stack were absent
        assert "AWS login expired: run 'aws login'" in err
        assert "not deployed" not in err
        assert err.count("\n") == 1


def test_a_missing_stack_message_is_not_taken_for_an_expired_login(tmp_path: Path) -> None:
    code, out, err, _ = _run(
        tmp_path,
        STUB_BUCKET="the-bucket",
        STUB_LIVE_FAIL="1",
        STUB_AWS_STDERR="ValidationError: Stack with id NtsbLiveStack does not exist",
    )
    assert code == 0
    assert "NTSB_LIVE_BUCKET" not in out
    assert "expired" not in err


def test_an_explicit_live_bucket_wins_and_is_not_looked_up(tmp_path: Path) -> None:
    code, out, _, calls = _run(tmp_path, STUB_BUCKET="b", NTSB_LIVE_BUCKET="mine")
    assert code == 0
    assert "NTSB_LIVE_BUCKET" not in out  # already in the caller's environment
    assert len(calls) == 1


def test_an_explicit_store_wins_and_no_lookup_is_made(tmp_path: Path) -> None:
    code, out, _, calls = _run(tmp_path, NTSB_STORE="s3://mine/x.sqlite", AWS_PROFILE="other")
    assert code == 0
    assert out.splitlines() == ["export AWS_PROFILE=other"]
    assert len(calls) == 1  # only the live stack's bucket is looked up
    assert "NtsbLiveStack" in calls[0]


def test_a_failed_or_empty_lookup_refuses_plainly_and_prints_no_store(tmp_path: Path) -> None:
    for extra in ({"STUB_AWS_FAIL": "1"}, {"STUB_BUCKET": ""}, {"STUB_BUCKET": "None"}):
        code, out, err, _ = _run(tmp_path, **extra)
        assert code == 1
        assert out == ""  # no export at all, so a caller that evals it changes nothing
        assert "the ntsb profile could not read the stack" in err
        assert "aws login" in err
        assert "--profile" not in err


def test_awss_own_error_is_shown_after_the_plain_message_and_nothing_is_exported(
    tmp_path: Path,
) -> None:
    code, out, err, _ = _run(
        tmp_path, STUB_AWS_FAIL="1", STUB_AWS_STDERR="Unable to locate profile"
    )
    assert code == 1
    assert out == ""
    assert "Unable to locate profile" in err
    assert err.index("the ntsb profile could not read the stack") < err.index(
        "Unable to locate profile"
    )


def test_the_exports_survive_eval_whatever_the_names_hold(tmp_path: Path) -> None:
    profile = "it's; touch pwned"
    code, out, _, _ = _run(tmp_path, STUB_BUCKET="the-bucket", AWS_PROFILE=profile)
    assert code == 0
    done = subprocess.run(  # noqa: S603 -- fixed argv; the script's own output is evaluated
        ["/bin/bash", "-c", 'eval "$1"; printf "%s|%s" "$AWS_PROFILE" "$NTSB_STORE"', "_", out],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert done.stdout == f"{profile}|s3://the-bucket/recorder.sqlite"
    assert not (tmp_path / "pwned").exists()
