"""``ntsb-ingest``: fetch raw pages (and, from Task 12, build the processed file)."""

import argparse
import logging
from collections.abc import Sequence

from ntsb_probable_cause.data.api import NtsbClient
from ntsb_probable_cause.data.ingest import fetch_months, months_between
from ntsb_probable_cause.settings import Settings


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and run one ingestion command."""
    parser = argparse.ArgumentParser(prog="ntsb-ingest")
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="fetch event months into data/raw/v2")
    fetch.add_argument("first", help="first month, YYYY-MM")
    fetch.add_argument("last", help="last month, YYYY-MM")
    fetch.add_argument(
        "--refresh", action="store_true", help="refetch months already in the manifest"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings()
    raw_dir = settings.data_dir / "raw"
    with NtsbClient(
        settings.require_api_key(), requests_per_minute=settings.requests_per_minute
    ) as client:
        written = fetch_months(
            client, months_between(args.first, args.last), raw_dir, refresh=args.refresh
        )
    records = sum(e.records for e in written)
    print(f"fetched {len(written)} months, {records} records -> {raw_dir / 'v2'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
