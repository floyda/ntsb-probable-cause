from pathlib import Path

from scripts.check_docs import AS_BUILT_PARTS

SKILL = Path(".claude/skills/close-stage/SKILL.md")


def test_skill_names_every_as_built_part_exactly() -> None:
    text = SKILL.read_text()
    assert text.startswith("---\nname: close-stage\n")
    for part in AS_BUILT_PARTS:
        assert f"### {part}" in text, part


def test_skill_runs_the_documentation_check() -> None:
    assert "uv run python -m scripts.check_docs" in SKILL.read_text()
