"""The rendered-text fingerprint (S3.3 Task 2; decision 0143): ``agent/rendered.py``.

The fingerprint hashes what the agent sends a model, not the source that writes it. These tests
hold it stable, hold the scenarios to the real run's guidance, and hold every model-text literal
of the covered modules to a scenario that sends it.
"""

import ast
import json
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path

import ntsb_probable_cause
from ntsb_probable_cause.agent import run, texts
from ntsb_probable_cause.agent.rendered import (
    MODEL_FACING_KEYS,
    RENDER_GUIDANCE,
    rendered_requests,
    rendered_sha256,
    scenario_runs,
)

_SRC = Path(ntsb_probable_cause.__file__).resolve().parents[1]
_NOT_MODEL_TEXT = Path(__file__).parent / "fixtures" / "rendered" / "not_model_text.toml"
_MIN_PART = 6  # an f-string's or a template's literal part counts from this many characters
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


def _docstring_nodes(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                found.add(id(body[0].value))
    return found


def _parts(value: str) -> Iterator[str]:
    """A literal's checkable parts: itself, or its text between ``{...}`` fields."""
    if re.search(r"\{[^{}]*\}", value):
        for part in re.split(r"\{[^{}]*\}", value):
            if len(part) >= _MIN_PART:
                yield part
    else:
        yield value


def _literals(path: Path, only_class: str | None = None) -> list[str]:
    """Every string literal of a module that is not a docstring (an f-string's: by part)."""
    tree: ast.AST = ast.parse(path.read_text(encoding="utf-8"))
    if only_class is not None:
        tree = next(
            n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == only_class
        )
    docstrings = _docstring_nodes(tree)
    in_fstring = {id(c) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for c in n.values}
    found: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docstrings:
            continue
        if id(node) in in_fstring:
            if len(node.value) >= _MIN_PART:
                found.append(node.value)
        else:
            found.extend(_parts(node.value))
    return found


def _covered() -> list[tuple[str, Path, str | None]]:
    """(module, file, only-class) of every module whose literals may be model text."""
    base = _SRC / "ntsb_probable_cause"
    entries: list[tuple[str, Path, str | None]] = []
    for package, name in texts.TEXT_SOURCES:
        folder = base / Path(*package.split(".")[1:])
        entries.append(
            (f"{package.removeprefix('ntsb_probable_cause.')}/{name}", folder / name, None)
        )
    entries.append(("agent/documents.py", base / "agent" / "documents.py", None))
    entries.append(("model/client.py", base / "model" / "client.py", "Payload"))
    return entries


def _listed() -> dict[str, str]:
    """Every listed literal with its reason: the plain ones, then the ``[unreachable]`` table."""
    data = tomllib.loads(_NOT_MODEL_TEXT.read_text(encoding="utf-8"))
    unreachable = data.pop("unreachable")
    assert all(isinstance(reason, str) for reason in (*data.values(), *unreachable.values()))
    return {**data, **unreachable}


def test_every_model_text_literal_is_reached() -> None:
    sent = json.dumps(rendered_requests(), ensure_ascii=False)
    listed = _listed()
    missing: set[str] = set()
    for module, path, only_class in _covered():
        for literal in _literals(path, only_class):
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
    present = {
        f"{module}:{literal}"
        for module, path, only_class in _covered()
        for literal in _literals(path, only_class)
    }
    for key, reason in _listed().items():
        assert reason.strip(), key
        assert key in present, f"no such literal any more: {key!r}"
        assert json.dumps(key.partition(":")[2], ensure_ascii=False)[1:-1] not in sent, (
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
