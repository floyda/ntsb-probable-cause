"""`site/scripts/publish.sh`, the publish step CodeBuild runs (S5 spec §18.1, §19.1).

A fake `aws` on PATH records each call, so the order is checked without AWS: styles and
scripts first, then pages, then removal of files no longer used, then CloudFront.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "site/scripts/publish.sh"
_BASH = shutil.which("bash") or "/bin/bash"


def _run(tmp_path: Path, mode: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    log = tmp_path / "aws.log"
    fake = tmp_path / "bin/aws"
    fake.parent.mkdir()
    fake.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n')
    fake.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake.parent}{os.pathsep}{os.environ['PATH']}",
        "SITE_MODE": mode,
        "SITE_BUCKET": "test-site-bucket",
        "DISTRIBUTION_ID": "E000TEST",
    }
    result = subprocess.run(  # noqa: S603 -- fixed script path, test input only
        [_BASH, str(_SCRIPT)], cwd=_REPO, env=env, capture_output=True, text=True, check=False
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return result, calls


def test_holding_publishes_assets_then_pages_then_removals_then_clears_cache(
    tmp_path: Path,
) -> None:
    result, calls = _run(tmp_path, "holding")
    assert result.returncode == 0, result.stderr
    assert len(calls) == 4
    assert calls[0].startswith("s3 sync site/holding s3://test-site-bucket --exclude *.html")
    assert calls[1].startswith(
        "s3 sync site/holding s3://test-site-bucket --exclude * --include *.html"
    )
    assert calls[2].startswith("s3 sync site/holding s3://test-site-bucket --delete")
    assert calls[3] == "cloudfront create-invalidation --distribution-id E000TEST --paths /*"


@pytest.mark.parametrize("mode", ["site", "", "launch"])
def test_every_other_mode_is_refused_and_nothing_is_published(tmp_path: Path, mode: str) -> None:
    result, calls = _run(tmp_path, mode)
    assert result.returncode == 2
    assert calls == []
