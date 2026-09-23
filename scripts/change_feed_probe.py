"""The change feed's shape, saved as a committed fixture (spec S2.5 §5.3, decision 0065).

Status
    One-shot. Re-establishes the ad-hoc probe the design session ran and discarded (spec §5.3,
    Task 11 controller note "rule 2"). Produces two files: ``tests/fixtures/api/
    change_feed_shape.json`` (the key list and, per key, the sorted set of value type names --
    never values) and ``docs/results/s25-change-feed.txt`` (counts only: row count, the key
    set with its types, ``mode`` counts and ``completionStatus`` counts, if that field is
    present -- category names, not case data, so printing them does not violate decision 0024).
    Once the fixture is committed, ``tests/test_api.py::
    test_cases_modified_parses_the_confirmed_live_shape`` stops skipping and checks
    ``NtsbClient.cases_modified`` against a synthetic row built from the real shape.

Usage:
    uv run python -m scripts.change_feed_probe [--days 7] \
        [--out docs/results/s25-change-feed.txt] \
        [--fixture tests/fixtures/api/change_feed_shape.json]

Read and discard: the fetched rows are held only long enough to compute their shape and two
category counts; no mkey, ntsbNumber, eventDate or other per-case value is ever printed or
saved (decision 0024).
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ntsb_probable_cause.data.api import NtsbClient
from ntsb_probable_cause.settings import Settings

DEFAULT_DAYS = 7
DEFAULT_FIXTURE = Path("tests/fixtures/api/change_feed_shape.json")


def shape_of(rows: Sequence[Mapping[str, object]]) -> dict[str, list[str]]:
    """Every key seen across ``rows``, mapped to the sorted set of its value type names.

    Pure and holds no value from ``rows`` -- only key names (category names, like column
    headers, not case data) and Python type names (``"int"``, ``"str"``, ``"NoneType"``, ...).
    A key missing from some rows simply contributes no type name for those rows; it is not
    recorded as "missing" separately, since every key seen across the whole response is what
    the committed fixture -- and the ``test_api.py`` assertion that reads it -- need.
    """
    shapes: dict[str, set[str]] = {}
    for row in rows:
        for key, value in row.items():
            shapes.setdefault(key, set()).add(type(value).__name__)
    return {key: sorted(types) for key, types in shapes.items()}


def report(
    *,
    shape: Mapping[str, Sequence[str]],
    mode_counts: Mapping[str, int],
    status_counts: Mapping[str, int],
    row_count: int,
) -> str:
    """Counts-only report: row count, the key/type shape, mode and status counts.

    ``mode``/``completionStatus`` values are category names (e.g. ``"Aviation"``,
    ``"Ongoing"``), not case data, so counting them does not violate decision 0024 -- the same
    reasoning ``docket_scan.py`` and ``ongoing_docket_probe.py`` apply to outcome and stratum
    labels.
    """
    lines = [
        "Change-feed probe (scripts/change_feed_probe.py; spec S2.5 §5.3, decision 0065)",
        "",
        f"row count: {row_count}",
        f"keys: {len(shape)}",
        "",
        "key types:",
    ]
    lines.extend(f"  {key}: {', '.join(shape[key])}" for key in sorted(shape))
    lines.append("")
    lines.append("mode counts:")
    if mode_counts:
        lines.extend(f"  {mode}: {mode_counts[mode]}" for mode in sorted(mode_counts))
    else:
        lines.append("  no data")
    lines.append("")
    lines.append("completionStatus counts (if the feed carries the field):")
    if status_counts:
        lines.extend(f"  {status}: {status_counts[status]}" for status in sorted(status_counts))
    else:
        lines.append("  no data")
    return "\n".join(lines)


def main(argv: Sequence[str]) -> int:
    """Fetch the feed once, print and save the counts-only report, save the shape fixture."""
    parser = argparse.ArgumentParser(prog="change_feed_probe")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--out", default=None)
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    args = parser.parse_args(argv)

    settings = Settings()
    api_key = settings.require_api_key()
    today = datetime.now(UTC).date()
    start = today - timedelta(days=args.days)

    with NtsbClient(api_key, requests_per_minute=settings.requests_per_minute) as client:
        rows = client.cases_modified(start, today)

    shape = shape_of(rows)
    mode_counts = Counter(str(row.get("mode")) for row in rows)
    status_counts = Counter(
        str(row.get("completionStatus")) for row in rows if "completionStatus" in row
    )

    text = report(
        shape=shape, mode_counts=mode_counts, status_counts=status_counts, row_count=len(rows)
    )
    print(text)

    fixture_path = Path(args.fixture)
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(json.dumps(shape, indent=2, sort_keys=True) + "\n")

    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
