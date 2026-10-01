"""The drivers: how a run puts its cases through their loops, and how it resumes (S3.1 Task 9).

A ``CaseLoop`` (``agent/loop.py``) never calls a model; it hands out its next call and takes the
reply. Two drivers make the calls. ``drive_sync`` sends one call at a time, for the shape probe
and smoke runs. ``drive_batch`` is the evaluation driver: each round sends the next call of every
case that has not stopped as one batch, waits, and hands every reply back, so cases at different
steps share a round (spec §8.1). A run is 10 to 15 rounds of about half an hour each, which is
why a resume has to be exact.

Two files in the run folder make it exact:

- ``replies.jsonl``: one ``ReplyRow`` per call, the reply (or the failure) exactly as the loop was
  given it, with its times and batch id. The row is written before the loop is given the reply,
  so a reply that was paid for is on disk before anything can go wrong with it.
- ``rounds.jsonl``: one ``RoundRow`` before a round's wait, so a batch that has been submitted
  is never lost, and a second row with the same ``round`` once its replies are used. A reader
  takes the last row of each round.

A round's finishing row records how it ended, and only some endings are a case's business:

- ``completed``: its replies are used; a call with no result is that case's failed call.
- ``expired``, ``failed`` or ``completed`` with a result for none of its calls: the provider's
  failure, not any case's. No reply is taken, no loop is told, and the same calls go out as the
  next round (bounded by ``max_rounds``).
- ``lost``: a batch recorded by an earlier attempt that the provider no longer serves. Finished,
  and its calls that are still unanswered go out again, as for a dead batch.
- ``cancelled``: usually an operator stopping spend, so the run does not go on by itself. The
  round is finished and ``BatchCancelledError`` stops the run; a resume then sends the calls again.

``replay`` feeds the saved rows to fresh loops, in order, through the same ``accept`` the live run
used, so no model is called and the loops come out equal to the live ones (same trail, same
outcome). **Both drivers call it themselves on entry**: give them fresh loops and the folder, and
a run that was started before is continued. Do not replay first. If the last round was submitted
and never finished, ``drive_batch`` waits on that batch instead of submitting again.

Case ids are public NTSB numbers, so the refusals below may name them. They never carry a reply,
a payload or provider text.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Final, NamedTuple

from pydantic import BaseModel, ConfigDict, ValidationError

from ntsb_probable_cause.agent.loop import CaseLoop, PendingCall
from ntsb_probable_cause.errors import (
    BatchCancelledError,
    BatchNotFoundError,
    ConfigurationError,
    ModelError,
)
from ntsb_probable_cause.model.batch import BatchRequest, BatchStatus
from ntsb_probable_cause.model.client import ModelClient, ModelReply
from ntsb_probable_cause.scoring.records import read_jsonl, write_jsonl
from ntsb_probable_cause.scoring.runner import BatchRunner

REPLIES_FILE: Final = "replies.jsonl"
ROUNDS_FILE: Final = "rounds.jsonl"
_SEPARATOR: Final = "#"
_ROUNDS_SPENT: Final = "failed: rounds"
_LOST: Final = "lost"
_CANCELLED: Final = "cancelled"


class _Row(BaseModel):
    """Base of the two row types: no extra fields, no change once built."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ReplyRow(_Row):
    """One call's reply as the loop was given it, in the order the loop took them.

    Attributes:
        case_id: the case.
        call_index: the call's place in the case (``CaseLoop.call_index`` when it was pending).
        reply: the model's reply, or None when the call failed.
        error: why it failed, when ``reply`` is None.
        sent_at: when the call was sent (a batch call: when its round was submitted).
        returned_at: when the reply, or the failure, came back.
        batch_id: the batch the call went in; None for a synchronous call.
    """

    case_id: str
    call_index: int
    reply: ModelReply | None
    error: str | None
    sent_at: datetime
    returned_at: datetime
    batch_id: str | None


class RoundRow(_Row):
    """One batch round: written when submitted, and again, completed, once its replies are used.

    Attributes:
        round: the round, from 1.
        batch_id: the provider's batch id.
        submitted_at: when the batch was submitted.
        custom_ids: the calls in the batch, as ``case#call_index``, in loop order.
        finished_at: when the batch came back and its replies were used; None until then.
        status: how the round ended: the batch's terminal status, or ``lost`` for a recorded
            batch the provider no longer serves; None until it is finished.
        reported_cost_usd: the cost the batch reported, if it reported one.
    """

    round: int
    batch_id: str
    submitted_at: datetime
    custom_ids: tuple[str, ...]
    finished_at: datetime | None = None
    status: str | None = None
    reported_cost_usd: float | None = None


class _Call(NamedTuple):
    """A call waiting for its reply: its batch custom id, its loop, and the call itself."""

    custom_id: str
    loop: CaseLoop
    call: PendingCall


def custom_id(case_id: str, call_index: int) -> str:
    """The name of one call in a batch: the case, then the call's place in it."""
    return f"{case_id}{_SEPARATOR}{call_index}"


def drive_sync(
    loops: Sequence[CaseLoop],
    client: ModelClient,
    *,
    folder: Path,
    now: Callable[[], datetime],
) -> None:
    """Run every loop to its end, one call at a time, each loop in turn.

    A call that fails with a ``ModelError`` is given to the loop as a failed call (it is
    re-issued once, then the case stops). Any other error ends the run, and the calls finished
    so far are on disk. Calls the folder already holds are replayed, not made again.

    Args:
        loops: one loop per case, fresh (see the module docstring).
        client: the model client.
        folder: the run folder; ``replies.jsonl`` is appended to.
        now: the clock; the only source of times.

    Raises:
        ConfigurationError: the folder does not match these loops, or holds a batch round that
            was never finished (resume that with ``drive_batch``).
    """
    if replay(loops, folder) is not None:
        raise ConfigurationError(
            f"cannot continue: {folder / ROUNDS_FILE} holds a batch round that was never "
            "finished, so its calls may already be paid for. Resume it with drive_batch."
        )
    for loop in loops:
        while (call := loop.next_call()) is not None:
            sent_at = now()
            reply: ModelReply | None = None
            error: str | None = None
            try:
                reply = client.complete(
                    call.payload, call.settings, system=call.system, history=call.history
                )
            except ModelError as failure:
                error = f"model: {failure}"
            row = ReplyRow(
                case_id=loop.case_id,
                call_index=loop.call_index,
                reply=reply,
                error=error,
                sent_at=sent_at,
                returned_at=now(),
                batch_id=None,
            )
            write_jsonl(folder / REPLIES_FILE, [row])
            _accept(loop, row)


def drive_batch(
    loops: Sequence[CaseLoop],
    batch: BatchRunner,
    *,
    folder: Path,
    now: Callable[[], datetime],
    max_rounds: int = 40,
) -> tuple[float | None, ...]:
    """Run every loop to its end in batch rounds, and resume a run that was cut short.

    A round collects the next call of every loop that has not stopped, submits them as one
    batch, waits, and gives each loop its reply. A call with no result in a batch that returned
    some, or whose result is an error, is given to its loop as a failed call: the loop re-issues
    it in the next round once, then stops the case. A batch that returned no result for any of
    its calls (``expired``, ``failed``, or ``completed`` empty) is not a case's failure: no loop
    is told, its round is recorded with that status, and the same calls are submitted again as
    the next round. Every round counts toward ``max_rounds``, dead ones too; at the limit the
    cases still running are stopped ``failed: rounds``. A batch that ended ``cancelled`` is
    usually an operator stopping spend: its round is recorded and the run stops with
    ``BatchCancelledError`` (its replies, if it returned any, are not used, as the runner's are
    not). Resume it, and the calls go out again.

    Resume is the same call: the replies the folder holds are replayed (no model call), and a
    round that was submitted and never finished is waited on instead of submitted again. If the
    provider has lost that batch (``BatchNotFoundError`` from the wait), the round is recorded
    as ``lost`` and its calls that are still unanswered are submitted again. A batch this call
    submitted that is lost is not: the error propagates, so no call is paid for twice. Time is
    read from ``now`` twice a round, after the submit and after the wait.

    Args:
        loops: one loop per case, fresh (see the module docstring).
        batch: the batch client.
        folder: the run folder; ``replies.jsonl`` and ``rounds.jsonl`` are appended to.
        now: the clock; the only source of times.
        max_rounds: the most rounds a run may take.

    Returns:
        Each round's reported cost, in order, the rounds of an earlier attempt included; None for
        a round whose batch reported none.

    Raises:
        ConfigurationError: the folder does not match these loops (a different case list, spec
            or code), a file of the folder is damaged, or a batch answers calls its round never
            asked about.
        BatchCancelledError: a batch ended ``cancelled``; its round is finished, and a resume
            sends its calls again.
        BatchNotFoundError: a batch submitted by this call is lost. The round stays open, and a
            resume then treats it as lost.
        ModelError: ``submit`` or ``wait`` failed; the round of a failed ``wait`` stays open, and
            a resume waits on it again.
    """
    cases = _by_case(loops)
    unfinished = replay(loops, folder)
    rounds = max(_rounds(folder), default=0)
    while True:
        resumed = unfinished is not None
        if unfinished is not None:
            row, calls = unfinished, _remaining(unfinished, cases)
            unfinished = None
        else:
            calls = _pending(loops)
            if not calls:
                break
            if rounds >= max_rounds:
                for loop in loops:
                    loop.stop(_ROUNDS_SPENT)
                break
            rounds += 1
            row = _submit(calls, batch, rounds, folder, now)
        status = _wait(batch, row, resumed=resumed)
        if status is None:  # an earlier attempt's batch, lost: nothing came back
            _finish_round(row, folder, now(), status=_LOST)
            continue
        _refuse_foreign_results(row, status)
        if status.status == _CANCELLED:
            _finish_round(row, folder, now(), status=_CANCELLED, cost=status.reported_cost_usd)
            raise BatchCancelledError(
                f"batch {row.batch_id} (round {row.round}) was cancelled, so the run stops here. "
                "The run can be resumed: a resume sends its calls again."
            )
        if _is_dead(status):  # nothing was accepted: the same calls go out in the next round
            _finish_round(row, folder, now(), status=status.status, cost=status.reported_cost_usd)
            continue
        _take(calls, row, status, now(), folder)
    return tuple(r.reported_cost_usd for r in _rounds(folder).values())


def replay(loops: Sequence[CaseLoop], folder: Path) -> RoundRow | None:
    """Feed the saved replies to fresh loops, in order. No model is called.

    The drivers call this themselves; it is public for the tools that read a run folder back.

    Args:
        loops: one fresh loop per case.
        folder: the run folder. A folder with no files replays nothing.

    Returns:
        The round that was submitted and never finished, if there is one; its calls may be paid
        for, and ``drive_batch`` waits on its batch.

    Raises:
        ConfigurationError: a file is damaged, or a saved reply is not the next call of any loop.
    """
    cases = _by_case(loops)
    for row in _read(folder / REPLIES_FILE, ReplyRow):
        loop = cases.get(row.case_id)
        if loop is None:
            raise ConfigurationError(
                f"cannot resume: {folder / REPLIES_FILE} holds a reply for {row.case_id}, "
                "which is not a case of this run"
            )
        if row.call_index != loop.call_index or loop.next_call() is None:
            raise ConfigurationError(
                f"cannot resume: {folder / REPLIES_FILE} holds a reply to call {row.call_index} "
                f"of {row.case_id}, and that is not the call this run is at "
                f"(call {loop.call_index}, "
                f"{'still running' if loop.next_call() is not None else 'stopped'}); "
                "the loops were not started fresh, or the cases or code differ"
            )
        _accept(loop, row)
    latest = list(_rounds(folder).values())
    last = latest[-1] if latest else None
    return last if last is not None and last.finished_at is None else None


def _accept(loop: CaseLoop, row: ReplyRow) -> None:
    """Give a loop the reply a row holds; the one route for live and replayed replies alike."""
    loop.accept(
        row.reply,
        error=row.error,
        sent_at=row.sent_at,
        returned_at=row.returned_at,
        batch_id=row.batch_id,
    )


def _by_case(loops: Sequence[CaseLoop]) -> dict[str, CaseLoop]:
    """The loops by case id; an id a custom id cannot be split on, or a repeat, is refused."""
    cases: dict[str, CaseLoop] = {}
    for loop in loops:
        if _SEPARATOR in loop.case_id:
            raise ConfigurationError(
                f"case id {loop.case_id!r} holds {_SEPARATOR!r}, which the batch custom id "
                f"'case{_SEPARATOR}call' is split on"
            )
        if loop.case_id in cases:
            raise ConfigurationError(f"case {loop.case_id} is in this run twice")
        cases[loop.case_id] = loop
    return cases


def _read[T: BaseModel](path: Path, model: type[T]) -> list[T]:
    """Every row of one file; none if there is no file; a damaged one is refused by name."""
    if not path.is_file():
        return []
    try:
        return read_jsonl(path, model)
    except ValidationError:
        raise ConfigurationError(
            f"cannot resume: {path} holds a row that is not a readable {model.__name__} "
            "(a killed process leaves a half-written line behind)"
        ) from None


def _rounds(folder: Path) -> dict[int, RoundRow]:
    """The last row of each round, in round order."""
    latest: dict[int, RoundRow] = {}
    for row in _read(folder / ROUNDS_FILE, RoundRow):
        latest[row.round] = row
    return latest


def _pending(loops: Sequence[CaseLoop]) -> list[_Call]:
    """The next call of every loop that has not stopped, in loop order."""
    return [
        _Call(custom_id(loop.case_id, loop.call_index), loop, call)
        for loop in loops
        if (call := loop.next_call()) is not None
    ]


def _submit(
    calls: Sequence[_Call],
    batch: BatchRunner,
    number: int,
    folder: Path,
    now: Callable[[], datetime],
) -> RoundRow:
    """Submit a round and record it at once: its batch id is on disk before the wait."""
    requests = [
        BatchRequest(
            custom_id=c.custom_id,
            payload=c.call.payload,
            settings=c.call.settings,
            system=c.call.system,
            history=c.call.history,
        )
        for c in calls
    ]
    batch_id = batch.submit(requests)
    row = RoundRow(
        round=number,
        batch_id=batch_id,
        submitted_at=now(),
        custom_ids=tuple(c.custom_id for c in calls),
    )
    write_jsonl(folder / ROUNDS_FILE, [row])
    return row


def _remaining(row: RoundRow, cases: Mapping[str, CaseLoop]) -> list[_Call]:
    """The calls of an unfinished round that still need their reply, checked against the loops.

    A call is answered already when its loop has moved past it (a kill after some replies were
    written), still to be answered when it is the loop's pending call, and anything else is
    refused: the round was not made by these loops, so its batch is not the one to wait on.
    """
    remaining: list[_Call] = []
    in_round: set[str] = set()
    for recorded in row.custom_ids:
        case_id, _, index = recorded.rpartition(_SEPARATOR)
        in_round.add(case_id)
        loop = cases.get(case_id)
        number = int(index) if index.isdecimal() else -1
        if loop is None or not 0 <= number <= loop.call_index:
            raise _mismatch(row, recorded)
        if number < loop.call_index:
            continue
        call = loop.next_call()
        if call is None:
            raise _mismatch(row, recorded)
        remaining.append(_Call(recorded, loop, call))
    for case_id, loop in cases.items():
        if case_id not in in_round and loop.next_call() is not None:
            raise _mismatch(row, custom_id(case_id, loop.call_index))
    return remaining


def _mismatch(row: RoundRow, example: str) -> ConfigurationError:
    return ConfigurationError(
        f"cannot resume: recorded batch {row.batch_id} (round {row.round}) was submitted for "
        f"{len(row.custom_ids)} calls, and they are not the calls this run makes now "
        f"(e.g. {example}). Resume with the cases, spec and code the run was started with."
    )


def _refuse_foreign_results(row: RoundRow, status: BatchStatus) -> None:
    """Refuse a batch that answers calls its round never asked about, before any reply is used.

    As ``runner.refuse_replay_mismatch`` does for a reused batch. A call with no result is not
    refused: the loop treats it as a failed call and re-issues it.
    """
    unexpected = sorted({r.custom_id for r in status.results} - set(row.custom_ids))
    if unexpected:
        raise ConfigurationError(
            f"cannot continue: batch {row.batch_id} answers {len(unexpected)} calls round "
            f"{row.round} never asked about (e.g. {unexpected[:3]}), so it is not the batch "
            "this round submitted"
        )


def _wait(batch: BatchRunner, row: RoundRow, *, resumed: bool) -> BatchStatus | None:
    """Wait for a round's batch; None if an earlier attempt's batch has been lost by the provider.

    ``BatchNotFoundError`` is what ``wait`` raises once its 404 grace is spent. For a batch that
    was only recorded (a resume) it means nothing came back, so the round can be finished and its
    calls sent again. For a batch this call submitted a moment ago it propagates, as the
    runner's does: sending the calls again could pay for them twice.
    """
    try:
        return batch.wait(row.batch_id)
    except BatchNotFoundError:
        if not resumed:
            raise
        return None


def _is_dead(status: BatchStatus) -> bool:
    """A batch that returned no result at all: the provider's failure, not any case's.

    By now ``_refuse_foreign_results`` has run, so every result is for a call of the round: no
    results means none for any of them. This holds for ``expired``, ``failed`` and ``completed``
    alike (``cancelled`` is dealt with before). A batch that returned some results is not dead:
    a call it left out is that case's failed call.
    """
    return not status.results


def _finish_round(
    row: RoundRow, folder: Path, returned_at: datetime, *, status: str, cost: float | None = None
) -> None:
    """Append the row that completes a round: when it ended, how, and what it cost."""
    finished = row.model_copy(
        update={"finished_at": returned_at, "status": status, "reported_cost_usd": cost}
    )
    write_jsonl(folder / ROUNDS_FILE, [finished])


def _take(
    calls: Sequence[_Call],
    row: RoundRow,
    status: BatchStatus,
    returned_at: datetime,
    folder: Path,
) -> None:
    """Write a round's replies, give them to the loops, and mark the round finished.

    The replies go to disk first, all in one write, in the round's order (so the file does not
    depend on the order the provider listed its results in); a loop is given its reply only
    after that. A call the batch has no usable result for becomes a failed call.
    """
    results = {r.custom_id: r for r in status.results}
    rows: list[ReplyRow] = []
    for c in calls:
        result = results.get(c.custom_id)
        reply = None if result is None else result.reply
        error = None
        if reply is None:
            error = (None if result is None else result.error) or (
                f"no result in the {status.status} batch"
            )
        rows.append(
            ReplyRow(
                case_id=c.loop.case_id,
                call_index=c.loop.call_index,
                reply=reply,
                error=error,
                sent_at=row.submitted_at,
                returned_at=returned_at,
                batch_id=row.batch_id,
            )
        )
    write_jsonl(folder / REPLIES_FILE, rows)
    for c, reply_row in zip(calls, rows, strict=True):
        _accept(c.loop, reply_row)
    _finish_round(row, folder, returned_at, status=status.status, cost=status.reported_cost_usd)
