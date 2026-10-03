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


# --- S3.2 Task 10: the paid s32 targets ---------------------------------------------------------

_PAID_S32 = (
    "s32-coding-ablation",
    "s32-heldout-a",
    "s32-heldout-b-answer",
    "s32-heldout-b-tools",
    "s32-heldout-b-check",
    "s32-heldout-c",
    "s32-heldout-c-nodocket",
)
_MODEL_COMMANDS = ("ntsb-eval run", "ntsb-eval tools", "ntsb-eval check")


def recipe(text: str, target: str) -> list[str]:
    """The tab-indented recipe lines of one target."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if _TARGET.match(line) and _name(line) == target)
    body: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith("\t"):
            break
        body.append(line.strip())
    return body


def comment_after(text: str, target: str) -> str:
    """The comment lines that follow a target's recipe (the layout of the S3 targets)."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if _TARGET.match(line) and _name(line) == target)
    i = start + 1
    while i < len(lines) and lines[i].startswith("\t"):
        i += 1
    block: list[str] = []
    while i < len(lines) and lines[i].startswith("#"):
        block.append(lines[i])
        i += 1
    return "\n".join(block)


def _name(line: str) -> str:
    match = _TARGET.match(line)
    assert match is not None
    return match.group(1)


def test_every_paid_s32_target_is_defined_and_phony() -> None:
    text = Path("Makefile").read_text()
    assert set(_PAID_S32) <= set(targets(text))
    assert set(_PAID_S32) <= set(phony_words(text))


def test_every_s32_model_command_is_preceded_by_the_stage_spend_line() -> None:
    text = Path("Makefile").read_text()
    checked = 0
    for name in (n for n in targets(text) if n.startswith("s32-")):
        body = recipe(text, name)
        for index, line in enumerate(body):
            if any(command in line for command in _MODEL_COMMANDS):
                checked += 1
                spend = [
                    i for i, other in enumerate(body) if "scripts.stage_spend --stage s3" in other
                ]
                assert spend, name
                assert spend[0] < index, name
    assert checked == len(_PAID_S32)


def test_every_s32_run_line_carries_the_one_cap() -> None:
    text = Path("Makefile").read_text()
    runs = [
        line
        for name in targets(text)
        if name.startswith("s32-")
        for line in recipe(text, name)
        if "ntsb-eval run" in line
    ]
    assert len(runs) == 5
    assert all("--cap-usd 0.30" in line for line in runs)
    assert all("--expected-cost-per-case-usd" in line for line in runs)


def test_every_held_out_s32_target_says_once_in_its_comment() -> None:
    text = Path("Makefile").read_text()
    held_out = [name for name in _PAID_S32 if "heldout" in name]
    assert len(held_out) == 6
    for name in held_out:
        assert "ONCE" in comment_after(text, name), name
    assert "ONCE" not in comment_after(text, "s32-coding-ablation")


def test_the_run_ids_the_tools_and_check_targets_need_are_required() -> None:
    text = Path("Makefile").read_text()
    for name in ("s32-heldout-b-tools", "s32-heldout-b-check"):
        assert "$(error RUN is required" in recipe(text, name)[0], name


def test_the_ablation_and_the_nodocket_run_name_the_flags_the_command_has() -> None:
    text = Path("Makefile").read_text()
    assert "--without coding" in recipe(text, "s32-coding-ablation")[1]
    nodocket = recipe(text, "s32-heldout-c-nodocket")[1]
    assert "--exclude docket_listing --exclude docket_documents" in nodocket
    answer = recipe(text, "s32-heldout-b-answer")[1]
    assert "--guidance r3-loc-stall --guidance r6-aircraft-control" in answer
