"""Create docket fixtures from development-split cases only (decision 0037).

Usage:
    uv run python -m scripts.make_docket_fixture listing [<case_id>]
        Fetch one dev-400 listing page (the seeded first case when no id is given) and
        commit it as received. Network; no key.

Later subcommands (Task 16): draw, document, handcheck.
"""

import argparse
import json
import random
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow.parquet as pq

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.errors import FixtureError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.splits import Split, split_of

FIXTURES = Path("tests/fixtures/docket")
SEED = 20260918


def _cases(processed: Path, ids: tuple[str, ...]) -> dict[str, tuple[int, str]]:
    """Case id to (mkey, event date) for the given ids, from cases.parquet."""
    wanted = set(ids)
    found: dict[str, tuple[int, str]] = {}
    with pq.ParquetFile(processed / "cases.parquet") as parquet_file:
        for batch in parquet_file.iter_batches(columns=["ntsb_number", "mkey", "event_date"]):
            for number, mkey, event in zip(
                batch.column("ntsb_number").to_pylist(),
                batch.column("mkey").to_pylist(),
                batch.column("event_date").to_pylist(),
                strict=True,
            ):
                if number in wanted:
                    found[str(number)] = (int(mkey), str(event))
    return found


def first_dev_400_case(processed: Path, *, seed: int = SEED) -> tuple[str, int, str]:
    """The first dev-400 case in seeded order: id, mkey, event date."""
    ids = list(samples.sample_ids("dev-400"))
    random.Random(seed).shuffle(ids)  # noqa: S311 -- reproducible draw, not security
    cases = _cases(processed, tuple(ids[:1]))
    mkey, event = cases[ids[0]]
    return ids[0], mkey, event


def write_listing_fixture(  # noqa: PLR0913, PLR0917 -- one argument per manifest field.
    case_id: str,
    mkey: int,
    event_date: str,
    html: str,
    fetched_at: str,
    criterion: str,
    *,
    root: Path = FIXTURES,
) -> Path:
    """Write the listing page as received and a manifest; refuse anything outside development."""
    if split_of(date.fromisoformat(event_date)) is not Split.DEV:
        raise FixtureError(f"{case_id}: event date {event_date} is not in the development split")
    folder = root / case_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "listing.html").write_text(html)
    manifest = {
        "fixture": {
            "source": f"https://data.ntsb.gov/Docket?ProjectID={mkey}",
            "fetched_at": fetched_at,
            "case_id": case_id,
            "mkey": mkey,
            "event_date": event_date,
            "criterion": criterion,
        },
        "documents": [],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return folder


def _cmd_listing(args: argparse.Namespace, settings: Settings) -> int:
    processed = settings.data_dir / "processed"
    if args.case_id:
        cases = _cases(processed, (args.case_id,))
        if args.case_id not in samples.sample_ids("dev-400") or args.case_id not in cases:
            raise FixtureError(f"{args.case_id}: not a dev-400 case")
        case_id, (mkey, event) = args.case_id, cases[args.case_id]
    else:
        case_id, mkey, event = first_dev_400_case(processed)
    with DocketClient(
        settings.docket_dir, seconds_per_request=settings.docket_seconds_per_request
    ) as client:
        html = client.listing_html(mkey)
    folder = write_listing_fixture(
        case_id, mkey, event, html, datetime.now(UTC).isoformat(), args.criterion
    )
    print(f"wrote {folder}")
    return 0


def main(argv: list[str]) -> int:
    """Dispatch one subcommand."""
    parser = argparse.ArgumentParser(prog="make_docket_fixture")
    commands = parser.add_subparsers(dest="command", required=True)
    listing_p = commands.add_parser("listing")
    listing_p.add_argument("case_id", nargs="?")
    listing_p.add_argument("--criterion", default="first draw")
    args = parser.parse_args(argv)
    settings = Settings()
    try:
        if args.command == "listing":
            return _cmd_listing(args, settings)
    except FixtureError as error:
        print(f"{args.command}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
