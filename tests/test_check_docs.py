from pathlib import Path

import pytest
from scripts.check_docs import AS_BUILT_PARTS, check

SPEC = "docs/specs/2026-09-13-s0.md"


def make_repo(root: Path) -> Path:
    (root / "docs/decisions").mkdir(parents=True)
    (root / "docs/specs").mkdir()
    (root / "docs/plans").mkdir()
    (root / "docs/decisions/0001-first.md").write_text(
        "# 0001 — First\n\n## Status\n\nAccepted, 2026-09-13.\n"
    )
    (root / "docs/decisions/README.md").write_text(
        "| # | Decision | Status |\n|---|---|---|\n| [0001](0001-first.md) | First | Accepted |\n"
    )
    (root / SPEC).write_text(
        "# S0\n\n*Status: Approved (2026-09-13).*\n\n"
        "See decision 0001 and [self](2026-09-13-s0.md).\n"
    )
    (root / "docs/plans/2026-09-13-s0.md").write_text(
        f"# Plan\n\n**Spec:** {SPEC}\n\n## Deviations\n\nNone.\n"
    )
    return root


def implemented_spec(parts: tuple[str, ...]) -> str:
    sections = "".join(f"### {part}\n\nText.\n\n" for part in parts)
    return f"# S0\n\n*Status: Implemented (2026-10-01, #12).*\n\n## As built\n\n{sections}"


def test_clean_repository_has_no_problems(tmp_path: Path) -> None:
    assert check(make_repo(tmp_path)) == []


def test_this_repository_is_clean() -> None:
    assert check(Path()) == []


def test_decision_missing_from_index(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / "docs/decisions/0002-second.md").write_text("# 0002\n\n## Status\n\nAccepted.\n")
    assert any("0002-second.md" in p and "not listed" in p for p in check(root))


def test_index_lists_missing_file(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    index = root / "docs/decisions/README.md"
    index.write_text(index.read_text() + "| [0003](0003-gone.md) | Gone | Accepted |\n")
    assert any("0003" in p and "no file" in p for p in check(root))


def test_status_mismatch_between_index_and_file(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / "docs/decisions/0001-first.md").write_text(
        "# 0001\n\n## Status\n\nSuperseded by 0001.\n"
    )
    assert any("status" in p and "0001" in p for p in check(root))


def test_dangling_decision_reference(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / SPEC).write_text("# S0\n\n*Status: Approved.*\n\nSee decision 0042.\n")
    assert any("0042" in p for p in check(root))


def test_broken_relative_link(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / SPEC).write_text("# S0\n\n*Status: Approved.*\n\n[missing](nowhere.md)\n")
    assert any("nowhere.md" in p for p in check(root))


def test_external_links_and_anchors_are_ignored(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / SPEC).write_text(
        "# S0\n\n*Status: Approved.*\n\n"
        "[a](https://example.org) [b](#section) [c](2026-09-13-s0.md#x)\n"
    )
    assert check(root) == []


def test_fenced_code_is_not_scanned(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / SPEC).write_text(
        "# S0\n\n*Status: Approved.*\n\n```python\nref = '0042'  # [x](nowhere.md)\n```\n"
    )
    assert check(root) == []


def test_spec_without_status(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / SPEC).write_text("# S0\n\nNo status here.\n")
    assert any("status line" in p for p in check(root))


@pytest.mark.parametrize("missing", AS_BUILT_PARTS)
def test_implemented_spec_missing_as_built_part(tmp_path: Path, missing: str) -> None:
    root = make_repo(tmp_path)
    (root / "docs/plans/2026-09-13-s0.md").unlink()
    parts = tuple(p for p in AS_BUILT_PARTS if p != missing)
    (root / SPEC).write_text(implemented_spec(parts))
    assert any(missing in p for p in check(root))


def test_implemented_spec_with_all_parts_and_no_plan_is_clean(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / "docs/plans/2026-09-13-s0.md").unlink()
    (root / SPEC).write_text(implemented_spec(AS_BUILT_PARTS))
    assert check(root) == []


def test_plan_left_behind_for_implemented_spec(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / SPEC).write_text(implemented_spec(AS_BUILT_PARTS))
    assert any("should have been deleted" in p for p in check(root))


def test_plan_without_deviations(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / "docs/plans/2026-09-13-s0.md").write_text(f"# Plan\n\n**Spec:** {SPEC}\n")
    assert any("Deviations" in p for p in check(root))


def test_plan_without_spec_line(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    (root / "docs/plans/2026-09-13-s0.md").write_text("# Plan\n\n## Deviations\n")
    assert any("**Spec:**" in p for p in check(root))
