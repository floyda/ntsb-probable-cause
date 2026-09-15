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
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq

from ntsb_probable_cause import fields
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.settings import Settings

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
    corpus_line = _corpus_check_line(Settings().data_dir)
    lines.append(
        corpus_line
        if corpus_line is not None
        else "corpus check: data/processed/cases.parquet not present; not run"
    )
    RESULT.write_text("\n".join(lines) + "\n")
    print(RESULT.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
