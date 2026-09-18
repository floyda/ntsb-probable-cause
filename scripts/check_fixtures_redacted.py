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
from collections.abc import Mapping
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


def _nearest_manifest_dir(start: Path, root: Path, manifests: Mapping[Path, object]) -> Path | None:
    """The nearest directory at or above ``start``, no higher than ``root``, that has a manifest."""
    current = start
    while True:
        if current in manifests:
            return current
        if current == root:
            return None
        current = current.parent


def docket_fixture_problems(root: Path = DOCKET_FIXTURES) -> list[str]:
    """Every docket document file is named by a manifest with a reviewer, wherever it sits (0037).

    Fix round 1, finding 3: the previous version only ever looked at each case folder's
    immediate children, so a document committed directly at ``root`` or nested inside a case
    folder went unchecked, and a case folder with no ``manifest.json`` raised
    ``FileNotFoundError`` instead of being reported. This walks the whole tree instead: every
    ``manifest.json`` under ``root`` is read once (naturally skipping any folder that lacks
    one -- ``Path.rglob`` only returns files that exist, so there is nothing left to raise),
    and every committed ``.pdf``/``.txt`` is matched to the nearest manifest above it, however
    deep it sits. A file with no manifest above it at all is reported as a problem, not raised
    past. This check exists to stop unreviewed document text reaching a public repository, so
    a hole in its own coverage has to fail loudly.
    """
    problems: list[str] = []
    if not root.exists():
        return problems
    manifests: dict[Path, dict[str, object]] = {}
    listed: dict[Path, set[Path]] = {}
    for manifest_path in sorted(root.rglob("manifest.json")):
        case_dir = manifest_path.parent
        manifest = json.loads(manifest_path.read_text())
        manifests[case_dir] = manifest
        names: set[Path] = set()
        for document in manifest.get("documents", []):
            for key in ("text_file", "pdf_file"):
                name = document.get(key)
                if name:
                    file_path = case_dir / str(name)
                    names.add(file_path)
                    if not str(document.get("reviewed_by") or "").strip():
                        problems.append(
                            f"{file_path}: document text committed without reviewed_by (0037)"
                        )
        listed[case_dir] = names
    for path in sorted({*root.rglob("*.pdf"), *root.rglob("*.txt")}):
        governing = _nearest_manifest_dir(path.parent, root, manifests)
        if governing is None:
            problems.append(f"{path}: no manifest.json covers this file (0037)")
        elif path not in listed[governing]:
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
