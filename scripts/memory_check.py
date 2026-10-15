"""Check a coding-memory snapshot against development case text, and stamp it (decision 0201).

Status
    Live tool, free, local: needs ``data/processed/cases.parquet``. Writes the stamp of
    decision 0201. CI cannot run it (no data); CI holds the identifier check and the stamp's
    hash instead.

What it reads
    The snapshot, and every development case's factual narrative, analysis narrative and
    probable cause (through ``fields``, never a second assembler). Rows of any other split
    are never read into the comparison.

What it writes
    ``<snapshot>.stamp.json`` beside the snapshot, only when all three checks pass: identifier
    (digits and unlisted capitalised words), withheld text (a lesson sentence found inside a
    withheld text) and copying (eight consecutive words shared with a probable-cause
    sentence). Findings are printed and nothing is written when any is found. Exit 1 then.

Usage
    uv run python -m scripts.memory_check --snapshot NAME
"""

import argparse
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

from ntsb_probable_cause import fields, gitinfo
from ntsb_probable_cause.memory import checks, snapshots
from ntsb_probable_cause.settings import Settings

DEV_SPLIT = "dev"


def processed_path() -> Path:
    """The processed case file."""
    return Settings().data_dir / "processed" / "cases.parquet"


def _development_texts() -> tuple[list[str], list[str]]:
    """The withheld texts and the probable-cause sentences of every development case."""
    withheld: list[str] = []
    causes: list[str] = []
    columns = ["split", "raw_json"]
    with pq.ParquetFile(processed_path()) as parquet:
        for batch in parquet.iter_batches(batch_size=512, columns=columns):
            rows = zip(*(batch.column(c).to_pylist() for c in columns), strict=True)
            for split, raw_json in rows:
                if split != DEV_SPLIT:
                    continue
                raw = json.loads(raw_json)
                cause = fields.probable_cause(raw)
                texts = (fields.factual_narrative(raw), fields.analysis_narrative(raw), cause)
                withheld.extend(t for t in texts if t)
                if cause:
                    causes.append(cause)
    return withheld, causes


def main(argv: Sequence[str] | None = None) -> int:
    """Run the three checks on a snapshot; stamp it if all pass.

    Returns:
        0 when the stamp was written, 1 when any check found something.
    """
    parser = argparse.ArgumentParser(prog="memory_check")
    parser.add_argument("--snapshot", required=True, help="snapshot name")
    args = parser.parse_args(argv)
    directory = snapshots.SNAPSHOT_DIR  # read at call time, so a test can point it elsewhere
    memory = snapshots.load(args.snapshot, directory)
    found = checks.identifier_findings(memory)
    if found:
        print("\n".join(f"- {f}" for f in found))
        return 1
    withheld, causes = _development_texts()
    found = checks.withheld_findings(memory, withheld) + checks.copying_findings(memory, causes)
    if found:
        print("\n".join(f"- {f}" for f in found))
        return 1
    commit, dirty = gitinfo.commit_state()
    stamp = checks.Stamp(
        snapshot=args.snapshot,
        sha256=snapshots.sha256_of(snapshots.snapshot_path(args.snapshot, directory)),
        withheld_texts_compared=len(withheld),
        causes_compared=len(causes),
        checked_on=date.today(),
        commit=commit,
        dirty=dirty,
    )
    snapshots.stamp_path(args.snapshot, directory).write_text(
        stamp.model_dump_json(indent=1) + "\n"
    )
    print(
        f"{args.snapshot}: 0 findings against {len(withheld)} withheld texts and "
        f"{len(causes)} probable-cause texts; stamped"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
