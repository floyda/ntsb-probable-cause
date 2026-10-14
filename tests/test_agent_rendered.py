"""The rendered-text fingerprint (S3.3 Task 2; decision 0143): ``agent/rendered.py``.

The fingerprint hashes what the agent sends a model, not the source that writes it. These tests
hold it stable, hold the scenarios to the real run's guidance, and hold every model-text literal
of the covered modules to a scenario that sends it.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.s33_mutation_sweep import covered, literals, present_keys, tables
from scripts.s33_mutation_sweep import listed as listed_names

import ntsb_probable_cause
from ntsb_probable_cause.agent import run, texts
from ntsb_probable_cause.agent.rendered import (
    MODEL_FACING_KEYS,
    RENDER_GUIDANCE,
    RENDER_MAX_CODING_CALLS,
    RENDER_STATS,
    rendered_requests,
    rendered_sha256,
    scenario_runs,
)

_SRC = Path(ntsb_probable_cause.__file__).resolve().parents[1]
_PRINT = "from ntsb_probable_cause.agent.rendered import rendered_sha256; print(rendered_sha256())"


def _hash_in(source: Path) -> str:
    """The fingerprint a fresh interpreter computes over the package under ``source``."""
    result = subprocess.run(  # noqa: S603 -- our own interpreter and a fixed program
        [sys.executable, "-c", _PRINT],
        env={"PYTHONPATH": str(source), "PYTHONHASHSEED": "random"},
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return result.stdout.strip()


def test_rendered_sha256_is_stable() -> None:
    first = rendered_sha256()
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert rendered_sha256() == first
    assert _hash_in(_SRC) == first, "another interpreter, another hash seed: the same hex"


def test_render_guidance_is_the_runs() -> None:
    assert RENDER_GUIDANCE == run.GUIDANCE


def test_render_settings_are_the_runs() -> None:
    """The scenarios use the statistics file and the coding-call limit the live agent uses."""
    assert RENDER_STATS == run.STATS
    assert RENDER_MAX_CODING_CALLS == run.MAX_CODING_CALLS


def test_every_scenario_ends() -> None:
    runs = scenario_runs()
    assert len(runs) >= 7
    for scenario in runs:
        assert scenario.stop_reason == scenario.expected_stop, scenario.name
        assert scenario.unused_replies == 0, f"{scenario.name}: replies the loop never asked for"
        assert scenario.requests, scenario.name
        for body in scenario.requests:
            assert set(body) <= set(MODEL_FACING_KEYS)


# --- the reach test ---


def test_every_model_text_literal_is_reached() -> None:
    sent = json.dumps(rendered_requests(), ensure_ascii=False)
    listed = listed_names()
    missing: set[str] = set()
    for module, path, only_class in covered():
        for literal in literals(path, only_class):
            if not literal.strip() or json.dumps(literal, ensure_ascii=False)[1:-1] in sent:
                continue
            if f"{module}:{literal}" not in listed:
                missing.add(f"{module}:{literal!r}")
    assert not missing, "model text no scenario sends (or list it, with a reason):\n" + "\n".join(
        sorted(missing)
    )


def test_the_list_holds_no_stale_entry() -> None:
    """An entry stays only while its literal exists and no scenario reaches it."""
    sent = json.dumps(rendered_requests(), ensure_ascii=False)
    present = present_keys()
    for name, table in tables().items():
        for key, reason in table.items():
            _check_entry(name, key, reason, present, sent)


def _check_entry(name: str, key: str, reason: str, present: set[str], sent: str) -> None:
    assert reason.strip(), key
    assert key in present, f"no such literal any more: {key!r}"
    literal = key.partition(":")[2]
    # A blank literal is in every request, and a 'coincident' one is meant to be found in one:
    # for those the sweep, not a substring, shows the literal itself does not feed the fingerprint.
    if literal.strip() and name != "coincident":
        assert json.dumps(literal, ensure_ascii=False)[1:-1] not in sent, (
            f"a scenario reaches it now, so it is not 'not model text': {key!r}"
        )


# --- the mutation test ---

# One edit to a model-text literal in each of the ten TEXT_SOURCES modules: (file under the
# package, the source text to find, the text to put in its place). Each is text a scenario sends,
# so the fingerprint must move; the "·" is appended inside the literal.
_MUTATIONS: tuple[tuple[str, str, str], ...] = (
    (
        "scoring/prompt.py",
        'REJECTED = "Your previous reply was rejected: "',
        'REJECTED = "Your previous reply was rejected: ·"',
    ),
    (
        "scoring/hypothesis.py",
        "occurrence probabilities sum to more than 1",
        "occurrence probabilities sum to more than 1·",
    ),
    ("scoring/codes.py", "unknown phase prefix ", "unknown phase prefix ·"),
    (
        "agent/texts.py",
        "Choose read or skip for every document listed above.",
        "Choose read or skip for every document listed above.·",
    ),
    ("agent/steps.py", "} or {options[-1]}", "} or· {options[-1]}"),
    (
        "agent/tools.py",
        "no findings recorded for this event.",
        "no findings recorded for this event.·",
    ),
    (
        "agent/schemas.py",
        "Look up the labels of occurrence codes, finding categories or finding items.",
        "Look up the labels of occurrence codes, finding categories or finding items.·",
    ),
    ("agent/later.py", 'PRIOR_CALL_ID: Final = "prior"', 'PRIOR_CALL_ID: Final = "prior·"'),
    ("agent/loop.py", r'f"{prompt.SYSTEM_REFINE}\n\n{', r'f"{prompt.SYSTEM_REFINE}\n\n·{'),
    ("agent/armb.py", 'FIXED: Final = "fixed pipeline"', 'FIXED: Final = "fixed pipeline·"'),
)
_COMMENT = ("agent/loop.py", "# Whether assistant turns", "# (edited) Whether assistant turns")


def _mutated_hash(tmp_path: Path, name: str, relative: str, old: str, new: str) -> str:
    """The fingerprint over a copy of the package with ``old`` replaced by ``new`` in one file."""
    copy = tmp_path / name
    shutil.copytree(_SRC, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    target = copy / "ntsb_probable_cause" / relative
    source = target.read_text(encoding="utf-8")
    assert old in source, f"{relative}: {old!r} is gone from the source; update the test"
    target.write_text(source.replace(old, new, 1), encoding="utf-8")
    return _hash_in(copy)


def test_a_changed_text_moves_the_fingerprint(tmp_path: Path) -> None:
    covered = {relative for relative, _, _ in _MUTATIONS}
    assert covered == {
        f"{package.removeprefix('ntsb_probable_cause.').replace('.', '/')}/{name}"
        for package, name in texts.TEXT_SOURCES
    }, "one mutation per module in TEXT_SOURCES"
    baseline = rendered_sha256()
    unmoved = [
        relative
        for n, (relative, old, new) in enumerate(_MUTATIONS)
        if _mutated_hash(tmp_path, f"m{n}", relative, old, new) == baseline
    ]
    assert not unmoved, f"an edit to the text sent did not move the fingerprint: {unmoved}"


def test_a_changed_comment_leaves_the_fingerprint_alone(tmp_path: Path) -> None:
    relative, old, new = _COMMENT
    assert _mutated_hash(tmp_path, "comment", relative, old, new) == rendered_sha256()


def test_a_flipped_reasoning_switch_moves_the_fingerprint(tmp_path: Path) -> None:
    """A2: ``PASS_REASONING`` changes what a later call carries, and a scripted reply has some."""
    flipped = _mutated_hash(
        tmp_path,
        "reasoning",
        "agent/loop.py",
        "PASS_REASONING: Final = False",
        "PASS_REASONING: Final = True",
    )
    assert flipped != rendered_sha256()


def test_the_scripted_replies_carry_reasoning_the_default_switch_leaves_out() -> None:
    sent = json.dumps(rendered_requests(), ensure_ascii=False)
    assert "reasoning_details" not in sent, "off in version 1: no request passes it back"
