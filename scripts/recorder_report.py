"""The recorder's counts-only report, read from the store (spec S2.5 §10.2, Task 11).

Status
    Live tool. Produces ``docs/results/s25-recorder-report.txt``. Its numbers become the
    stage's As-built record, and the 8-week comparisons in spec §10.2, once ``runs`` holds 14
    or more FINISHED nights (spec "Done means" §14, item 2; a crashed run is not a night the
    recorder actually completed, so it does not count toward the threshold) -- run before
    that, it still prints, but its output is not yet citable. Prints, counts only (decision
    0024; never a case number, an mkey, a title or any other per-case text): the per-night run
    summaries; arrival percentiles (days from event to first appearance, present- and
    absent-side, nearest-rank method) per evidence field, for the preliminary narrative and for
    the docket, each split into before/same-run/after closure and cases excluded as currently
    unwatched -- only the before-closure figures are the mask distribution spec §10.2 means;
    the change-feed comparison, at both field-row and case-night granularity; regulation
    transitions (migration 2's history, replacing the previous lower-bound estimate); the
    30-day closure tail, split by same-run/after/total and reported separately for "not
    returned" cases; suspected re-numbers; a possible-false-"not returned" count; and
    compressed listing-page sizes.

    Fix round 1 (Task 11, 2026-09-23): rewrote every arrival query the report reads from
    (before/same-run/after-closure classification, the corrected feed rule, the docket
    absent-side rule, the preliminary narrative, migration 2's regulation history); see
    ``docs/plans/2026-09-22-s25-recorder.md``'s Deviations for what changed and why.

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
from collections.abc import Sequence
from pathlib import Path

from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.store import (
    ArrivalClassification,
    ArrivalRow,
    DocketArrivalRow,
    FeedComparisonResult,
    FieldArrivalRow,
    RegulationTransitions,
    RunSummaryRow,
    Store,
    TailArrivals,
)
from ntsb_probable_cause.store.sync import Location, pull

_PERCENTILES: tuple[float, ...] = (0.25, 0.5, 0.75, 0.9)
_MIN_N_FOR_PERCENTILES = 3
_REPORT_WORK_FILENAME = "recorder-report-work.sqlite"

_ArrivalRowLike = FieldArrivalRow | ArrivalRow | DocketArrivalRow


def _percentiles(values: Sequence[int], qs: Sequence[float] = _PERCENTILES) -> dict[float, float]:
    """Nearest-rank percentiles; empty input gives an empty dict (rule 8: "no data" upstream)."""
    if not values:
        return {}
    ordered = sorted(values)
    n = len(ordered)
    return {q: ordered[min(n - 1, max(0, math.ceil(q * n) - 1))] for q in qs}


def _format_days(values: Sequence[int]) -> str:
    """Nearest-rank percentile text (MINOR 2), or a floor/empty note.

    ``n<3`` suppresses percentiles below the reliable floor (MINOR 4); an empty sequence reads
    ``no data``.
    """
    if not values:
        return "no data"
    if len(values) < _MIN_N_FOR_PERCENTILES:
        return f"n={len(values)} (n<3, percentiles suppressed)"
    percentiles = _percentiles(values)
    return (
        f"n={len(values)} p25={percentiles[0.25]:.0f} p50={percentiles[0.5]:.0f} "
        f"p75={percentiles[0.75]:.0f} p90={percentiles[0.9]:.0f}"
    )


def _fmt_int(value: int | None) -> str:
    return "-" if value is None else str(value)


def _fmt_minutes(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}"


def _classification_counts(rows: Sequence[_ArrivalRowLike]) -> dict[ArrivalClassification, int]:
    counts: dict[ArrivalClassification, int] = defaultdict(int)
    for row in rows:
        counts[row.classification] += 1
    return counts


def _before_closure_days(rows: Sequence[_ArrivalRowLike]) -> tuple[list[int], list[int]]:
    """``(present_days, absent_days)`` for the before-closure rows only -- the mask population."""
    before = [r for r in rows if r.classification == ArrivalClassification.BEFORE_CLOSURE]
    return [r.days for r in before], [r.absent_days for r in before]


def _arrival_lines(label: str, rows: Sequence[_ArrivalRowLike]) -> list[str]:
    """The percentile lines plus classification breakdown for one arrival population."""
    if not rows:
        return ["  no data"]
    present_days, absent_days = _before_closure_days(rows)
    counts = _classification_counts(rows)
    return [
        f"  {label} (before closure only -- the mask population):",
        f"    present-side: {_format_days(present_days)}",
        f"    absent-side:  {_format_days(absent_days)}",
        f"  {label} classification: "
        f"before_closure={counts[ArrivalClassification.BEFORE_CLOSURE]} "
        f"same_run_as_closure={counts[ArrivalClassification.SAME_RUN_AS_CLOSURE]} "
        f"after_closure={counts[ArrivalClassification.AFTER_CLOSURE]} "
        f"excluded_unwatched={counts[ArrivalClassification.EXCLUDED_UNWATCHED]}",
    ]


def _run_summary_lines(run_rows: Sequence[RunSummaryRow]) -> list[str]:
    finished = [r for r in run_rows if r.finished_at is not None]
    unfinished = [r for r in run_rows if r.finished_at is None]
    lines = [
        f"nights: {len(run_rows)}",
        f"finished nights: {len(finished)} "
        "(the 14-night citability threshold, spec 'Done means' §14, counts these, not `nights`)",
        f"unfinished (crashed) runs: {len(unfinished)}",
        "",
    ]
    if not run_rows:
        lines.append("run summaries: no data")
        return lines
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
    return lines


def _field_lines(field_arrivals: Sequence[FieldArrivalRow], first_sight_fields: int) -> list[str]:
    lines = ["evidence-field arrival percentiles, days from event to first appearance:"]
    if not field_arrivals:
        lines.append("  no data")
    else:
        by_role: dict[str, list[FieldArrivalRow]] = defaultdict(list)
        for row in field_arrivals:
            by_role[row.role].append(row)
        for role in sorted(by_role):
            lines.extend(_arrival_lines(role, by_role[role]))
    lines.append(
        "  first-sight fields (present by the day watching began, a lower bound, excluded "
        f"above): {first_sight_fields}"
    )
    return lines


def _prelim_lines(prelim_arrivals: Sequence[ArrivalRow], prelim_first_sight: int) -> list[str]:
    lines = ["preliminary narrative arrival:"]
    lines.extend(_arrival_lines("prelim_narrative", prelim_arrivals))
    lines.append(
        "  first-sight prelim narratives (present by the day watching began, excluded above): "
        f"{prelim_first_sight}"
    )
    return lines


def _docket_lines(
    docket_arrivals: Sequence[DocketArrivalRow],
    docket_first_sight: int,
    docket_absent_side_unknown: int,
) -> list[str]:
    lines = ["docket arrival, days from event to the first poll with documents:"]
    lines.extend(_arrival_lines("docket", docket_arrivals))
    if docket_arrivals:
        before = [
            r for r in docket_arrivals if r.classification == ArrivalClassification.BEFORE_CLOSURE
        ]
        lines.append(
            "  document count at that poll (before closure): "
            f"{_format_days([r.document_count for r in before])}"
        )
    lines.append(
        "  first-sight dockets (documents present at the first poll ever, a lower bound, "
        f"excluded above): {docket_first_sight}"
    )
    lines.append(
        "  absent side unknown (a documented first read poll preceded only by failed polls, "
        f"never a genuine no-docket/empty observation): {docket_absent_side_unknown}"
    )
    return lines


def _feed_lines(feed_comparison: FeedComparisonResult, feed_window_days: int) -> list[str]:
    lines = [
        "feed comparison rule (CRITICAL 2): a field change is 'reported' iff some change_feed "
        "row for the same case has last_change_utc strictly after the absent run's start time, "
        f"AND was polled by a run whose start time falls within {feed_window_days} day(s), by "
        "time, at or after the present run's start."
    ]
    if not feed_comparison.field_changes:
        lines.append("  no data")
        return lines
    lines.append(
        f"  field changes: reported {feed_comparison.field_changes_reported} of "
        f"{feed_comparison.field_changes}"
    )
    lines.append(
        f"  case-nights: reported {feed_comparison.case_nights_reported} of "
        f"{feed_comparison.case_nights}"
    )
    return lines


def _regulation_lines(transitions: RegulationTransitions) -> list[str]:
    return [
        "regulation transitions, watched cases only (IMPORTANT 7; migration 2 -- a store that "
        "ran only before migration 2 has no history for those nights, which reads as zero "
        "here, not a gap):",
        f"  empty -> 091 (filled in): {transitions.empty_to_091}",
        f"  days from first sight to fill-in: {_format_days(list(transitions.empty_to_091_days))}",
        f"  empty -> other (filled in and dropped): {transitions.empty_to_other}",
        f"  value -> different value (changed after first recorded): {transitions.changed_value}",
        f"  value -> empty: {transitions.value_to_empty}",
    ]


def _tail_lines(tail: TailArrivals) -> list[str]:
    return [
        "closure tail (IMPORTANT 3; real closures only -- Completed or N/A; 'appeared' also "
        "covers reappearances and one half of a suspected re-numbered pair):",
        f"  same run as closure (order unknown, spec §7 rule 4): {tail.same_run}",
        f"  strictly after closure: {tail.after}",
        f"  total (at or after closure, spec §7): {tail.total}",
        "  'not returned' tail (reported separately, not a real closure): "
        f"{tail.not_returned_tail}",
    ]


def report(  # noqa: PLR0913 -- one counts-only value per spec §10.2 bullet; see Task 11's brief.
    *,
    run_rows: Sequence[RunSummaryRow],
    field_arrivals: Sequence[FieldArrivalRow],
    first_sight_fields: int,
    prelim_arrivals: Sequence[ArrivalRow],
    prelim_first_sight: int,
    docket_arrivals: Sequence[DocketArrivalRow],
    docket_first_sight: int,
    docket_absent_side_unknown: int,
    feed_comparison: FeedComparisonResult,
    feed_window_days: int,
    regulation_transitions: RegulationTransitions,
    tail_arrivals: TailArrivals,
    renumber_suspects: int,
    possible_false_not_returned: int,
    page_sizes: Sequence[int],
) -> str:
    """Build the report text from already-computed rows/numbers. Pure -- no store access.

    Every argument is a number or a sequence of small, case-free rows (day counts and
    classification labels only -- no case number, mkey or title ever crosses into this
    function), so this cannot leak one regardless of what the store contains (decision 0024).
    """
    lines = [
        "Recorder report (scripts/recorder_report.py; spec S2.5 §10.2)",
        "Percentiles: nearest-rank method throughout; suppressed (n<3) below 3 observations.",
        "",
        *_run_summary_lines(run_rows),
        "",
        "arrival classification rule (IMPORTANT 5): each true arrival is BEFORE_CLOSURE, "
        "SAME_RUN_AS_CLOSURE or AFTER_CLOSURE, relative to the case's most recent real closure "
        "(Completed or N/A -- never 'not returned'); a case not currently watched (dropped for "
        "its regulation) is EXCLUDED_UNWATCHED instead. Only BEFORE_CLOSURE arrivals are the "
        "mask distribution spec §10.2 means.",
        "",
        *_field_lines(field_arrivals, first_sight_fields),
        "",
        *_prelim_lines(prelim_arrivals, prelim_first_sight),
        "",
        *_docket_lines(docket_arrivals, docket_first_sight, docket_absent_side_unknown),
        "",
        *_feed_lines(feed_comparison, feed_window_days),
        "",
        *_regulation_lines(regulation_transitions),
        "",
        *_tail_lines(tail_arrivals),
        "",
        f"suspected re-numbers: {renumber_suspects}",
        f"possible false 'not returned' events: {possible_false_not_returned}",
        "",
    ]
    if not page_sizes:
        lines.append("compressed listing page sizes: no data")
    else:
        p50 = _percentiles(page_sizes, (0.5,))[0.5]
        lines.append(f"compressed listing page sizes (bytes): p50={p50:.0f} max={max(page_sizes)}")

    return "\n".join(lines)


def _open_store(settings: Settings) -> Store:
    """Open the store the recorder itself writes to; read-only, S3 pulled but never pushed."""
    location = Location(settings.store)
    if location.is_s3:
        local = settings.data_dir / _REPORT_WORK_FILENAME
        local.parent.mkdir(parents=True, exist_ok=True)
        pull(location, local)
    else:
        local = Path(location.raw)
    store = Store(local)
    store.migrate()
    return store


def main(argv: Sequence[str]) -> int:
    """Read the store, compute every measure, print and optionally write the report."""
    parser = argparse.ArgumentParser(prog="recorder_report")
    parser.add_argument("--out", default=None)
    parser.add_argument("--feed-window-days", type=int, default=1)
    args = parser.parse_args(argv)

    settings = Settings()
    store = _open_store(settings)
    try:
        text = report(
            run_rows=store.run_summaries(),
            field_arrivals=store.field_change_arrivals(),
            first_sight_fields=store.first_sight_field_count(),
            prelim_arrivals=store.prelim_arrivals(),
            prelim_first_sight=store.prelim_first_sight_count(),
            docket_arrivals=store.docket_arrivals(),
            docket_first_sight=store.docket_first_sight_count(),
            docket_absent_side_unknown=store.docket_absent_side_unknown_count(),
            feed_comparison=store.feed_comparison(window_days=args.feed_window_days),
            feed_window_days=args.feed_window_days,
            regulation_transitions=store.regulation_transitions(),
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
