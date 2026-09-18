"""Pre-commit hook: fail if a fixture carries data it is not allowed to carry.

Three checks, all on `tests/fixtures`:

* JSON records must have their owner and operator fields redacted (0015).
* CSV fixtures must not carry a withheld column. The evaluation fixtures are lists of
  held-out case ids, and the spike's own labelling sheets -- which those lists come from --
  hold the NTSB's probable cause and finding codes (verdict) and the investigator's factual
  account (synthesis). Both were briefly committed here in full, for all 70 cases, guarded
  only by a sentence in a README promising they "never enter a payload". Decision 0016 is
  explicit that the split is guarded in code and never by convention, so the promise is a
  check now.
* Docket document text committed under `tests/fixtures/docket/` names its reviewer, and no
  committed `.pdf`/`.txt` is left out of its manifest (0037).
"""

import csv
import json
import sys
from pathlib import Path

from ntsb_probable_cause.data.redaction import find_redacted_fields

# Column names that carry synthesis or verdict, as the spike's labelling sheets spell them
# and as this repo's own exports would. Matched case-insensitively against a normalised
# header, so `NTSB Probable Cause` and `ntsb_probable_cause` both trip it.
WITHHELD_COLUMNS = frozenset(
    {
        "ntsb_probable_cause",
        "probable_cause",
        "ntsb_finding_codes",
        "finding_codes",
        "ntsb_occurrence",
        "occurrence_codes",
        "factual_account",
        "factual_narrative",
        "analysis_narrative",
    }
)


def _normalise(column: str) -> str:
    return column.strip().lower().replace(" ", "_").replace("-", "_")


def withheld_columns_in(path: Path) -> list[str]:
    """The withheld column names this CSV carries, if any."""
    with path.open(newline="") as handle:
        header = next(csv.reader(handle), [])
    return sorted({c for c in header if _normalise(c) in WITHHELD_COLUMNS})


DOCKET_FIXTURES = Path("tests/fixtures/docket")


def docket_fixture_problems(root: Path = DOCKET_FIXTURES) -> list[str]:
    """Every docket text fixture must name its reviewer; every document file is listed (0037)."""
    problems: list[str] = []
    if not root.exists():
        return problems
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        manifest = json.loads((folder / "manifest.json").read_text())
        listed: set[str] = set()
        for document in manifest.get("documents", []):
            for key in ("text_file", "pdf_file"):
                name = document.get(key)
                if name:
                    listed.add(str(name))
                    if not str(document.get("reviewed_by") or "").strip():
                        problems.append(
                            f"{folder / name}: document text committed without reviewed_by (0037)"
                        )
        for path in sorted(folder.iterdir()):
            if path.suffix in {".pdf", ".txt"} and path.name not in listed:
                problems.append(f"{path}: not listed in manifest.json with reviewed_by (0037)")
    return problems


def main(paths: list[str]) -> int:
    """Check the given files, or every fixture JSON and CSV when none are given."""
    given = [Path(p) for p in paths]
    json_files = [p for p in given if p.suffix == ".json"] or (
        sorted(Path("tests/fixtures").rglob("*.json")) if not given else []
    )
    csv_files = [p for p in given if p.suffix == ".csv"] or (
        sorted(Path("tests/fixtures").rglob("*.csv")) if not given else []
    )
    failed = False
    for path in json_files:
        for found in find_redacted_fields(json.loads(path.read_text())):
            print(f"{path}: {found}")
            failed = True
    for path in csv_files:
        for column in withheld_columns_in(path):
            print(
                f"{path}: withheld column {column!r} -- synthesis and verdict never go in "
                f"git (0013, 0016). Keep case ids and event dates only."
            )
            failed = True
    for problem in docket_fixture_problems():
        print(problem)
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
