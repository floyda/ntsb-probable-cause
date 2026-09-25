"""One evaluation run: cases → payloads → answering pass → scored results (spec §6)."""

import contextlib
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from ntsb_probable_cause import sources
from ntsb_probable_cause.data.build import investigation_class
from ntsb_probable_cause.docket import filter as docket_filter
from ntsb_probable_cause.docket.attach import prepare_attachment
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.manifest import Docket, read_docket
from ntsb_probable_cause.errors import (
    BatchNotFoundError,
    BudgetError,
    ConfigurationError,
    LeakageError,
    ModelError,
    SchemaError,
)
from ntsb_probable_cause.fields import (
    EvidenceRole,
    finding_codes,
    finding_codes_in_cause,
    occurrence_codes,
)
from ntsb_probable_cause.model.batch import BatchRequest, BatchResult, BatchStatus
from ntsb_probable_cause.model.client import (
    ModelClient,
    ModelReply,
    ModelSettings,
    Payload,
    Turn,
    cost_usd,
)
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.budget import (
    budget_lock,
    month_spent,
    open_reservations,
    reserve,
    settle,
)
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.hypothesis import (
    HYPOTHESIS_SCHEMA,
    REFINEMENT_SCHEMA,
    Hypothesis,
    parse_hypothesis,
    parse_refinement,
)
from ntsb_probable_cause.scoring.ledger import append_row, refuse_if_heldout_and_dirty
from ntsb_probable_cause.scoring.metrics import CaseScores, score_case
from ntsb_probable_cause.scoring.records import (
    CaseResult,
    EvidenceVersion,
    RunRecord,
    StepRecord,
    fingerprint,
    write_jsonl,
)
from ntsb_probable_cause.scoring.samples import arm_exclusions
from ntsb_probable_cause.splits import Split, split_of


@dataclass(frozen=True)
class RunSpec:
    """Everything that varies between runs (spec §2)."""

    sample: str
    arm: Literal["A", "B", "ceiling"]
    # Decision 0076: the evidence version this run reads the docket at. Refused past "v1"
    # until the reader that builds it exists (Task 14 for v2, Task 16 for v3).
    evidence_version: EvidenceVersion = "v1"
    exclusions: frozenset[EvidenceRole] = frozenset()
    include_case_number: bool = False
    model: str = sources.DEFAULT_MODEL
    reasoning_effort: sources.ReasoningEffort | None = sources.DEFAULT_REASONING_EFFORT
    # The reply budget, reasoning included (S2.6 Task 9A). Recorded on every run.
    max_output_tokens: int = 2000
    price_variant: Literal["batch", "standard"] = "batch"
    cap_usd: float = 0.05
    # Decision 0083: $40 a month during the development stages, until the live board (S4).
    budget_usd: float = 40.0
    sync: bool = False
    expected_cost_per_case_usd: float | None = None


SPEC_FILE = "spec.json"
BATCHES_FILE = "batches.jsonl"
RUN_FILE = "run.jsonl"


def spec_json(
    spec: RunSpec, *, commit_sha: str, dirty: bool, case_ids: Sequence[str]
) -> dict[str, object]:
    """Everything a run folder must record about the spec that produced it (0032 point 1).

    The key order is the order a resume checks the fields in, so the first difference
    reported is the shortest useful one; ``case_ids`` is last because a 400-case list makes
    the longest message.

    ``dirty`` is recorded beside the sha because a dirty tree means the code is *not* the
    sha: two runs can carry the same commit and different working trees. 0032 point 4 names
    only the sha, but its reason — that the replay is sound exactly when the spec and the
    code are identical — is what this enforces.

    Args:
        spec: the spec the run was started with.
        commit_sha: the runner's commit sha — a resume on different code is refused.
        dirty: whether the working tree carried uncommitted changes (0018).
        case_ids: the run's case ids, in order; what makes ``--limit`` safe to resume.

    Returns:
        A JSON-serialisable object, one key per recorded field.
    """
    return {
        "sample": spec.sample,
        "arm": spec.arm,
        "evidence_version": spec.evidence_version,
        "exclusions": sorted(role.value for role in spec.exclusions),
        "include_case_number": spec.include_case_number,
        "model": spec.model,
        "reasoning_effort": spec.reasoning_effort,
        "max_output_tokens": spec.max_output_tokens,
        "price_variant": spec.price_variant,
        "cap_usd": spec.cap_usd,
        "budget_usd": spec.budget_usd,
        "sync": spec.sync,
        "expected_cost_per_case_usd": spec.expected_cost_per_case_usd,
        "prompt_version": prompt.PROMPT_VERSION,
        "commit_sha": commit_sha,
        "dirty": dirty,
        "case_ids": list(case_ids),
    }


def write_spec_json(
    folder: Path, spec: RunSpec, *, commit_sha: str, dirty: bool, case_ids: Sequence[str]
) -> None:
    """Write ``spec.json`` into a run folder, creating the folder if it does not exist.

    The only writer of that file, so a folder repaired by hand (0032 point 5 calls that a
    deliberate, recorded act of recovery) is written by the same code that reads it and
    cannot drift from the reader's expectations.

    Args:
        folder: the run folder.
        spec: the spec the run was started with.
        commit_sha: the runner's commit sha.
        dirty: whether the working tree carried uncommitted changes.
        case_ids: the run's case ids, in order.
    """
    folder.mkdir(parents=True, exist_ok=True)
    recorded = spec_json(spec, commit_sha=commit_sha, dirty=dirty, case_ids=case_ids)
    (folder / SPEC_FILE).write_text(json.dumps(recorded, indent=2) + "\n")


def _json_lines(path: Path) -> list[tuple[int, dict[str, object]]]:
    """Every JSON object in a JSON-lines file, numbered, refusing a damaged line by name.

    A half-written final line is exactly what a killed process leaves behind, and these are
    the files a resume reads to find out what the dead run paid for. So a parse failure has
    to be a refusal an operator can act on — naming the file and the line — rather than a
    ``JSONDecodeError`` traceback past the command's own error handling.

    Args:
        path: the JSON-lines file to read.

    Returns:
        One ``(line number, object)`` pair per non-blank line, in order.

    Raises:
        ConfigurationError: a line is not readable JSON, or is not a JSON object.
    """
    rows: list[tuple[int, dict[str, object]]] = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ConfigurationError(
                f"cannot resume: {path} line {number} is not readable JSON "
                f"(a killed process leaves a half-written line behind): {error}"
            ) from error
        if not isinstance(row, dict):
            raise ConfigurationError(
                f"cannot resume: {path} line {number} does not hold a JSON object"
            )
        rows.append((number, row))
    return rows


def _nth(items: Sequence[object], index: int) -> object | None:
    """``items[index]``, or ``None`` past the end.

    So two lists can be compared position by position without minding which is longer.
    """
    return items[index] if index < len(items) else None


def case_ids_mismatch(recorded: object, current: object) -> str:
    """Why two case-id lists differ: the two counts, and the first index where they part.

    Never the lists themselves. On ``dev-400`` that would be two 401-element lists inside an
    exception message, and a refusal nobody can read is a refusal an operator works around
    rather than acts on. The counts alone usually say it — a resume with a different
    ``--limit`` is the case this check exists for — and the first differing index says it
    for a same-length list in a different order.

    Args:
        recorded: the ``case_ids`` value read from ``spec.json``.
        current: the ``case_ids`` of the run now asking to resume.

    Returns:
        One sentence naming the field and the difference.
    """
    if not isinstance(recorded, list) or not isinstance(current, list):
        return f"case_ids: the run recorded {recorded!r}, which is not a list of case ids"
    index = next(
        position
        for position in range(max(len(recorded), len(current)))
        if _nth(recorded, position) != _nth(current, position)
    )
    return (
        f"case_ids: the run recorded {len(recorded)} case ids and this one has "
        f"{len(current)}; the first difference is at index {index}, where the run recorded "
        f"{_nth(recorded, index)!r} and this one has {_nth(current, index)!r}"
    )


def refuse_sync_resume(spec: RunSpec, resume: str | None) -> None:
    """A sync run has no batches to resume from, so ``--resume`` on one is refused.

    What a resume reuses is a batch: one submitted, recorded, paid-for unit of work whose
    replies the provider still holds (0032 point 3). The sync path buys its replies one call
    at a time and records none of them, so adopting a run folder with ``--sync`` would
    re-call and re-pay for every case while reading, to the operator, as a resume that cost
    nothing. Refused here, beside the other pre-flight refusals, so it cannot be reached by
    a caller that skips the command line.

    Args:
        spec: the spec the run was started with.
        resume: the run id passed to ``--resume``, or ``None``.

    Raises:
        ConfigurationError: both ``--sync`` and ``--resume`` were given.
    """
    if resume is not None and spec.sync:
        raise ConfigurationError(
            f"--resume cannot be used with --sync: {resume} has no batches to resume from, "
            "because a sync run buys its replies one case at a time and records none of "
            "them. Drop --sync to resume a batch run, or start a new run."
        )


def refuse_finished(folder: Path) -> None:
    """Refuse to resume a run that already finished, which is nothing but a mis-pasted id.

    A completed run passes every other check — its spec matches, its batches are recorded —
    and resuming it would set its results aside to write them again. If the provider no
    longer holds those batches (they expire), the folder is left reporting ``finished=None``
    and a real result drops out of ``report --latest``, ``make bars`` and the month's spend.
    A judged folder is worse: the judge pass's own ``RunRecord`` row goes aside with the
    rest and nothing rewrites it, so that spend goes permanently invisible. Every row is
    checked, so a folder whose answering run never finished but which carries a finished
    judge pass is refused too — and the message names this folder's own run rather than the
    judge's synthetic ``<run-id>-judge``, which is not an id anyone can act on.

    A folder with **no** ``run.jsonl`` is not finished and is not refused: that is what a
    process killed before it could write anything leaves behind, which is the case this
    whole feature exists to recover.

    Args:
        folder: the run folder named by ``--resume``.

    Raises:
        ConfigurationError: the folder's ``run.jsonl`` already holds a finished record.
    """
    path = folder / RUN_FILE
    if not path.is_file():
        return
    for _number, row in _json_lines(path):
        finished = row.get("finished")
        if finished is None:
            continue
        what = (
            f"already finished at {finished}"
            if row.get("run_id") == folder.name
            else f"carries a finished judge pass, recorded at {finished}"
        )
        raise ConfigurationError(
            f"cannot resume {folder.name}: it {what}. Resuming it would set its results "
            "aside to write them again. Start a new run instead."
        )


def refuse_replay_mismatch(
    batch_id: str, requests: Sequence[BatchRequest], status: BatchStatus
) -> None:
    """Refuse a reused batch that answers cases this pass never asked about.

    An *unexpected* id is evidence of the wrong batch: the replay is supposed to reproduce
    the dead run's requests exactly (0032's Why), and a reply for a case this pass does not
    know about means it did not. Carrying on would score replies against the wrong records.

    A *missing* id is not that, and is deliberately not refused. The fresh path already
    tolerates it — ``_run_stage1_pass`` finds no result row for a custom id, files the case
    as ``model: no reply`` and retries it in the next batch — and a reused batch must not be
    held to a stricter standard than the batch it stands in for. Refusing here would make a
    partly-delivered batch unresumable *deterministically*: every retry would fail the same
    way, which is precisely the recovery this feature exists to perform (the stranded
    dev-400 batch has 3 of its 401 replies unusable).

    Args:
        batch_id: the recorded batch that was waited on instead of submitting.
        requests: the requests this pass replayed.
        status: the terminal status returned for the recorded batch.

    Raises:
        ConfigurationError: the batch answers ids this pass did not ask for.
    """
    wanted = {request.custom_id for request in requests}
    unexpected = sorted({result.custom_id for result in status.results} - wanted)
    if not unexpected:
        return
    raise ConfigurationError(
        f"cannot resume: recorded batch {batch_id} answers {len(unexpected)} cases this "
        f"pass never asked about (e.g. {unexpected[:3]}), so it is not the batch this "
        f"replay reproduces. It was waited on for {len(wanted)} cases."
    )


def refuse_unresumable(folder: Path, current: Mapping[str, object]) -> None:
    """Refuse a resume unless the folder records exactly the spec now being asked for.

    A resume replays the requests the dead run would have made and reads replies that run
    already paid for. That is only sound if the spec and the code are identical, so anything
    less than equality is refused rather than warned about (0032 point 4). A folder written
    before 0032 has no ``spec.json`` and is refused too (0032 point 5): there is nothing to
    check it against, and guessing the spec from the run id would put a permanently
    unverifiable branch into the harness.

    Args:
        folder: the run folder named by ``--resume``.
        current: ``spec_json`` for the spec and records this run was handed.

    Raises:
        ConfigurationError: the folder is missing, records no spec, or records a different
            one -- naming the first field that differs and both values.
    """
    if not folder.is_dir():
        raise ConfigurationError(f"cannot resume: no run folder at {folder}")
    refuse_finished(folder)
    path = folder / SPEC_FILE
    if not path.is_file():
        raise ConfigurationError(
            f"cannot resume: {path} is missing. A run folder written before decision 0032 "
            "records no spec, so there is nothing to check this resume against."
        )
    try:
        recorded = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise ConfigurationError(f"cannot resume: {path} is not readable JSON: {error}") from error
    if not isinstance(recorded, dict):
        raise ConfigurationError(f"cannot resume: {path} does not hold a JSON object")
    for name, value in current.items():
        was = recorded.get(name)
        if was != value:
            detail = (
                case_ids_mismatch(was, value)
                if name == "case_ids"
                else f"{name} was {was!r} when the run started, and is {value!r} now"
            )
            raise ConfigurationError(f"cannot resume {folder.name}: {detail}")


def recorded_batches(folder: Path) -> list[tuple[str, str, str | None]]:
    """The ``(stage, batch_id, recorded_time)`` rows of a run folder's ``batches.jsonl``.

    Every batch id is appended before its wait begins, so this is the complete list of
    batches the dead run paid for. An empty list where the file does not exist: a run that
    died before its first submit has nothing to reuse and simply runs from the start.
    ``recorded_time`` is the row's own ``time`` field (the moment the batch was recorded,
    used only to label a reused batch in the run log) and is ``None`` where a row predates
    that field or does not carry a string there -- the reuse itself does not depend on it.

    A batch the provider has since lost (``BatchNotFoundError``, task 7b) gets a second row
    for the same id, ``{"batch_id": ..., "stage": ..., "lost": true, "time": ...}``, appended
    wherever that is discovered -- not necessarily the row directly after it, since other
    batches may have been recorded first. Neither that row nor the original row for the lost
    id is returned here, however far apart they are: a lost batch has nothing left to reuse,
    and the stage that recorded it must be resubmitted fresh, exactly as if nothing had ever
    been recorded for it.

    Every batch recorded *after* a lost one in the dead run depended on its replies (stage 2's
    requests are built from stage 1's hypothesis, a retry's from the pass it retries) and so
    is not a valid replay of anything once the batch it depended on is gone (fix round 1). Each
    such batch gets its own row, ``{"batch_id": ..., "stage": ..., "superseded": true,
    "depends_on_batch_id": <the lost id>, "time": ...}``, appended the moment the loss is
    discovered (``Runner._submit_and_wait``, which also empties the in-memory reuse queue so
    the rest of the run submits every one of them fresh). Neither a ``superseded`` row nor the
    original row for a superseded id is returned here, for the same reason as a lost one.

    Nothing is ever deleted from ``batches.jsonl``; this only filters what is handed back.

    Args:
        folder: the run folder.

    Returns:
        One ``(stage, batch_id, recorded_time)`` triple per recorded, still-usable batch, in
        the order they were submitted.

    Raises:
        ConfigurationError: a line is damaged or records no stage and batch id.
    """
    path = folder / BATCHES_FILE
    if not path.is_file():
        return []
    rows: list[tuple[str, str, str | None, bool]] = []
    for number, row in _json_lines(path):
        stage, batch_id = row.get("stage"), row.get("batch_id")
        if not isinstance(stage, str) or not isinstance(batch_id, str):
            raise ConfigurationError(
                f"cannot resume: {path} line {number} records no stage and batch id: {row!r}"
            )
        time = row.get("time")
        unusable = row.get("lost") is True or row.get("superseded") is True
        rows.append((stage, batch_id, time if isinstance(time, str) else None, unusable))
    unusable_ids = {batch_id for _stage, batch_id, _time, unusable in rows if unusable}
    return [
        (stage, batch_id, time)
        for stage, batch_id, time, unusable in rows
        if not unusable and batch_id not in unusable_ids
    ]


RESULT_FILES = ("cases.jsonl", "steps.jsonl", RUN_FILE)


def set_aside_aborted_outputs(folder: Path) -> float:
    """Rename a dead run's result files out of the way, just before the resume writes its own.

    Every one of these files is appended to, and a resumed run re-derives all three from the
    same spec, the same code and the same replies. Left in place, the dead run's rows would
    be read ahead of the resumed run's: ``cases.jsonl`` would hold each case twice, once as
    an ``aborted: ...`` failure; ``month_spent`` would count the same spend from two
    ``RunRecord`` rows; and ``apps.eval.answering_run_record``, which takes the first row of
    ``run.jsonl``, would go on reporting the run as incomplete after it had finished. None
    of that is what 0032 point 2 means by the resumed run being the same run.

    **When** this happens matters as much as that it happens. Called at the top of a resume,
    it would leave the 30-to-100 minutes of the run itself with the dead run's spend renamed
    out of ``month_spent``'s sight — so a resume that was killed in its turn, which is the
    exact failure 0032 exists for, would lose the record of what the first run paid. It is
    therefore called immediately before the replacement files are written, on the success
    path and the abort path alike, leaving a window of microseconds.

    They are renamed, not deleted, for the same reason: they are the only surviving record
    of what the dead run paid for.

    Args:
        folder: the run folder being resumed.

    Returns:
        The dollars the superseded ``run.jsonl`` reported, which the replacement record must
        not report less than. The renamed file is outside ``month_spent``'s glob, so without
        that floor a resume that aborted before re-reading the dead run's replies would file
        a $0 record over a record of real spending and erase it from the month.
    """
    superseded = _superseded_cost(folder)
    for name in RESULT_FILES:
        path = folder / name
        if not path.is_file():
            continue
        stem = name.removesuffix(".jsonl")
        attempt = 1
        while (target := folder / f"{stem}.aborted-{attempt}.jsonl").exists():
            attempt += 1
        path.rename(target)
    return superseded


def _superseded_cost(folder: Path) -> float:
    """What the run records this resume is about to replace already reported spending.

    Read before the rename, since afterwards the file is no longer where anything looks for
    it. Every row counts, because every row is a row ``month_spent`` was counting.

    Args:
        folder: the run folder being resumed.

    Returns:
        The total ``cost_usd`` of the folder's current ``run.jsonl``, or ``0.0`` where there
        is none — a process killed before it wrote anything leaves no record to preserve.
    """
    path = folder / RUN_FILE
    if not path.is_file():
        return 0.0
    total = 0.0
    for _number, row in _json_lines(path):
        cost = row.get("cost_usd")
        if isinstance(cost, int | float):
            total += float(cost)
    return total


class BatchRunner(Protocol):
    """The subset of ``BatchClient`` the runner uses.

    A ``Protocol`` rather than importing ``BatchClient`` directly, so a scripted fake batch
    client can stand in structurally without inheriting from the real one (controller
    resolution 2 for Task 11).
    """

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        """Submit one batch of requests and return its id."""
        ...

    def wait(
        self, batch_id: str, *, on_status: Callable[[BatchStatus], None] = lambda _s: None
    ) -> BatchStatus:
        """Poll until the batch is terminal."""
        ...


def project_cost(spec: RunSpec, cases: int) -> float:
    """Cases times the measured cost per case, or the cap where there is no measurement (0030)."""
    per_case = (
        spec.expected_cost_per_case_usd
        if spec.expected_cost_per_case_usd is not None
        else spec.cap_usd
    )
    return cases * per_case


def refuse_over_budget(
    projected: float, month_spent: float, budget: float, *, reserved: float = 0.0
) -> None:
    """Refuse a run that would take the month past its budget, counting open reservations."""
    if month_spent + reserved + projected > budget:
        raise BudgetError(
            f"projected ${projected:.2f} plus ${month_spent:.2f} spent and ${reserved:.2f} "
            f"reserved by other runs exceeds the ${budget:.2f} budget"
        )


def refuse_sync_with_batch_price(spec: RunSpec) -> None:
    """A sync run cannot use the ``batch`` price variant: it is a different API endpoint.

    ``--sync`` sends every case straight to the chat-completions endpoint. The ``batch``
    price variant names a model id (``...:batch``) that the provider serves only through
    its separate batch-submission API, so a sync call against it fails every case with a
    404 after real requests have already gone out. Caught here, before any model call,
    alongside the budget and dirty-tree refusals -- so it cannot be bypassed by a caller
    that skips some other entry point.
    """
    if spec.sync and spec.price_variant == "batch":
        raise ConfigurationError(
            "--sync cannot use --price-variant batch: the batch model id is only served "
            "through the batch API. Pass --price-variant standard for a sync run, or drop "
            "--sync to use the batch service."
        )


def _reply_detail(reply: ModelReply) -> str:
    """The trailing detail a reply-format failure carries (S2.6 Task 9A).

    Appended to every ``schema:`` failure text, sync and batch alike, so a truncated or
    empty reply says why: the finish reason the provider gave and the token counts that let
    ``scripts/reply_budget.py`` tell a genuine schema violation from a reply cut short by
    ``max_output_tokens``. ``failure_summary`` (report.py) splits on the first ``":"``, so
    this trailing text never changes its counts.
    """
    return (
        f" (finish_reason={reply.finish_reason}, "
        f"completion_tokens={reply.usage.completion_tokens}, "
        f"reasoning_tokens={reply.usage.reasoning_tokens})"
    )


def _settings(spec: RunSpec, schema: dict[str, object], name: str) -> ModelSettings:
    """Model settings for one call; ``schema`` and ``name`` vary between the two stages."""
    return ModelSettings(
        model=spec.model,
        price_variant=spec.price_variant,
        reasoning_effort=spec.reasoning_effort,
        max_output_tokens=spec.max_output_tokens,
        json_schema=schema,
        schema_name=name,
    )


def _sample_split(sample: str) -> Split:
    """The split a sample name implies, from its prefix (``dev-400``, ``heldout-40``, ...)."""
    if sample.startswith("dev"):
        return Split.DEV
    if sample.startswith("heldout"):
        return Split.HELDOUT
    return Split.OPEN


class DocketReader(Protocol):
    """Where arm B (and later the loop) gets a case's docket from."""

    def read(self, mkey: int) -> Docket:
        """The docket for a case's internal key."""
        ...


class CachedDocketReader:
    """The real reader: the client's cache (spec §7.1). Decision 0056: no deny-list to apply."""

    def __init__(self, client: DocketClient) -> None:
        self._client = client

    def read(self, mkey: int) -> Docket:
        """The docket for a case's internal key, fetched (or read from cache) and classified."""
        return read_docket(self._client, mkey)


@dataclass(frozen=True)
class Prepared:
    """Everything one case needs before its first call, and what the attach step did."""

    payload: Payload
    system: str
    verdict: Verdict
    evidence: Evidence
    attached: tuple[int, ...] = ()
    not_read: tuple[str, ...] = ()
    not_available: tuple[str, ...] = ()
    documents_attached: tuple[str, ...] = ()


# The two evidence roles arm B is defined by (spec §7.1). Excluding either one leaves the
# payload unable to grow as documents are attached, so the cap never binds and the loop
# silently attaches everything while the model never sees any of it (fix round 1, Finding 2).
_DOCKET_ROLES = frozenset({EvidenceRole.DOCKET_LISTING, EvidenceRole.DOCKET_DOCUMENTS})


def _system_text(raw: Mapping[str, object], spec: RunSpec, tables: CodeTables, case_id: str) -> str:
    """The case-number line exists on development cases alone.

    The probe is refused unless *both* the run's sample name implies development and the
    record's own event date falls in the development split (spec §6.2: "development split
    only, refused on any other sample"). Checking the sample alone would let a run labelled
    ``dev-400`` leak a case number on a record that is not actually a development case;
    checking the date alone would not refuse a run explicitly requested against a held-out
    sample when it is (as in this module's own tests) handed a development-dated record.
    """
    case_number: str | None = None
    if spec.include_case_number:
        event = date.fromisoformat(str(raw["eventDate"])[:10])
        if _sample_split(spec.sample) is not Split.DEV or split_of(event) is not Split.DEV:
            raise LeakageError(
                f"{case_id}: the case number may be included on development cases only"
            )
        case_number = case_id
    return f"{prompt.SYSTEM_ANSWER}\n\n{prompt.tables_block(tables, case_number=case_number)}"


def _split_and_render(
    context: Mapping[str, object], spec: RunSpec
) -> tuple[Evidence, Verdict, Payload]:
    evidence, _, verdict = split_record(context, exclude=spec.exclusions | arm_exclusions(spec.arm))
    return evidence, verdict, Payload.from_evidence(evidence)


def prepare_case(
    raw: Mapping[str, object], spec: RunSpec, tables: CodeTables, docket: Docket | None
) -> Prepared:
    """The only route to a payload. Arm B attaches whole documents, smallest first, up to the cap.

    Decision 0043: documents are added one at a time; the first that would take the case
    over the cap stops the loop, and it and every document after it are recorded as
    ``not read: cap`` with their estimated tokens. Every trial context goes through the split,
    so the tripwire runs on every document that is attached.

    Decisions 0052, 0054, 0056: every readable document is weighed against the cap -- there is
    no longer a category-based filter that can exclude one before that loop ever sees it.
    """
    evidence, verdict, payload = _split_and_render(raw, spec)
    system = _system_text(raw, spec, tables, evidence.case_id)
    if spec.arm != "B":
        return Prepared(payload, system, verdict, evidence)
    excluded_docket_roles = (spec.exclusions | arm_exclusions(spec.arm)) & _DOCKET_ROLES
    if excluded_docket_roles:
        names = ", ".join(sorted(role.value for role in excluded_docket_roles))
        raise ConfigurationError(
            f"arm B cannot exclude the docket it is defined by: {names} excluded"
        )
    if docket is None:
        raise ConfigurationError("arm B needs a docket reader")
    ordered = docket_filter.arm_b_documents(docket)
    attachment = prepare_attachment(raw, docket)
    attached: list[int] = []
    not_read: list[str] = []
    result = attachment.context_for(attached)
    evidence, verdict, payload = _split_and_render(result.context, spec)
    for position, index in enumerate(ordered):
        trial = attachment.context_for([*attached, index])
        trial_evidence, trial_verdict, trial_payload = _split_and_render(trial.context, spec)
        if over_cap(trial_payload.text, system, spec):
            not_read.extend(
                f"{i}: cap, {docket.record(i).estimated_tokens} tokens" for i in ordered[position:]
            )
            break
        attached.append(index)
        result, evidence, verdict, payload = trial, trial_evidence, trial_verdict, trial_payload
    documents_attached = tuple(
        f"{i}: {docket.record(i).category}, {docket.record(i).estimated_tokens} tokens"
        for i in attached
    )
    return Prepared(
        payload,
        system,
        verdict,
        evidence,
        tuple(attached),
        tuple(not_read),
        result.not_available,
        documents_attached,
    )


def case_payload(
    raw: Mapping[str, object], spec: RunSpec, tables: CodeTables
) -> tuple[Payload, str, Verdict, Evidence]:
    """The one-call arms' payload; kept for callers that predate arm B."""
    prepared = prepare_case(raw, spec, tables, None)
    return prepared.payload, prepared.system, prepared.verdict, prepared.evidence


# A case is answered in two model calls, not one (spec §3.4 / fix finding 1): stage 1
# (hypothesis) and stage 2 (refinement) each send the same payload and system text and
# each reserve the same maximum output. Named so it is never scattered through the file as
# a bare literal. Retries (one per stage, on a schema rejection) are not counted, so an
# estimate built from this constant is a floor on what a case can cost, not a ceiling.
ANSWERING_TURNS = 2


def estimated_cost_usd(payload_text: str, system: str, spec: RunSpec) -> float:
    """The estimated cost of answering one case: ``ANSWERING_TURNS`` calls, not one.

    One call is the prompt at one token per four characters at the input price, plus the
    maximum output at the output price -- the output reserve is what the S1 cap ignored
    (spec §3.4): with the default model it is a tenth of a cent, with Sonnet 5 at its
    standard price two cents of a five-cent cap. A case pays that twice: the same payload
    and system text are sent again on the stage-2 (refinement) turn, and the output reserve
    applies to that turn too. Retries are not included, so this is a floor on a case's cost,
    not the worst case.
    """
    settings = _settings(spec, HYPOTHESIS_SCHEMA, "hypothesis")
    price = sources.price_of(settings.model_id())
    prompt_tokens = (len(payload_text) + len(system)) / 4
    call_cost = (
        prompt_tokens * price.input_usd_per_mtok
        + settings.max_output_tokens * price.output_usd_per_mtok
    ) / 1e6
    return ANSWERING_TURNS * call_cost


def over_cap(payload_text: str, system: str, spec: RunSpec) -> bool:
    """Would answering the case (both calls) cost more than the cap?"""
    return estimated_cost_usd(payload_text, system, spec) > spec.cap_usd


@dataclass
class _CaseContext:
    """Per-case working state, kept from the payload build until the case has a result.

    ``stage1_content`` pins the *accepted* stage-1 reply's text once, for the stage-2 turn's
    history: a batch run may resubmit stage 2 as a retry batch, and ``replies[-1]`` at that
    point is the *rejected* stage-2 reply, not the stage-1 hypothesis (fix round 1, Important
    1). The sync path pins the same content into a local ``history`` tuple and reuses it for
    both stage-2 attempts, so it never had this bug.
    """

    raw: Mapping[str, object]
    evidence: Evidence
    verdict: Verdict
    payload: Payload
    system: str
    spec: RunSpec
    attached: tuple[int, ...] = ()
    not_read: tuple[str, ...] = ()
    not_available: tuple[str, ...] = ()
    documents_attached: tuple[str, ...] = ()
    replies: list[ModelReply] = field(default_factory=list)
    stage1_content: str | None = None
    # The last SchemaError's reply detail (S2.6 Task 9A fix round 1): kept apart from the
    # batch path's ``need_retry`` error text, which is also sent back to the model as the
    # retry prompt ("Your previous reply was rejected: ..."). That text must stay exactly
    # what it was before this task -- the detail is appended only when a case's *failure* is
    # finally recorded, by ``_fail_case``, never by ``_retry_system``/``_stage2_system``.
    schema_detail: str | None = None


@dataclass
class _BatchRun:
    """Mutable state threaded through one batch answering pass (spec §7.2).

    ``costs`` holds one entry per batch submitted, in order, ``None`` where that batch did
    not report a cost — so the caller can tell a genuine total from a partial one (fix round
    1, Minor 4) instead of silently summing only the batches that happened to report.

    ``reusable`` is the resume queue: the ``(stage, batch_id)`` rows this run's folder
    already recorded, emptied as ``_submit_and_wait`` consumes them (0032 point 3). It lives
    here, not on ``Runner``, because a ``Runner`` is reused across runs and this queue
    belongs to one answering pass.
    """

    folder: Path
    reusable: list[tuple[str, str, str | None]] = field(default_factory=list)
    contexts: dict[str, _CaseContext] = field(default_factory=dict)
    results: dict[str, CaseResult] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    hyps: dict[str, Hypothesis] = field(default_factory=dict)
    finals: dict[str, Hypothesis] = field(default_factory=dict)
    batch_ids: list[str] = field(default_factory=list)
    costs: list[float | None] = field(default_factory=list)


class Runner:
    """Runs one RunSpec over raw records and writes the records (spec §6.4)."""

    def __init__(  # noqa: PLR0913 -- fixed by the plan's Interfaces block.
        self,
        client: ModelClient,
        *,
        batch: BatchRunner | None,
        tables: CodeTables,
        seen_pairs: frozenset[str],
        runs_dir: Path,
        ledger_path: Path,
        month_spent_usd: float,
        commit: tuple[str, bool],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        docket: DocketReader | None = None,
    ) -> None:
        self._client = client
        self._batch = batch
        self._tables = tables
        self._seen = seen_pairs
        self._runs_dir = runs_dir
        self._ledger = ledger_path
        self._spent = month_spent_usd
        self._sha, self._dirty = commit
        self._now = now
        self._docket = docket

    def run(  # noqa: PLR0915 -- the evidence-version refusal adds one line to an already-long method.
        self,
        spec: RunSpec,
        raws: Sequence[Mapping[str, object]],
        *,
        resume: str | None = None,
    ) -> RunRecord:
        """Run every case, write three JSON-lines files, append the ledger for held-out samples.

        On any exception once answering has started — a batch ending badly, an arm A or
        ceiling case's ``LeakageError`` (arm B's own docket tripwire fails the case, not the
        run: see ``_leaked_case``, fix finding 4), a ``KeyboardInterrupt`` while a real
        batch's ``wait`` is polling, anything, ``BaseException`` included — the cases and
        cost paid so far are still written (``finished=None`` marks the run incomplete)
        before the exception is re-raised, so a crashed or interrupted run's spend is never
        invisible to the next run's budget check (fix round 1, Important 2; widened to
        ``BaseException`` in fix round 2, Minor 1, since Ctrl-C during a long real-run
        ``wait`` is the most likely real mid-run abort and ``except Exception`` does not
        catch it). On a resume that holds for the superseded attempt's spend as well: the
        record written never reports less ``cost_usd`` than the record it replaces, so the
        handover from one attempt to the next cannot lose money either.

        Args:
            spec: what varies between runs.
            raws: the raw records to answer, in order.
            resume: a run id to continue instead of starting a new run (0032). The recorded
                id and folder are adopted, so the resumed run is the same run and not a
                second one that duplicates it, and every batch already recorded for a stage
                is waited on rather than submitted again. ``started`` is still this moment:
                the run id already carries the original start time.

        Returns:
            The run's own ``RunRecord``, also written to ``run.jsonl``.

        Raises:
            ConfigurationError: a resume asked for alongside ``--sync``, or one naming a
                folder that does not exist, records no spec, or records a different spec
                than the one passed in.
        """
        refuse_if_heldout_and_dirty(spec.sample, self._dirty)
        refuse_sync_with_batch_price(spec)
        refuse_sync_resume(spec, resume)
        if spec.evidence_version != "v1":
            # Replaced in Task 14 (v2) and Task 16 (v3) by the readers that build them.
            raise ConfigurationError(f"evidence version {spec.evidence_version} is not built yet")
        started = self._now()
        case_ids = [str(raw["ntsbNumber"]) for raw in raws]
        reusable: list[tuple[str, str, str | None]] = []
        if resume is None:
            run_id = f"{started:%Y%m%dT%H%M%S}-{self._sha}-{spec.sample}-{spec.arm}"
            folder = self._runs_dir / run_id
            # Before the first model call, so a folder that dies early still describes
            # itself (0032 point 1).
            write_spec_json(
                folder, spec, commit_sha=self._sha, dirty=self._dirty, case_ids=case_ids
            )
        else:
            run_id = resume
            folder = self._runs_dir / run_id
            refuse_unresumable(
                folder,
                spec_json(spec, commit_sha=self._sha, dirty=self._dirty, case_ids=case_ids),
            )
            reusable = recorded_batches(folder)
        if spec.arm == "B" and self._docket is None:
            raise ConfigurationError("arm B needs a docket reader")
        self._reserve_budget(spec, run_id, len(raws), started)
        self._log_header(spec, run_id, len(case_ids), resumed=resume is not None)
        results: list[CaseResult] = []
        batch_ids: tuple[str, ...] = ()
        reported_batch_cost: float | None = None

        def build_record(finished: datetime | None, cost_floor: float) -> RunRecord:
            return RunRecord(
                run_id=run_id,
                sample=spec.sample,
                arm=spec.arm,
                evidence_version=spec.evidence_version,
                exclusions=tuple(sorted(e.value for e in spec.exclusions)),
                includes=("case_number",) if spec.include_case_number else (),
                prompt_version=prompt.PROMPT_VERSION,
                model=spec.model,
                reasoning_effort=spec.reasoning_effort,
                price_variant=spec.price_variant,
                cap_usd=spec.cap_usd,
                budget_usd=spec.budget_usd,
                max_output_tokens=spec.max_output_tokens,
                commit_sha=self._sha,
                dirty=self._dirty,
                started=started,
                finished=finished,
                batch_ids=batch_ids,
                cases=len(results),
                # Never less than the record this one supersedes (``cost_floor``): a
                # resumed run carries the same run id, and the batches the superseded
                # attempt paid for belong to it. Without the floor, a resume that aborted
                # before re-reading those replies would file a $0 record over a record of
                # real spending, and ``month_spent`` — which globs ``*/run.jsonl`` and so
                # cannot see the renamed file — would lose it. On the ordinary path the
                # floor is inert: this run re-prices every reply the dead one read.
                cost_usd=max(sum(r.cost_usd for r in results), cost_floor),
                reported_batch_cost_usd=reported_batch_cost,
            )

        def write_outputs(finished: datetime | None) -> RunRecord:
            """The dead run's files aside (resume only), then this run's three files.

            The set-aside happens here, a moment before the replacement files are written,
            and not at the top of the resume: until this point the dead run's ``run.jsonl``
            is the only record of what it paid, and a resume that is killed in its turn
            must not be the thing that loses it. What that record reported becomes the
            floor under this one, so the handover never loses money either.
            """
            cost_floor = set_aside_aborted_outputs(folder) if resume is not None else 0.0
            self._write_files(folder, results)
            record = build_record(finished, cost_floor)
            write_jsonl(folder / RUN_FILE, [record])
            settle(self._runs_dir, run_id)
            return record

        try:
            if spec.sync:
                for raw in raws:
                    results.append(self._answer_case(raw, spec))
            else:
                batch_run = _BatchRun(folder=folder, reusable=reusable)
                try:
                    self._answer_batch(raws, spec, batch_run)
                finally:
                    results = [
                        batch_run.results[cid]
                        for cid in batch_run.order
                        if cid in batch_run.results
                    ]
                    batch_ids = tuple(batch_run.batch_ids)
                    reported_batch_cost = self._reported_total(batch_run.costs)
        except BaseException:
            write_outputs(None)
            raise

        record = write_outputs(self._now())
        if spec.sample.startswith("heldout"):
            append_row(self._ledger, record, str(folder / "cases.jsonl"))
        return record

    # --- shared helpers (sync and batch) ---

    def _reserve_budget(self, spec: RunSpec, run_id: str, cases: int, started: datetime) -> None:
        """Refuse the run if its projected cost would bust the budget, then reserve it (0045).

        Held under the runs directory's lock: the caller's ``self._spent`` figure is only a
        floor, so ``month_spent`` is re-read here in case a run finished a moment ago, and
        every other run's open reservation is added to what this run must fit under.
        """
        projected = project_cost(spec, cases)
        with budget_lock(self._runs_dir):
            spent = max(self._spent, month_spent(self._runs_dir, now=started))
            reserved = sum(v for k, v in open_reservations(self._runs_dir).items() if k != run_id)
            refuse_over_budget(projected, spent, spec.budget_usd, reserved=reserved)
            reserve(self._runs_dir, run_id, projected, now=started)

    def _prepare(self, raw: Mapping[str, object], spec: RunSpec) -> Prepared:
        docket: Docket | None = None
        if spec.arm == "B":
            if self._docket is None:
                raise ConfigurationError(
                    "arm B needs a docket reader (--arm B reads the docket cache)"
                )
            mkey = raw.get("mKey")
            if not isinstance(mkey, int):
                raise ConfigurationError(f"{raw.get('ntsbNumber')}: no mKey, so no docket")
            docket = self._docket.read(mkey)
        return prepare_case(raw, spec, self._tables, docket)

    @staticmethod
    def _write_files(folder: Path, results: Sequence[CaseResult]) -> None:
        """cases.jsonl and steps.jsonl; called both on success and on a mid-run abort."""
        write_jsonl(folder / "cases.jsonl", results)
        write_jsonl(folder / "steps.jsonl", (s for r in results for s in r.steps))

    @staticmethod
    def _reported_total(costs: Sequence[float | None]) -> float | None:
        """Sum of batch-level reported costs; ``None`` if any batch stayed silent (Minor 4)."""
        if not costs or any(c is None for c in costs):
            return None
        return sum(c for c in costs if c is not None)

    def _cost(self, replies: Sequence[ModelReply], spec: RunSpec) -> float:
        """Dollars for a case, summed over every reply obtained for it (even failed ones)."""
        settings = _settings(spec, HYPOTHESIS_SCHEMA, "hypothesis")
        return sum(cost_usd(reply, settings)[0] for reply in replies)

    def _step(self, ctx: _CaseContext, hypothesis: Hypothesis, cost: float) -> StepRecord:
        is_arm_b = ctx.spec.arm == "B"
        return StepRecord(
            case_id=ctx.evidence.case_id,
            step=0,
            arm=ctx.spec.arm,
            condition="full",
            day=None,
            tool="docket" if is_arm_b else "none",
            arguments={"documents": list(ctx.attached)} if is_arm_b else {},
            reason="",
            expected_effect="",
            returned_roles=tuple(sorted(ctx.payload.fields())),
            not_available=ctx.not_available,
            documents_attached=ctx.documents_attached,
            documents_not_read=ctx.not_read,
            payload_fingerprint=fingerprint(ctx.payload),
            hypothesis=hypothesis,
            observed_effect="",
            stop_reason="abstained" if hypothesis.abstain else "answered",
            model=ctx.spec.model,
            price_variant=ctx.spec.price_variant,
            prompt_tokens=sum(r.usage.prompt_tokens for r in ctx.replies),
            completion_tokens=sum(r.usage.completion_tokens for r in ctx.replies),
            reasoning_tokens=(
                sum(r.usage.reasoning_tokens or 0 for r in ctx.replies)
                if any(r.usage.reasoning_tokens is not None for r in ctx.replies)
                else None
            ),
            reply_completion_tokens=tuple(r.usage.completion_tokens for r in ctx.replies),
            reply_reasoning_tokens=tuple(r.usage.reasoning_tokens for r in ctx.replies),
            reply_finish_reasons=tuple(r.finish_reason for r in ctx.replies),
            cost_usd=cost,
            cumulative_cost_usd=cost,
            commit_sha=self._sha,
            dirty=self._dirty,
        )

    def _case_result(
        self,
        ctx: _CaseContext,
        steps: tuple[StepRecord, ...],
        scores: CaseScores | None,
        cost: float,
        failure: str | None,
    ) -> CaseResult:
        event = date.fromisoformat(str(ctx.raw["eventDate"])[:10])
        flavour = ctx.raw.get("factualFinalReportFlavor")
        return CaseResult(
            case_id=ctx.evidence.case_id,
            split=split_of(event).value,
            fatal=ctx.raw.get("highestInjuryLevel") == "Fatal",
            investigation_class=investigation_class(ctx.evidence.case_id),
            report_flavour=str(flavour) if flavour is not None else None,
            verdict_occurrence=ctx.verdict.occurrence_codes,
            verdict_findings=ctx.verdict.finding_codes,
            verdict_findings_in_cause=ctx.verdict.finding_codes_in_cause,
            steps=steps,
            scores=scores,
            cost_usd=cost,
            failure=failure,
            # Set from ``ctx``, not from ``steps``: a case whose base prompt (with whatever
            # documents made it in) is still over the cap fails via ``_failed`` before any
            # step is built (``steps=()``), and that is exactly the case that dropped the
            # most of the docket -- ``cap_summary`` must see it too (fix round 1, Finding 4).
            documents_not_read=ctx.not_read,
            # Every reply the case received, in call order, whether it was scored or failed
            # (S2.6 Task 9C) -- the same source ``_step`` reads, but recorded here so a
            # failed case (``steps=()``) still carries it. Empty when ``ctx.replies`` is
            # empty (a "cap" failure made no call).
            reply_completion_tokens=tuple(r.usage.completion_tokens for r in ctx.replies),
            reply_reasoning_tokens=tuple(r.usage.reasoning_tokens for r in ctx.replies),
            reply_finish_reasons=tuple(r.finish_reason for r in ctx.replies),
        )

    def _failed(
        self, ctx: _CaseContext, failure: str, cost: float, steps: tuple[StepRecord, ...] = ()
    ) -> CaseResult:
        return self._case_result(ctx, steps, None, cost, failure)

    def _result(
        self, ctx: _CaseContext, steps: tuple[StepRecord, ...], scores: CaseScores, cost: float
    ) -> CaseResult:
        return self._case_result(ctx, steps, scores, cost, None)

    @staticmethod
    def _leaked_case(raw: Mapping[str, object], error: LeakageError) -> CaseResult:
        """An arm B case whose ``_prepare`` tripped the leakage guard: fails alone, closed (fix 4).

        ``self._prepare`` runs ``split_record`` on the base payload and, for arm B, on every
        trial payload as documents are attached smallest first -- so a hit can come from any
        one document in a docket, not just the first. Spec §6.5's "a hit fails the case
        closed" names the case, not the run: every arm B case reads a docket, and one false
        trip on one document's prose must not abort a batch that has already paid for the
        rest of it. Callers use this only for arm B (``_answer_case`` and
        ``_prepare_contexts`` re-raise a ``LeakageError`` from any other arm): a ceiling or
        arm A case never reads untrusted docket prose, so a leak there points at the
        evidence fields themselves, not per-case variance in document text, and stays a
        loud, run-aborting bug rather than a silent per-case failure.

        Because ``split_record`` raised instead of returning, there is no ``Evidence`` or
        ``Verdict`` object to read the report's fields from. This rebuilds only the verdict
        fields the report needs, calling the same pure extraction functions
        ``split_record`` already called before it decided to raise -- never re-run through
        the guard, since nothing here is at risk of reaching a model. ``error.args[0]``
        (``LeakageError``'s own message) names role, kind and source only, never the
        withheld text (decision 0016), so it is safe to record in ``failure`` and, from
        there, in a committed run folder.

        Args:
            raw: the case's raw record.
            error: the ``LeakageError`` ``self._prepare`` raised.

        Returns:
            A ``CaseResult`` with no steps and no scores, ``cost_usd=0.0`` (no model call was
            made), and ``failure`` prefixed ``"leak:"`` so it reads distinctly from ``"cap"``,
            ``"schema:"`` and ``"model:"`` in a run's failure list. Unlike a "cap" failure
            (fix round 1, Finding 4), ``documents_not_read`` is deliberately left empty here:
            ``self._prepare`` raised instead of returning a ``Prepared``, so whatever the cap
            loop had or had not attached or dropped at the moment of the trip is not
            available to read -- there is nothing truthful, rather than merely nothing, to
            put in the field (re-review round 2, minor).
        """
        case_id = str(raw["ntsbNumber"])
        event = date.fromisoformat(str(raw["eventDate"])[:10])
        flavour = raw.get("factualFinalReportFlavor")
        return CaseResult(
            case_id=case_id,
            split=split_of(event).value,
            fatal=raw.get("highestInjuryLevel") == "Fatal",
            investigation_class=investigation_class(case_id),
            report_flavour=str(flavour) if flavour is not None else None,
            verdict_occurrence=occurrence_codes(raw),
            verdict_findings=finding_codes(raw),
            verdict_findings_in_cause=finding_codes_in_cause(raw),
            steps=(),
            scores=None,
            cost_usd=0.0,
            failure=f"leak: {error}",
            documents_not_read=(),
        )

    # --- the sync path ---

    def _answer_case(self, raw: Mapping[str, object], spec: RunSpec) -> CaseResult:
        try:
            prepared = self._prepare(raw, spec)
        except LeakageError as error:
            if spec.arm != "B":
                raise
            return self._leaked_case(raw, error)
        ctx = _CaseContext(
            raw=raw,
            evidence=prepared.evidence,
            verdict=prepared.verdict,
            payload=prepared.payload,
            system=prepared.system,
            spec=spec,
            attached=prepared.attached,
            not_read=prepared.not_read,
            not_available=prepared.not_available,
            documents_attached=prepared.documents_attached,
        )
        if over_cap(prepared.payload.text, prepared.system, spec):
            return self._failed(ctx, "cap", 0.0)
        hypothesis: Hypothesis | None = None
        failure: str | None = None
        try:
            hypothesis = self._two_turns(ctx)
        except SchemaError as error:
            failure = f"schema: {error}{_reply_detail(ctx.replies[-1])}"
        except ModelError as error:
            failure = f"model: {error}"
        cost = self._cost(ctx.replies, spec)
        if failure is not None or hypothesis is None:
            return self._failed(ctx, failure or "model: no reply", cost)
        scores = score_case(hypothesis, ctx.verdict, self._tables, seen_pairs=self._seen)
        step = self._step(ctx, hypothesis, cost)
        return self._result(ctx, (step,), scores, cost)

    def _two_turns(self, ctx: _CaseContext) -> Hypothesis:
        """Stage 1 then stage 2, each with one retry on a schema error.

        ``ctx.replies`` is appended to as calls are made, including calls that end up
        failing, so the caller can still price a case that never produced a usable answer
        (controller resolution: the brief's version returned replies only on success, which
        recorded $0 for a case that made two real calls and failed both — see the Deviations
        log).
        """
        spec, payload, system = ctx.spec, ctx.payload, ctx.system
        first = self._client.complete(
            payload, _settings(spec, HYPOTHESIS_SCHEMA, "hypothesis"), system=system
        )
        ctx.replies.append(first)
        try:
            hypothesis = parse_hypothesis(first.content or "", self._tables)
        except SchemaError as error:
            retry = self._client.complete(
                payload,
                _settings(spec, HYPOTHESIS_SCHEMA, "hypothesis"),
                system=f"{system}\n\nYour previous reply was rejected: {error}",
            )
            ctx.replies.append(retry)
            hypothesis = parse_hypothesis(retry.content or "", self._tables)
        if hypothesis.abstain or not hypothesis.findings:
            return hypothesis
        history = (Turn(role="assistant", content=ctx.replies[-1].content),)
        refine_system = (
            f"{prompt.SYSTEM_REFINE}\n\n{prompt.refine_message(hypothesis, self._tables)}"
        )
        second = self._client.complete(
            payload,
            _settings(spec, REFINEMENT_SCHEMA, "refinement"),
            system=refine_system,
            history=history,
        )
        ctx.replies.append(second)
        try:
            return parse_refinement(second.content or "", self._tables, hypothesis)
        except SchemaError as error:
            retry = self._client.complete(
                payload,
                _settings(spec, REFINEMENT_SCHEMA, "refinement"),
                system=f"{refine_system}\n\nYour previous reply was rejected: {error}",
                history=history,
            )
            ctx.replies.append(retry)
            return parse_refinement(retry.content or "", self._tables, hypothesis)

    # --- the batch path ---

    _STAGE_WIDTH = 13  # the longest stage name ("stage1-retry"/"stage2-retry") plus a gap
    _WORD_WIDTH = 11  # "SUPERSEDED" (10 chars) plus a gap; every other word pads out to match
    _STATUS_WIDTH = 12  # "in_progress" (11 chars) plus a gap
    _COUNTS_WIDTH = 10  # "9999/9999" (9 chars, a large batch) plus a gap

    def _log_header(self, spec: RunSpec, run_id: str, case_count: int, *, resumed: bool) -> None:
        """One line naming a run as it starts: the same facts as ``spec.json`` (§4).

        Written after the pre-flight refusals and the folder/spec bookkeeping, so a log
        found later -- while the run is still in flight -- identifies itself the same way
        the run folder does, without having to open ``spec.json``.
        """
        word = "RESUMED" if resumed else "FRESH"
        self._write_log_line(
            lambda: (
                f"run {run_id} {word} sample={spec.sample} arm={spec.arm} cases={case_count} "
                f"model={spec.model} price={spec.price_variant}"
            )
        )

    def _write_log_line(self, build_body: Callable[[], str]) -> None:
        """Every run-log line: the wall clock (UTC, marked), then the built body, to stderr only.

        ``build_body`` is called *inside* the guard, not by the caller before this is reached
        (fix round 2, I1): the brief says "a logging failure must never kill a run", and a
        defect in formatting -- not only in the final ``write`` -- is exactly the kind of
        logging failure that must never reach ``wait()`` and abort a paid batch mid-flight.
        Catching bare ``Exception`` is deliberate and total: ``OSError`` covers a closed
        pipe, ``ValueError`` covers writing to a *closed* file object (the case the brief's
        docstring names), and nothing narrower can promise "never" for code that will go on
        changing after this fix.
        """
        with contextlib.suppress(Exception):
            sys.stderr.write(f"{self._now():%H:%M:%S}Z {build_body()}\n")

    @staticmethod
    def _format_counts(status: BatchStatus) -> tuple[str, str]:
        """``completed/total`` and the failed count, each ``-`` where the provider did not say."""
        counts = status.counts
        completed = "-" if counts.completed is None else str(counts.completed)
        total = "-" if counts.total is None else str(counts.total)
        failed = "-" if counts.failed is None else str(counts.failed)
        return f"{completed}/{total}", failed

    @staticmethod
    def _format_elapsed(elapsed: timedelta) -> str:
        """``NmNNs``, or ``NhNNm`` once the elapsed time passes an hour (brief format)."""
        total_seconds = max(0, int(elapsed.total_seconds()))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}h{minutes:02d}m"
        return f"{minutes}m{seconds:02d}s"

    def _log_status(self, stage: str, status: BatchStatus, wait_started: datetime) -> None:
        """One line per poll: status, counts, cost (if reported) and elapsed since waiting began.

        ``wait_started`` is the moment ``_submit_and_wait`` began waiting on this batch, not
        anything the provider reports (controller resolution 3), so elapsed is meaningful
        even across a resume that waits on a batch recorded long before this process started.
        """

        def body() -> str:
            counts_str, failed_str = self._format_counts(status)
            elapsed = self._format_elapsed(self._now() - wait_started)
            cost = "" if status.reported_cost_usd is None else f" ${status.reported_cost_usd:.4f}"
            stage_field = stage.ljust(self._STAGE_WIDTH)
            status_field = status.status.ljust(self._STATUS_WIDTH)
            counts_field = counts_str.ljust(self._COUNTS_WIDTH)
            return f"{stage_field}{status_field}{counts_field}failed={failed_str}{cost} ({elapsed})"

        self._write_log_line(body)

    def _log_reused(self, stage: str, batch_id: str, recorded_time: str | None) -> None:
        """One line when a stage waits on a recorded batch instead of submitting: no new money."""

        def body() -> str:
            recorded = self._format_recorded_time(recorded_time)
            stage_field = stage.ljust(self._STAGE_WIDTH)
            word_field = "REUSED".ljust(self._WORD_WIDTH)
            return f"{stage_field}{word_field}{batch_id} (recorded {recorded})"

        self._write_log_line(body)

    def _log_lost(self, stage: str, batch_id: str) -> None:
        """One line when a reused batch has vanished at the provider: it is resubmitted fresh."""

        def body() -> str:
            stage_field = stage.ljust(self._STAGE_WIDTH)
            word_field = "LOST".ljust(self._WORD_WIDTH)
            return (
                f"{stage_field}{word_field}{batch_id} no longer exists at the provider; "
                "submitting afresh (new money)"
            )

        self._write_log_line(body)

    def _log_superseded(self, stage: str, batch_id: str, lost_batch_id: str) -> None:
        """One line per downstream batch dropped because the batch it depended on is lost."""

        def body() -> str:
            stage_field = stage.ljust(self._STAGE_WIDTH)
            word_field = "SUPERSEDED".ljust(self._WORD_WIDTH)
            return (
                f"{stage_field}{word_field}{batch_id} depended on {lost_batch_id}, which is "
                "lost; submitting afresh (new money)"
            )

        self._write_log_line(body)

    def _log_submitted(self, stage: str, batch_id: str, request_count: int) -> None:
        """One line when a stage submits a fresh batch (§3): new money, and how much of it."""

        def body() -> str:
            plural = "request" if request_count == 1 else "requests"
            stage_field = stage.ljust(self._STAGE_WIDTH)
            word_field = "SUBMITTED".ljust(self._WORD_WIDTH)
            return f"{stage_field}{word_field}{batch_id} {request_count} {plural}"

        self._write_log_line(body)

    @staticmethod
    def _format_recorded_time(recorded_time: str | None) -> str:
        """The ``HH:MM:SSZ`` a batch was recorded at, or ``unknown`` for an unreadable value.

        A malformed or missing ``time`` field (an old run folder, a hand-edited row) must
        not raise out of the run log (brief: "log what is known and carry on"). The stored
        ``time`` is always UTC (``self._now().isoformat()`` in ``_record_batch_id``), so this
        only reformats it -- it never converts a timezone.
        """
        if recorded_time is None:
            return "unknown"
        try:
            return f"{datetime.fromisoformat(recorded_time):%H:%M:%S}Z"
        except ValueError:
            return "unknown"

    def _record_batch_id(self, folder: Path, batch_id: str, stage: str) -> None:
        """Append the batch id before waiting (spec §7.2: an interrupted run can resume)."""
        folder.mkdir(parents=True, exist_ok=True)
        row = {"batch_id": batch_id, "stage": stage, "time": self._now().isoformat()}
        with (folder / BATCHES_FILE).open("a") as handle:
            handle.write(json.dumps(row) + "\n")

    def _record_lost_batch(self, folder: Path, batch_id: str, stage: str) -> None:
        """Append a ``lost`` row for a reused batch the provider no longer recognises.

        Task 7b: this marks the id so a later resume's ``recorded_batches`` skips it (and
        its original row) instead of waiting on it again. Nothing is ever deleted from
        ``batches.jsonl`` -- the original row stays, this is a second row for the same id.
        """
        folder.mkdir(parents=True, exist_ok=True)
        row = {
            "batch_id": batch_id,
            "stage": stage,
            "lost": True,
            "time": self._now().isoformat(),
        }
        with (folder / BATCHES_FILE).open("a") as handle:
            handle.write(json.dumps(row) + "\n")

    def _record_superseded_batch(
        self, folder: Path, batch_id: str, stage: str, lost_batch_id: str
    ) -> None:
        """Append a ``superseded`` row for a batch recorded after one the provider has lost.

        Same shape as ``_record_lost_batch``'s row, plus ``depends_on_batch_id`` naming the
        lost batch whose replies this one's requests were built from (fix round 1). Nothing
        is ever deleted from ``batches.jsonl``.
        """
        folder.mkdir(parents=True, exist_ok=True)
        row = {
            "batch_id": batch_id,
            "stage": stage,
            "superseded": True,
            "depends_on_batch_id": lost_batch_id,
            "time": self._now().isoformat(),
        }
        with (folder / BATCHES_FILE).open("a") as handle:
            handle.write(json.dumps(row) + "\n")

    def _supersede_downstream(self, run: _BatchRun, *, lost_batch_id: str) -> None:
        """Drop every batch still queued for reuse once one it depends on is found lost.

        Fix round 1: stage 2's requests are built from stage 1's hypothesis (``history`` and
        ``system``, see ``_stage2_system``), and a retry's requests are built from the pass it
        retries, so every batch the dead run recorded *after* the one just found lost is not a
        valid replay of anything any more -- it would parse replies written for content that
        no longer exists into this run's records. This appends a ``superseded`` row for each
        one still in ``run.reusable`` (naming the lost batch it depended on) and empties the
        queue, so every downstream stage submits fresh for the rest of this run, and
        ``recorded_batches`` keeps a later resume from ever reusing them either.
        """
        downstream = list(run.reusable)
        run.reusable.clear()
        for stage, batch_id, _recorded_time in downstream:
            self._record_superseded_batch(run.folder, batch_id, stage, lost_batch_id)
            self._log_superseded(stage, batch_id, lost_batch_id)

    @staticmethod
    def _take_reusable(run: _BatchRun, stage: str) -> tuple[str, str | None] | None:
        """The first unconsumed recorded ``(batch_id, recorded_time)`` for ``stage``.

        By stage name and order, not one row per stage: a retry pass can legitimately run
        twice across a resume (``stage1-retry`` in the dead run and again in the resumed
        one), so the queue hands out the earliest row for that stage that no call has taken
        yet, and runs dry into a normal submit once they are used up.

        Args:
            run: the answering pass's state, whose ``reusable`` queue is consumed in place.
            stage: the stage name the batch is for.

        Returns:
            The batch id to wait on instead of submitting, and the time it was recorded (for
            the run log only), or ``None`` to submit normally.
        """
        for index, (recorded_stage, batch_id, recorded_time) in enumerate(run.reusable):
            if recorded_stage == stage:
                del run.reusable[index]
                return batch_id, recorded_time
        return None

    def _submit_and_wait(
        self, requests: Sequence[BatchRequest], run: _BatchRun, stage: str
    ) -> BatchStatus:
        """Submit one batch, record its id, wait for a terminal status; status to stderr.

        The single point where a batch is submitted, and so the single point where a resume
        reuses one (0032 point 3): a stage with an unconsumed recorded id skips the submit
        and waits on that id, which returns at once for a batch that has already completed.
        A reused id is not appended to ``batches.jsonl`` a second time — it is already
        there. Everything after the wait is identical either way, so a reused batch's
        reported cost lands in the run record exactly as a fresh one's does, which is how
        money already spent stays visible to the next run's budget check. The one addition
        is ``refuse_replay_mismatch``: a reused batch's replies must cover exactly the
        cases this pass replayed, which is the only checkable evidence that the replay
        reproduced the dead run's requests.

        The batch id and its (possibly ``None``) reported cost are appended to ``run``
        before the status is checked, so a batch that ends anything but ``completed`` still
        contributes its honest entry — a ``None`` cost, not a missing one silently treated
        as zero — instead of vanishing from the run's totals, and its id still shows up in
        the aborted ``RunRecord.batch_ids`` (fix round 2, Minor 2).

        Before the wait begins, one line goes to the run log saying whether this batch is
        reused (no new money) or freshly submitted (new money, and how much of it) -- the
        money trail the brief calls out as currently invisible.

        Task 7b: if the batch being waited on was reused and the provider has since lost it
        (``BatchNotFoundError``, raised by ``BatchClient.wait`` once its 404 grace elapses),
        that is treated as the batch no longer existing, not as the pass failing. A ``lost``
        row is appended to ``batches.jsonl`` (so a later resume never waits on that id
        again), one line is logged, and the same ``requests`` are submitted fresh -- new
        money, spent visibly, exactly once. Its cost never lands in ``run.costs``/
        ``run.batch_ids`` under the lost id -- only the fresh batch that replaces it does, the
        same as for any batch that was never recorded at all. A batch submitted fresh *in this
        call* that then raises ``BatchNotFoundError`` is not retried again: it propagates and
        the run aborts, so a run never silently re-spends more than once on the same stage.

        Fix round 1: every batch the dead run recorded *after* the lost one carries content
        derived from it (stage 2's requests are built from stage 1's hypothesis) and so is not
        a valid replay of anything any more either -- ``_supersede_downstream`` drops the rest
        of this pass's reuse queue at the same moment, marking each one ``superseded`` so a
        later resume does not reuse it either. Its rows are written *before* the ``lost`` row
        (final review): otherwise a crash between the two writes would leave a ``lost`` row on
        disk with no ``superseded`` rows for the batches that depended on it, so a resume that
        stopped there would still think those batches are reusable.
        """
        if self._batch is None:
            raise ConfigurationError("a batch client is required for a non-sync run")
        batch = self._batch
        reused = self._take_reusable(run, stage)
        if reused is not None:
            batch_id, recorded_time = reused
            self._log_reused(stage, batch_id, recorded_time)
            try:
                status = self._wait_and_log(batch, batch_id, stage)
            except BatchNotFoundError:
                self._supersede_downstream(run, lost_batch_id=batch_id)
                self._record_lost_batch(run.folder, batch_id, stage)
                self._log_lost(stage, batch_id)
                reused = None
            else:
                run.batch_ids.append(status.batch_id)
                run.costs.append(status.reported_cost_usd)
                if status.status != "completed":
                    raise ModelError(f"batch {batch_id} ended {status.status}")
                refuse_replay_mismatch(batch_id, requests, status)
                return status
        batch_id = batch.submit(requests)
        self._record_batch_id(run.folder, batch_id, stage)
        self._log_submitted(stage, batch_id, len(requests))
        status = self._wait_and_log(batch, batch_id, stage)
        run.batch_ids.append(status.batch_id)
        run.costs.append(status.reported_cost_usd)
        if status.status != "completed":
            raise ModelError(f"batch {batch_id} ended {status.status}")
        return status

    def _wait_and_log(self, batch: BatchRunner, batch_id: str, stage: str) -> BatchStatus:
        """Wait for one batch's terminal status, logging every poll (shared by both paths)."""
        wait_started = self._now()
        return batch.wait(
            batch_id,
            on_status=lambda s: self._log_status(stage, s, wait_started),
        )

    def _answer_batch(
        self, raws: Sequence[Mapping[str, object]], spec: RunSpec, run: _BatchRun
    ) -> None:
        """Two batches (stage 1, stage 2), each with one retry batch on failures (spec §7.2).

        Populates ``run`` in place rather than returning, so the caller (``Runner.run``)
        still has ``run.results``/``run.order``/``run.batch_ids``/``run.costs`` to write a
        partial run from if this raises partway through (fix round 1, Important 2).
        """
        self._prepare_contexts(raws, spec, run)
        try:
            self._stage1(run)
            stage2_ids = [cid for cid, h in run.hyps.items() if not (h.abstain or not h.findings)]
            for cid, hypothesis in run.hyps.items():
                if cid not in stage2_ids:
                    self._finish_case(cid, hypothesis, run)
            if stage2_ids:
                self._stage2(stage2_ids, run)
        except BaseException as error:
            self._abort_unresolved(run, error)
            raise

    def _abort_unresolved(self, run: _BatchRun, error: BaseException) -> None:
        """Give every case with no result yet one, priced from whatever it already cost.

        Reached when a batch ends ``expired``/``failed``/``cancelled`` (or any other
        exception) partway through a run: cases that already had a stage-1 (or stage-2)
        reply billed to them keep that cost instead of it vanishing (fix round 1,
        Important 2).
        """
        for case_id, ctx in run.contexts.items():
            if case_id not in run.results:
                cost = self._cost(ctx.replies, ctx.spec)
                run.results[case_id] = self._failed(ctx, f"aborted: {error}", cost)

    def _prepare_contexts(
        self, raws: Sequence[Mapping[str, object]], spec: RunSpec, run: _BatchRun
    ) -> None:
        for raw in raws:
            try:
                prepared = self._prepare(raw, spec)
            except LeakageError as error:
                if spec.arm != "B":
                    raise
                case_id = str(raw["ntsbNumber"])
                run.order.append(case_id)
                run.results[case_id] = self._leaked_case(raw, error)
                continue
            run.order.append(prepared.evidence.case_id)
            ctx = _CaseContext(
                raw=raw,
                evidence=prepared.evidence,
                verdict=prepared.verdict,
                payload=prepared.payload,
                system=prepared.system,
                spec=spec,
                attached=prepared.attached,
                not_read=prepared.not_read,
                not_available=prepared.not_available,
                documents_attached=prepared.documents_attached,
            )
            if over_cap(prepared.payload.text, prepared.system, spec):
                run.results[prepared.evidence.case_id] = self._failed(ctx, "cap", 0.0)
                continue
            run.contexts[prepared.evidence.case_id] = ctx

    def _finish_case(self, case_id: str, hypothesis: Hypothesis, run: _BatchRun) -> None:
        ctx = run.contexts[case_id]
        scores = score_case(hypothesis, ctx.verdict, self._tables, seen_pairs=self._seen)
        cost = self._cost(ctx.replies, ctx.spec)
        step = self._step(ctx, hypothesis, cost)
        run.results[case_id] = self._result(ctx, (step,), scores, cost)

    def _fail_case(self, case_id: str, failure: str, run: _BatchRun) -> None:
        """Record one case's failure -- the only place ``schema_detail`` reaches a result.

        ``failure`` here is the batch path's ``need_retry`` text, which is also sent back to
        the model verbatim as the next retry's system message (``_retry_system`` /
        ``_stage2_system``). The reply-budget detail (S2.6 Task 9A fix round 1) must never
        reach the model, so it is appended only here, into the *recorded* failure, from
        ``ctx.schema_detail`` -- set beside ``need_retry`` but never folded into it.
        """
        ctx = run.contexts[case_id]
        if failure.startswith("schema:") and ctx.schema_detail is not None:
            failure = f"{failure}{ctx.schema_detail}"
        cost = self._cost(ctx.replies, ctx.spec)
        run.results[case_id] = self._failed(ctx, failure, cost)

    def _stage1(self, run: _BatchRun) -> None:
        ids = [cid for cid in run.contexts if cid not in run.results]
        need_retry = self._run_stage1_pass(ids, run, "stage1", errors={})
        if need_retry:
            # The retry pass's own return value carries the retry's own error text, not
            # pass 1's — using ``need_retry`` here instead would file a case that failed
            # with a model error on retry as "schema: ..." from the first attempt (fix
            # round 1, Minor 5).
            still_failing = self._run_stage1_pass(
                list(need_retry), run, "stage1-retry", errors=need_retry
            )
            for cid, error in still_failing.items():
                if cid not in run.hyps and cid not in run.results:
                    self._fail_case(cid, error, run)

    def _run_stage1_pass(
        self, ids: Sequence[str], run: _BatchRun, stage: str, *, errors: dict[str, str]
    ) -> dict[str, str]:
        """One stage-1 batch (first pass or retry); returns ids still needing a retry, with why."""
        if not ids:
            return {}
        requests = [
            BatchRequest(
                custom_id=cid,
                payload=run.contexts[cid].payload,
                settings=_settings(run.contexts[cid].spec, HYPOTHESIS_SCHEMA, "hypothesis"),
                system=self._retry_system(run.contexts[cid].system, errors.get(cid)),
            )
            for cid in ids
        ]
        status = self._submit_and_wait(requests, run, stage)
        by_id = {r.custom_id: r for r in status.results}
        need_retry: dict[str, str] = {}
        for cid in ids:
            result = by_id.get(cid)
            if result is None or result.reply is None:
                need_retry[cid] = self._reply_error(result)
                continue
            run.contexts[cid].replies.append(result.reply)
            try:
                hypothesis = parse_hypothesis(result.reply.content or "", self._tables)
            except SchemaError as error:
                need_retry[cid] = f"schema: {error}"
                run.contexts[cid].schema_detail = _reply_detail(result.reply)
            else:
                run.hyps[cid] = hypothesis
                # Pinned once, so a stage-2 retry batch replays the accepted stage-1
                # content, never a rejected stage-2 reply (fix round 1, Important 1).
                run.contexts[cid].stage1_content = result.reply.content
        return need_retry

    def _stage2(self, ids: list[str], run: _BatchRun) -> None:
        need_retry = self._run_stage2_pass(ids, run, "stage2", errors={})
        if need_retry:
            # Same fix as _stage1: use the retry pass's own errors, not pass 1's (Minor 5).
            still_failing = self._run_stage2_pass(
                list(need_retry), run, "stage2-retry", errors=need_retry
            )
            for cid, error in still_failing.items():
                if cid not in run.finals:
                    self._fail_case(cid, error, run)
        for cid, hypothesis in run.finals.items():
            self._finish_case(cid, hypothesis, run)

    def _run_stage2_pass(
        self, ids: Sequence[str], run: _BatchRun, stage: str, *, errors: dict[str, str]
    ) -> dict[str, str]:
        """One stage-2 batch (first pass or retry); returns ids still needing a retry, with why."""
        if not ids:
            return {}
        requests = [
            BatchRequest(
                custom_id=cid,
                payload=run.contexts[cid].payload,
                settings=_settings(run.contexts[cid].spec, REFINEMENT_SCHEMA, "refinement"),
                system=self._stage2_system(run.hyps[cid], errors.get(cid)),
                # The accepted stage-1 content, pinned in _run_stage1_pass — never
                # ``replies[-1]``, which on a stage-2 retry pass is the *rejected* stage-2
                # reply, not the stage-1 hypothesis (fix round 1, Important 1).
                history=(Turn(role="assistant", content=run.contexts[cid].stage1_content),),
            )
            for cid in ids
        ]
        status = self._submit_and_wait(requests, run, stage)
        by_id = {r.custom_id: r for r in status.results}
        need_retry: dict[str, str] = {}
        for cid in ids:
            result = by_id.get(cid)
            if result is None or result.reply is None:
                need_retry[cid] = self._reply_error(result)
                continue
            run.contexts[cid].replies.append(result.reply)
            try:
                run.finals[cid] = parse_refinement(
                    result.reply.content or "", self._tables, run.hyps[cid]
                )
            except SchemaError as error:
                need_retry[cid] = f"schema: {error}"
                run.contexts[cid].schema_detail = _reply_detail(result.reply)
        return need_retry

    @staticmethod
    def _reply_error(result: BatchResult | None) -> str:
        """The ``model:`` failure text for a batch result with no usable reply."""
        error = result.error if result is not None else None
        return f"model: {error if error else 'no reply'}"

    @staticmethod
    def _retry_system(system: str, error: str | None) -> str:
        if error is None:
            return system
        return f"{system}\n\nYour previous reply was rejected: {error}"

    def _stage2_system(self, hypothesis: Hypothesis, error: str | None) -> str:
        base = f"{prompt.SYSTEM_REFINE}\n\n"
        if error is not None:
            base += f"Your previous reply was rejected: {error}\n\n"
        return base + prompt.refine_message(hypothesis, self._tables)
