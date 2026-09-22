"""Listing pages of ongoing cases: what the site returns before closure, numbers only (spec §10.1).

Status
    One-shot (S2.5). Produces ``docs/results/s25-ongoing-dockets.txt``. Fixes the ``no-docket``
    outcome of the recorder (spec §6.2) from what the site actually returns for a case with no
    public docket. Nothing is cached, no case number is printed (decision 0024).

Usage:
    uv run python -m scripts.ongoing_docket_probe [--n 100] [--seed 2026] \
        [--out docs/results/s25-ongoing-dockets.txt]

Population (controller resolution, Task 3 §1): the recorder will watch aviation cases with
``completionStatus == "Ongoing"`` (exact equality, never ``!= "Completed"``) whose regulation
is Part 91 or not yet recorded -- so this probe draws from that same population, not every
ongoing aviation case, since it exists to fix an outcome rule for the recorder's own polls.

Read and discard: ``DocketClient(None, ...)`` never writes a cache. The drawn mkeys are used
only to fetch and are never printed or saved (decision 0024).
"""

import argparse
import math
import random
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from ntsb_probable_cause.data.ingest import iter_raw_records, latest_entries, read_manifest
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.listing import parse_listing
from ntsb_probable_cause.errors import DocketError
from ntsb_probable_cause.paths import resolve_path
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.splits import GA_REGULATION

STRATA: tuple[tuple[str, int, int], ...] = (
    ("0-30", 0, 30),
    ("31-90", 31, 90),
    ("91-180", 91, 180),
    ("181+", 181, 10**6),
)
ONGOING = "Ongoing"
# The record field's own value -- sources.MODE_AVIATION is the lowercase API query param, not this.
_AVIATION_MODE = "Aviation"
_HTTP_STATUS = re.compile(r"returned (\d+)$")
_REGULATION_PATH = "aircrafts[0].ownerOperators[0].regulationFlightConductedUnder"


def stratify(days: int) -> str:
    """The stratum name for ``days`` since the event."""
    return next(name for name, lo, hi in STRATA if lo <= days <= hi)


def classify_page(page: str, mkey: int) -> str:
    """``"read"``, ``"empty"``, ``"no-info-block"`` or ``"count-mismatch"`` for a fetched page."""
    try:
        listing = parse_listing(page, mkey=mkey)
    except DocketError:
        return "count-mismatch"
    if listing.info is None:
        return "no-info-block"
    return "empty" if not listing.entries else "read"


def outcome_for_error(message: str) -> str:
    """``"http-<status>"`` when the client's ``DocketError`` message names one HTTP status.

    ``DocketClient._get`` raises with ``f"{url} returned {status}"`` for a non-retried status
    (a 404 for a case with no docket, most likely) and with ``f"{url} failed after {n}
    attempts; last status {status}"`` once every retry is exhausted, where ``status`` may be a
    transport exception's class name rather than a number. Only the first form names a clean
    HTTP status; anything else -- including an exhausted-retries message -- is ``"fetch-failed"``.
    """
    match = _HTTP_STATUS.search(message)
    return f"http-{match.group(1)}" if match else "fetch-failed"


def ongoing_records(raw_dir: Path) -> Iterator[dict[str, object]]:
    """Every aviation record with completionStatus Ongoing, newest fetch wins per mkey."""
    newest: dict[int, tuple[datetime, dict[str, object]]] = {}
    for entry, record in iter_raw_records(raw_dir):
        if record.get("mode") != _AVIATION_MODE or record.get("completionStatus") != ONGOING:
            continue
        mkey = record.get("mKey")
        if not isinstance(mkey, int):
            continue
        if mkey not in newest or entry.fetched_at > newest[mkey][0]:
            newest[mkey] = (entry.fetched_at, record)
    yield from (record for _, record in newest.values())


def has_open_date_set(raw_dir: Path) -> dict[int, bool]:
    """Per ongoing case's own record, whether ``docketOpenDate`` is a non-empty string.

    Controller resolution 2 (Task 3): ``docketOpenDate`` is a field on every record and may
    predict the ``no-docket`` outcome, so the probe cross-tabs its outcomes by this flag for
    the cases it actually draws. Read over the same ``ongoing_records`` every drawn mkey comes
    from, keyed by mkey so ``main`` can look up only the cases it drew.
    """
    result: dict[int, bool] = {}
    for record in ongoing_records(raw_dir):
        mkey = record.get("mKey")
        if not isinstance(mkey, int):
            continue
        value = record.get("docketOpenDate")
        result[mkey] = isinstance(value, str) and bool(value.strip())
    return result


def _in_population(record: Mapping[str, object]) -> bool:
    """Part 91, or a regulation not yet recorded -- the population the recorder will watch."""
    regulation = resolve_path(record, _REGULATION_PATH)
    return regulation in (None, "", GA_REGULATION)


def _population(raw_dir: Path, today: date) -> dict[str, list[tuple[int, int]]]:
    """Eligible ongoing cases as ``(mkey, days_since_event)``, bucketed by day-stratum."""
    buckets: dict[str, list[tuple[int, int]]] = {name: [] for name, _, _ in STRATA}
    for record in ongoing_records(raw_dir):
        if not _in_population(record):
            continue
        mkey = record.get("mKey")
        if not isinstance(mkey, int):
            continue
        try:
            event_date = date.fromisoformat(str(record.get("eventDate"))[:10])
        except ValueError:
            continue
        days = (today - event_date).days
        if days < 0:
            continue
        buckets[stratify(days)].append((mkey, days))
    return buckets


def population_sizes(raw_dir: Path, today: date) -> dict[str, int]:
    """How many eligible ongoing cases exist per day-stratum -- what ``draw`` samples from."""
    return {name: len(members) for name, members in _population(raw_dir, today).items()}


def draw(raw_dir: Path, n: int, seed: int, today: date) -> list[tuple[int, int]]:
    """``n`` (mkey, days_since_event) pairs, split as evenly as possible across ``STRATA``."""
    buckets = _population(raw_dir, today)
    rng = random.Random(seed)  # noqa: S311 -- reproducible draw, not security
    names = [name for name, _, _ in STRATA]
    base, extra = divmod(n, len(names))
    shares = {name: base + (1 if i < extra else 0) for i, name in enumerate(names)}
    drawn: list[tuple[int, int]] = []
    for name in names:
        members = sorted(buckets[name])
        drawn.extend(rng.sample(members, min(shares[name], len(members))))
    return drawn


def _percentiles(values: Sequence[int]) -> dict[float, float]:
    """Nearest-rank p25/p50/p75/max; empty input gives an empty dict."""
    if not values:
        return {}
    ordered = sorted(values)
    n = len(ordered)
    return {q: ordered[min(n - 1, max(0, math.ceil(q * n) - 1))] for q in (0.25, 0.5, 0.75, 1.0)}


def report(  # noqa: PLR0913 -- the brief's Interfaces block fixes report()'s fields.
    *,
    outcomes: Mapping[str, int],
    doc_counts: Sequence[int],
    by_stratum: Mapping[str, Mapping[str, int]],
    attempted: int,
    creation_date_present: int = 0,
    seed: int | None = None,
    by_open_date: Mapping[bool, Mapping[str, int]] | None = None,
) -> str:
    """Counts-only report: outcome mix, document-count percentiles, seed. Nothing per-case.

    Outcome mix is broken down overall, by day-stratum, and (when given) by whether the
    case's own record carried a non-empty ``docketOpenDate``. Never printed: a case number,
    an mkey, a title, or any other per-case text (decision 0024).
    """
    lines = [
        "Ongoing-docket probe (scripts/ongoing_docket_probe.py; spec S2.5 §10.1)",
        "",
        f"cases attempted: {attempted}",
        "",
        "outcomes (overall):",
    ]
    lines.extend(f"  {name}: {outcomes[name]}" for name in sorted(outcomes))
    lines.append("")
    lines.append("outcomes by stratum:")
    for name, _, _ in STRATA:
        counts = by_stratum.get(name, {})
        if not counts:
            continue
        lines.append(f"  {name}:")
        lines.extend(f"    {outcome}: {counts[outcome]}" for outcome in sorted(counts))
    if by_open_date:
        lines.append("")
        lines.append("outcomes by docketOpenDate presence:")
        for known, label in ((True, "set"), (False, "not set")):
            counts = by_open_date.get(known, {})
            if not counts:
                continue
            lines.append(f"  docketOpenDate {label}:")
            lines.extend(f"    {outcome}: {counts[outcome]}" for outcome in sorted(counts))
    lines.append("")
    lines.append(f"read pages: {outcomes.get('read', 0)}")
    percentiles = _percentiles(doc_counts)
    if percentiles:
        lines.append(
            "document counts (read pages): "
            f"p25={percentiles[0.25]:.0f} p50={percentiles[0.5]:.0f} "
            f"p75={percentiles[0.75]:.0f} max={percentiles[1.0]:.0f}"
        )
    lines.append(f"read pages with a creation date: {creation_date_present}")
    if seed is not None:
        lines.append("")
        lines.append(f"seed: {seed}")
    return "\n".join(lines)


def main(argv: Sequence[str]) -> int:
    """Draw the sample, fetch each listing once with no cache, print and optionally write."""
    parser = argparse.ArgumentParser(prog="ongoing_docket_probe")
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    settings = Settings()
    raw_dir = settings.data_dir / "raw"
    today = datetime.now(UTC).date()

    drawn = draw(raw_dir, args.n, args.seed, today)
    sizes = population_sizes(raw_dir, today)
    open_date_set = has_open_date_set(raw_dir)
    fetch_dates = [e.fetched_at.date() for e in latest_entries(read_manifest(raw_dir)).values()]

    outcomes: Counter[str] = Counter()
    by_stratum: dict[str, Counter[str]] = defaultdict(Counter)
    by_open_date: dict[bool, Counter[str]] = defaultdict(Counter)
    doc_counts: list[int] = []
    creation_present = 0
    attempted = 0
    with DocketClient(None, seconds_per_request=settings.docket_seconds_per_request) as client:
        for position, (mkey, days) in enumerate(drawn, start=1):
            stratum = stratify(days)
            attempted += 1
            try:
                page = client.listing_html(mkey)
            except DocketError as error:
                outcome = outcome_for_error(str(error))
            else:
                outcome = classify_page(page, mkey)
                if outcome == "read":
                    listing = parse_listing(page, mkey=mkey)
                    doc_counts.append(len(listing.entries))
                    if listing.info is not None and listing.info.creation_date is not None:
                        creation_present += 1
            outcomes[outcome] += 1
            by_stratum[stratum][outcome] += 1
            by_open_date[open_date_set.get(mkey, False)][outcome] += 1
            print(f"{position}/{len(drawn)}: {outcome}", file=sys.stderr)

    text = report(
        outcomes=outcomes,
        doc_counts=doc_counts,
        by_stratum=by_stratum,
        by_open_date=by_open_date,
        attempted=attempted,
        creation_date_present=creation_present,
        seed=args.seed,
    )
    drawn_counts = Counter(stratify(days) for _, days in drawn)
    text += "\n\n" + "\n".join(
        f"drew {drawn_counts[name]} of {sizes[name]} {name}-day ongoing cases in the population"
        for name, _, _ in STRATA
    )
    if fetch_dates:
        text += (
            f"\n\nraw store fetched as of {max(fetch_dates).isoformat()}: case statuses above "
            "are as of that date, not today's; a case may have closed since."
        )
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
