from pathlib import Path

from scripts.check_docs import AS_BUILT_PARTS

SKILL = Path(".claude/skills/close-stage/SKILL.md")
TEMPLATE = Path(".github/pull_request_template.md")


def test_skill_names_every_as_built_part_exactly() -> None:
    text = SKILL.read_text()
    assert text.startswith("---\nname: close-stage\n")
    for part in AS_BUILT_PARTS:
        assert f"### {part}" in text, part


def test_skill_runs_the_documentation_check() -> None:
    assert "uv run python -m scripts.check_docs" in SKILL.read_text()


def test_skill_exempts_its_own_close_out_steps() -> None:
    text = SKILL.read_text()
    assert "that runs `/close-stage` onward" in text
    assert "has no open pull request" in text
    assert "gh pr view --json state --jq .state" in text
    assert "git branch --show-current" in text


def test_skill_sets_the_release_version_and_names_the_release_command() -> None:
    text = SKILL.read_text()
    assert "git describe --tags --abbrev=0 --match 'v*'" in text
    assert "uv lock" in text
    assert "gh release create v<version> --target main --generate-notes" in text


def test_pull_request_template_carries_the_release_steps() -> None:
    text = TEMPLATE.read_text()
    assert "`version` in `pyproject.toml`" in text
    assert "gh release create v<version> --target main --generate-notes" in text
