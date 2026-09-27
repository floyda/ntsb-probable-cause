"""Draw the sealed development sample once, or verify the committed list against a re-draw.

Status
    One-shot for S2.7 (decision 0095): ``draw`` writes tests/fixtures/eval/dev_seal_400_ids.csv
    and refuses to overwrite it; ``--verify`` re-draws and compares, free, reading only the
    processed file's index columns (no case is scored, read or fetched).

Why
    The sealed sample is the one clean check that guidance written from dev-400 generalises.
    It is drawn exactly as dev-400 was (0026) with a new seed and every dev-400 case excluded.

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.draw_sealed [--verify]
"""

import argparse
import csv
from collections import Counter
from collections.abc import Sequence

from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.splits import Split

SEED = 20260926
OUT = samples.EVAL_DIR / "dev_seal_400_ids.csv"


def drawn() -> list[tuple[str, str]]:
    """The sealed draw: dev split, classes C/F/L, 200 fatal and 200 non-fatal, no dev-400 case."""
    processed = Settings().data_dir / "processed"
    return samples.draw(
        processed, Split.DEV, seed=SEED, exclude=frozenset(samples.sample_ids("dev-400"))
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Write the list once, or verify it."""
    parser = argparse.ArgumentParser(prog="draw_sealed")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    rows = drawn()
    if args.verify:
        with OUT.open(newline="") as handle:
            committed = [(r["case_id"], r["event_date"]) for r in csv.DictReader(handle)]
        same = committed == rows
        print(f"dev-seal-400: {len(committed)} committed, {len(rows)} re-drawn, identical: {same}")
        return 0 if same else 1
    if OUT.exists():
        raise SystemExit(f"{OUT} exists: the sealed sample is drawn once (decision 0095)")
    with OUT.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["case_id", "event_date"])
        writer.writerows(rows)
    years = Counter(date[:4] for _case, date in rows)
    print(
        f"dev-seal-400: {len(rows)} cases written to {OUT}; by year {dict(sorted(years.items()))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
