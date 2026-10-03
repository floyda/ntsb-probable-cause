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
    assert "${NTSB_PAID_BRANCH:-s3-2-claims}" in text
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
    assert "head -n 1" in key_line
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
