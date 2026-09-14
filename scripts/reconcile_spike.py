"""Case-level reconciliation against the spike's processed file (S0 spec §6.2).

Usage:
    uv run python -m scripts.reconcile_spike /path/to/ntsb-spike \
        > docs/results/s0-reconciliation.txt
"""

import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

from ntsb_probable_cause.data.build import SPIKE_SPLIT_COUNTS
from ntsb_probable_cause.paths import resolve_path
from ntsb_probable_cause.settings import Settings

_HELDOUT_MAX_YEAR = 2023


def main(argv: list[str]) -> int:
    """Print counts and every case present in one set but not the other, with deciding fields."""
    spike_table = pq.read_table(
        Path(argv[0]) / "data/processed/filtered.parquet", columns=["ntsbNumber", "_event_year"]
    )
    spike = {
        n
        for n, y in zip(
            spike_table["ntsbNumber"].to_pylist(),
            spike_table["_event_year"].to_pylist(),
            strict=True,
        )
        if y <= _HELDOUT_MAX_YEAR
    }
    ours_table = pq.read_table(
        Settings().data_dir / "processed/cases.parquet",
        columns=["ntsb_number", "split", "raw_json"],
    )
    ours_rows = [r for r in ours_table.to_pylist() if r["split"] in SPIKE_SPLIT_COUNTS]
    ours = {r["ntsb_number"] for r in ours_rows}

    print("# S0 reconciliation against the spike (event years up to 2023)")
    print(
        f"spike filtered cases: {len(spike)}; this build: {len(ours)}; in both: {len(spike & ours)}"
    )
    for split, count in SPIKE_SPLIT_COUNTS.items():
        print(
            f"{split}: spike {count}, this build {sum(1 for r in ours_rows if r['split'] == split)}"
        )
    raw_by_number = {r["ntsb_number"]: json.loads(r["raw_json"]) for r in ours_rows}
    print(f"\n## only in this build ({len(ours - spike)})")
    for number in sorted(ours - spike):
        record = raw_by_number[number]
        far = resolve_path(record, "aircrafts[0].ownerOperators[0].regulationFlightConductedUnder")
        print(
            f"{number} eventDate={record.get('eventDate')} "
            f"completionStatus={record.get('completionStatus')} far={far}"
        )
    print(f"\n## only in the spike ({len(spike - ours)})")
    for number in sorted(spike - ours):
        print(number)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
