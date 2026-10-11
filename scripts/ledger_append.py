"""Append the live bucket's new manifest hashes to the ledger (decision 0178).

Status
    Live tooling, run by ``.github/workflows/ledger.yml`` only.

Why
    The ledger makes a rewritten run or night manifest visible in public: the job publishes
    each manifest's SHA-256, never its contents. It lists ``runs/`` and ``nights/`` (every page
    of the listing), downloads only keys ending ``/manifest.json``, appends
    ``ntsb_probable_cause.live.ledger.new_lines`` to the ledger file, and prints
    ``appended: N`` and nothing else. The role it signs in with may list those two prefixes and
    read the two manifest patterns, so it needs nothing more. A ledger line holds the key
    (``runs/<run id>/manifest.json``, whose run id is a timestamp, commit and sample, never a
    case number) and the hash.

Usage
    uv run --locked --extra aws python -m scripts.ledger_append --bucket NAME --ledger PATH
"""

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ntsb_probable_cause.live.ledger import new_lines, read_ledger, render_line

PREFIXES = ("runs/", "nights/")
MANIFEST_SUFFIX = "/manifest.json"


def _client() -> Any:
    import boto3  # noqa: PLC0415 -- the optional `aws` extra, imported only when run

    return boto3.client("s3")


def manifests_from(s3: Any, bucket: str) -> dict[str, bytes]:
    """Every ``runs/`` and ``nights/`` manifest in the bucket, by key, from every page."""
    found: dict[str, bytes] = {}
    for prefix in PREFIXES:
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                key = str(item["Key"])
                if key.endswith(MANIFEST_SUFFIX):
                    found[key] = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return found


def append(s3: Any, bucket: str, ledger: Path, now: datetime) -> int:
    """Append the new lines to ``ledger``; return how many."""
    lines = new_lines(read_ledger(ledger), manifests_from(s3, bucket), now)
    if lines:
        with ledger.open("a") as handle:
            handle.writelines(render_line(line) for line in lines)
    return len(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the append; print the count only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--ledger", required=True, type=Path)
    args = parser.parse_args(argv)
    count = append(_client(), args.bucket, args.ledger, datetime.now(UTC))
    print(f"appended: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
