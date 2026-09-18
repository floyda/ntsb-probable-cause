"""Docket shape on closed open-split cases, 40 per stratum, numbers only (decision 0040).

Usage:
    uv run python -m scripts.docket_shape_open [--per-stratum 40] \
        [--out docs/results/s2-shape-open.txt]

Read and discard: the client has no cache, nothing is written under data/, and no case number
is printed. The seed and the rule are here; the drawn list is not (0024).

Fix round 1 (spec-compliance review), finding 4: ``report()``'s "cases attempted / listing
fetch failed / skipped for missing mKey" denominator (added to ``docket_scan.py`` so a reader
can tell a complete run from a partial one) was never filled here -- ``main`` now calls
``record_attempt`` and ``record_listing_failed`` on the matching paths, as ``docket_scan.main``
does. There is no missing-mKey path in this script: ``draw`` already resolves every case to an
``int`` mkey before ``main``'s loop ever runs.
"""

import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.manifest import read_docket
from ntsb_probable_cause.errors import DocketError
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.splits import COMPLETED_STATUS, OPEN_MIN_YEAR
from scripts.docket_scan import (
    ShapeState,
    accumulate,
    record_attempt,
    record_listing_failed,
    report,
)

SEED = 20260918
PER_STRATUM = 40


def draw(
    processed: Path, *, per_stratum: int = PER_STRATUM, seed: int = SEED
) -> list[tuple[int, bool]]:
    """(mkey, fatal) for up to ``per_stratum`` closed open-split cases per fatal stratum."""
    columns = ["mkey", "event_date", "completion_status", "raw_json"]
    table = pq.read_table(processed / "cases.parquet", columns=columns)
    pool: dict[bool, list[int]] = {True: [], False: []}
    for mkey, event, status, raw_json in zip(*(table[c].to_pylist() for c in columns), strict=True):
        event_date = event if isinstance(event, date) else date.fromisoformat(str(event)[:10])
        if status != COMPLETED_STATUS or event_date.year < OPEN_MIN_YEAR:
            continue
        pool[json.loads(raw_json)["highestInjuryLevel"] == "Fatal"].append(int(mkey))
    rng = random.Random(seed)  # noqa: S311 -- reproducible draw, not security
    drawn: list[tuple[int, bool]] = []
    for fatal in (True, False):
        members = sorted(pool[fatal])
        drawn.extend((m, fatal) for m in rng.sample(members, min(per_stratum, len(members))))
    return drawn


def main(argv: list[str]) -> int:
    """Draw, stream every docket through the parser and extractor, print the numbers."""
    parser = argparse.ArgumentParser(prog="docket_shape_open")
    parser.add_argument("--per-stratum", type=int, default=PER_STRATUM)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    settings = Settings()
    drawn = draw(settings.data_dir / "processed", per_stratum=args.per_stratum)
    state = ShapeState()
    with DocketClient(None, seconds_per_request=settings.docket_seconds_per_request) as client:
        for position, (mkey, fatal) in enumerate(drawn, start=1):
            # Fix round 1, finding 4: record_attempt/record_listing_failed, the same pair
            # docket_scan.main calls, so this script's own "cases attempted" denominator
            # (report(), inherited from ShapeState) is not left silently at zero -- there is
            # no missing-mKey path here, since draw() already resolved every mkey to an int.
            record_attempt(state, fatal=fatal)
            try:
                docket = read_docket(client, mkey)
            except DocketError as error:
                record_listing_failed(state, fatal=fatal)
                print(
                    f"{position}/{len(drawn)}: listing failed ({type(error).__name__})",
                    file=sys.stderr,
                )
                continue
            accumulate(state, docket, fatal=fatal, raw={})
            print(f"{position}/{len(drawn)}: {len(docket.documents)} documents", file=sys.stderr)
    text = report(state).replace(
        "S2 development docket shape (scripts/docket_scan.py)",
        "S2 open-split docket shape (scripts/docket_shape_open.py; decision 0040)",
    )
    text += (
        "\n\nThe 111 closed fatal open-split cases (docs/results/s0-corpus-scan.txt) are a small "
        "population and a draw of 40 covers over a third of it; these figures describe that "
        "population, not cases still open."
    )
    text += (
        "\n\nName and amateur-built figures above are zero by construction: this script calls "
        "accumulate() with an empty record (raw={}) for every case, so no per-case field is read "
        "and neither owner/operator names nor the amateur-built flag are looked up here (0024)."
    )
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
