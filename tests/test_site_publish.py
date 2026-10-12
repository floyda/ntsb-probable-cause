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
    fake.write_text(
        "#!/bin/sh\n"
        f'echo "$*" >> "{log}"\n'
        # create-invalidation prints the invalidation's id, as `--query Invalidation.Id` does.
        'case "$*" in *create-invalidation*) echo I2EXAMPLE ;; esac\n'
    )
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


def test_holding_publishes_in_an_order_no_reader_can_see_half_done(tmp_path: Path) -> None:
    # Review finding (2026-10-12): files were deleted before CloudFront's copies were cleared,
    # and nothing set how long a browser may keep a page.
    result, calls = _run(tmp_path, "holding")
    assert result.returncode == 0, result.stderr
    target = "s3://test-site-bucket"
    assert calls == [
        # Hashed assets first; their names change with their content, so a year is safe.
        f"s3 sync site/holding {target} --exclude * --include _astro/* "
        "--cache-control public, max-age=31536000, immutable",
        # Other files (none in holding mode yet), cached briefly.
        f"s3 sync site/holding {target} --exclude _astro/* --exclude *.html "
        "--cache-control public, max-age=300",
        # Then the pages, which a browser must check again each time.
        f"s3 sync site/holding {target} --exclude * --include *.html --cache-control no-cache",
        "cloudfront create-invalidation --distribution-id E000TEST --paths /* "
        "--query Invalidation.Id --output text",
        # Only once every edge has dropped the old pages are stale files removed, and never
        # the hashed assets an old page might still name.
        "cloudfront wait invalidation-completed --distribution-id E000TEST --id I2EXAMPLE",
        f"s3 sync site/holding {target} --delete --exclude _astro/*",
    ]


@pytest.mark.parametrize("mode", ["site", "", "launch"])
def test_every_other_mode_is_refused_and_nothing_is_published(tmp_path: Path, mode: str) -> None:
    result, calls = _run(tmp_path, mode)
    assert result.returncode == 2
    assert calls == []
