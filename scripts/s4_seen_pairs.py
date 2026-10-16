"""Write the development split's primary occurrence codes as a committed table.

Status
    Run once in S4 (Task 6). Free; development split; codes only.
    The live night runs in a container that holds no ``cases.parquet``; ``pair_unseen`` needs the
    set of primary occurrence codes the development split holds. This script writes that set,
    sorted, to ``scoring/tables/seen_pairs_dev.json`` through the existing ``seen_pairs``. The
    table holds codes only: no case number, no text. It changes no score.

Usage
    uv run --locked python -m scripts.s4_seen_pairs [--out PATH]
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.settings import Settings

TABLE: Final = Path(samples.__file__).parent / "tables" / samples.SEEN_PAIRS_FILE


def write_table(processed: Path, out: Path) -> int:
    """Write the table from the processed folder to ``out``; return how many codes it holds."""
    codes = sorted(samples.seen_pairs(processed))
    out.write_text(
        json.dumps({"format": "seen-pairs/1", "split": "dev", "codes": codes}, indent=1) + "\n"
    )
    return len(codes)


def main(argv: Sequence[str] | None = None) -> int:
    """Write the table; print the number of codes."""
    parser = argparse.ArgumentParser(prog="s4_seen_pairs", description=__doc__)
    parser.add_argument("--out", type=Path, default=TABLE)
    args = parser.parse_args(argv)
    count = write_table(Settings().data_dir / "processed", args.out)
    print(f"{count} primary occurrence codes written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
