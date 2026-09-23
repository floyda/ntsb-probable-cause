"""The recorder's counts-only report, read from the store (spec S2.5 §10.2, Task 11).

Status
    Repeatable. Produces ``docs/results/s25-recorder-report.txt``. Its numbers become the
    stage's As-built record, and the 8-week comparisons in spec §10.2, once ``runs`` holds 14
    or more nights (spec "Done means" §14, item 2) -- run before that, it still prints, but its
    output is not yet citable. Prints, counts only (decision 0024; never a case number, an
    mkey, a title or any other per-case text): the per-night run summaries; arrival percentiles
    (days from event to first appearance) per evidence field and for the docket; the
    change-feed comparison; regulation changes; the 30-day closure tail; suspected
    re-numbers; a possible-false-"not returned" count; and compressed listing-page sizes.

Usage:
    uv run python -m scripts.recorder_report [--out docs/results/s25-recorder-report.txt] \
        [--feed-window-days 1]

Reads ``NTSB_STORE`` (a local path or an ``s3://bucket/key`` URL, exactly as the recorder
itself does -- ``store/sync.py``): an S3 location is pulled read-only to a local working file
under ``NTSB_DATA_DIR`` and never pushed back.
"""

import argparse
import math
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.store import RunSummaryRow, Store
from ntsb_probable_cause.store.sync import Location, pull

_PERCENTILES: tuple[float, ...] = (0.25, 0.5, 0.75, 0.9)
_REPORT_WORK_FILENAME = "recorder-report-work.sqlite"


def _percentiles(values: Sequence[int], qs: Sequence[float] = _PERCENTILES) -> dict[float, float]:
    """Nearest-rank percentiles; empty input gives an empty dict (rule 8: "no data" upstream)."""
    if not values:
        return {}
    ordered = sorted(values)
    n = len(ordered)
    return {q: ordered[min(n - 1, max(0, math.ceil(q * n) - 1))] for q in qs}


def _format_days(values: Sequence[int]) -> str:
    """``n=... p25=... p50=... p75=... p90=...``, or ``no data`` for an empty sequence."""
    percentiles = _percentiles(values)
    if not percentiles:
        return "no data"
    return (
        f"n={len(values)} p25={percentiles[0.25]:.0f} p50={percentiles[0.5]:.0f} "
        f"p75={percentiles[0.75]:.0f} p90={percentiles[0.9]:.0f}"
    )


def _fmt_int(value: int | None) -> str:
    return "-" if value is None else str(value)


def _fmt_minutes(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}"


def report(  # noqa: PLR0913 -- one counts-only value per spec §10.2 bullet; see Task 11's brief.
    *,
    run_rows: Sequence[RunSummaryRow],
    field_arrivals: Mapping[str, Sequence[int]],
    first_sight_fields: int,
    docket_arrivals: Sequence[tuple[int, int]],
    docket_first_sight: int,
    feed_comparison: tuple[int, int],
    regulation_changes: int,
    tail_arrivals: int,
    renumber_suspects: int,
    possible_false_not_returned: int,
    page_sizes: Sequence[int],
) -> str:
    """Build the report text from already-computed numbers. Pure -- no store access.

    Every argument is a number or a sequence of numbers; nothing here ever holds a case
    number, an mkey, a title or any other per-case text (decision 0024), so this function
    cannot leak one regardless of what the store contains.
    """
    lines = ["Recorder report (scripts/recorder_report.py; spec S2.5 §10.2)", ""]

    finished = [r for r in run_rows if r.finished_at is not None]
    unfinished = [r for r in run_rows if r.finished_at is None]
    lines.append(f"nights: {len(run_rows)}")
    lines.append(f"unfinished (crashed) runs: {len(unfinished)}")
    lines.append("")

    if not run_rows:
        lines.append("run summaries: no data")
    else:
        lines.append("run summaries (most recent first):")
        lines.append(
            "  run_id  started_at             status      polled changed new_docs failed "
            "suspects minutes"
        )
        for r in run_rows:
            status = "ok" if r.finished_at is not None else "UNFINISHED"
            lines.append(
                f"  {r.run_id:<7} {r.started_at:<22} {status:<11} "
                f"{_fmt_int(r.cases_polled):>6} {_fmt_int(r.cases_changed):>7} "
                f"{_fmt_int(r.new_documents):>8} {_fmt_int(r.failures):>6} "
                f"{_fmt_int(r.suspected_renumbers):>8} {_fmt_minutes(r.minutes):>7}"
            )
        lines.append("")
        lines.append(
            "totals over finished runs (rule: unfinished runs' rows are real observations but "
            "excluded from these sums): "
            f"cases_polled={sum(r.cases_polled or 0 for r in finished)} "
            f"cases_changed={sum(r.cases_changed or 0 for r in finished)} "
            f"new_documents={sum(r.new_documents or 0 for r in finished)} "
            f"failures={sum(r.failures or 0 for r in finished)} "
            f"minutes={sum(r.minutes or 0.0 for r in finished):.0f}"
        )
    lines.append("")

    lines.append(
        "arrival percentiles, days from event to first appearance (present-side only, an "
        "upper bound -- the absent side is also on record):"
    )
    if not field_arrivals:
        lines.append("  no data")
    else:
        for role in sorted(field_arrivals):
            lines.append(f"  {role}: {_format_days(field_arrivals[role])}")
    lines.append(
        "  first-sight fields (present by the day watching began, a lower bound, excluded "
        f"above): {first_sight_fields}"
    )
    lines.append("")

    docket_days = [days for days, _count in docket_arrivals]
    docket_counts = [count for _days, count in docket_arrivals]
    lines.append("docket arrival, days from event to the first poll with documents:")
    lines.append(f"  {_format_days(docket_days)}")
    if docket_counts:
        lines.append(f"  document count at that poll: {_format_days(docket_counts)}")
    lines.append(
        "  first-sight dockets (documents present at the first poll ever, a lower bound, "
        f"excluded above): {docket_first_sight}"
    )
    lines.append("")

    field_changes, reported = feed_comparison
    if field_changes:
        lines.append(f"feed comparison: reported {reported} of {field_changes} field changes")
    else:
        lines.append("feed comparison: no data")
    lines.append("")

    lines.append(
        f"regulation changes (current, still-open drops -- a lower bound): {regulation_changes}"
    )
    lines.append(f"tail arrivals (documents appeared strictly after closure): {tail_arrivals}")
    lines.append(f"suspected re-numbers: {renumber_suspects}")
    lines.append(f"possible false 'not returned' events: {possible_false_not_returned}")
    lines.append("")

    if not page_sizes:
        lines.append("compressed listing page sizes: no data")
    else:
        p50 = _percentiles(page_sizes, (0.5,))[0.5]
        lines.append(f"compressed listing page sizes (bytes): p50={p50:.0f} max={max(page_sizes)}")

    return "\n".join(lines)


def _open_store(settings: Settings) -> tuple[Store, Path | None]:
    """Open the store the recorder itself writes to; read-only, S3 pulled but never pushed."""
    location = Location(settings.store)
    if location.is_s3:
        local = settings.data_dir / _REPORT_WORK_FILENAME
        local.parent.mkdir(parents=True, exist_ok=True)
        pull(location, local)
        store = Store(local)
        store.migrate()
        return store, local
    local = Path(location.raw)
    store = Store(local)
    store.migrate()
    return store, None


def main(argv: Sequence[str]) -> int:
    """Read the store, compute every measure, print and optionally write the report."""
    parser = argparse.ArgumentParser(prog="recorder_report")
    parser.add_argument("--out", default=None)
    parser.add_argument("--feed-window-days", type=int, default=1)
    args = parser.parse_args(argv)

    settings = Settings()
    store, _local = _open_store(settings)
    try:
        run_rows = store.run_summaries()
        field_arrivals: dict[str, list[int]] = defaultdict(list)
        for role, days in store.field_change_arrivals():
            field_arrivals[role].append(days)
        text = report(
            run_rows=run_rows,
            field_arrivals=field_arrivals,
            first_sight_fields=store.first_sight_field_count(),
            docket_arrivals=store.docket_arrivals(),
            docket_first_sight=store.docket_first_sight_count(),
            feed_comparison=store.feed_comparison(window_days=args.feed_window_days),
            regulation_changes=store.regulation_changes(),
            tail_arrivals=store.tail_arrivals(),
            renumber_suspects=store.renumber_suspects(),
            possible_false_not_returned=store.possible_false_not_returned(),
            page_sizes=store.compressed_page_sizes(),
        )
    finally:
        store.close()

    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
