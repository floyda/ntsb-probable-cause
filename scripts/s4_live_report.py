"""The counts-only report of the cloud live nights (S4 specification sections 8, 11 and 15).

Status
    Live tool (S4 Task 14). Counts only (decision 0024). Free: it reads four local things and
    nothing else: a local copy of the live bucket (``--mirror``: ``runs/``, ``scores/``,
    ``nights/``), the ``board/1`` export built from that copy on the Mac (``--export``, no
    store), the night's own export copied from the bucket (``--night-export``, built with the
    store; it supplies closures per night and condition 6) and the ledger file (``--ledger``). It
    never reads the bucket itself, calls no model and needs no key. With ``--out`` it writes
    ``docs/results/s4-live.txt``. It prints no case number, no case key, no title and no model
    text; a check on the finished text refuses to print or write anything
    shaped like an NTSB case number. This is live tooling, so it reads live runs on purpose and is
    not behind ``scripts/_live_fence.py``.

What it prints, in this order
    nights (started, finished, stopped by kind); alerts by kind; cases (coded, not coded by kind,
    unreachable, awaiting the NTSB's codes) and later scores; the six grades and a 95% Wilson
    interval on "same first code"; finding recall@10; replies by provider and replies from
    another model than the one asked for (decision 0169); names replaced, as a floor (decision
    0180 item 5); money (the live key's spend in the first cloud nights apart from later nights,
    decision 0170 item 6, and S4's development spend); the backfill (count and SHA-256);
    closures per night since 2026-09-23; the closing rule's seven conditions, each "met" or "not
    met" (decision 0181); and a line that the open split enters only as counts.

Two of the seven conditions cannot be seen in the files: the alert email received and the
missed-night alarm shown to fire (5), and the Mac's key removed (7). Andy records each with its
date in an attestation file (``--attest``, a small JSON object with the keys
``alert_email_received``, ``alarm_test_fired`` and ``mac_key_removed``). Without one, they read
"not met".

Printed alone
    No held-out or development figure is shown beside it (decision 0021); at this size the
    interval is wide.

Usage
    make s4-report
    uv run --locked ntsb-live report --mirror DIR --export DIR --night-export DIR --ledger PATH
        [--attest PATH] [--out PATH]
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from ntsb_probable_cause.agent.version import VERSION_1
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.live.export import BoardIndex, CaseFile
from ntsb_probable_cause.live.ledger import LedgerLine, read_ledger
from ntsb_probable_cause.live.local import live_run_folders
from ntsb_probable_cause.live.morning import ALERT_KINDS
from ntsb_probable_cause.live.names import NAME_MARKER
from ntsb_probable_cause.live.night import NIGHT_FILE, NIGHT_MANIFEST_FILE
from ntsb_probable_cause.live.queue import DECLARED_START
from ntsb_probable_cause.live.records import (
    BACKFILL_FILE,
    CLOSURES_FILE,
    MANIFEST_FILE,
    Backfill,
    ClosureRecord,
    ClosureRecordV1,
    read_closure_records,
)
from ntsb_probable_cause.live.state import NightState
from ntsb_probable_cause.scoring.budget import spent_usd, stage_spent
from ntsb_probable_cause.scoring.metrics import wilson
from ntsb_probable_cause.scoring.records import RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings
from scripts import stage_spend

CASE_NUMBER: Final = re.compile(r"[A-Z]{3}\d{2}[A-Z]{2}\d{3}")
WAIT_LIMIT_DAYS: Final = 14  # decision 0181: the fresh-closure time limit after the backfill drains
GRADES: Final = (
    "same_first",
    "same_codes_other_order",
    "different",
    "abstained",
    "not_coded",
    "awaiting_ntsb",
)
ATTESTATION_KEYS: Final = ("alert_email_received", "alarm_test_fired", "mac_key_removed")
CONTINUITY_FILE: Final = Path("docs") / "results" / "s33-fingerprint-continuity.txt"
_REPO_ROOT: Final = Path(__file__).resolve().parents[1]


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def _json(path: Path) -> Any:
    return json.loads(path.read_text())


# --- what the mirror holds ---


class _Night:
    """One night folder: the marker, the record and the manifest, read once."""

    def __init__(self, folder: Path) -> None:
        self.date = date.fromisoformat(folder.name)
        self.marked = (folder / "started").is_file()
        record = folder / NIGHT_FILE
        manifest = folder / NIGHT_MANIFEST_FILE
        self.record: dict[str, Any] | None = _json(record) if record.is_file() else None
        self.manifest: dict[str, Any] | None = _json(manifest) if manifest.is_file() else None

    @property
    def started(self) -> bool:
        return self.marked or self.record is not None

    @property
    def finished(self) -> bool:
        return bool(self.manifest and self.manifest.get("finished") is True)

    @property
    def alerts(self) -> list[str]:
        return [str(k) for k in (self.record or {}).get("alerts", [])]

    @property
    def run_ids(self) -> set[str]:
        """The run folders this night's manifest lists among the files it wrote."""
        found: set[str] = set()
        for entry in (self.manifest or {}).get("night_files", []):
            parts = str(entry.get("path", "")).split("/")
            if len(parts) > 2 and parts[0] == "runs":  # noqa: PLR2004 -- runs/<id>/<file>
                found.add(parts[1])
        return found


def _nights(mirror: Path) -> list[_Night]:
    root = mirror / "nights"
    if not root.is_dir():
        return []
    found: list[_Night] = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            found.append(_Night(folder))
        except ValueError:
            continue  # a folder not named for a date is not a night
    return found


class _Run:
    """One live run folder: its record, closures, backfill, trail replies and manifest."""

    def __init__(self, folder: Path) -> None:
        self.id = folder.name
        self.folder = folder
        run_file = folder / "run.jsonl"
        records = read_jsonl(run_file, RunRecord) if run_file.is_file() else []
        self.records = records
        closures = folder / CLOSURES_FILE
        self.closures: list[ClosureRecord | ClosureRecordV1] = (
            read_closure_records(closures) if closures.is_file() else []
        )
        backfill = folder / BACKFILL_FILE
        self.backfill = (
            Backfill.model_validate_json(backfill.read_text()) if backfill.is_file() else None
        )
        self.manifest_sha: str | None = None
        manifest = folder / MANIFEST_FILE
        if manifest.is_file():
            self.manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()

    @property
    def asked_model(self) -> str | None:
        return self.records[0].model if self.records else None

    @property
    def started(self) -> date | None:
        return self.records[0].started.astimezone(UTC).date() if self.records else None

    def replies(self) -> list[tuple[str | None, str | None]]:
        """``(reply_model, reply_provider)`` of every call row; nothing else of a row is read."""
        trail = self.folder / "trail.jsonl"
        if not trail.is_file():
            return []
        rows = [json.loads(line) for line in trail.read_text().splitlines() if line.strip()]
        return [(row.get("reply_model"), row.get("reply_provider")) for row in rows]


def _runs(mirror: Path) -> list[_Run]:
    return [_Run(folder) for folder in live_run_folders(mirror / "runs")]


def _later_ids(mirror: Path) -> tuple[set[str], int]:
    """The case ids with a later score, and how many score lines there are."""
    ids: set[str] = set()
    lines = 0
    scores = mirror / "scores"
    for path in sorted(scores.glob("*.jsonl")) if scores.is_dir() else []:
        for text in path.read_text().splitlines():
            if text.strip():
                lines += 1
                ids.add(str(json.loads(text)["case_id"]))
    return ids, lines


# --- what the export holds ---


class _Export:
    """The export: its index, its case files (validated), and the count of name markers."""

    def __init__(self, folder: Path | None) -> None:
        self.index: BoardIndex | None = None
        self.cases: list[CaseFile] = []
        self.valid = False
        self.name_markers = 0
        if folder is None:
            return
        index = folder / "index.json"
        if not index.is_file():
            return
        try:
            self.index = BoardIndex.model_validate_json(index.read_text())
            case_files = sorted((folder / "cases").glob("*.json"))
            self.cases = [CaseFile.model_validate_json(p.read_text()) for p in case_files]
            self.valid = True
        except ValidationError:
            self.valid = False
        files = [index, *sorted((folder / "cases").glob("*.json"))]
        self.name_markers = sum(p.read_text().count(NAME_MARKER) for p in files)


# --- the sections ---


def _nights_section(nights: Sequence[_Night]) -> list[str]:
    stopped = Counter(n.alerts[0] if n.alerts else "unknown" for n in nights if _stopped(n))
    unrecorded = sum(1 for n in nights if n.started and n.record is None)
    lines = [
        "nights",
        f"nights started: {sum(1 for n in nights if n.started)}",
        f"nights finished: {sum(1 for n in nights if n.finished)}",
        f"nights stopped, with a record: {sum(stopped.values())}",
        *(f"nights stopped, {kind}: {count}" for kind, count in sorted(stopped.items())),
        f"nights started with no record (killed, crashed or still running): {unrecorded}",
    ]
    started = [n.date for n in nights if n.started]
    if started:
        lines.append(
            f"first night: {min(started).isoformat()}; last night: {max(started).isoformat()}"
        )
    return lines


def _stopped(night: _Night) -> bool:
    return night.record is not None and not night.finished


def _alerts_section(nights: Sequence[_Night]) -> list[str]:
    counts = Counter(kind for n in nights for kind in n.alerts)
    known = [(kind, counts[kind]) for kind in ALERT_KINDS if counts[kind]]
    other = sum(count for kind, count in counts.items() if kind not in ALERT_KINDS)
    lines = ["alerts, by kind (one per night per kind)"]
    lines += [f"alert, {kind}: {count}" for kind, count in known]
    if other:
        lines.append(f"alert, a kind not in the list: {other}")
    if not known and not other:
        lines.append("alerts: none")
    return lines


def _cases_section(export: _Export, nights: Sequence[_Night], later_lines: int) -> list[str]:
    lines = ["cases"]
    if export.index is None:
        return [*lines, "no export was found: the case counts are not available"]
    counts = export.index.counts
    not_coded = sum(counts.not_coded.values())
    later_recorded = sum(int((n.record or {}).get("later_scored", 0)) for n in nights)
    lines += [
        f"cases on the board: {len(export.index.rows)}",
        f"cases coded: {counts.coded}",
        f"cases not coded: {not_coded}",
        *(f"not coded, {kind}: {count}" for kind, count in sorted(counts.not_coded.items())),
        f"unreachable (not coded, final): {counts.not_coded.get('unreachable', 0)}",
        f"awaiting the NTSB's codes: {counts.awaiting_ntsb}",
        f"later scores written (night records): {later_recorded}",
        f"later scores held (score files): {later_lines}",
        f"open cases watched, counts only: {counts.open_watched}",
        f"open cases holding a docket, counts only: {counts.open_with_docket}",
    ]
    return lines


def _grades_section(export: _Export) -> list[str]:
    lines = ["grades"]
    if export.index is None:
        return [*lines, "no export was found: the grades are not available"]
    rows = export.index.rows
    tally = Counter(r.grade for r in rows)
    lines += [f"grade, {name}: {tally[name]}" for name in GRADES]
    graded = sum(1 for r in rows if r.grade != "awaiting_ntsb")
    low, high = wilson(tally["same_first"], graded)
    interval = f"{_pct(low)} to {_pct(high)}" if graded else "n/a"
    lines.append(
        f"95% interval for same first code ({tally['same_first']} of {graded} cases the NTSB has "
        f"coded, a case not coded or abstained counting as not right): {interval}"
    )
    recalls = [
        c.comparison.finding_recall_10
        for c in export.cases
        if c.comparison is not None and c.comparison.finding_recall_10 is not None
    ]
    lines.append(
        f"finding recall@10, mean over {len(recalls)} cases: {sum(recalls) / len(recalls):.3f}"
        if recalls
        else "finding recall@10, mean: no case has one yet"
    )
    return lines


def _replies_section(runs: Sequence[_Run]) -> list[str]:
    by_provider: Counter[str] = Counter()
    differ = unnamed = total = 0
    for run in runs:
        for model, provider in run.replies():
            total += 1
            if model is None:
                unnamed += 1
                continue
            by_provider[provider or "none named"] += 1
            if run.asked_model is not None and model != run.asked_model:
                differ += 1
    return [
        "replies (decision 0169)",
        f"model calls with a trail row: {total}",
        *(f"replies, provider {name}: {count}" for name, count in sorted(by_provider.items())),
        f"replies whose model differs from the one asked for: {differ}",
        f"calls with no reply model recorded: {unnamed}",
    ]


def _names_section(export: _Export) -> list[str]:
    return [
        "names (decisions 0180 item 5, 0182, 0183)",
        f"words replaced with a name marker in the export: {export.name_markers}, a floor: a name "
        "the rule cannot recognise is not replaced",
    ]


def _unreachable_ids(mirror: Path) -> set[str]:
    """The case ids ``nights/state.json`` settles as unreachable; none when it is absent."""
    path = mirror / "nights" / "state.json"
    if not path.is_file():
        return set()
    return set(NightState.model_validate_json(path.read_text()).unreachable)


def _drained_on(
    runs: Sequence[_Run],
    backfill: Backfill | None,
    unreachable: set[str],
    last_night: date | None,
) -> date | None:
    """The UTC day the last backfill case was settled, or None while any is not.

    A backfill case is settled when it has any closure record (coded or not coded, dated by
    ``last_returned``, else ``first_sent``, else its run's start), or when ``nights/state.json``
    holds it as unreachable. State does not date a settlement, so those cases count from the last
    night folder in the mirror, an upper bound.
    """
    if backfill is None:
        return None
    wanted = set(backfill.case_ids)
    settled: dict[str, date] = {}
    for run in runs:
        for record in run.closures:
            if record.case_id not in wanted:
                continue
            when = record.last_returned or record.first_sent
            day = when.astimezone(UTC).date() if when is not None else run.started
            settled[record.case_id] = day or backfill.fixed_on
    for case_id in unreachable & wanted:
        settled.setdefault(case_id, last_night or backfill.fixed_on)
    if set(settled) != wanted:
        return None
    return max(settled.values()) if settled else backfill.fixed_on


def _money_section(
    runs: Sequence[_Run], drained: date | None, dev_spend: Sequence[str]
) -> list[str]:
    first: list[RunRecord] = []
    later: list[RunRecord] = []
    for run in runs:
        for record in run.records:
            started = record.started.astimezone(UTC).date()
            (first if drained is None or started <= drained else later).append(record)

    def line(label: str, records: Sequence[RunRecord]) -> str:
        billed = sum(spent_usd(r) for r in records)
        computed = sum(r.cost_usd for r in records)
        return (
            f"{label}: ${billed:.4f} over {len(records)} run records "
            f"(computed list price ${computed:.4f})"
        )

    return [
        "money",
        line("live key, first cloud nights (to the night the backfill drained)", first),
        line("live key, later nights", later),
        "the live key's spend is counted from each night's run records (decision 0170 item 6); "
        "a call that never reached a record is not in it",
        *dev_spend,
    ]


def _backfill_section(backfill: Backfill | None) -> list[str]:
    if backfill is None:
        return ["backfill", "backfill: not yet fixed"]
    return [
        "backfill",
        f"backfill: {len(backfill.case_ids)} cases, SHA-256 {backfill.sha256}",
        f"fixed on {backfill.fixed_on.isoformat()}",
    ]


def _per_night_section(export: _Export, today: date) -> list[str]:
    lines = ["closures per night (UTC), since 2026-09-23"]
    if export.index is None:
        return [
            *lines,
            "no night export was found: the night builds the export with the store, and this "
            "section reads that one (run make s4-export)",
        ]
    counts = export.index.counts.closures_per_night
    last = max([today, *counts])
    day = DECLARED_START
    while day <= last:
        lines.append(f"{day.isoformat()}: {counts.get(day, 0)}")
        day += timedelta(days=1)
    return lines


# --- the closing rule (decision 0181) ---


def _met(ok: bool) -> str:
    return "met" if ok else "not met"


def _attested(value: str | None) -> tuple[date | None, str | None]:
    """An attestation as ``(date, problem)``: both None when it was not given."""
    if not value:
        return None, None
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, "attestation value is not a date"


def _stated(attested: tuple[date | None, str | None]) -> str:
    day, problem = attested
    return day.isoformat() if day is not None else (problem or "not given")


def _closing_section(  # noqa: PLR0913, PLR0917 -- one section, seven conditions' inputs.
    runs: Sequence[_Run],
    nights: Sequence[_Night],
    backfill: Backfill | None,
    night_export: _Export,
    ledger: Sequence[LedgerLine],
    later_ids: set[str],
    attest: Mapping[str, str],
    continuity: str | None,
    today: date,
    drained_on: date | None,
    upper_bound: bool = False,
) -> list[str]:
    records = [r for run in runs for r in run.closures]
    held_ids = set(backfill.case_ids) if backfill is not None else set()

    # 1. version 1 re-pinned, continuity shown
    pin = VERSION_1.rsplit("+t", 1)[-1]
    shown = continuity is not None and "match: yes" in continuity and pin in continuity
    labels = {r.prompt_version for r in records}
    one = shown and labels <= {VERSION_1}

    # 2. the backfill drained, written by scheduled nights
    scheduled = {run_id for n in nights for run_id in n.run_ids}
    holders = {run.id for run in runs if any(r.case_id in held_ids for r in run.closures)}
    two = drained_on is not None and holders <= scheduled

    # 3. a fresh closure coded and scored on the night after it closed
    fresh_runs: set[str] = set()
    fresh = 0
    for run in runs:
        for record in run.closures:
            scored = record.scored or record.case_id in later_ids
            if (
                backfill is not None
                and record.case_id not in held_ids
                and record.outcome == "coded"
                and record.waited_days <= 1
                and scored
            ):
                fresh += 1
                fresh_runs.add(run.id)
    three = fresh >= 1

    # 4. the ledger holds those runs' manifest hashes
    latest = {line.key: line for line in ledger}
    by_id = {run.id: run for run in runs}
    four = three and all(
        (line := latest.get(f"runs/{run_id}/manifest.json")) is not None
        and line.sha256 == by_id[run_id].manifest_sha
        for run_id in fresh_runs
    )

    # 5, 7. Andy's word, dated: each value must be an ISO date
    given = {key: _attested(attest.get(key)) for key in ATTESTATION_KEYS}
    five = given["alert_email_received"][0] is not None and given["alarm_test_fired"][0] is not None
    seven = given["mac_key_removed"][0] is not None

    # 6. an export built from the real store (the night's own) passes the board/1 models
    six = (
        night_export.valid and night_export.index is not None and len(night_export.index.rows) >= 1
    )

    days = (today - drained_on).days if drained_on is not None else None
    limit_reached = (not three) and days is not None and days >= WAIT_LIMIT_DAYS
    others = [one, two, four if three else True, five, six, seven]
    lines = [
        "closing rule (decision 0181)",
        f"1. version 1 re-pinned with continuity shown, no other label run: {_met(one)}",
        f"2. backfill drained by scheduled nights ({len(held_ids)} cases): {_met(two)} "
        "(it counts any night manifest, so a hand-started night cannot be told apart)",
        f"3. a fresh closure coded and scored on the night after it closed "
        f"({fresh} such cases): {_met(three)}",
        f"4. the ledger holds those runs' manifest hashes: {_met(four)}",
        f"5. test alert email received and the alarm shown to fire (Andy's attestation: "
        f"{_stated(given['alert_email_received'])}; {_stated(given['alarm_test_fired'])}): "
        f"{_met(five)}",
        f"6. the night's export, built from the real store, passes board/1 and holds at least "
        f"one case: {_met(six)}",
        f"7. the Mac's key removed (Andy's attestation: {_stated(given['mac_key_removed'])}): "
        f"{_met(seven)}",
        "(condition 6 also needs this file committed by Andy from this script; "
        "conditions 5 and 7 are Andy's word, dated in the attestation file)",
        f"days since the backfill drained: {days if days is not None else 'not drained'}"
        + (
            " (upper bound: unreachable cases are dated by the last night in the mirror)"
            if upper_bound
            else ""
        ),
        f"time limit ({WAIT_LIMIT_DAYS} days after the drain, no fresh closure): "
        f"{'reached' if limit_reached else 'not reached'}",
    ]
    conditions = [one, two, three, four, five, six, seven]
    if all(conditions):
        verdict = "all seven conditions met"
    elif limit_reached and all(others):
        verdict = "the six others met and the time limit reached: S4 closes on the rest and says so"
    else:
        verdict = f"{sum(conditions)} of 7 conditions met"
    return [*lines, f"closing rule: {verdict}"]


def report_text(  # noqa: PLR0913 -- the report's inputs.
    mirror: Path,
    export: Path,
    ledger: Sequence[LedgerLine],
    *,
    night_export: Path | None = None,
    today: date,
    dev_spend: Sequence[str] = (),
    attest: Mapping[str, str] | None = None,
    continuity: str | None = None,
) -> str:
    """The report as plain text; counts only.

    Args:
        mirror: A local copy of the live bucket (``runs/``, ``scores/``, ``nights/``).
        export: The ``board/1`` export built from it on the Mac (without the store).
        ledger: The ledger's lines, oldest first.
        night_export: The night's own export, copied from ``export/board-1/`` in the bucket. It
            is built with the store, so it holds ``closures_per_night``; the closures-per-night
            section and closing condition 6 read it, and the cases, grades and names floor read
            ``export``.
        today: The UTC date the report is read on (the closing rule's clock).
        dev_spend: S4's development spend, as printed lines.
        attest: Andy's dated attestations (:data:`ATTESTATION_KEYS`).
        continuity: The text of the fingerprint continuity file, if it exists.

    Returns:
        The text, ending with the closing rule line.
    """
    nights, runs = _nights(mirror), _runs(mirror)
    held = next((r.backfill for r in runs if r.backfill is not None), None)
    loaded = _Export(export)
    nightly = _Export(night_export)
    last_night = max((n.date for n in nights if n.started), default=None)
    unreachable = _unreachable_ids(mirror)
    drained = _drained_on(runs, held, unreachable, last_night)
    closed = {r.case_id for run in runs for r in run.closures}
    upper = (
        drained is not None
        and held is not None
        and bool((unreachable & set(held.case_ids)) - closed)
    )
    later_ids, later_lines = _later_ids(mirror)
    sections = [
        [
            "S4 live nights: counts only (decision 0024). The open split enters this report only "
            "as counts and distributions; no case number, title or text is in it. Live and "
            "held-out numbers are never shown together (decision 0021); at this size the "
            "interval is wide.",
        ],
        _nights_section(nights),
        _alerts_section(nights),
        _cases_section(loaded, nights, later_lines),
        _grades_section(loaded),
        _replies_section(runs),
        _names_section(loaded),
        _money_section(runs, drained, dev_spend),
        _backfill_section(held),
        _per_night_section(nightly, today),
        _closing_section(
            runs,
            nights,
            held,
            nightly,
            ledger,
            later_ids,
            attest or {},
            continuity,
            today,
            drained,
            upper,
        ),
    ]
    return "\n\n".join("\n".join(section) for section in sections) + "\n"


def development_spend() -> list[str]:
    """S4's development spend and line, from ``stage_spend`` (counted by commit); never raises."""
    stage = stage_spend.STAGES["s4"]
    try:
        branches = stage_spend.stage_branches(stage)
        runs, spend = stage_spent(Settings().runs_dir, stage_spend.stage_commits(stage, branches))
    except ConfigurationError:
        return ["development spend, S4: not available here (git could not list the commits)"]
    text, _ = stage_spend.report(stage, runs=runs, spend=spend, estimate=0.0)
    return [
        "development spend, S4 (the development key, apart from the live key):",
        *text.splitlines()[:1],
    ]


def _attestations(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    loaded = _json(path)
    if not isinstance(loaded, dict):
        raise ConfigurationError(f"{path}: the attestation file must be a JSON object")
    return {k: str(loaded[k]) for k in ATTESTATION_KEYS if loaded.get(k)}


def main(argv: Sequence[str] | None = None) -> int:
    """Print the report and, with ``--out``, write it. Returns the exit code."""
    parser = argparse.ArgumentParser(prog="s4_live_report", description=__doc__)
    parser.add_argument("--mirror", required=True, help="a local copy of the live bucket")
    parser.add_argument("--export", required=True, help="the board/1 export built from it")
    parser.add_argument(
        "--night-export", default=None, help="the night's own export, built with the store"
    )
    parser.add_argument("--ledger", required=True, help="ledger.jsonl")
    parser.add_argument("--attest", default=None, help="Andy's attestations (JSON)")
    parser.add_argument("--out", default=None, help="also write the text to this file")
    args = parser.parse_args(argv)
    mirror, export, ledger = Path(args.mirror), Path(args.export), Path(args.ledger)
    night = Path(args.night_export) if args.night_export else None
    for label, folder in (("--mirror", mirror), ("--export", export)):
        if not folder.is_dir():
            print(f"s4_live_report: {label} {folder} is not a folder", file=sys.stderr)
            return 1
    if not ledger.is_file():
        print(f"s4_live_report: --ledger {ledger} is not a file", file=sys.stderr)
        return 1
    continuity_path = _REPO_ROOT / CONTINUITY_FILE
    text = report_text(
        mirror,
        export,
        read_ledger(ledger),
        night_export=night,
        today=datetime.now(UTC).date(),
        dev_spend=development_spend(),
        attest=_attestations(Path(args.attest) if args.attest else None),
        continuity=continuity_path.read_text() if continuity_path.is_file() else None,
    )
    if CASE_NUMBER.search(text):
        # The report is built from counts, so this is a bug; it is checked on the output itself
        # because a report that names a live case must not be printed, written or committed.
        print(
            "s4_live_report: the report holds text shaped like an NTSB case number, so nothing "
            "was printed or written. Tell Claude.",
            file=sys.stderr,
        )
        return 1
    print(text, end="")
    if args.out:
        Path(args.out).write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
