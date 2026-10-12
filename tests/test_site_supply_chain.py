"""The site's supply-chain safeguards (S5 spec §17.2) cannot be removed silently.

Andy asked (2026-10-11) that the site's dependencies be locked and that new releases not be
taken too soon. These settings live in `site/pnpm-workspace.yaml` and `site/package.json`; this
test fails if any is weakened, so a change to them is a reviewed decision, not a side effect.
"""

import json
import re
from pathlib import Path
from typing import Any

import yaml

_SITE = Path(__file__).resolve().parents[1] / "site"
_SEVEN_DAYS_IN_MINUTES = 7 * 24 * 60


def _workspace() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((_SITE / "pnpm-workspace.yaml").read_text())
    return loaded


def test_minimum_release_age_is_at_least_seven_days() -> None:
    assert _workspace()["minimumReleaseAge"] >= _SEVEN_DAYS_IN_MINUTES


def test_trust_policy_refuses_a_downgrade() -> None:
    assert _workspace()["trustPolicy"] == "no-downgrade"


def test_trust_exemptions_name_exact_versions_only() -> None:
    # An exemption covers one reviewed release, never a whole package or a range (Andy,
    # 2026-10-12, for chokidar@4.0.3).
    for entry in _workspace().get("trustPolicyExclude", []):
        assert re.fullmatch(r"(@[a-z0-9._-]+/)?[a-z0-9._-]+@\d+\.\d+\.\d+", entry), entry


def test_unreviewed_build_scripts_fail_the_install() -> None:
    assert _workspace()["strictDepBuilds"] is True


def test_indirect_dependencies_come_from_the_registry() -> None:
    assert _workspace()["blockExoticSubdeps"] is True


def test_every_allowed_build_is_named() -> None:
    allowed = _workspace().get("allowBuilds", {})
    assert isinstance(allowed, dict)
    assert all(isinstance(value, bool) for value in allowed.values())


def test_package_manager_is_an_exact_pnpm_version() -> None:
    package = json.loads((_SITE / "package.json").read_text())
    assert re.fullmatch(r"pnpm@\d+\.\d+\.\d+", package["packageManager"])


def test_node_version_is_pinned() -> None:
    assert re.fullmatch(r"\d+\n?", (_SITE / ".node-version").read_text())


def test_lockfile_is_committed() -> None:
    assert (_SITE / "pnpm-lock.yaml").is_file()
