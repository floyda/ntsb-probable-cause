"""Build the code tables from the NTSB data dictionary in avall.zip (spec §3.1, decision 0025).

Usage:
    uv run python -m scripts.build_code_tables ../ntsb-spike/data/raw/avall.zip

Needs mdbtools (`brew install mdbtools`). Writes labels only: five CSVs under
src/ntsb_probable_cause/scoring/tables/ and a summary under docs/results/s1-code-tables.txt.

Phase and event labels both come from the ``eADMSPUB_DataDictionary`` table's
``Events_Sequence``/``Occurrence_Code`` rows, keyed by ``code_iaids``: a phase row's code is
three digits followed by the literal ``"xxx"`` (e.g. ``"552xxx"`` -> "Landing-Landing Roll"), an
event row's code is the literal ``"xxx"`` followed by three digits (e.g. ``"xxx230"`` -> "Loss
of control on ground"). See the Deviations section of docs/plans/2026-09-15-s1-scoring-and-
evaluation.md, Task 5, for why this replaces the brief's Events_Sequence-table
Occurrence_Description-stripping heuristic.
"""

import csv
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq

from ntsb_probable_cause import fields
from ntsb_probable_cause.fields import Raw
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.settings import Settings

#: Splits a case-level coverage measurement may use; ``open`` is excluded (spec §5, task 5b):
#: it may enter a measurement only as a count, and this measurement needs none of its cases.
COVERAGE_SPLITS = ("dev", "heldout")

TABLES = Path("src/ntsb_probable_cause/scoring/tables")
RESULT = Path("docs/results/s1-code-tables.txt")


def export(mdb: str, table: str) -> list[dict[str, str]]:
    """Export one table with mdbtools."""
    out = subprocess.run(  # noqa: S603
        ["mdb-export", mdb, table],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return list(csv.DictReader(io.StringIO(out)))


def write(name: str, rows: dict[str, str]) -> None:
    """Write code,label sorted by code."""
    TABLES.mkdir(parents=True, exist_ok=True)
    with (TABLES / f"{name}.csv").open("w", newline="") as handle:
        w = csv.writer(handle, lineterminator="\n")
        w.writerow(["code", "label"])
        w.writerows(sorted(rows.items()))


def _codes_in_use(cases_path: Path) -> set[str]:
    """Every occurrence and finding code used in the processed corpus."""
    table = pq.read_table(cases_path, columns=["raw_json"])
    used: set[str] = set()
    for row in table.to_pylist():
        raw = json.loads(str(row["raw_json"]))
        used.update(fields.occurrence_codes(raw))
        used.update(fields.finding_codes(raw))
    return used


def _corpus_check_line(data_dir: Path) -> str | None:
    """Codes in use that the built tables lack, or None if the processed corpus is absent."""
    cases_path = data_dir / "processed/cases.parquet"
    if not cases_path.exists():
        return None
    tables = load_tables()
    known_occurrence = {p + e for p in tables.phases for e in tables.events}
    known_finding = {i + m for i in tables.items for m in tables.modifiers}
    missing = sorted(
        code
        for code in _codes_in_use(cases_path)
        if code not in known_occurrence and code not in known_finding
    )
    return f"codes in use but not in the tables: {len(missing)} {missing}"


@dataclass(frozen=True)
class SplitCoverage:
    """One split's case-level coverage of the code tables."""

    cases: int
    primary_not_composable: int
    finding_not_composable: int

    @property
    def primary_not_composable_pct(self) -> float:
        """Percentage of cases whose primary occurrence code cannot be composed."""
        return 100 * self.primary_not_composable / self.cases if self.cases else 0.0


def _missing_occurrence_parts(code: str, tables: CodeTables) -> list[str]:
    phase, event = code[:3], code[3:]
    parts = []
    if phase not in tables.phases:
        parts.append(f"phase {phase}")
    if event not in tables.events:
        parts.append(f"event {event}")
    return parts


def _missing_finding_parts(code: str, tables: CodeTables) -> list[str]:
    item, modifier = code[:8], code[8:]
    parts = []
    if item not in tables.items:
        parts.append(f"item {item}")
    if modifier not in tables.modifiers:
        parts.append(f"modifier {modifier}")
    return parts


def coverage_check(
    raws: Iterable[tuple[str, Raw]], tables: CodeTables
) -> tuple[dict[str, SplitCoverage], list[tuple[str, int]]]:
    """Per-split case coverage over ``(split, raw)`` pairs, and missing parts ranked by case count.

    Only ``dev`` and ``heldout`` splits are counted (spec §5, task 5b); other splits are ignored.
    A case's primary occurrence code is the first of ``fields.occurrence_codes(raw)``; a case
    counts under "finding not composable" if any finding flagged in the probable cause
    (``fields.finding_codes_in_cause(raw)``) has an item or modifier the tables lack. The ranking
    counts every occurrence of a missing part: once per case for a missing phase or event (a case
    has one primary code), once per flagged finding that needs it for a missing item or modifier
    (a case with two such findings needing the same modifier counts it twice).
    """
    counts = {split: [0, 0, 0] for split in COVERAGE_SPLITS}
    missing_part_counts: Counter[str] = Counter()
    for split, raw in raws:
        if split not in counts:
            continue
        row = counts[split]
        row[0] += 1
        occurrence = fields.occurrence_codes(raw)
        if occurrence and (parts := _missing_occurrence_parts(occurrence[0], tables)):
            row[1] += 1
            missing_part_counts.update(parts)
        finding_flagged = False
        for code in fields.finding_codes_in_cause(raw):
            if parts := _missing_finding_parts(code, tables):
                finding_flagged = True
                missing_part_counts.update(parts)
        if finding_flagged:
            row[2] += 1
    stats = {split: SplitCoverage(*row) for split, row in counts.items()}
    return stats, missing_part_counts.most_common()


def _coverage_lines(cases_path: Path, tables: CodeTables) -> list[str]:
    """The per-split coverage lines and the ranked missing-parts line."""
    table = pq.read_table(cases_path, columns=["raw_json", "split"])
    raws = ((str(row["split"]), json.loads(str(row["raw_json"]))) for row in table.to_pylist())
    stats, ranked = coverage_check(raws, tables)
    lines = [
        f"{split}: {s.cases} cases; primary occurrence code not composable: "
        f"{s.primary_not_composable} ({s.primary_not_composable_pct:.2f}%); cases with a "
        f"flagged finding not composable: {s.finding_not_composable}"
        for split, s in stats.items()
    ]
    lines.append(
        "missing parts (dev+heldout), ranked by case count: "
        + "; ".join(f"{part} {count}" for part, count in ranked)
    )
    return lines


def main(argv: list[str]) -> int:
    """Build the five tables."""
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(argv[0]) as z:
        z.extract("avall.mdb", tmp)
        mdb = f"{tmp}/avall.mdb"
        dictionary = export(mdb, "eADMSPUB_DataDictionary")
    items: dict[str, str] = {}
    definitions: dict[str, str] = {}
    for r in dictionary:
        if (
            r["Table"] == "Findings"
            and r["Column"] == "findings_code"
            and r["code_iaids"].endswith("XX")
        ):
            items[r["code_iaids"][:8]] = r["meaning"].replace(" - ", " — ")
            if r.get("Question_Def"):
                definitions[r["code_iaids"][:8]] = r["Question_Def"].strip()
    modifiers = {
        r["code_iaids"][-2:]: r["meaning"]
        for r in dictionary
        if r["Table"] == "Findings" and r["Column"] == "modifier_no"
    }
    occurrence_rows = [
        r
        for r in dictionary
        if r["Table"] == "Events_Sequence" and r["Column"] == "Occurrence_Code"
    ]
    phase_labels = {
        r["code_iaids"][:3]: r["meaning"]
        for r in occurrence_rows
        if r["code_iaids"].endswith("xxx")
    }
    events = {
        r["code_iaids"][-3:]: r["meaning"]
        for r in occurrence_rows
        if r["code_iaids"].startswith("xxx") and not r["code_iaids"].endswith("xxx")
    }
    categories: dict[str, str] = {}
    for code, label in items.items():
        parts = label.split(" — ")
        categories.setdefault(code[:6], " — ".join(parts[:3]))
    write("phases", phase_labels)
    write("events", events)
    write("categories", categories)
    write("items", {k: f"{v} | {definitions.get(k, '')}".rstrip(" |") for k, v in items.items()})
    write("modifiers", modifiers)
    lines = [
        f"S1 code tables, built {datetime.now(UTC).date()} from {Path(argv[0]).name} by "
        "scripts/build_code_tables.py",
        f"phases {len(phase_labels)}; events {len(events)}; categories {len(categories)}; "
        f"items {len(items)}; modifiers {len(modifiers)}",
    ]
    cases_path = Settings().data_dir / "processed/cases.parquet"
    corpus_line = _corpus_check_line(Settings().data_dir)
    lines.append(
        corpus_line
        if corpus_line is not None
        else "corpus check: data/processed/cases.parquet not present; not run"
    )
    if cases_path.exists():
        lines.extend(_coverage_lines(cases_path, load_tables()))
    RESULT.write_text("\n".join(lines) + "\n")
    print(RESULT.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
