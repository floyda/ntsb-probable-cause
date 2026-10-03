"""The Makefile's ``.PHONY`` line matches the targets the file defines.

An edit to the one long ``.PHONY`` line has fused two neighbouring words twice (S3.1 Task 2,
then Task 5: ``s27-coding-stats`` and ``s27-round0-cards`` became one word). A fused word
names no target, and the two targets it swallowed stop being phony, which ``make`` does not
report. Every target is phony here (none of them makes a file of its own name).
"""

import re
from pathlib import Path

_TARGET = re.compile(r"^([A-Za-z0-9_][^\s:=%]*)[ ]*:(?!=)")


def phony_words(text: str) -> list[str]:
    """The words of every ``.PHONY:`` line."""
    return [
        word
        for line in text.splitlines()
        if line.startswith(".PHONY:")
        for word in line.removeprefix(".PHONY:").split()
    ]


def targets(text: str) -> list[str]:
    """Targets defined at the start of a line (not a recipe, a comment or an assignment)."""
    return [match.group(1) for line in text.splitlines() if (match := _TARGET.match(line))]


def problems(text: str) -> list[str]:
    """What is wrong between the ``.PHONY`` words and the defined targets, as readable lines."""
    phony, defined = phony_words(text), targets(text)
    found = [f".PHONY names no target: {word}" for word in sorted(set(phony) - set(defined))]
    found += [f"target not in .PHONY: {name}" for name in sorted(set(defined) - set(phony))]
    found += [f"duplicate .PHONY word: {word}" for word in sorted(_repeated(phony))]
    found += [f"target defined twice: {name}" for name in sorted(_repeated(defined))]
    return found


def _repeated(words: list[str]) -> set[str]:
    return {word for word in words if words.count(word) > 1}


def test_the_makefile_phony_line_and_its_targets_agree() -> None:
    text = Path("Makefile").read_text()
    assert {"check", "lint", "test", "s3-draw-sealed"} <= set(targets(text))  # the parse found them
    assert problems(text) == []


def test_a_fused_phony_word_is_reported_with_the_two_targets_it_swallowed() -> None:
    """The check can fail: the defect it exists for, written out."""
    text = (
        ".PHONY: check s27-coding-statss27-round0-cards\n"
        "\n"
        "check:\n"
        "\techo ok\n"
        "\n"
        "s27-coding-stats:\n"
        "\techo stats\n"
        "\n"
        "s27-round0-cards:\n"
        "\techo cards\n"
    )
    assert problems(text) == [
        ".PHONY names no target: s27-coding-statss27-round0-cards",
        "target not in .PHONY: s27-coding-stats",
        "target not in .PHONY: s27-round0-cards",
    ]


def test_repeats_are_reported_and_assignments_recipes_and_comments_are_not_targets() -> None:
    text = ".PHONY: a b a\n# c: a comment\nX := 1\nY = 2\na:\n\tx: a recipe line\nb:\na:\n"
    assert targets(text) == ["a", "b", "a"]
    assert problems(text) == ["duplicate .PHONY word: a", "target defined twice: a"]
