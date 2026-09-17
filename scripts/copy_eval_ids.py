"""Copy evaluation case IDs and event dates from the frozen spike (decision 0015).

Usage:
    uv run python -m scripts.copy_eval_ids ../ntsb-spike
"""

import csv
import subprocess
import sys
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

from ntsb_probable_cause.splits import Split, split_of

OUT = Path("tests/fixtures/eval")
SHEETS = {
    "decidability_ids.csv": "labelling/decidability.filled.csv",
    "leakage_ids.csv": "labelling/leakage.filled.csv",
}
# The spike's full sheets are deliberately NOT copied. They carry its columns verbatim:
# `ntsb_probable_cause` and `ntsb_finding_codes` are verdict, `factual_account` is synthesis
# (0013), and every case in both sheets is held-out by event date -- the 40-case sheet IS
# `heldout-40`, the sample a bar was measured on. Copying them put the answer sheet for our
# own exam in the repository, guarded only by a README sentence saying it "never enters a
# payload". Decision 0016 forbids exactly that: guarded in code, never by convention. Nothing
# ever read them. `scripts/check_fixtures_redacted.py` now fails if they come back.


def main(argv: list[str]) -> int:
    """Write one ID list per labelling sheet, with event dates, plus a provenance README."""
    spike = Path(argv[0])
    table = pq.read_table(
        spike / "data/processed/filtered.parquet", columns=["ntsbNumber", "eventDate"]
    )
    dates = {
        str(n): str(d)[:10]
        for n, d in zip(
            table["ntsbNumber"].to_pylist(), table["eventDate"].to_pylist(), strict=True
        )
    }
    commit = subprocess.run(  # noqa: S603 -- fixed argv, no shell, spike path is a CLI argument
        ["git", "-C", str(spike), "rev-parse", "--short", "HEAD"],  # noqa: S607 -- git on PATH
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, sheet in SHEETS.items():
        with (spike / sheet).open(newline="") as handle:
            ids = sorted({row["case_id"] for row in csv.DictReader(handle)})
        missing = [i for i in ids if i not in dates]
        if missing:
            print(f"{sheet}: no event date for {missing}", file=sys.stderr)
            return 1
        not_held_out = [
            i for i in ids if split_of(date.fromisoformat(dates[i])) is not Split.HELDOUT
        ]
        if not_held_out:
            print(f"{sheet}: not held-out by event date: {not_held_out}", file=sys.stderr)
            return 1
        with (OUT / name).open("w", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["case_id", "event_date"])
            writer.writerows((i, dates[i]) for i in ids)
        print(f"{OUT / name}: {len(ids)} cases")
    (OUT / "README.md").write_text(
        "# Evaluation case lists\n\n"
        f"Copied by `scripts/copy_eval_ids.py` from the spike repository at commit `{commit}`: "
        "`labelling/decidability.filled.csv` (the 40-case like-for-like set) and "
        "`labelling/leakage.filled.csv`. Event dates come from the spike's processed file. "
        "**Case id and event date only.** Every case in both sheets is held-out by event "
        "date, and the 40-case sheet is the `heldout-40` sample itself, so the spike's own "
        "cause, finding-code and factual-account columns are withheld data (0013) and are "
        "not copied here at all. `scripts/check_fixtures_redacted.py` fails if a fixture CSV "
        "grows a column carrying them.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
