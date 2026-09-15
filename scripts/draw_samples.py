"""Draw the two fixed S1 samples, heldout-400 and dev-400, from cases.parquet (spec §5).

Usage:
    NTSB_DATA_DIR=... uv run python -m scripts.draw_samples
"""

import csv
import json
import sys
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

from ntsb_probable_cause.scoring.samples import draw
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.splits import Split

OUT = Path("tests/fixtures/eval")
_TARGETS = {"heldout-400": Split.HELDOUT, "dev-400": Split.DEV}
_FILES = {"heldout-400": "heldout_400_ids.csv", "dev-400": "dev_400_ids.csv"}


def _counts(processed: Path, ids: list[str]) -> Counter[tuple[bool, str]]:
    """Fatal x class counts for the drawn IDs, for the printed report."""
    columns = ["ntsb_number", "investigation_class", "raw_json"]
    table = pq.read_table(processed / "cases.parquet", columns=columns)
    by_id = {
        n: (c, json.loads(r)["highestInjuryLevel"] == "Fatal")
        for n, c, r in zip(*(table[col].to_pylist() for col in columns), strict=True)
    }
    return Counter((by_id[i][1], by_id[i][0]) for i in ids)


def main(argv: list[str]) -> int:
    """Draw both samples, write their ID/date CSVs, print fatal x class counts."""
    del argv
    processed = Settings().data_dir / "processed"
    OUT.mkdir(parents=True, exist_ok=True)
    for name, split in _TARGETS.items():
        drawn = draw(processed, split)
        with (OUT / _FILES[name]).open("w", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["case_id", "event_date"])
            writer.writerows(drawn)
        counts = _counts(processed, [case_id for case_id, _ in drawn])
        print(f"{name}: {len(drawn)} cases")
        for (fatal, cls), n in sorted(counts.items()):
            print(f"  fatal={fatal} class={cls}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
