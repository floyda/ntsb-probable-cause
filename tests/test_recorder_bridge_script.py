"""``scripts/recorder_bridge.sh``, the Mac bridge wrapper (S2.5 Task 10, fix round 1, Important 1).

Runs the real script as a subprocess, under ``bash``, with fake ``pass`` and ``uv``
executables placed first on ``PATH`` -- **never** the real ``pass`` (no GPG agent, no
pinentry dialog, no real secret), **never** ``launchctl``, and no network call, per the fix
round's safety note. ``NTSB_BRIDGE_DATA_DIR`` and ``NTSB_BRIDGE_KEY_TIMEOUT`` (read only by
the script itself, never set by ``launchd``) isolate every run to a tmp directory and keep an
intentional hang short; ``NTSB_BRIDGE_RUN_TIMEOUT`` does the same for the overall wall-clock
alarm the script now wraps the run in.
"""

import os
import shutil
import stat
import subprocess
from collections.abc import Mapping
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "recorder_bridge.sh"
# An absolute path, not the bare name "bash" (ruff S607): resolved once, from the real PATH,
# before any test overrides PATH to put the fakes first.
BASH = shutil.which("bash") or "/bin/bash"
SENTINEL_KEY = "sk-test-sentinel-should-never-appear-anywhere"


def _make_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _fake_pass(bin_dir: Path, *, output: str, exit_code: int = 0) -> None:
    """A fake ``pass show api/ntsb`` -- prints ``output`` (no trailing newline added) and exits."""
    body = f"#!/bin/bash\nprintf '%s' {output!r}\nexit {exit_code}\n"
    _make_executable(bin_dir / "pass", body)


def _fake_uv(bin_dir: Path, *, exit_code: int = 0, sleep_seconds: float = 0) -> None:
    """A fake ``uv`` -- sleeps, echoes its arguments (never ``$NTSB_API_KEY``), then exits."""
    body = f'#!/bin/bash\nsleep {sleep_seconds}\necho "uv ran with: $*"\nexit {exit_code}\n'
    _make_executable(bin_dir / "uv", body)


def _run_bridge(
    tmp_path: Path,
    *,
    code_dir: Path | None = None,
    key_timeout: int = 5,
    extra_env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    data_dir = tmp_path / "data"
    env = dict(os.environ)
    env["PATH"] = f"{tmp_path / 'bin'}:{env.get('PATH', '')}"
    env["NTSB_BRIDGE_DATA_DIR"] = str(data_dir)
    env["NTSB_BRIDGE_KEY_TIMEOUT"] = str(key_timeout)
    if extra_env:
        env.update(extra_env)
    target = code_dir if code_dir is not None else tmp_path
    return subprocess.run(  # noqa: S603 -- fixed argv, no shell; a controlled fixture, not user input
        [BASH, str(SCRIPT), str(target)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )


def _log_text(tmp_path: Path) -> str:
    return (tmp_path / "data" / "recorder.log").read_text()


def test_a_successful_run_logs_start_and_done_and_exits_0(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_pass(bin_dir, output="sk-not-the-sentinel\n")
    _fake_uv(bin_dir, exit_code=0)

    result = _run_bridge(tmp_path)

    assert result.returncode == 0
    log_text = _log_text(tmp_path)
    assert "run start" in log_text
    assert "run done" in log_text
    assert "run failed" not in log_text


def test_a_failed_run_reports_and_exits_with_uvs_real_status(tmp_path: Path) -> None:
    """Fix round 1, Important 1: the bug this guards against made every failure read exit=0."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_pass(bin_dir, output="sk-not-the-sentinel\n")
    _fake_uv(bin_dir, exit_code=3)

    result = _run_bridge(tmp_path)

    assert result.returncode == 3
    log_text = _log_text(tmp_path)
    assert "run failed exit=3" in log_text
    assert "run done" not in log_text


def test_the_key_never_appears_in_the_log_or_in_process_output(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_pass(bin_dir, output=SENTINEL_KEY + "\n")
    _fake_uv(bin_dir, exit_code=0)

    result = _run_bridge(tmp_path)

    assert result.returncode == 0
    log_text = _log_text(tmp_path)
    assert SENTINEL_KEY not in log_text
    assert SENTINEL_KEY not in result.stdout
    assert SENTINEL_KEY not in result.stderr


def test_the_key_never_appears_even_when_the_run_fails(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_pass(bin_dir, output=SENTINEL_KEY + "\n")
    _fake_uv(bin_dir, exit_code=1)

    result = _run_bridge(tmp_path)

    assert result.returncode == 1
    log_text = _log_text(tmp_path)
    assert SENTINEL_KEY not in log_text
    assert SENTINEL_KEY not in result.stdout
    assert SENTINEL_KEY not in result.stderr


def test_empty_pass_output_gives_key_unavailable_and_never_runs_uv(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_pass(bin_dir, output="")  # `pass` succeeds but prints nothing -- still no usable key
    _fake_uv(bin_dir, exit_code=0)

    result = _run_bridge(tmp_path)

    assert result.returncode != 0
    log_text = _log_text(tmp_path)
    assert "NTSB key unavailable" in log_text
    assert "uv ran with" not in log_text


def test_a_failing_pass_command_gives_key_unavailable(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_pass(bin_dir, output="", exit_code=1)
    _fake_uv(bin_dir, exit_code=0)

    result = _run_bridge(tmp_path)

    assert result.returncode != 0
    log_text = _log_text(tmp_path)
    assert "NTSB key unavailable" in log_text
    assert "uv ran with" not in log_text


def test_a_hung_run_is_stopped_by_the_wall_clock_alarm(tmp_path: Path) -> None:
    """Fix round 1, Minor 4: the overall run is wrapped in its own alarm, logged if it trips."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_pass(bin_dir, output="sk-not-the-sentinel\n")
    _fake_uv(bin_dir, exit_code=0, sleep_seconds=5)

    result = _run_bridge(tmp_path, extra_env={"NTSB_BRIDGE_RUN_TIMEOUT": "1"})

    assert result.returncode == 142  # 128 + SIGALRM(14)
    log_text = _log_text(tmp_path)
    assert "exceeded the 1s wall-clock limit" in log_text
    assert "run failed exit=142" in log_text


def test_extra_arguments_are_forwarded_to_ntsb_record(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_pass(bin_dir, output="sk-not-the-sentinel\n")
    _fake_uv(bin_dir, exit_code=0)

    result = subprocess.run(  # noqa: S603
        [BASH, str(SCRIPT), str(tmp_path), "--dry-run", "--verbose"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
            "NTSB_BRIDGE_DATA_DIR": str(tmp_path / "data"),
            "NTSB_BRIDGE_KEY_TIMEOUT": "5",
        },
        timeout=30,
        check=False,
    )

    assert result.returncode == 0
    log_text = _log_text(tmp_path)
    assert "uv ran with: run ntsb-record run --dry-run --verbose" in log_text


def test_no_code_dir_argument_is_a_usage_error(tmp_path: Path) -> None:
    result = subprocess.run(  # noqa: S603
        [BASH, str(SCRIPT)],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": os.environ.get("PATH", "")},
        timeout=30,
        check=False,
    )

    assert result.returncode == 2
    assert "usage" in result.stderr.lower()
