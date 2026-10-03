"""Draw a sealed development sample once, or verify the committed list against a re-draw.

Status
    One-shot per sample, chosen with ``--sample`` (default ``dev-seal-400``). ``draw`` writes
    the sample's list under tests/fixtures/eval and refuses to overwrite it: S2.7's
    dev_seal_400_ids.csv (decision 0095) and S3's dev_seal_s3_400_ids.csv (decision 0129).
    ``--verify`` re-draws and compares, free, reading only the processed file's index columns
    and each case's injury level (no case is scored, read or fetched).

Why
    A sealed sample is the one clean check that work tuned on dev-400 generalises. Each is
    drawn exactly as dev-400 was (0026) with its own seed and every earlier sample excluded:
    dev-seal-400 leaves out dev-400; dev-seal-s3-400 leaves out dev-400 and dev-seal-400, so
    S3's check is a fresh one (S2.7's sample was opened once, and a second look would make it
    a working sample).

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.draw_sealed [--sample {dev-seal-400,dev-seal-s3-400}]
        [--verify]
"""

import argparse
import csv
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.splits import Split

CLASSES = ("C", "F", "L")


@dataclass(frozen=True)
class Draw:
    """How one sealed sample is drawn."""

    seed: int
    excluded: tuple[str, ...]  # earlier samples whose cases are never drawn


DRAWS: dict[str, Draw] = {
    "dev-seal-400": Draw(seed=20260926, excluded=("dev-400",)),
    "dev-seal-s3-400": Draw(seed=20260930, excluded=("dev-400", "dev-seal-400")),
}


def drawn(sample: str) -> list[tuple[str, str]]:
    """The sealed draw: dev split, classes C/F/L, 200 fatal and 200 non-fatal, no earlier case."""
    plan = DRAWS[sample]
    processed = Settings().data_dir / "processed"
    exclude = frozenset(case for name in plan.excluded for case in samples.sample_ids(name))
    return samples.draw(processed, Split.DEV, seed=plan.seed, exclude=exclude)


def strata(processed: Path, cases: Sequence[str]) -> dict[str, dict[str, int]]:
    """Counts of the listed cases by fatal or non-fatal and by investigation class.

    Reads only the class column and each listed case's highest injury level, the two things
    the draw itself stratifies on; nothing else of a case is read or kept.
    """
    wanted = set(cases)
    counts: Counter[tuple[str, str]] = Counter()
    with pq.ParquetFile(processed / "cases.parquet") as parquet:
        for batch in parquet.iter_batches(
            batch_size=512, columns=["ntsb_number", "investigation_class", "raw_json"]
        ):
            for case, klass, raw in zip(
                batch.column("ntsb_number").to_pylist(),
                batch.column("investigation_class").to_pylist(),
                batch.column("raw_json").to_pylist(),
                strict=True,
            ):
                if case in wanted:
                    fatal = json.loads(raw)["highestInjuryLevel"] == "Fatal"
                    counts["fatal" if fatal else "non-fatal", klass] += 1
    return {
        slice_name: {klass: counts[slice_name, klass] for klass in CLASSES}
        for slice_name in ("fatal", "non-fatal")
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Write the list once, or verify it."""
    parser = argparse.ArgumentParser(prog="draw_sealed")
    parser.add_argument("--sample", choices=sorted(DRAWS), default="dev-seal-400")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    sample: str = args.sample
    out = samples.sample_path(sample)
    rows = drawn(sample)
    if args.verify:
        with out.open(newline="") as handle:
            committed = [(r["case_id"], r["event_date"]) for r in csv.DictReader(handle)]
        same = committed == rows
        print(f"{sample}: {len(committed)} committed, {len(rows)} re-drawn, identical: {same}")
        return 0 if same else 1
    if out.exists():
        raise SystemExit(f"{out} exists: a sealed sample is drawn once (decisions 0095, 0129)")
    with out.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["case_id", "event_date"])
        writer.writerows(rows)
    years = Counter(date[:4] for _case, date in rows)
    by_stratum = strata(Settings().data_dir / "processed", [case for case, _date in rows])
    print(
        f"{sample}: {len(rows)} cases written to {out}; by year {dict(sorted(years.items()))}; "
        f"by fatal and class {by_stratum}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
