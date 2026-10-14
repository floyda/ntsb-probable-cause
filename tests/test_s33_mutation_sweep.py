"""Tests for the rendered-text mutation sweep (S3.3 final review, A1): ``s33_mutation_sweep``.

Offline and fast: the sweep's own run (818 interpreter starts) is ``make s33-mutation-sweep``, not
a test. These tests hold the parts around it: where a literal is edited, how a result is judged.
"""

import ast
from pathlib import Path

import pytest
from scripts import s33_mutation_sweep as sweep

MARK = sweep.MARK.decode()
SOURCE = '''"""Docstring: never a site."""

PLAIN = "plain text here"
SINGLE = 'single'
BLOCK = """triple
quoted"""
JOINED = "one " "two"
FORMATTED = f"before {PLAIN} after {PLAIN!r:>10}"


def f() -> str:
    """Another docstring."""
    return "inside a function"
'''


def _sites(tmp_path: Path) -> tuple[Path, list[sweep.Site]]:
    path = tmp_path / "module.py"
    path.write_text(SOURCE, encoding="utf-8")
    return path, sweep.sites("module.py", path, None)


def test_docstrings_are_not_sites(tmp_path: Path) -> None:
    _, found = _sites(tmp_path)
    assert not [s for s in found if "docstring" in s.value.lower()]


def test_every_edit_is_inside_its_literal_and_the_source_still_parses(tmp_path: Path) -> None:
    path, found = _sites(tmp_path)
    assert {s.value for s in found} >= {
        "plain text here",
        "single",
        "triple\nquoted",
        "one two",
        "before ",
        " after ",
        "inside a function",
    }
    data = path.read_bytes()
    for site in found:
        edited = data[: site.position] + sweep.MARK + data[site.position :]
        tree = ast.parse(edited)  # a mark in the wrong place is a syntax error or a new token
        values = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)}
        assert site.value + MARK in values, site


def test_parts_of_a_template_literal_count_from_six_characters() -> None:
    assert list(sweep.parts("a {x} longer part {y} b")) == [" longer part "]
    assert list(sweep.parts("no fields")) == ["no fields"]


def test_literals_of_a_class_only(tmp_path: Path) -> None:
    path = tmp_path / "klass.py"
    path.write_text('A = "outside the class"\n\nclass K:\n    B = "inside the class"\n')
    assert sweep.literals(path, "K") == ["inside the class"]


def test_the_covered_modules_exist_and_hold_the_new_ones() -> None:
    names = {module for module, _, _ in sweep.covered()}
    assert {"fields.py", "docket/attach.py", "docket/extract.py", "docket/listing.py"} <= names
    assert "agent/documents.py" in names
    assert all(path.is_file() for _, path, _ in sweep.covered())


def test_the_list_has_four_tables_and_every_reason_is_given() -> None:
    four = sweep.tables()
    assert set(four) == {"plain", "unreachable", "coincident", "selects"}
    assert all(reason.strip() for table in four.values() for reason in table.values())
    assert set(sweep.selecting()) == set(four["selects"])


def _site(value: str, module: str = "agent/texts.py", line: int = 1) -> sweep.Site:
    return sweep.Site(module, line, value, 0)


BASE = "a" * 64


@pytest.fixture
def lists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sweep, "listed", lambda: {"agent/texts.py:key": "a key", "m.py:path": "p"})
    monkeypatch.setattr(sweep, "selecting", lambda: {"m.py:path": "p"})


@pytest.mark.usefixtures("lists")
def test_a_literal_whose_edit_moves_the_fingerprint_passes() -> None:
    assert sweep.report(BASE, [(_site("model text"), "b" * 64)]) == 0


@pytest.mark.usefixtures("lists")
def test_an_unchanged_literal_that_is_not_listed_is_a_gap(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert sweep.report(BASE, [(_site("model text"), BASE)]) == 1
    assert "GAP agent/texts.py:1 'model text'" in capsys.readouterr().out


@pytest.mark.usefixtures("lists")
def test_an_unchanged_literal_that_is_listed_passes() -> None:
    assert sweep.report(BASE, [(_site("key"), BASE)]) == 0


@pytest.mark.usefixtures("lists")
def test_a_part_of_a_listed_template_is_listed() -> None:
    assert sweep.is_listed(_site("x {n} key"), {"agent/texts.py:key": "a key"}) is False
    assert sweep.is_listed(_site("a longer key {n}"), {"agent/texts.py:a longer key ": "r"})


@pytest.mark.usefixtures("lists")
def test_a_selects_entry_whose_edit_changes_nothing_is_misfiled(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert sweep.report(BASE, [(_site("path", "m.py"), BASE)]) == 1
    assert "MISFILED m.py:1 'path'" in capsys.readouterr().out


@pytest.mark.usefixtures("lists")
def test_an_edit_that_breaks_the_import_is_counted_and_never_a_gap(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert sweep.report(BASE, [(_site("model text"), "ERROR:SyntaxError")]) == 0
    assert "1 breaks the import" in capsys.readouterr().out


@pytest.mark.usefixtures("lists")
def test_a_listed_literal_that_moves_the_fingerprint_is_only_a_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert sweep.report(BASE, [(_site("key"), "b" * 64)], verbose=True) == 0
    assert "moves: agent/texts.py:1 'key'" in capsys.readouterr().out
