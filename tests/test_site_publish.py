"""`site/scripts/publish.sh`, the publish step CodeBuild runs (S5 spec §18.1, §19.1).

A fake `aws` on PATH records each call, so the order is checked without AWS: styles and
scripts first, then pages, then removal of files no longer used, then CloudFront. In site mode,
fake `node` and `pnpm` record theirs too, in a copy of the repository's layout, so nothing is
built in the real `site/` (the checks they stand for have their own tests).
"""

import os
import re
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


@pytest.mark.parametrize("mode", ["", "launch", "Site"])
def test_every_other_mode_is_refused_and_nothing_is_published(tmp_path: Path, mode: str) -> None:
    result, calls = _run(tmp_path, mode)
    assert result.returncode == 2
    assert calls == []


# Site mode (plan 2026-11-01, Task 3). One log holds every tool's calls in order.
_FAKES = {
    # Copies the fake export into the folder named, as `aws s3 sync s3://... <dir>` would.
    "aws": (
        'echo "aws $*" >> "$LOG"\n'
        'case "$*" in\n'
        '  "s3 sync s3://"*) mkdir -p "$4"; cp -R "$FAKE_EXPORT/." "$4" ;;\n'
        # The mark as it stands at publish time: tonight's, unless a test says a newer one landed.
        '  "s3 cp s3://"*) cp "${FAKE_MARK_NOW:-$FAKE_EXPORT/_finished.json}" "$4" ;;\n'
        "  *create-invalidation*) echo I2EXAMPLE ;;\n"
        "esac\n"
    ),
    # The real check prints this line only when the export is whole; publish.sh requires it.
    "node": (
        'echo "node $*" >> "$LOG"\n'
        '[ "$FAIL_AT" != node ] || exit 1\n'
        '[ "$FAIL_AT" = silent ] || echo "check-finished: the export is whole"\n'
    ),
    # `pnpm run build` leaves a page in site/dist, as Astro would.
    "pnpm": (
        'echo "pnpm $* in=$(basename "$PWD") export=${BOARD_EXPORT_DIR:+set}" >> "$LOG"\n'
        'case "$*" in\n'
        '  "run build") [ "$FAIL_AT" != build ] || exit 1; mkdir -p dist;'
        ' [ "$FAIL_AT" = nopage ] || echo page > dist/index.html ;;\n'
        '  "exec vitest"*) [ "$FAIL_AT" != checks ] || exit 1 ;;\n'
        "esac\n"
    ),
}


def _run_site(
    tmp_path: Path, *, env: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    root = tmp_path / "repo"
    (root / "site").mkdir(parents=True)
    # A dist left from an earlier build must never be published: the script removes it first.
    (root / "site/dist").mkdir()
    (root / "site/dist/stale.html").write_text("stale")
    export = tmp_path / "export"
    export.mkdir()
    (export / "index.json").write_text("{}")
    (export / "_finished.json").write_text('{"built_at": "night N"}')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in _FAKES.items():
        (bin_dir / name).write_text("#!/bin/sh\n" + body)
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "calls.log"
    full_env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "LOG": str(log),
        "FAKE_EXPORT": str(export),
        "FAIL_AT": "",
        "SITE_MODE": "site",
        "SITE_BUCKET": "test-site-bucket",
        "DISTRIBUTION_ID": "E000TEST",
        "LIVE_BUCKET": "test-live-bucket",
        **(env or {}),
    }
    result = subprocess.run(  # noqa: S603 -- fixed script path, test input only
        [_BASH, str(_SCRIPT)], cwd=root, env=full_env, capture_output=True, text=True, check=False
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return result, [re.sub(r" /\S+/board-1", " <export>", call) for call in calls]


def test_site_builds_from_a_whole_export_then_publishes_in_holdings_order(tmp_path: Path) -> None:
    result, calls = _run_site(tmp_path)
    assert result.returncode == 0, result.stderr
    target = "s3://test-site-bucket"
    assert calls == [
        "aws s3 sync s3://test-live-bucket/export/board-1/ <export> --only-show-errors",
        # The export is whole before anything is installed or built.
        "node scripts/check-finished.ts <export>",
        "pnpm install --frozen-lockfile in=site export=",
        "pnpm run build in=site export=set",
        "pnpm exec vitest run tests/dist.test.ts in=site export=set",
        # The mark again, just before publishing: unchanged, so this build's export is current.
        "aws s3 cp s3://test-live-bucket/export/board-1/_finished.json <export>.mark-now "
        "--only-show-errors",
        f"aws s3 sync site/dist {target} --exclude * --include _astro/* "
        "--cache-control public, max-age=31536000, immutable",
        f"aws s3 sync site/dist {target} --exclude _astro/* --exclude *.html "
        "--cache-control public, max-age=300",
        f"aws s3 sync site/dist {target} --exclude * --include *.html --cache-control no-cache",
        "aws cloudfront create-invalidation --distribution-id E000TEST --paths /* "
        "--query Invalidation.Id --output text",
        "aws cloudfront wait invalidation-completed --distribution-id E000TEST --id I2EXAMPLE",
        f"aws s3 sync site/dist {target} --delete --exclude _astro/*",
    ]
    assert not (tmp_path / "repo/site/dist/stale.html").exists()


@pytest.mark.parametrize("step", ["node", "silent", "build", "nopage", "checks"])
def test_site_publishes_nothing_when_a_step_fails(tmp_path: Path, step: str) -> None:
    # node: the finished mark is missing or stale; silent: the check exits 0 without saying the
    # export is whole; build: the export or the claims fail; nopage: the build wrote no first
    # page, so the page checks would all skip; checks: a built page fails respect, links or
    # tags. Yesterday's site stays (spec §19.1).
    result, calls = _run_site(tmp_path, env={"FAIL_AT": step})
    assert result.returncode != 0
    assert not [call for call in calls if "test-site-bucket" in call or "cloudfront" in call]


def test_site_needs_s4s_bucket(tmp_path: Path) -> None:
    result, calls = _run_site(tmp_path, env={"LIVE_BUCKET": ""})
    assert result.returncode != 0
    assert "LIVE_BUCKET" in result.stderr
    assert calls == []


def test_site_leaves_publishing_to_a_newer_nights_build(tmp_path: Path) -> None:
    # Review (2026-11-01): two builds can overlap, so a build whose export is no longer the
    # latest publishes nothing, and does not fail: the newer night's own build publishes it.
    newer = tmp_path / "newer-mark.json"
    newer.write_text('{"built_at": "night N+1"}')
    result, calls = _run_site(tmp_path, env={"FAKE_MARK_NOW": str(newer)})
    assert result.returncode == 0, result.stderr
    assert "a newer export arrived" in result.stdout
    assert not [call for call in calls if "test-site-bucket" in call or "cloudfront" in call]
