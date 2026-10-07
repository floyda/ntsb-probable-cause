"""The counts-only report of the live shadow's mornings (S3.3 spec sections 10 and 11).

Status
    Live tool (S3.3 spec §10). Counts only (decision 0024). Free: it reads the live run folders
    under ``NTSB_RUNS_DIR``, the refusal log and the recorder's store (pulled to the work file
    and opened read-only); it calls no model and needs no model key and no NTSB key. It writes
    ``docs/results/s33-live-shadow.txt`` with ``--out``. This is live tooling, so it reads live
    runs on purpose and is not behind ``scripts/_live_fence.py``; it prints no case number, no
    case key, no title and no model text.

What it prints, in this order
    mornings; money; outcomes (the three grades, a 95% Wilson interval on "first code right",
    abstains, failures by reason); the new checks; the backfill (count and SHA-256); closures
    per recorder night since 2026-09-23; the closing rule's inputs and its one-line verdict
    (spec §11).

Printed alone
    No held-out or development figure is shown beside it (decision 0021).

Usage
    make s33-report
    uv run --locked --extra aws ntsb-live report [--out PATH]
"""

import argparse
import json
import re
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

from ntsb_probable_cause.live.local import STORE_WORK_FILENAME, S3StoreSource, live_run_folders
from ntsb_probable_cause.live.morning import REFUSALS_FILE
from ntsb_probable_cause.live.queue import DECLARED_START, build_queue, closures_per_night
from ntsb_probable_cause.live.records import (
    BACKFILL_FILE,
    CLOSURES_FILE,
    Backfill,
    ClosureRecord,
)
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.metrics import wilson
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.store import Closure
from ntsb_probable_cause.store.sync import Location

WAIT_LIMIT_DAYS: Final = 14  # spec §11
_REASON_CHARS: Final = 40
_CASE_NUMBER = re.compile(r"[A-Z]{3}\d{2}[A-Z]{2}\d{3}")
_OCCURRENCE_PHASE_LEN: Final = 3
_FINDING_ITEM_LEN: Final = 8


class _Run:
    """What one live run folder holds, read once."""

    def __init__(self, folder: Path) -> None:
        records = (
            read_jsonl(folder / "run.jsonl", RunRecord) if (folder / "run.jsonl").is_file() else []
        )
        self.record: RunRecord | None = records[0] if records else None
        self.records = records
        cases = folder / "cases.jsonl"
        self.results = read_jsonl(cases, CaseResult) if cases.is_file() else []
        closures = folder / CLOSURES_FILE
        self.closures = read_jsonl(closures, ClosureRecord) if closures.is_file() else []
        backfill = folder / BACKFILL_FILE
        self.backfill = (
            Backfill.model_validate_json(backfill.read_text()) if backfill.is_file() else None
        )


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _reason(failure: str | None) -> str:
    """A failure cut to its kind: the words before the first colon, with no case number."""
    text = _CASE_NUMBER.sub("", failure or "unknown")
    head = re.split(r"[:;(]", text, maxsplit=1)[0].strip() or "unknown"
    return head[:_REASON_CHARS]


def _mornings(
    runs: Sequence[_Run], closures: Sequence[Closure], records: list[ClosureRecord]
) -> list[str]:
    lines = ["mornings", f"runs: {len(runs)}"]
    lines.append("cases per run: " + (", ".join(str(len(r.results)) for r in runs) or "none"))
    done: set[str] = set()
    queue: list[str] = []
    for run in runs:
        done.update(r.case_id for r in run.results)
        queue.append(str(len(build_queue(closures, done))))
    lines.append(
        "queue after each run (as the store stands today): " + (", ".join(queue) or "none")
    )
    waited = [r.waited_days for r in records]
    lines.append(
        f"days waited: p50 {statistics.median(waited):g}, max {max(waited)}"
        if waited
        else "days waited: none yet"
    )
    spans: list[str] = []
    for run in runs:
        sent = [r.first_sent for r in run.closures if r.first_sent is not None]
        back = [r.last_returned for r in run.closures if r.last_returned is not None]
        spans.append(
            f"{(max(back) - min(sent)).total_seconds() / 60:.0f}" if sent and back else "n/a"
        )
    lines.append("minutes, first round to last: " + (", ".join(spans) or "none"))
    return lines


def _computed(runs: Sequence[_Run]) -> float:
    return sum(x.cost_usd for r in runs for x in r.records)


def _reported(runs: Sequence[_Run]) -> list[_Run]:
    """The runs whose every record carries the provider's reported total."""
    return [r for r in runs if all(x.reported_batch_cost_usd is not None for x in r.records)]


def _billed(runs: Sequence[_Run]) -> float:
    return sum(x.reported_batch_cost_usd or 0.0 for r in runs for x in r.records)


def _per_case(total: float, cases: int) -> str:
    return f"${total / cases:.4f}" if cases else "n/a"


def _money(runs: Sequence[_Run]) -> list[str]:
    started = [r for r in runs if r.record is not None]
    reported = _reported(started)
    lines = [
        "money",
        f"computed: ${_computed(started):.4f} in all, "
        f"{_per_case(_computed(started), sum(len(r.results) for r in started))} per case",
        f"billed ({len(reported)} of {len(started)} runs reported): "
        f"${_billed(reported):.4f} in all, "
        f"{_per_case(_billed(reported), sum(len(r.results) for r in reported))} per case",
    ]
    by_month: dict[str, list[_Run]] = {}
    for run in started:
        if run.record is not None:
            month = run.record.started.astimezone(UTC).strftime("%Y-%m")
            by_month.setdefault(month, []).append(run)
    for month, group in sorted(by_month.items()):
        got = _reported(group)
        lines.append(
            f"{month}: computed ${_computed(group):.4f}, billed ${_billed(got):.4f} "
            f"({len(got)} of {len(group)} runs reported)"
        )
    return lines


def _outcomes(records: Sequence[ClosureRecord]) -> list[str]:
    scored = [r for r in records if r.scored]
    first = sum(1 for r in scored if r.top1)
    other = sum(1 for r in scored if r.top3 and not r.top1)
    different = len(scored) - first - other
    low, high = wilson(first, len(scored))
    interval = f"{_pct(low)} to {_pct(high)}" if scored else "n/a"
    reasons = Counter(_reason(r.failure) for r in records if r.outcome == "not coded")
    return [
        "outcomes",
        f"first code right: {first}",
        f"right code in another position: {other}",
        f"different: {different}",
        f"95% interval for first code right ({first} of {len(scored)} scored): {interval}",
        f"abstained: {sum(1 for r in records if r.abstained)}",
        f"not coded: {sum(reasons.values())}",
        *(f"not coded, {reason}: {count}" for reason, count in sorted(reasons.items())),
    ]


def _cases_in(found: Mapping[str, set[int]]) -> int:
    return len({number for numbers in found.values() for number in numbers})


def _missing_codes(
    runs: Sequence[_Run], tables: CodeTables
) -> tuple[tuple[int, int], tuple[int, int]]:
    """(distinct codes, cases) the tables lack, for occurrence and for finding codes."""
    occurrence: dict[str, set[int]] = {}
    finding: dict[str, set[int]] = {}
    number = 0
    for run in runs:
        for result in run.results:
            number += 1
            for code in result.verdict_occurrence:
                if not (
                    code[:_OCCURRENCE_PHASE_LEN] in tables.phases
                    and code[_OCCURRENCE_PHASE_LEN:] in tables.events
                ):
                    occurrence.setdefault(code, set()).add(number)
            for code in result.verdict_findings:
                if not (
                    code[:_FINDING_ITEM_LEN] in tables.items
                    and code[_FINDING_ITEM_LEN:] in tables.modifiers
                ):
                    finding.setdefault(code, set()).add(number)
    return (len(occurrence), _cases_in(occurrence)), (len(finding), _cases_in(finding))


def _checks(
    runs: Sequence[_Run],
    records: Sequence[ClosureRecord],
    tables: CodeTables,
    refusals: Sequence[Mapping[str, str]],
) -> list[str]:
    (occ_codes, occ_cases), (find_codes, find_cases) = _missing_codes(runs, tables)
    kinds = Counter(str(row.get("reason", "unknown")) for row in refusals)
    unscored = sum(1 for r in records if r.outcome == "coded" and not r.scored)
    return [
        "checks",
        f"preliminary narrative present: {sum(1 for r in records if r.prelim_present)} "
        f"of {len(records)}",
        f"refusals before a run: {sum(kinds.values())}",
        *(f"refusals, {kind}: {count}" for kind, count in sorted(kinds.items())),
        "cases returned to the queue: not recorded (a case that fails before it is seen "
        "leaves no row; the morning's summary printed the count)",
        f"verdict codes missing from the tables, occurrence: {occ_codes} code"
        f"{'' if occ_codes == 1 else 's'} in {occ_cases} case{'' if occ_cases == 1 else 's'}",
        f"verdict codes missing from the tables, finding: {find_codes} code"
        f"{'' if find_codes == 1 else 's'} in {find_cases} case{'' if find_cases == 1 else 's'}",
        f"closures without a verdict: {unscored}",
        "closures as N/A: not separable (a record that closed as N/A holds no verdict, so it "
        f"is in the line above; {unscored} in all)",
    ]


def _backfill(runs: Sequence[_Run]) -> tuple[Backfill | None, list[str]]:
    held = next((r.backfill for r in runs if r.backfill is not None), None)
    if held is None:
        return None, ["backfill", "backfill: not yet fixed"]
    return held, [
        "backfill",
        f"backfill: {len(held.case_ids)} cases, SHA-256 {held.sha256}",
        f"fixed on {held.fixed_on.isoformat()}",
    ]


def _per_night(closures: Sequence[Closure], today: date) -> list[str]:
    counts = closures_per_night(closures)
    last = max([today, *counts])
    lines = ["closures per night (UTC), since 2026-09-23"]
    day = DECLARED_START
    while day <= last:
        lines.append(f"{day.isoformat()}: {counts.get(day, 0)}")
        day += timedelta(days=1)
    return lines


def _closing(
    runs: Sequence[_Run], backfill: Backfill | None, records: Sequence[ClosureRecord], today: date
) -> list[str]:
    coded = {r.case_id for run in runs for r in run.results}
    drained = backfill is not None and set(backfill.case_ids) <= coded
    fresh = (
        sum(1 for r in records if r.outcome == "coded" and r.closed_on > backfill.fixed_on)
        if backfill is not None
        else 0
    )
    starts = [run.record.started.astimezone(UTC).date() for run in runs if run.record]
    days = (today - min(starts)).days if starts else 0
    if drained and fresh >= 1:
        verdict = "met (fresh closure)"
    elif drained and starts and days >= WAIT_LIMIT_DAYS:
        verdict = "met (14 days)"
    else:
        verdict = "not met"
    return [
        "closing rule inputs",
        f"backfill drained: {'yes' if drained else 'no'}",
        f"fresh closures coded: {fresh}",
        f"days since the first live morning: {days}",
        f"closing rule: {verdict}",
    ]


def report_text(
    folders: Sequence[Path],
    closures: Sequence[Closure],
    tables: CodeTables,
    refusals: Sequence[Mapping[str, str]],
    *,
    today: date,
) -> str:
    """The report as plain text; counts only.

    Args:
        folders: Live run folders, oldest first.
        closures: Every closure in the recorder's store.
        tables: The code tables Ellery and the scorer share.
        refusals: Rows of ``live-refusals.jsonl`` (``{"at", "reason"}``).
        today: The UTC date the report is read on (the closing rule's clock).

    Returns:
        The text, ending with the closing rule line.
    """
    runs = [_Run(folder) for folder in folders]
    records = [r for run in runs for r in run.closures]
    held, backfill_lines = _backfill(runs)
    sections = [
        [
            "S3.3 live shadow: counts only (decision 0024). Live and held-out numbers are never "
            "shown together (decision 0021); at this size the interval is wide.",
        ],
        _mornings(runs, closures, records),
        _money(runs),
        _outcomes(records),
        _checks(runs, records, tables, refusals),
        backfill_lines,
        _per_night(closures, today),
        _closing(runs, held, records, today),
    ]
    return "\n\n".join("\n".join(section) for section in sections) + "\n"


def _read_closures(settings: Settings) -> list[Closure]:
    source = S3StoreSource(Location(settings.store), settings.data_dir / STORE_WORK_FILENAME)
    try:
        return source.open().closures()
    finally:
        source.discard()


def _read_refusals(runs_dir: Path) -> list[dict[str, str]]:
    path = runs_dir / REFUSALS_FILE
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    """Print the report and, with ``--out``, write it. Returns the exit code."""
    parser = argparse.ArgumentParser(prog="s33_live_report", description=__doc__)
    parser.add_argument("--out", default=None, help="also write the text to this file")
    args = parser.parse_args(argv)
    settings = Settings()
    text = report_text(
        live_run_folders(settings.runs_dir),
        _read_closures(settings),
        load_tables(),
        _read_refusals(settings.runs_dir),
        today=datetime.now(UTC).date(),
    )
    print(text, end="")
    if args.out:
        Path(args.out).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
