"""``scripts/paid_run.sh``, the S3.2 paid-run wrapper (spec §14, Task 10).

Static checks on the file text, plus ``bash -n``. The script is never run here: it would clone
a repository, read a key from ``pass`` and call a paid ``make`` target.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "paid_run.sh"


def _lines() -> list[str]:
    return [line for line in SCRIPT.read_text().splitlines() if not line.lstrip().startswith("#")]


def _index(fragment: str) -> int:
    return next(i for i, line in enumerate(_lines()) if fragment in line)


def test_the_script_exists_and_is_executable() -> None:
    assert SCRIPT.is_file()
    assert os.access(SCRIPT, os.X_OK)
    assert SCRIPT.read_text().startswith("#!/usr/bin/env bash\n")


def test_bash_accepts_the_syntax() -> None:
    bash = shutil.which("bash")
    assert bash is not None
    done = subprocess.run(  # noqa: S603 -- fixed argv, no shell: `bash -n` parses, never runs
        [bash, "-n", str(SCRIPT)], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


def test_the_header_carries_a_status_paragraph() -> None:
    head = "\n".join(SCRIPT.read_text().splitlines()[:12])
    assert "Status" in head
    assert "S3.2" in head


def test_the_script_stops_on_error_and_never_traces() -> None:
    code = _lines()
    assert "set -euo pipefail" in code
    assert "set +x" in code
    assert not any(re.search(r"\bset\s+-\w*x", line) for line in code)
    assert not any("bash -x" in line or "xtrace" in line for line in code)


def test_the_defaults_are_the_documented_ones() -> None:
    text = SCRIPT.read_text()
    assert "${NTSB_PAID_CHECKOUT:-$HOME/Workspace/ntsb-demo-agent/ntsb-paid-runs}" in text
    assert "${NTSB_PASS_OPENROUTER:-api/openrouter}" in text
    assert "${NTSB_DATA_DIR:-$HOME/Workspace/ntsb-demo-agent/ntsb-probable-cause/data}" in text


def test_no_command_prints_a_variable_that_holds_a_key() -> None:
    for line in _lines():
        if re.match(r"\s*(echo|printf)\b", line):
            assert "KEY" not in line.upper().replace("PASS_ENTRY", ""), line
            assert "pass show" not in line, line
    key_line = next(line for line in _lines() if "pass show" in line)
    assert key_line.startswith("OPENROUTER_API_KEY=")
    assert "sed -n 1p" in key_line  # reads all of pass's output: no SIGPIPE under pipefail
    assert "head" not in key_line
    assert "export OPENROUTER_API_KEY" in _lines()


def test_a_dirty_checkout_is_refused_before_make_runs() -> None:
    refusal = _index("git status --porcelain")
    assert refusal < _index('make "$target"')
    assert "exit 1" in _lines()[refusal + 2]
    assert _index("git checkout --quiet -B") > refusal


def test_the_key_is_read_after_the_checkout_is_clean_and_just_before_make() -> None:
    assert _index("git status --porcelain") < _index("pass show") < _index('make "$target"')


def test_only_the_held_out_ledger_is_committed() -> None:
    code = _lines()
    adds = [line for line in code if "git add" in line]
    assert adds == ["  git add docs/results/heldout-ledger.md"]
    assert not any(re.search(r"git commit .*(-a|--all)\b", line) for line in code)
    assert not any("git add -A" in line or "git add ." in line for line in code)
    assert any("git diff --quiet -- docs/results/heldout-ledger.md" in line for line in code)
    assert _index("git push") > _index("git commit")
    assert _index('make "$target"') < _index("git add")


def test_the_push_goes_to_the_branch_and_never_forces() -> None:
    pushes = [line for line in _lines() if "git push" in line]
    assert len(pushes) == 1
    assert "HEAD:$branch" in pushes[0]
    assert "--force" not in pushes[0]
    assert "-f " not in pushes[0]


def test_unpushed_local_commits_are_refused_before_any_reset() -> None:
    code = _lines()
    count = _index('git rev-list --count "origin/$branch..$branch"')
    assert _index("git fetch") < count < _index("git checkout --quiet -B")
    assert count < _index('make "$target"')
    guard = "\n".join(code[count : count + 4])
    assert '"$unpushed" != "0"' in guard
    assert "exit 1" in guard
    assert "not on origin/$branch" in "\n".join(SCRIPT.read_text().splitlines())


def test_a_failed_push_is_loud_and_the_script_exits_nonzero() -> None:
    code = _lines()
    push = _index("git push")
    assert code[push].lstrip().startswith("if ! git push")
    after = "\n".join(code[push + 1 : push + 4])
    assert "NOT PUSHED" in after
    assert ">&2" in after
    assert "exit 1" in after


def test_the_branch_is_required_and_has_no_default() -> None:
    """Final review: a default branch outlives its stage, so the branch must be named each time."""
    code = _lines()
    branch = next(line for line in code if line.startswith("branch="))
    assert branch.startswith('branch="${NTSB_PAID_BRANCH:?')
    assert not any("s3-2-claims" in line for line in code)
    assert _index("branch=") < _index("git fetch")


def test_main_is_refused_before_anything_is_fetched() -> None:
    """The script commits and pushes a ledger row to its branch: never to main."""
    refusal = _index('if [[ "$branch" == "main" ]]')
    assert refusal < _index("git fetch")
    assert "exit 1" in "\n".join(_lines()[refusal : refusal + 3])


def test_the_fetch_prunes() -> None:
    assert "git fetch --quiet --prune origin" in _lines()


def test_the_dirty_checkout_message_says_commit_never_discard() -> None:
    message = _lines()[_index("git status --porcelain") + 1]
    assert "commit (never discard) a ledger row" in message.lower()
    assert "Commit or discard" not in message


_STUB_GIT = """#!/bin/bash
echo "git $*" >> "$STUB_LOG"
case "$1 $2" in
  "rev-parse --verify") exit 0 ;;
  "rev-list --count") echo "${STUB_UNPUSHED:-0}" ;;
  "status --porcelain") printf '%s' "${STUB_STATUS:-}" ;;
  "rev-parse --short") echo "abc1234" ;;
  "diff --quiet") exit 0 ;;
esac
exit 0
"""
_STUB_UV = '#!/bin/bash\necho "uv $*" >> "$STUB_LOG"\n'
_STUB_KEYSTORE = """#!/bin/bash
echo "pass $*" >> "$STUB_LOG"
case "$2" in
  api/ntsb|custom/ntsb) echo ntsb-test-not-a-key ;;
  *) echo sk-or-test-not-a-key ;;
esac
"""
_STUB_MAKE = """#!/bin/bash
echo "make $* UV_LOCKED=${UV_LOCKED:-unset}" >> "$STUB_LOG"
echo "env NTSB_API_KEY=${NTSB_API_KEY:-unset}" >> "$STUB_LOG"
"""
_FAKE_KEY = "sk-or-test-not-a-key"
_FAKE_NTSB_KEY = "ntsb-test-not-a-key"


def _run(
    tmp_path: Path, branch: str = "s3-3-live-shadow", target: str = "s33-dry-run", **extra: str
) -> tuple[int, str, list[str]]:
    """Run the script against stand-in commands; return exit code, output, and the call log."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (
        ("git", _STUB_GIT),
        ("uv", _STUB_UV),
        ("pass", _STUB_KEYSTORE),
        ("make", _STUB_MAKE),
    ):
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)
    (tmp_path / "checkout" / ".git").mkdir(parents=True, exist_ok=True)
    log = tmp_path / "calls.log"
    log.unlink(missing_ok=True)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "NTSB_PAID_BRANCH": branch,
        "NTSB_PAID_CHECKOUT": str(tmp_path / "checkout"),
        "NTSB_DATA_DIR": str(tmp_path / "data"),
        "STUB_LOG": str(log),
        **extra,
    }
    done = subprocess.run(  # noqa: S603 -- fixed argv; every external command is a stand-in
        ["/bin/bash", str(SCRIPT), target],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return done.returncode, done.stdout + done.stderr, calls


def test_a_run_installs_locked_and_makes_with_uv_locked(tmp_path: Path) -> None:
    code, output, calls = _run(tmp_path)
    assert code == 0, output
    assert "uv sync --quiet --locked" in calls
    assert not any("--frozen" in call for call in calls)
    assert "make s33-dry-run UV_LOCKED=1" in calls
    assert calls.index("uv sync --quiet --locked") < calls.index("pass show api/openrouter")
    assert calls.index("pass show api/openrouter") < calls.index("make s33-dry-run UV_LOCKED=1")
    assert _FAKE_KEY not in output


def test_main_is_refused_before_any_git_call(tmp_path: Path) -> None:
    code, _, calls = _run(tmp_path, branch="main")
    assert code == 1
    assert not any(call.startswith("git") for call in calls)


def test_a_dirty_checkout_is_refused_before_make(tmp_path: Path) -> None:
    code, _, calls = _run(tmp_path, STUB_STATUS=" M x\n")
    assert code == 1
    assert not any(call.startswith("make") for call in calls)


def test_unpushed_commits_are_refused_before_checkout(tmp_path: Path) -> None:
    code, _, calls = _run(tmp_path, STUB_UNPUSHED="2")
    assert code == 1
    assert not any(call.startswith("git checkout") for call in calls)
    assert not any(call.startswith("make") for call in calls)


def test_an_s33_target_gets_the_ntsb_key_from_pass_and_it_is_never_printed(tmp_path: Path) -> None:
    code, output, calls = _run(tmp_path)
    assert code == 0, output
    assert "pass show api/ntsb" in calls
    assert "env NTSB_API_KEY=ntsb-test-not-a-key" in calls
    assert calls.index("pass show api/ntsb") < calls.index("make s33-dry-run UV_LOCKED=1")
    assert _FAKE_NTSB_KEY not in output
    assert _FAKE_KEY not in output


def test_the_ntsb_pass_entry_can_be_overridden(tmp_path: Path) -> None:
    code, _, calls = _run(tmp_path, NTSB_PASS_NTSB="custom/ntsb")  # noqa: S106
    assert code == 0
    assert "pass show custom/ntsb" in calls
    assert "env NTSB_API_KEY=ntsb-test-not-a-key" in calls


def test_another_target_never_reads_the_ntsb_key(tmp_path: Path) -> None:
    code, _, calls = _run(tmp_path, target="s32-heldout-a")
    assert code == 0
    assert "pass show api/ntsb" not in calls
    assert "env NTSB_API_KEY=unset" in calls
