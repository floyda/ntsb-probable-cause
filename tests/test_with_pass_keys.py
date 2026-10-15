"""``scripts/with_pass_keys.sh``, the coding memory's key wrapper (decisions 0202, 0207, Task 11).

The script runs here against a fake ``pass`` first on ``PATH``: it never reads the real store.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "with_pass_keys.sh"

FAKE_SCRIPT = """\
#!/bin/sh
# fake pass: `pass show <entry>` prints a secret named for the entry, then a second line
[ "$1" = show ] || exit 2
case "$2" in
  *fail*) echo "no such entry" >&2; exit 1 ;;
esac
echo "secret-for-$2"
echo "second-line-must-not-be-read"
"""


def _run(
    tmp_path: Path, command: list[str], env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "pass"
    fake.write_text(FAKE_SCRIPT)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    environment = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        **(env or {}),
    }
    return subprocess.run(  # noqa: S603 -- fixed argv, no shell; the fake `pass` is ours
        [str(SCRIPT), *command], capture_output=True, text=True, check=False, env=environment
    )


def test_the_script_is_executable_and_stops_on_error() -> None:
    assert os.access(SCRIPT, os.X_OK)
    assert "set -euo pipefail" in SCRIPT.read_text()


def test_both_keys_reach_the_child_and_neither_is_printed(tmp_path: Path) -> None:
    done = _run(tmp_path, ["env"])
    assert done.returncode == 0
    lines = done.stdout.splitlines()
    assert "OPENROUTER_API_KEY=secret-for-api/openrouter" in lines
    assert "ANTHROPIC_API_KEY=secret-for-api/anthropic" in lines
    assert "second-line-must-not-be-read" not in done.stdout
    assert "secret-for" not in done.stderr


def test_the_entry_names_can_be_overridden(tmp_path: Path) -> None:
    done = _run(
        tmp_path,
        ["env"],
        {"NTSB_PASS_ANTHROPIC": "other/anthropic", "NTSB_PASS_OPENROUTER": "other/openrouter"},
    )
    assert "ANTHROPIC_API_KEY=secret-for-other/anthropic" in done.stdout.splitlines()
    assert "OPENROUTER_API_KEY=secret-for-other/openrouter" in done.stdout.splitlines()


@pytest.mark.parametrize("variable", ["NTSB_PASS_OPENROUTER", "NTSB_PASS_ANTHROPIC"])
def test_a_failed_pass_stops_before_the_command_and_leaks_nothing(
    tmp_path: Path, variable: str
) -> None:
    marker = tmp_path / "ran"
    done = _run(tmp_path, ["touch", str(marker)], {variable: "api/fail"})
    assert done.returncode != 0
    assert not marker.exists()
    assert "secret-for" not in done.stdout + done.stderr
