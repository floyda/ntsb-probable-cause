"""The recorder's counts-only report, read from the store (spec S2.5 §10.2, Task 11).

Status
    Live tool. Produces ``docs/results/s25-recorder-report.txt``. Its numbers become the
    stage's As-built record, and the 8-week comparisons in spec §10.2, once ``runs`` holds 14
    or more distinct FINISHED nights (spec "Done means" §14, item 2; a crashed run is not a
    night the recorder actually completed, so it does not count toward the threshold, and a
    night the recorder ran more than once counts once) -- run before that, it still prints,
    but its output is not yet citable. Prints, counts only (decision 0024; never a case number,
    an mkey, a title or any other per-case text): the per-night run summaries; arrival
    percentiles (days from event to first appearance, present- and absent-side, nearest-rank
    method) per evidence field, for the preliminary narrative and for the docket, each split
    into before/same-run/after closure and cases excluded because their regulation, at the
    time, was not Part 91 -- only the before-closure figures are the mask distribution spec
    §10.2 means; the change-feed comparison, at both field-row and case-night granularity;
    regulation transitions (migration 2's history, replacing the previous lower-bound
    estimate); the 30-day closure tail, split by same-run/after/total and reported separately
    for "not returned" cases; suspected re-numbers; a possible-false-"not returned" count; and
    compressed listing-page sizes. Opens the store strictly read-only and never migrates it.

    Fix round 1 (Task 11, 2026-09-23): rewrote every arrival query the report reads from
    (before/same-run/after-closure classification, the corrected feed rule, the docket
    absent-side rule, the preliminary narrative, migration 2's regulation history).

    Fix round 2 (2026-09-23): the "excluded" classification no longer reads the case's current
    ``watched`` flag, which a closed case's tail expiry clears regardless of its regulation --
    it now reads the case's regulation history, as recorded at the time of each arrival; the
    report text was rewritten in plain language, without reviewer shorthand or raw column
    names; "finished nights" now counts distinct UTC calendar dates, not run rows; the store is
    opened truly read-only (no ``migrate()`` call) with a schema-version check.

    Fix round 3 (2026-09-23): a real closure now includes one reached via ``'not returned'``
    (round 2's own ``old_status = 'Ongoing'`` requirement, meant only to block a
    ``Completed``-to-``N/A`` relabel, wrongly excluded that path too); the run table and totals
    line no longer show raw column names; the classification paragraph states the whole I5
    rule; the read-only URI now percent-encodes the store path, so one containing ``?`` or
    ``#`` cannot lose ``mode=ro`` or open the wrong file. See
    ``docs/plans/2026-09-22-s25-recorder.md``'s Deviations for the full account.

Usage:
    uv run python -m scripts.recorder_report [--out docs/results/s25-recorder-report.txt] \
        [--feed-window-days 1]

Reads ``NTSB_STORE`` (a local path or an ``s3://bucket/key`` URL, exactly as the recorder
itself does -- ``store/sync.py``): an S3 location is pulled to a local working file under
``NTSB_DATA_DIR`` (a plain download; the S3 object itself is never touched), which is then
opened read-only and never migrated. If the store does not exist yet, or its schema version
does not match what this code expects, the script says so and either prints an all-zero report
(no store yet) or refuses to read it (a mismatched version) -- it never writes to try to fix
either.
"""

import argparse
import math
import sys
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
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
from ntsb_probable_cause.store import schema as store_schema
from ntsb_probable_cause.store.sync import Location, pull

_PERCENTILES: tuple[float, ...] = (0.25, 0.5, 0.75, 0.9)
_MIN_N_FOR_PERCENTILES = 3
_REPORT_WORK_FILENAME = "recorder-report-work.sqlite"
_RUN_TABLE_TEXT_COLUMNS = 3  # run, started (UTC), finished (UTC): left-aligned; the rest right.

_ArrivalRowLike = FieldArrivalRow | ArrivalRow | DocketArrivalRow


def _percentiles(values: Sequence[int], qs: Sequence[float] = _PERCENTILES) -> dict[float, float]:
    """Nearest-rank percentiles; empty input gives an empty dict (rule 8: "no data" upstream)."""
    if not values:
        return {}
    ordered = sorted(values)
    n = len(ordered)
    return {q: ordered[min(n - 1, max(0, math.ceil(q * n) - 1))] for q in qs}


def _format_days(values: Sequence[int]) -> str:
    """Nearest-rank percentile text, or a floor/empty note.

    ``n<3`` suppresses percentiles below the reliable floor; an empty sequence reads ``no
    data``.
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
        f"before closure={counts[ArrivalClassification.BEFORE_CLOSURE]} "
        f"same run as closure={counts[ArrivalClassification.SAME_RUN_AS_CLOSURE]} "
        f"after closure={counts[ArrivalClassification.AFTER_CLOSURE]} "
        f"excluded (not Part 91 at the time)={counts[ArrivalClassification.EXCLUDED_UNWATCHED]}",
    ]


# One (label, width) per run-table column, shared by the header and every row (Task 11 fix
# round 3, WORDING 6): building both from the same tuple makes a header/row misalignment
# structurally impossible, rather than relying on hand-counted spaces in a literal string.
_RUN_TABLE_COLUMNS: tuple[tuple[str, int], ...] = (
    ("run", 7),
    ("started (UTC)", 26),
    ("finished (UTC)", 26),
    ("polled", 6),
    ("changed", 7),
    ("new documents", 14),
    ("failures", 8),
    ("re-numbers", 10),
    ("minutes", 7),
)


def _run_table_header() -> str:
    return "  " + " ".join(f"{name:<{width}}" for name, width in _RUN_TABLE_COLUMNS)


def _run_table_row(r: RunSummaryRow) -> str:
    finished_display = r.finished_at if r.finished_at is not None else "UNFINISHED"
    values = (
        str(r.run_id),
        r.started_at,
        finished_display,
        _fmt_int(r.cases_polled),
        _fmt_int(r.cases_changed),
        _fmt_int(r.new_documents),
        _fmt_int(r.failures),
        _fmt_int(r.suspected_renumbers),
        _fmt_minutes(r.minutes),
    )
    # The first three columns (run, started, finished) are text, left-aligned; the rest are
    # counts, right-aligned -- same convention a spreadsheet uses, and it does not affect
    # column boundaries, which come from the shared widths alone.
    cells = [
        f"{value:<{width}}" if i < _RUN_TABLE_TEXT_COLUMNS else f"{value:>{width}}"
        for i, ((_label, width), value) in enumerate(zip(_RUN_TABLE_COLUMNS, values, strict=True))
    ]
    return "  " + " ".join(cells)


def _run_summary_lines(run_rows: Sequence[RunSummaryRow]) -> list[str]:
    finished = [r for r in run_rows if r.finished_at is not None]
    unfinished = [r for r in run_rows if r.finished_at is None]
    finished_dates = {datetime.fromisoformat(r.started_at).date() for r in finished}
    lines = [
        f"nights recorded (every run, finished or not): {len(run_rows)}",
        f"finished runs: {len(finished)}",
        f"distinct finished nights: {len(finished_dates)} "
        "(counts each UTC calendar date once, even when the recorder ran more than once that "
        "night; this is the number the 14-night threshold counts)",
        f"unfinished (crashed) runs: {len(unfinished)}",
        "",
    ]
    if not run_rows:
        lines.append("run summaries: no data")
        return lines
    lines.append("run summaries (most recent first):")
    lines.append(_run_table_header())
    lines.extend(_run_table_row(r) for r in run_rows)
    lines.append("")
    lines.append(
        "totals over finished runs (unfinished runs' rows are real observations but excluded "
        "from these sums): "
        f"cases polled={sum(r.cases_polled or 0 for r in finished)} "
        f"cases changed={sum(r.cases_changed or 0 for r in finished)} "
        f"new documents={sum(r.new_documents or 0 for r in finished)} "
        f"failures={sum(r.failures or 0 for r in finished)} "
        f"minutes={sum(r.minutes or 0.0 for r in finished):.0f}"
    )
    return lines


def _field_lines(field_arrivals: Sequence[FieldArrivalRow], first_sight_fields: int) -> list[str]:
    lines = [
        "evidence-field arrival percentiles, days from event to first appearance:",
        "  the names below (e.g. weather_condition) are this project's own evidence field "
        "names, not raw database column names.",
        "  a case first seen after the recorder's first night has an absent side if the "
        "latest earlier night whose fetch of its event month was clean and fully observed "
        "found it absent -- never simply 'the night before'. It then counts as a true "
        "arrival below, not as first-sight. A record the API returned but never stored "
        "(not watchable and unknown, or an observation that failed) is never treated as "
        "new later either, whichever night it eventually becomes storable on.",
        "  which nights count as 'clean and fully observed' is known only from the night "
        "this store gained the table that records it; a case first seen on that same night "
        "has no earlier clean-fetch record to check yet, so it may still read as "
        "first-sight even when it genuinely was absent the night before.",
    ]
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
    lines = [
        "preliminary narrative arrival:",
        "  the same rule applies here as for evidence fields: a case first seen after the "
        "recorder's first night has an absent side if the latest earlier night whose fetch "
        "of its event month was clean and fully observed found it absent -- never simply "
        "'the night before'; and the same caveat applies about clean fetches being known "
        "only from the night that history was added to this store.",
    ]
    lines.extend(_arrival_lines("preliminary narrative", prelim_arrivals))
    lines.append(
        "  first-sight preliminary narratives (present by the day watching began, excluded "
        f"above): {prelim_first_sight}"
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
        "comparison between the month re-fetch and the change feed: a field change counts as "
        "reported by the feed only when the feed's own record of that case's change happened "
        "strictly after the last time the field was seen absent, AND the feed was checked at "
        f"the same time as, or within {feed_window_days} day(s) after, the run that found the "
        "change.",
        f"  timestamps that could not be read at all: {feed_comparison.unparsable_timestamps}",
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
        "regulation transitions, watched cases only. Regulation changes are known only from "
        "the night the regulation-history table was added to this store; for any nights "
        "before that, changes are unknown, not zero.",
        f"  empty -> 091 (filled in): {transitions.empty_to_091}",
        f"  days from first sight to fill-in: {_format_days(list(transitions.empty_to_091_days))}",
        f"  empty -> other (filled in and dropped): {transitions.empty_to_other}",
        f"  value -> different value (changed after first recorded): {transitions.changed_value}",
        f"  value -> empty: {transitions.value_to_empty}",
    ]


def _tail_lines(tail: TailArrivals) -> list[str]:
    return [
        "closure tail: documents that appeared at or after a case's closure (real closures "
        "only -- a status change to Completed or N/A, never 'not returned'; a document seen "
        "for the first time ever, with no earlier poll that showed it absent, is not counted "
        "as an arrival here at all). Reappearances and one half of a suspected re-numbered "
        "pair count the same as any other appearance. A case can have both a 'not returned' "
        "event and, later, a real closure; its documents can then be counted in both tails "
        "below.",
        f"  same run as closure (order unknown): {tail.same_run}",
        f"  strictly after closure: {tail.after}",
        f"  total (at or after closure): {tail.total}",
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
    Written in plain language throughout: no internal review labels and no raw column names,
    since this text becomes the stage's citable record.
    """
    lines = [
        "Recorder report (scripts/recorder_report.py; spec S2.5 §10.2)",
        "Percentiles: nearest-rank method throughout; suppressed (n<3) below 3 observations.",
        "",
        *_run_summary_lines(run_rows),
        "",
        "How arrivals are classified: each true arrival is BEFORE, on the SAME RUN AS, or "
        "AFTER its case's real closure. Separately, a case can be EXCLUDED instead, decided "
        "purely from its regulation history, never from closing or from the end of the 30-day "
        "watch after closing: the latest regulation change recorded at or before the "
        "arrival's run decides; if the only changes recorded are later than the arrival, the "
        "regulation recorded before the first of those changes decides; if the case has no "
        "recorded regulation changes at all, its regulation as currently recorded decides. A "
        "case is excluded only when that decided regulation is neither not-yet-recorded nor "
        "Part 91 -- so a regulation change recorded on the very same run as an arrival "
        "excludes that arrival too, which is a deliberately cautious reading. Only the "
        "before-closure arrivals are the mask distribution spec §10.2 means.",
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


def _empty_report(feed_window_days: int) -> str:
    """The report an empty store would print, without ever opening a file (Task 11 MINOR 4)."""
    return report(
        run_rows=[],
        field_arrivals=[],
        first_sight_fields=0,
        prelim_arrivals=[],
        prelim_first_sight=0,
        docket_arrivals=[],
        docket_first_sight=0,
        docket_absent_side_unknown=0,
        feed_comparison=FeedComparisonResult(
            field_changes=0,
            field_changes_reported=0,
            case_nights=0,
            case_nights_reported=0,
            unparsable_timestamps=0,
        ),
        feed_window_days=feed_window_days,
        regulation_transitions=RegulationTransitions(
            empty_to_091=0,
            empty_to_091_days=(),
            empty_to_other=0,
            changed_value=0,
            value_to_empty=0,
        ),
        tail_arrivals=TailArrivals(same_run=0, after=0, total=0, not_returned_tail=0),
        renumber_suspects=0,
        possible_false_not_returned=0,
        page_sizes=[],
    )


def _open_store(settings: Settings) -> tuple[Store | None, str | None]:
    """Open the store the recorder writes to, strictly read-only and never migrated.

    Task 11 fix round 2, MINOR 4: no ``migrate()`` call -- the script's "read-only" claim was
    not true while it silently upgraded the schema on every run. Returns ``(store, None)`` on
    success, ``(None, None)`` when no store exists yet (the caller prints an all-zero report
    without ever touching a file), or ``(None, message)`` when the store's schema version does
    not match what this code expects (refused, rather than read partially or migrated).

    An ``s3://`` location is still pulled to a local working file first -- a plain download,
    never a write to the S3 object itself -- and that local copy is then opened read-only.
    """
    location = Location(settings.store)
    if location.is_s3:
        local = settings.data_dir / _REPORT_WORK_FILENAME
        local.parent.mkdir(parents=True, exist_ok=True)
        pull(location, local)
    else:
        local = Path(location.raw)

    if not local.exists():
        return None, None

    store = Store(local, readonly=True)
    version = store.schema_version()
    expected = len(store_schema.MIGRATIONS)
    if version != expected:
        store.close()
        return None, (
            f"the store's schema version ({version}) does not match what this code expects "
            f"({expected}); refusing to read a mismatched store. Run the recorder itself "
            "(which migrates on write) against it first, or check that NTSB_STORE points at "
            "the intended file."
        )
    return store, None


def main(argv: Sequence[str]) -> int:
    """Read the store, compute every measure, print and optionally write the report."""
    parser = argparse.ArgumentParser(prog="recorder_report")
    parser.add_argument("--out", default=None)
    parser.add_argument("--feed-window-days", type=int, default=1)
    args = parser.parse_args(argv)

    settings = Settings()
    store, error = _open_store(settings)
    if error is not None:
        print(error, file=sys.stderr)
        return 1

    if store is None:
        text = _empty_report(args.feed_window_days)
    else:
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
