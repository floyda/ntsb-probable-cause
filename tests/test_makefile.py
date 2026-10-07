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


def test_every_run_target_forwards_resume() -> None:
    """A cancelled batch run continues with RESUME=<run id>; the post-passes have no hook."""
    text = Path("Makefile").read_text()
    run_targets = [n for n in _PAID_S32 if any("ntsb-eval run" in x for x in recipe(text, n))]
    assert len(run_targets) == 5
    for name in run_targets:
        run_line = next(x for x in recipe(text, name) if "ntsb-eval run" in x)
        assert "$(if $(RESUME),--resume $(RESUME))" in run_line, name
        assert "RESUME=<run id>" in comment_after(text, name), name
    for name in ("s32-heldout-b-tools", "s32-heldout-b-check"):
        assert "RESUME" not in "\n".join(recipe(text, name)), name


def _run_line(name: str) -> str:
    text = Path("Makefile").read_text()
    return next(line for line in recipe(text, name) if "ntsb-eval run" in line)


def _flags(line: str, flag: str) -> list[str]:
    words = line.split()
    return [words[i + 1] for i, word in enumerate(words[:-1]) if word == flag]


def test_each_registered_command_has_its_registered_identity() -> None:
    """Spec §3: the sample, the arm and the flags of each of the six held-out commands."""
    expected = {
        "s32-heldout-a": "A",
        "s32-heldout-b-answer": "B",
        "s32-heldout-c": "C",
        "s32-heldout-c-nodocket": "C",
    }
    for name, arm in expected.items():
        line = _run_line(name)
        assert _flags(line, "--arm") == [arm], name
        assert _flags(line, "--sample") == ["heldout-400"], name
        assert _flags(line, "--cap-usd") == ["0.30"], name
    loop = _run_line("s32-heldout-c")
    assert "--exclude" not in loop
    assert "--without" not in loop
    assert _flags(_run_line("s32-heldout-c-nodocket"), "--exclude") == [
        "docket_listing",
        "docket_documents",
    ]
    assert "--without" not in _run_line("s32-heldout-c-nodocket")
    ablation = _run_line("s32-coding-ablation")
    assert _flags(ablation, "--arm") == ["C"]
    assert _flags(ablation, "--sample") == ["dev-400"]
    assert _flags(ablation, "--without") == ["coding"]
    assert "--exclude" not in ablation
    assert _flags(_run_line("s32-heldout-b-answer"), "--guidance") == [
        "r3-loc-stall",
        "r6-aircraft-control",
    ]
    for name in ("s32-heldout-a", "s32-heldout-c", "s32-heldout-c-nodocket"):
        assert "--guidance" not in _run_line(name), name


def test_the_post_passes_name_the_registered_way_and_statistics() -> None:
    text = Path("Makefile").read_text()
    check = next(x for x in recipe(text, "s32-heldout-b-check") if "ntsb-eval check" in x)
    assert _flags(check, "--way") == ["luna"]
    assert _flags(check, "--stats") == ["s3"]
    tools = next(x for x in recipe(text, "s32-heldout-b-tools") if "ntsb-eval tools" in x)
    assert tools.endswith("ntsb-eval tools $(RUN)")


def test_every_s33_target_is_phony_and_the_morning_checks_both_lines_first() -> None:
    text = Path("Makefile").read_text()
    s33 = {name for name in targets(text) if name.startswith("s33-")}
    assert {"s33-dry-run", "s33-morning", "s33-report"} <= s33
    assert s33 <= set(phony_words(text))
    recipe = text.split("\ns33-morning:\n", 1)[1].split("\n\n", 1)[0]
    lines = [line.strip() for line in recipe.splitlines() if line.startswith("\t")]
    stages = [i for i, line in enumerate(lines) if "stage_spend" in line]
    run = next(i for i, line in enumerate(lines) if "ntsb-live run" in line)
    assert [("--stage s3 " in lines[i], "--stage s33 " in lines[i]) for i in stages] == [
        (True, False),
        (False, True),
    ]
    assert max(stages) < run


def test_the_s33_recipes_reach_the_s3_store_through_live_env_and_the_aws_extra() -> None:
    text = Path("Makefile").read_text()
    for name in ("s33-dry-run", "s33-morning"):
        recipe = text.split(f"\n{name}:\n", 1)[1].split("\n\n", 1)[0]
        (run,) = [line for line in recipe.splitlines() if "ntsb-live run" in line]
        assert "scripts/live_env.sh" in run, name
        assert "--extra aws --with awscrt" in run, name
        assert run.index("live_env.sh") < run.index("ntsb-live run")
        assert "&& eval" in run, name  # a failed lookup stops the recipe
