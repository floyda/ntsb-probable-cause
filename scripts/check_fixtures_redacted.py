"""Pre-commit hook: fail if a fixture carries data it is not allowed to carry.

Four checks, all on `tests/fixtures`:

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
* Fix finding 6 (final whole-branch review): a committed docket listing (`.html`) or titles
  sheet (`.csv`) under `tests/fixtures/docket/` never carries a name. Spec §7.2's "titles hold
  no personal data" was asserted, not measured, and NTSB docket titles routinely name people
  ("Statement of ...", "Interview of ..."). Two checks, neither printing what it finds (the
  same rule ``scripts/name_coverage.py`` follows): the case's own recorded owner/operator
  strings, searched for in the file's visible text where the raw record is available locally;
  and a crude, explained name-shape heuristic over every title, which needs no raw data and so
  is the only one of the two that runs in CI.
"""

import csv
import html
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path

import pyarrow.parquet as pq

from ntsb_probable_cause.data.redaction import find_redacted_fields
from ntsb_probable_cause.docket.attach import owner_operator_values
from ntsb_probable_cause.docket.listing import parse_listing
from ntsb_probable_cause.errors import DocketError
from ntsb_probable_cause.settings import Settings

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


# Fix finding 6: a crude, explained heuristic for a docket title that names a person. NTSB
# titles routinely read "Statement of <Name>" or "Interview of <Name>"; this looks for two or
# three consecutive capitalised words right after one of a short list of person-introducing
# words. It is neither sound nor complete -- a two-word organisation after "submitted by"
# also matches, and a single-word name does not (re-review round 2, minor: this pattern is
# case-sensitive for the introducing word only, e.g. "of", not "OF" -- an ALL CAPS *name*
# after a lowercase introducing word does match; the docstring previously claimed it did not)
# -- but a crude check that is explained is better than a clever one that is not (the
# finding's own instruction), and a false positive here costs a second look while a false
# negative costs a name reaching a public repository.
_NAME_SHAPED_TITLE = re.compile(
    r"\b(?:of|by|with|from|signed)\s+[A-Z][a-zA-Z'-]+(?:\s+[A-Z][a-zA-Z'-]+){1,2}\b"
)
_TAG = re.compile(r"<[^>]+>")


def title_looks_like_a_name(title: str) -> bool:
    """True if ``title`` reads as naming a person, by the crude rule above."""
    return _NAME_SHAPED_TITLE.search(title) is not None


def _visible_text(html_text: str) -> str:
    """``html_text`` with tags stripped and entities unescaped, for a plain-text name search."""
    return html.unescape(_TAG.sub(" ", html_text))


def _raw_record(case_id: str, processed: Path) -> Mapping[str, object] | None:
    """The raw record for ``case_id``, from ``data/processed/cases.parquet``, if present.

    This check runs in CI and every pre-commit hook, where raw data never exists (0014's
    ``data/`` is git-ignored). A missing file is not an error: there is simply nothing to
    check the owner/operator search against, and ``title_looks_like_a_name`` still runs
    without it -- it is the only one of the two checks that needs no raw data.
    """
    path = processed / "cases.parquet"
    if not path.is_file():
        return None
    with pq.ParquetFile(path) as parquet_file:
        for batch in parquet_file.iter_batches(columns=["ntsb_number", "raw_json"]):
            for number, raw_json in zip(
                batch.column("ntsb_number").to_pylist(),
                batch.column("raw_json").to_pylist(),
                strict=True,
            ):
                if str(number) == case_id:
                    parsed = json.loads(raw_json)
                    return parsed if isinstance(parsed, dict) else None
    return None


def _carries_a_known_detail(text: str, raw: Mapping[str, object]) -> bool:
    """True if any of the case's own recorded owner/operator strings appears in ``text``.

    Same word-boundary, case-insensitive match ``attach.redact_known_names`` uses on a live
    docket (decision 0046), so a committed fixture is held to the rule the running system
    enforces -- not a separately re-derived one.
    """
    for value in owner_operator_values(raw):
        pattern = re.compile(rf"(?<!\w){re.escape(value)}(?!\w)", re.IGNORECASE)
        if pattern.search(text):
            return True
    return False


def _manifest_case_id(case_dir: Path) -> str | None:
    manifest_path = case_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text())
    fixture = manifest.get("fixture")
    case_id = fixture.get("case_id") if isinstance(fixture, dict) else None
    return case_id if isinstance(case_id, str) else None


def _html_name_problems(path: Path, processed: Path) -> list[str]:
    problems: list[str] = []
    text = path.read_text(encoding="utf-8")
    case_id = _manifest_case_id(path.parent)
    raw = _raw_record(case_id, processed) if case_id else None
    if raw is not None and _carries_a_known_detail(_visible_text(text), raw):
        problems.append(
            f"{path}: visible text carries the case record's own owner/operator detail "
            "(0046) -- check by eye before committing"
        )
    try:
        listing = parse_listing(text, mkey=0)
    except DocketError:
        return problems
    for entry in listing.entries:
        if title_looks_like_a_name(entry.title):
            problems.append(
                f"{path}: title {entry.index} matches the name-shape heuristic -- check by "
                "eye before committing (see title_looks_like_a_name)"
            )
    return problems


def _csv_name_problems(path: Path, processed: Path) -> list[str]:
    problems: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for line, row in enumerate(csv.DictReader(handle), start=2):  # header is line 1
            for column, value in row.items():
                if value and title_looks_like_a_name(value):
                    problems.append(
                        f"{path}:{line}: column {column!r} matches the name-shape heuristic "
                        "-- check by eye before committing (see title_looks_like_a_name)"
                    )
            case_id = next((v for k, v in row.items() if k and "case" in k.lower() and v), None)
            raw = _raw_record(case_id, processed) if case_id else None
            if raw is None:
                continue
            row_text = " | ".join(v for v in row.values() if v)
            if _carries_a_known_detail(row_text, raw):
                problems.append(
                    f"{path}:{line}: row carries the case record's own owner/operator detail "
                    "(0046) -- check by eye before committing"
                )
    return problems


def docket_fixture_name_problems(
    root: Path = DOCKET_FIXTURES, processed: Path | None = None
) -> list[str]:
    """Every committed listing or titles sheet under ``root``, checked for a name (finding 6).

    Covers ``.html`` listings and ``.csv`` titles sheets. Never prints what it finds -- only
    where, the same rule ``scripts/name_coverage.py`` follows -- so review the file by eye,
    not this output.
    """
    if processed is None:
        processed = Settings().data_dir / "processed"
    if not root.exists():
        return []
    problems: list[str] = []
    for path in sorted(root.rglob("*.html")):
        problems.extend(_html_name_problems(path, processed))
    for path in sorted(root.rglob("*.csv")):
        problems.extend(_csv_name_problems(path, processed))
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
    for problem in docket_fixture_name_problems():
        print(problem)
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
