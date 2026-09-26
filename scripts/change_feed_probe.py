"""The change feed's shape, saved as a committed fixture (spec S2.5 §5.3, decision 0065).

Status
    One-shot. Re-establishes the ad-hoc probe the design session ran and discarded (spec §5.3,
    Task 11 controller note "rule 2"). Produces two files: ``tests/fixtures/api/
    change_feed_shape.json`` (``{"shape": {key: [sorted type names]}, "last_change_utc_
    signatures": [masked format signatures]}`` -- never a value) and ``docs/results/
    s25-change-feed.txt`` (counts only: row count, the key/type shape, ``mode``, ``caseClosed``
    and ``stepId`` counts, and the ``lastChangeDateTimeUtc`` format signature(s) -- category
    names and a digit-masked format string, not case data, so printing them does not violate
    decision 0024). Once the fixture is committed, ``tests/test_api.py::
    test_cases_modified_parses_the_confirmed_live_shape`` stops skipping and checks both
    ``NtsbClient.cases_modified`` and ``recorder.run._feed_rows`` against a synthetic row built
    from the real shape. Refuses to write the fixture from an empty response.

    Fix round 1 (Task 11, 2026-09-23): CRITICAL 1 added the format-signature recording (a
    masked ``lastChangeDateTimeUtc`` shape, confirming its format without printing a value);
    IMPORTANT 8 replaced the guessed ``completionStatus`` count with the two keys the feed is
    actually confirmed to carry, ``caseClosed`` and ``stepId``, and added the empty-response
    refusal.

Usage:
    uv run python -m scripts.change_feed_probe [--days 7] \
        [--out docs/results/s25-change-feed.txt] \
        [--fixture tests/fixtures/api/change_feed_shape.json]

Read and discard: the fetched rows are held only long enough to compute their shape, a masked
timestamp-format signature, and three category counts; no mkey, ntsbNumber, eventDate or other
per-case value is ever printed or saved (decision 0024).
"""

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ntsb_probable_cause.data.api import NtsbClient
from ntsb_probable_cause.settings import Settings

DEFAULT_DAYS = 7
DEFAULT_FIXTURE = Path("tests/fixtures/api/change_feed_shape.json")

_DIGIT = re.compile(r"\d")
_TIMESTAMP_KEY = "lastChangeDateTimeUtc"


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


def format_signature(text: str) -> str:
    """``text`` with every digit replaced by ``d`` -- confirms a format, never a value.

    E.g. ``"2026-09-22T14:03:00.123"`` -> ``"dddd-dd-ddTdd:dd:dd.ddd"``. Task 11 fix round 1,
    CRITICAL 1: this is how the probe records ``lastChangeDateTimeUtc``'s real shape (whether
    it carries a zone offset, fractional seconds, ...) without ever writing the value itself
    into the fixture or the printed report (decision 0024).
    """
    return _DIGIT.sub("d", text)


def feed_timestamp_signatures(rows: Sequence[Mapping[str, object]]) -> list[str]:
    """Every distinct :func:`format_signature` seen on ``lastChangeDateTimeUtc``, sorted.

    Skips a row where the key is missing or not a string -- those are already visible in
    :func:`shape_of`'s own type list for the key.
    """
    signatures = set()
    for row in rows:
        value = row.get(_TIMESTAMP_KEY)
        if isinstance(value, str):
            signatures.add(format_signature(value))
    return sorted(signatures)


def report(  # noqa: PLR0913 -- one counts-only value per what the probe measures; see its Status block.
    *,
    shape: Mapping[str, Sequence[str]],
    mode_counts: Mapping[str, int],
    case_closed_counts: Mapping[str, int],
    step_id_counts: Mapping[str, int],
    timestamp_signatures: Sequence[str],
    row_count: int,
    fixture_written: bool,
) -> str:
    """Counts-only report: row count, the key/type shape, category counts, format signature(s).

    ``mode``/``caseClosed``/``stepId`` values are category names (e.g. ``"Aviation"``,
    ``"True"``, ``"S3"``), not case data, so counting them does not violate decision 0024 -- the
    same reasoning ``docket_scan.py`` and ``ongoing_docket_probe.py`` apply to outcome and
    stratum labels. ``timestamp_signatures`` are digit-masked format strings, not values.
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
    lines.append(f"{_TIMESTAMP_KEY} format signature(s) (digits masked as 'd'):")
    if timestamp_signatures:
        lines.extend(f"  {signature}" for signature in timestamp_signatures)
    else:
        lines.append("  no data")
    lines.append("")
    lines.append("mode counts:")
    if mode_counts:
        lines.extend(f"  {mode}: {mode_counts[mode]}" for mode in sorted(mode_counts))
    else:
        lines.append("  no data")
    lines.append("")
    lines.append("caseClosed counts:")
    if case_closed_counts:
        lines.extend(
            f"  {value}: {case_closed_counts[value]}" for value in sorted(case_closed_counts)
        )
    else:
        lines.append("  no data")
    lines.append("")
    lines.append("stepId counts:")
    if step_id_counts:
        lines.extend(f"  {value}: {step_id_counts[value]}" for value in sorted(step_id_counts))
    else:
        lines.append("  no data")
    lines.append("")
    lines.append(
        f"fixture written: {fixture_written}"
        + ("" if fixture_written else " (refused -- the response held no rows)")
    )
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
    case_closed_counts = Counter(str(row.get("caseClosed")) for row in rows if "caseClosed" in row)
    step_id_counts = Counter(str(row.get("stepId")) for row in rows if "stepId" in row)
    timestamp_signatures = feed_timestamp_signatures(rows)

    # IMPORTANT 8: never write a fixture from an empty response -- it would record "no keys at
    # all" as if that were the feed's real shape.
    fixture_written = bool(rows)
    text = report(
        shape=shape,
        mode_counts=mode_counts,
        case_closed_counts=case_closed_counts,
        step_id_counts=step_id_counts,
        timestamp_signatures=timestamp_signatures,
        row_count=len(rows),
        fixture_written=fixture_written,
    )
    print(text)

    if fixture_written:
        fixture_path = Path(args.fixture)
        fixture_path.parent.mkdir(parents=True, exist_ok=True)
        fixture_path.write_text(
            json.dumps(
                {"shape": shape, "last_change_utc_signatures": timestamp_signatures},
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
