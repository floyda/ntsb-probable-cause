"""Documentation consistency check (decision 0017).

Status
    Live check (S0). Runs in CI and is what decision 0017's stage close-out depends on.
    Not a measurement: it writes nothing under ``docs/results/``.

Usage:
    uv run python -m scripts.check_docs [root]

Fails when decision files and their index disagree, when a decision reference or a relative
link resolves to nothing, when a specification lacks a status line, when an Implemented
specification lacks an As-built part, or when a plan is left behind or malformed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SPEC_STATUSES = ("Draft", "Approved", "Implemented", "Superseded")
AS_BUILT_PARTS = (
    "Delivered",
    "Done means, with evidence",
    "Departures from this specification",
    "Decisions taken during the stage",
    "Implementation record",
)

_INDEX_ROW = re.compile(r"^\| \[(\d{4})\]\(([^)]+)\) \| .+ \| (.+) \|$")
_DECISION_REF = re.compile(r"(?<![\d.])\b(0\d{3})\b(?!\.\d)")
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_FENCE = re.compile(r"^(`{3,})[^\n]*\n.*?^\1`*[ \t]*$", re.MULTILINE | re.DOTALL)
_SPEC_STATUS = re.compile(r"Status:\s*(" + "|".join(SPEC_STATUSES) + r")\b")
_PLAN_SPEC = re.compile(r"^\*\*Spec:\*\*\s*(\S+)", re.MULTILINE)
_DECISION_STATUS = re.compile(r"^## Status\s*\n+\s*(\S.*)$", re.MULTILINE)
_STATUS_WORD = re.compile(r"(Accepted|Superseded)")
_STATUS_SCAN_LINES = 20


def _markdown_files(root: Path) -> list[Path]:
    candidates = [root / "README.md", root / "CLAUDE.md", *sorted((root / "docs").rglob("*.md"))]
    return [p for p in candidates if p.is_file() and not p.name.endswith(".local.md")]


def _status_word(text: str) -> str | None:
    match = _STATUS_WORD.match(text)
    return match.group(1) if match else None


def _decision_files(root: Path) -> dict[str, Path]:
    directory = root / "docs/decisions"
    return {p.name[:4]: p for p in sorted(directory.glob("[0-9][0-9][0-9][0-9]-*.md"))}


def _check_decisions(root: Path) -> list[str]:
    index_path = root / "docs/decisions/README.md"
    files = _decision_files(root)
    if not files and not index_path.exists():
        return []
    rows: dict[str, tuple[str, str]] = {}
    for line in index_path.read_text().splitlines() if index_path.exists() else []:
        match = _INDEX_ROW.match(line)
        if match:
            rows[match.group(1)] = (match.group(2), match.group(3).strip())
    problems: list[str] = []
    for number, path in files.items():
        name = path.relative_to(root)
        if number not in rows:
            problems.append(f"{name}: not listed in docs/decisions/README.md")
            continue
        link, index_status = rows[number]
        if link != path.name:
            problems.append(
                f"docs/decisions/README.md: {number} links to {link}, file is {path.name}"
            )
        found = _DECISION_STATUS.search(path.read_text())
        if found is None:
            problems.append(f"{name}: no '## Status' section")
        elif _status_word(found.group(1)) != _status_word(index_status):
            problems.append(
                f"{name}: status {found.group(1)!r} disagrees with index status {index_status!r}"
            )
    problems.extend(
        f"docs/decisions/README.md: {number} is listed but has no file"
        for number in sorted(rows.keys() - files.keys())
    )
    return problems


def _check_references_and_links(root: Path) -> list[str]:
    decisions = _decision_files(root).keys()
    problems: list[str] = []
    for path in _markdown_files(root):
        text = _FENCE.sub("", path.read_text())
        name = path.relative_to(root)
        problems.extend(
            f"{name}: refers to decision {number}, which does not exist"
            for number in sorted(set(_DECISION_REF.findall(text)))
            if number not in decisions
        )
        for target in _LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            relative = target.split("#", 1)[0]
            if not (path.parent / relative).exists():
                problems.append(f"{name}: link target {target} does not exist")
    return problems


def _spec_status(text: str) -> str | None:
    head = "\n".join(text.splitlines()[:_STATUS_SCAN_LINES])
    match = _SPEC_STATUS.search(head)
    return match.group(1) if match else None


def _check_specs(root: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted((root / "docs/specs").glob("*.md")):
        text = path.read_text()
        name = path.relative_to(root)
        status = _spec_status(text)
        if status is None:
            problems.append(
                f"{name}: no status line ({', '.join(SPEC_STATUSES)}) in the first lines"
            )
            continue
        if status != "Implemented":
            continue
        _, _, as_built = text.partition("\n## As built")
        if not as_built:
            problems.append(f"{name}: Implemented but has no '## As built' section")
            continue
        problems.extend(
            f"{name}: As-built section lacks '### {part}'"
            for part in AS_BUILT_PARTS
            if f"\n### {part}" not in as_built
        )
    return problems


def _check_plans(root: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted((root / "docs/plans").glob("*.md")):
        text = path.read_text()
        name = path.relative_to(root)
        if "\n## Deviations" not in text:
            problems.append(f"{name}: no '## Deviations' section")
        match = _PLAN_SPEC.search(text)
        if match is None:
            problems.append(f"{name}: no '**Spec:** <path>' line")
            continue
        spec = root / match.group(1)
        if not spec.is_file():
            problems.append(f"{name}: spec {match.group(1)} does not exist")
        elif _spec_status(spec.read_text()) == "Implemented":
            problems.append(
                f"{name}: its spec is Implemented, so this plan should have been deleted"
            )
    return problems


def check(root: Path) -> list[str]:
    """Return every documentation problem under ``root``; an empty list means clean."""
    return [
        *_check_decisions(root),
        *_check_references_and_links(root),
        *_check_specs(root),
        *_check_plans(root),
    ]


def main(argv: list[str]) -> int:
    """Print problems and return a process exit code."""
    root = Path(argv[1]) if len(argv) > 1 else Path()
    problems = check(root)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
