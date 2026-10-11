"""``infra/app.py``'s live-stack context handling (S4 Task 12 follow-up).

Runs ``app.py`` as a script in a subprocess, as the CDK CLI does, with ``cdk.out`` in a temp dir.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

if shutil.which("node") is None:
    pytest.skip("aws-cdk-lib needs Node.js (via jsii); none found", allow_module_level=True)

INFRA = Path(__file__).resolve().parents[1] / "infra"
sys.path.insert(0, str(INFRA))
from app import parse_branches  # noqa: E402

_PROVIDER = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"


def _synth(tmp_path: Path, **context: str) -> subprocess.CompletedProcess[str]:
    code = (
        "import runpy, aws_cdk as cdk; "
        "orig = cdk.App.__init__; "
        f"cdk.App.__init__ = lambda self, **kw: orig(self, context={context!r}, "
        f"outdir={str(tmp_path / 'out')!r}, **kw); "
        f"runpy.run_path({str(INFRA / 'app.py')!r}, run_name='__main__')"
    )
    return subprocess.run(  # noqa: S603 -- fixed argv
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=INFRA,
        check=False,
    )


def test_parse_branches_is_safe() -> None:
    assert parse_branches(None) == ("main", "s4-predictions-and-resolution")
    assert parse_branches(" , ") == ("main", "s4-predictions-and-resolution")
    assert parse_branches("main, dev ,") == ("main", "dev")


def test_missing_context_fails_with_one_named_line(tmp_path: Path) -> None:
    done = _synth(tmp_path, recorder_bucket="r")
    assert done.returncode != 0
    assert "Traceback" not in done.stderr
    last = done.stderr.strip().splitlines()[-1]
    assert "alert_email" in last
    assert "github_oidc_provider_arn" in last
    assert "live_image_digest" in last


def test_placeholder_with_enabled_schedule_is_refused(tmp_path: Path) -> None:
    done = _synth(
        tmp_path,
        recorder_bucket="r",
        alert_email="a@example.com",
        github_oidc_provider_arn=_PROVIDER,
        live_image_digest_placeholder="1",
        live_schedule="enabled",
    )
    assert done.returncode != 0
    assert "Traceback" not in done.stderr
    assert "live_schedule=enabled" in done.stderr


def test_full_context_synthesises(tmp_path: Path) -> None:
    done = _synth(
        tmp_path,
        recorder_bucket="r",
        alert_email="a@example.com",
        github_oidc_provider_arn=_PROVIDER,
        live_image_digest_placeholder="1",
    )
    assert done.returncode == 0, done.stderr
