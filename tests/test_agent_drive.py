"""Tests for the drivers (S3.1 Task 9): ``agent/drive.py``.

Two cases are driven with scripted replies: ``ANC09CA024`` with its docket (the eight calls of
Task 8's happy path) and a second fixture record with no docket (two calls). The batch tests use
``FakeBatchClient`` from ``tests/test_runner.py``, whose handler is given each request's
``custom_id``; the sync tests use a client scripted the same way. Offline; no model is called.
A resume is shown exact the way the brief puts it: the same outcomes and the same
``replies.jsonl`` as a run that was never interrupted.
"""

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from tests.conftest import load_record_fixtures
from tests.test_agent_documents import _raw
from tests.test_agent_loop import HAPPY, T0, _config, _hyp, _view
from tests.test_runner import FakeBatchClient

from ntsb_probable_cause.agent.drive import (
    REPLIES_FILE,
    ROUNDS_FILE,
    ReplyRow,
    RoundRow,
    custom_id,
    drive_batch,
    drive_sync,
    replay,
)
from ntsb_probable_cause.agent.loop import CaseLoop
from ntsb_probable_cause.agent.trail import LoopOutcome
from ntsb_probable_cause.errors import ConfigurationError, ModelError
from ntsb_probable_cause.model.batch import BatchRequest, BatchResult, BatchStatus
from ntsb_probable_cause.model.client import ModelReply, Payload, Turn, Usage, tool_reply
from ntsb_probable_cause.model.client import ModelSettings as Settings
from ntsb_probable_cause.scoring.records import read_jsonl

A = "ANC09CA024"
Handler = Callable[[str, Sequence[BatchRequest]], BatchStatus]


def _other() -> dict[str, object]:
    return next(r for r in load_record_fixtures() if r["ntsbNumber"] != A)


B = str(_other()["ntsbNumber"])


class _KilledError(Exception):
    """A process killed mid-run, as far as the drivers can tell."""


class Clock:
    """A deterministic ``now``: one second per call, so two runs can be compared byte for byte."""

    def __init__(self, ticks: int = 0) -> None:
        self.ticks = ticks

    def __call__(self) -> datetime:
        self.ticks += 1
        return T0 + timedelta(seconds=self.ticks)


def _reply(scripted: ModelReply | str, n: int) -> ModelReply:
    """A scripted reply with usage and reasoning that differ by position, so a mix-up shows."""
    base = (
        scripted
        if isinstance(scripted, ModelReply)
        else ModelReply(
            content=scripted,
            usage=Usage(prompt_tokens=0, completion_tokens=0),
            model="fake",
            response_id="fake",
        )
    )
    usage = Usage(
        prompt_tokens=1000 + n,
        completion_tokens=100 + n,
        reported_cost_usd=0.0011 * (n + 1),
        reasoning_tokens=n,
        cached_tokens=500 + n,
    )
    details = ({"type": "reasoning.summary", "index": n, "nested": {"score": 0.1 * n, "ok": [n]}},)
    return base.model_copy(update={"usage": usage, "reasoning_details": details})


def _script(replies: Sequence[ModelReply | str | None]) -> list[ModelReply | None]:
    """``None`` is a call that fails: a batch item with an error, or a ``ModelError`` when sync."""
    return [None if r is None else _reply(r, n) for n, r in enumerate(replies)]


B_REPLIES: list[ModelReply | str | None] = [
    tool_reply("record_hypothesis", _hyp()),
    tool_reply("submit_answer", _hyp(findings=[])),
]


def _scripts(
    b: Sequence[ModelReply | str | None] = tuple(B_REPLIES),
    a: Sequence[ModelReply | str | None] = tuple(HAPPY),
) -> dict[str, list[ModelReply | None]]:
    """Each case's replies by call index: a failed call takes up an index of its own."""
    return {A: _script(a), B: _script(b)}


def _loops() -> list[CaseLoop]:
    return [CaseLoop(_raw(), _view(), _config()), CaseLoop(_other(), None, _config())]


def _answers(
    scripts: Mapping[str, Sequence[ModelReply | None]], *, extra: Sequence[BatchResult] = ()
) -> Handler:
    """A batch handler: each request gets the scripted reply for its case and call index."""

    def handler(batch_id: str, requests: Sequence[BatchRequest]) -> BatchStatus:
        results: list[BatchResult] = []
        for request in requests:
            case_id, _, index = request.custom_id.rpartition("#")
            scripted = scripts[case_id][int(index)]
            error = "boom" if scripted is None else None
            results.append(BatchResult(custom_id=request.custom_id, reply=scripted, error=error))
        return BatchStatus(
            batch_id=batch_id,
            status="completed",
            results=(*results, *extra),
            reported_cost_usd=0.25 * len(requests),
        )

    return handler


def _die(_batch_id: str, _requests: Sequence[BatchRequest]) -> BatchStatus:
    raise _KilledError


class ScriptedClient:
    """A ``ModelClient`` that answers its calls in order: a ``ModelError`` for ``None``."""

    def __init__(self, replies: Sequence[ModelReply | None], *, die_at: int | None = None) -> None:
        self._replies = list(replies)
        self._die_at = die_at
        self.calls = 0

    def complete(
        self,
        payload: Payload,
        settings: Settings,
        *,
        system: str = "",
        history: Sequence[Turn] = (),
    ) -> ModelReply:
        self.calls += 1
        if self.calls == self._die_at:
            raise _KilledError
        reply = self._replies[self.calls - 1]
        if reply is None:
            raise ModelError("boom")
        return reply


def _sync_replies(scripts: Mapping[str, Sequence[ModelReply | None]]) -> list[ModelReply | None]:
    """What a sync run asks for: the first loop to its end, then the second."""
    return [*scripts[A], *scripts[B]]


def _core(outcome: LoopOutcome) -> LoopOutcome:
    """The outcome without what only the way of driving decides: times and the batch id."""
    calls = tuple(
        c.model_copy(update={"sent_at": T0, "returned_at": T0, "batch_id": None})
        for c in outcome.calls
    )
    return outcome.model_copy(update={"calls": calls})


def _outcomes(loops: Sequence[CaseLoop]) -> list[LoopOutcome]:
    return [loop.outcome for loop in loops]


def _rounds(folder: Path) -> list[RoundRow]:
    return read_jsonl(folder / ROUNDS_FILE, RoundRow)


def _replies(folder: Path) -> list[ReplyRow]:
    return read_jsonl(folder / REPLIES_FILE, ReplyRow)


def _interrupt_after_round_two_is_submitted(folder: Path) -> FakeBatchClient:
    """Run until the second batch is submitted, then die while waiting for it."""
    dead = FakeBatchClient(handlers=[_answers(_scripts()), _die])
    with pytest.raises(_KilledError):
        drive_batch(_loops(), dead, folder=folder, now=Clock())
    return dead


def _resumer(dead: FakeBatchClient, batch_id: str, handlers: list[Handler]) -> FakeBatchClient:
    """The batch client of a resume: it holds the dead run's batch, and mints the next ids.

    ``submitted`` is seeded so the ids it mints go on from the dead run's (``b3``, ``b4`` ...),
    which is what makes the resumed run's files comparable with an uninterrupted run's.
    """
    index = int(batch_id.removeprefix("b"))
    return FakeBatchClient(
        handlers=handlers,
        submitted=[[] for _ in range(index)],
        preloaded={batch_id: dead.submitted[index - 1]},
    )


def _accept_fails_at(monkeypatch: pytest.MonkeyPatch, case_id: str, call_index: int) -> None:
    """Make ``CaseLoop.accept`` raise once for one call, as a fault in the loop's code would."""
    real = CaseLoop.accept

    def flaky(  # noqa: PLR0913 -- the signature of CaseLoop.accept.
        self: CaseLoop,
        reply: ModelReply | None,
        *,
        error: str | None = None,
        sent_at: datetime,
        returned_at: datetime,
        batch_id: str | None = None,
    ) -> None:
        if (self.case_id, self.call_index) == (case_id, call_index):
            monkeypatch.setattr(CaseLoop, "accept", real)
            raise _KilledError
        real(self, reply, error=error, sent_at=sent_at, returned_at=returned_at, batch_id=batch_id)

    monkeypatch.setattr(CaseLoop, "accept", flaky)


# --------------------------------------------------------------------------------------------
# Batch rounds
# --------------------------------------------------------------------------------------------


class TestRounds:
    def test_two_cases_of_different_lengths_finish_in_as_many_rounds_as_the_longer(
        self, tmp_path: Path
    ) -> None:
        folder = tmp_path / "run"
        fake = FakeBatchClient(handlers=[_answers(_scripts())] * 8)
        loops = _loops()
        costs = drive_batch(loops, fake, folder=folder, now=Clock())
        assert [len(batch) for batch in fake.submitted] == [2, 2, 1, 1, 1, 1, 1, 1]
        assert fake.waited == [f"b{n}" for n in range(1, 9)]
        assert [o.stop_reason for o in _outcomes(loops)] == ["done", "done"]
        assert [(o.case_id, len(o.calls)) for o in _outcomes(loops)] == [(A, 8), (B, 2)]
        assert [r.custom_id for r in fake.submitted[0]] == [custom_id(A, 0), custom_id(B, 0)]
        assert [r.custom_id for r in fake.submitted[2]] == [custom_id(A, 2)]
        assert costs == (0.5, 0.5, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25)

    def test_the_custom_id_is_the_case_and_the_call_index(self) -> None:
        assert custom_id("ANC09CA024", 3) == "ANC09CA024#3"

    def test_every_request_is_the_loops_own_pending_call(self, tmp_path: Path) -> None:
        fake = FakeBatchClient(handlers=[_answers(_scripts())] * 8)
        drive_batch(_loops(), fake, folder=tmp_path / "run", now=Clock())
        first = fake.submitted[0][0]
        pending = CaseLoop(_raw(), _view(), _config()).next_call()
        assert pending is not None
        assert (first.payload, first.settings, first.system, first.history) == (
            pending.payload,
            pending.settings,
            pending.system,
            pending.history,
        )

    def test_cases_at_different_steps_share_a_round(self, tmp_path: Path) -> None:
        """B's first call fails, so in round 2 A is at its read choice and B re-issues its h0."""
        scripts = _scripts([None, *B_REPLIES])
        fake = FakeBatchClient(handlers=[_answers(scripts)] * 9)
        loops = _loops()
        drive_batch(loops, fake, folder=tmp_path / "run", now=Clock())
        second = {r.custom_id: r for r in fake.submitted[1]}
        assert set(second) == {custom_id(A, 1), custom_id(B, 1)}
        assert (
            second[custom_id(A, 1)].settings.tool_choice
            != second[custom_id(B, 1)].settings.tool_choice
        )
        assert [len(batch) for batch in fake.submitted][:3] == [2, 2, 2]

    def test_a_failed_batch_item_is_re_issued_next_round(self, tmp_path: Path) -> None:
        folder = tmp_path / "run"
        fake = FakeBatchClient(handlers=[_answers(_scripts([None, *B_REPLIES]))] * 9)
        loops = _loops()
        drive_batch(loops, fake, folder=folder, now=Clock())
        outcome = loops[1].outcome
        assert outcome.stop_reason == "done"
        failed, again, *_ = outcome.calls
        assert (failed.protocol_error, failed.retry, failed.cost_usd) == ("boom", False, 0.0)
        assert (again.protocol_error, again.retry, again.step) == (None, True, "h0")
        row = next(r for r in _replies(folder) if (r.case_id, r.call_index) == (B, 0))
        assert (row.reply, row.error, row.batch_id) == (None, "boom", "b1")

    def test_a_second_failure_in_a_row_stops_the_case(self, tmp_path: Path) -> None:
        scripts = _scripts([None, None])
        fake = FakeBatchClient(handlers=[_answers(scripts)] * 8)
        loops = _loops()
        drive_batch(loops, fake, folder=tmp_path / "run", now=Clock())
        assert loops[1].outcome.stop_reason == "failed: h0"
        assert loops[0].outcome.stop_reason == "done"  # the other case is not held back

    def test_a_batch_that_ended_without_results_fails_every_call_in_it_once(
        self, tmp_path: Path
    ) -> None:
        folder = tmp_path / "run"

        def expired(batch_id: str, _requests: Sequence[BatchRequest]) -> BatchStatus:
            return BatchStatus(
                batch_id=batch_id, status="expired", results=(), reported_cost_usd=None
            )

        # Call 0 of each case is the one the dead batch lost; call 1 re-issues its step.
        scripts = _scripts([None, *B_REPLIES], [None, *HAPPY])
        fake = FakeBatchClient(handlers=[expired, *[_answers(scripts)] * 9])
        loops = _loops()
        costs = drive_batch(loops, fake, folder=folder, now=Clock())
        assert [o.stop_reason for o in _outcomes(loops)] == ["done", "done"]
        for outcome in _outcomes(loops):
            lost, again, *_ = outcome.calls
            assert (lost.protocol_error, lost.retry) == ("no result in the expired batch", False)
            assert (again.protocol_error, again.retry, again.step) == (None, True, "h0")
        finished = _rounds(folder)[1]  # the row that completes round 1
        assert (finished.status, finished.reported_cost_usd) == ("expired", None)
        assert costs[:2] == (None, 0.5)

    def test_max_rounds_stops_the_cases_still_running(self, tmp_path: Path) -> None:
        fake = FakeBatchClient(handlers=[_answers(_scripts())] * 8)
        loops = _loops()
        costs = drive_batch(loops, fake, folder=tmp_path / "run", now=Clock(), max_rounds=2)
        assert len(fake.submitted) == 2
        assert len(costs) == 2
        assert [o.stop_reason for o in _outcomes(loops)] == ["failed: rounds", "done"]
        a = loops[0].outcome
        assert [kind for kind, _ in a.checkpoints] == ["h0"]  # what it had recorded is kept
        assert a.answer is None
        assert len(a.calls) == 2

    def test_a_result_for_a_call_the_round_never_made_is_refused_before_any_reply_is_used(
        self, tmp_path: Path
    ) -> None:
        folder = tmp_path / "run"
        stray = BatchResult(custom_id="Z#0", reply=_script(B_REPLIES)[0], error=None)
        fake = FakeBatchClient(handlers=[_answers(_scripts(), extra=(stray,))])
        loops = _loops()
        with pytest.raises(ConfigurationError, match=r"answers 1 calls round 1 never asked about"):
            drive_batch(loops, fake, folder=folder, now=Clock())
        assert not (folder / REPLIES_FILE).exists()  # nothing was used; the round is left open
        assert [r.finished_at for r in _rounds(folder)] == [None]
        assert [loop.call_index for loop in loops] == [0, 0]

    def test_a_finished_run_driven_again_submits_nothing(self, tmp_path: Path) -> None:
        folder = tmp_path / "run"
        first = FakeBatchClient(handlers=[_answers(_scripts())] * 8)
        costs = drive_batch(_loops(), first, folder=folder, now=Clock())
        again = FakeBatchClient(handlers=[])
        loops = _loops()
        assert drive_batch(loops, again, folder=folder, now=Clock()) == costs
        assert (again.submitted, again.waited) == ([], [])
        assert [o.stop_reason for o in _outcomes(loops)] == ["done", "done"]

    def test_no_loops_no_rounds(self, tmp_path: Path) -> None:
        fake = FakeBatchClient(handlers=[])
        assert drive_batch([], fake, folder=tmp_path / "run", now=Clock()) == ()
        assert fake.submitted == []

    def test_the_files_describe_every_round_and_every_reply(self, tmp_path: Path) -> None:
        folder = tmp_path / "run"
        fake = FakeBatchClient(handlers=[_answers(_scripts())] * 8)
        loops = _loops()
        drive_batch(loops, fake, folder=folder, now=Clock())
        raw = [json.loads(line) for line in (folder / ROUNDS_FILE).read_text().splitlines()]
        assert len(raw) == 16  # each round: the row before the wait, the row after it
        assert [(r["round"], r["finished_at"] is None) for r in raw[:4]] == [
            (1, True),
            (1, False),
            (2, True),
            (2, False),
        ]
        rounds = _rounds(folder)
        assert [r.round for r in rounds] == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8]
        done = rounds[1]
        assert done.custom_ids == (custom_id(A, 0), custom_id(B, 0))
        assert (done.batch_id, done.status, done.reported_cost_usd) == ("b1", "completed", 0.5)
        assert done.submitted_at < (done.finished_at or T0)
        rows = _replies(folder)
        assert len(rows) == 10
        assert [(r.case_id, r.call_index, r.batch_id) for r in rows[:4]] == [
            (A, 0, "b1"),
            (B, 0, "b1"),
            (A, 1, "b2"),
            (B, 1, "b2"),
        ]
        assert {r.sent_at for r in rows if r.batch_id == "b1"} == {done.submitted_at}
        assert {r.returned_at for r in rows if r.batch_id == "b1"} == {done.finished_at}
        # The trail says what the rows say: the loop was given the times and the batch id.
        for loop in loops:
            first = loop.outcome.calls[0]
            assert (first.sent_at, first.returned_at) == (done.submitted_at, done.finished_at)
            assert first.batch_id == "b1"
            assert [c.batch_id for c in loop.outcome.calls[:2]] == ["b1", "b2"]


# --------------------------------------------------------------------------------------------
# Resume
# --------------------------------------------------------------------------------------------


def _uninterrupted(folder: Path) -> list[CaseLoop]:
    loops = _loops()
    drive_batch(
        loops, FakeBatchClient(handlers=[_answers(_scripts())] * 8), folder=folder, now=Clock()
    )
    return loops


class TestResume:
    def test_a_run_interrupted_after_a_submit_resumes_by_waiting_on_the_recorded_batch(
        self, tmp_path: Path
    ) -> None:
        whole, cut = tmp_path / "whole", tmp_path / "cut"
        reference = _uninterrupted(whole)
        dead = _interrupt_after_round_two_is_submitted(cut)
        assert [r.finished_at is None for r in _rounds(cut)] == [True, False, True]
        assert len(dead.submitted) == 2

        clock = Clock(ticks=3)  # the dead run's three ticks: two submits and one finish
        resumed = _resumer(dead, "b2", [_answers(_scripts())] * 7)
        loops = _loops()
        costs = drive_batch(loops, resumed, folder=cut, now=clock)

        assert resumed.waited == ["b2", "b3", "b4", "b5", "b6", "b7", "b8"]
        assert len(resumed.submitted) == 8  # the two seeded entries, then rounds 3 to 8
        assert [len(batch) for batch in resumed.submitted[2:]] == [1, 1, 1, 1, 1, 1]
        assert _outcomes(loops) == _outcomes(reference)
        assert (cut / REPLIES_FILE).read_text() == (whole / REPLIES_FILE).read_text()
        assert (cut / ROUNDS_FILE).read_text() == (whole / ROUNDS_FILE).read_text()
        assert costs == (0.5, 0.5, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25)

    def test_the_resumed_run_makes_no_call_for_what_was_answered(self, tmp_path: Path) -> None:
        dead = _interrupt_after_round_two_is_submitted(tmp_path / "cut")
        resumed = _resumer(dead, "b2", [_answers(_scripts())] * 7)
        drive_batch(_loops(), resumed, folder=tmp_path / "cut", now=Clock(ticks=3))
        ids = [r.custom_id for batch in resumed.submitted[2:] for r in batch]
        assert ids == [custom_id(A, n) for n in range(2, 8)]  # no call of round 1 or 2 again

    def test_a_reply_is_on_disk_before_its_loop_sees_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fault in the loop's code after the batch came back costs the run nothing it paid."""
        whole, cut = tmp_path / "whole", tmp_path / "cut"
        reference = _uninterrupted(whole)
        _accept_fails_at(monkeypatch, B, 1)
        dead = FakeBatchClient(handlers=[_answers(_scripts())] * 2)
        with pytest.raises(_KilledError):
            drive_batch(_loops(), dead, folder=cut, now=Clock())
        assert [(r.case_id, r.call_index) for r in _replies(cut)][-2:] == [(A, 1), (B, 1)]
        assert _rounds(cut)[-1].finished_at is None

        resumed = _resumer(dead, "b2", [_answers(_scripts())] * 7)
        loops = _loops()
        drive_batch(loops, resumed, folder=cut, now=Clock(ticks=3))
        assert resumed.waited[0] == "b2"
        assert _outcomes(loops) == _outcomes(reference)
        assert (cut / REPLIES_FILE).read_text() == (whole / REPLIES_FILE).read_text()
        assert (cut / ROUNDS_FILE).read_text() == (whole / ROUNDS_FILE).read_text()

    def test_every_reply_written_but_the_round_not_finished(self, tmp_path: Path) -> None:
        """A kill after the replies were written and before the round was marked finished."""
        folder = tmp_path / "run"
        first = FakeBatchClient(handlers=[_answers(_scripts())] * 8)
        reference = _loops()
        costs = drive_batch(reference, first, folder=folder, now=Clock())
        lines = (folder / ROUNDS_FILE).read_text().splitlines(keepends=True)
        (folder / ROUNDS_FILE).write_text("".join(lines[:-1]))  # round 8 has no finished row
        replies_before = (folder / REPLIES_FILE).read_text()

        second = _resumer(first, "b8", [_answers(_scripts())])
        loops = _loops()
        assert drive_batch(loops, second, folder=folder, now=Clock(ticks=15)) == costs
        assert second.waited == ["b8"]
        assert len(second.submitted) == 8  # only the seeded entries: nothing was submitted
        assert (folder / REPLIES_FILE).read_text() == replies_before  # nothing written twice
        assert _rounds(folder)[-1].finished_at is not None
        assert _outcomes(loops) == _outcomes(reference)

    def test_some_replies_written_and_some_not(self, tmp_path: Path) -> None:
        """A kill between two replies of one round: only the missing one is taken from the batch."""
        whole, cut = tmp_path / "whole", tmp_path / "cut"
        reference = _uninterrupted(whole)
        first_batch = FakeBatchClient(handlers=[_answers(_scripts())] * 8)
        drive_batch(_loops(), first_batch, folder=cut, now=Clock())
        rounds = (cut / ROUNDS_FILE).read_text().splitlines(keepends=True)
        replies = (cut / REPLIES_FILE).read_text().splitlines(keepends=True)
        (cut / ROUNDS_FILE).write_text("".join(rounds[:3]))  # round 2 open
        (cut / REPLIES_FILE).write_text("".join(replies[:3]))  # round 1, and A's reply of round 2

        resumed = _resumer(first_batch, "b2", [_answers(_scripts())] * 7)
        loops = _loops()
        drive_batch(loops, resumed, folder=cut, now=Clock(ticks=3))
        assert resumed.waited[0] == "b2"
        assert _outcomes(loops) == _outcomes(reference)
        assert (cut / REPLIES_FILE).read_text() == (whole / REPLIES_FILE).read_text()
        assert (cut / ROUNDS_FILE).read_text() == (whole / ROUNDS_FILE).read_text()

    def test_replay_gives_the_loops_exactly_the_state_the_live_run_had(
        self, tmp_path: Path
    ) -> None:
        folder = tmp_path / "run"
        live = _uninterrupted(folder)
        rebuilt = _loops()
        assert replay(rebuilt, folder) is None
        assert _outcomes(rebuilt) == _outcomes(live)  # times, batch ids, costs and all

    def test_replay_returns_the_open_round_and_calls_no_model(self, tmp_path: Path) -> None:
        _interrupt_after_round_two_is_submitted(tmp_path / "cut")
        loops = _loops()
        open_round = replay(loops, tmp_path / "cut")
        assert open_round is not None
        assert (open_round.round, open_round.batch_id) == (2, "b2")
        assert open_round.finished_at is None
        assert [loop.call_index for loop in loops] == [1, 1]

    def test_replay_of_an_empty_folder_changes_nothing(self, tmp_path: Path) -> None:
        loops = _loops()
        assert replay(loops, tmp_path / "nothing-yet") is None
        assert [loop.call_index for loop in loops] == [0, 0]

    def test_recorded_calls_that_are_not_the_pending_calls_are_refused(
        self, tmp_path: Path
    ) -> None:
        folder = tmp_path / "cut"
        dead = _interrupt_after_round_two_is_submitted(folder)
        text = (folder / ROUNDS_FILE).read_text()
        (folder / ROUNDS_FILE).write_text(text.replace(custom_id(B, 1), custom_id(B, 9)))
        resumed = _resumer(dead, "b2", [_answers(_scripts())] * 7)
        with pytest.raises(ConfigurationError, match=r"cannot resume: recorded batch b2"):
            drive_batch(_loops(), resumed, folder=folder, now=Clock(ticks=3))
        assert resumed.waited == []  # refused before the batch was waited on
        assert len(resumed.submitted) == 2  # and before anything was submitted

    def test_a_case_that_the_open_round_never_held_is_refused(self, tmp_path: Path) -> None:
        folder = tmp_path / "cut"
        dead = _interrupt_after_round_two_is_submitted(folder)
        rows = _rounds(folder)
        only_a = rows[-1].model_copy(update={"custom_ids": (custom_id(A, 1),)})
        (folder / ROUNDS_FILE).write_text(
            "".join(r.model_dump_json() + "\n" for r in [*rows[:-1], only_a])
        )
        resumed = _resumer(dead, "b2", [_answers(_scripts())] * 7)
        with pytest.raises(ConfigurationError, match="cannot resume"):
            drive_batch(_loops(), resumed, folder=folder, now=Clock(ticks=3))
        assert resumed.waited == []

    @pytest.mark.parametrize("recorded", ["Z#1", "ANC09CA024#x", "ANC09CA024#7", "ANC09CA024"])
    def test_a_recorded_id_that_is_not_a_call_of_this_run_is_refused(
        self, tmp_path: Path, recorded: str
    ) -> None:
        folder = tmp_path / "cut"
        dead = _interrupt_after_round_two_is_submitted(folder)
        rows = _rounds(folder)
        wrong = rows[-1].model_copy(update={"custom_ids": (recorded, custom_id(B, 1))})
        (folder / ROUNDS_FILE).write_text(
            "".join(r.model_dump_json() + "\n" for r in [*rows[:-1], wrong])
        )
        resumed = _resumer(dead, "b2", [_answers(_scripts())] * 7)
        with pytest.raises(ConfigurationError, match="cannot resume"):
            drive_batch(_loops(), resumed, folder=folder, now=Clock(ticks=3))

    def test_a_loop_that_would_not_make_the_recorded_call_is_refused(self, tmp_path: Path) -> None:
        """A cap lowered between the attempts stops a case before the call the round holds."""
        folder = tmp_path / "cut"
        dead = FakeBatchClient(handlers=[_die])
        with pytest.raises(_KilledError):
            drive_batch(_loops(), dead, folder=folder, now=Clock())
        capped = [CaseLoop(_raw(), _view(), _config(cap_usd=0.0001)), _loops()[1]]
        resumed = _resumer(dead, "b1", [_answers(_scripts())])
        with pytest.raises(ConfigurationError, match="cannot resume"):
            drive_batch(capped, resumed, folder=folder, now=Clock(ticks=1))
        assert resumed.waited == []

    def test_a_reply_for_a_case_not_in_the_run_is_refused(self, tmp_path: Path) -> None:
        folder = tmp_path / "cut"
        _interrupt_after_round_two_is_submitted(folder)
        with pytest.raises(ConfigurationError, match="ANC09CA024"):
            replay([CaseLoop(_other(), None, _config())], folder)

    def test_a_reply_out_of_order_is_refused(self, tmp_path: Path) -> None:
        folder = tmp_path / "cut"
        _interrupt_after_round_two_is_submitted(folder)
        rows = _replies(folder)
        late = rows[0].model_copy(update={"call_index": 3})
        (folder / REPLIES_FILE).write_text(late.model_dump_json() + "\n")
        with pytest.raises(ConfigurationError, match="call 3"):
            replay(_loops(), folder)

    def test_a_reply_for_a_case_that_has_stopped_is_refused(self, tmp_path: Path) -> None:
        folder = tmp_path / "cut"
        _interrupt_after_round_two_is_submitted(folder)
        loops = _loops()
        loops[0].stop("failed: rounds")
        with pytest.raises(ConfigurationError, match="call 0"):
            replay(loops, folder)

    @pytest.mark.parametrize("name", [REPLIES_FILE, ROUNDS_FILE])
    def test_a_half_written_line_is_refused_by_file(self, tmp_path: Path, name: str) -> None:
        folder = tmp_path / "cut"
        _interrupt_after_round_two_is_submitted(folder)
        with (folder / name).open("a") as handle:
            handle.write('{"case_id": "ANC09CA024", "call_in')
        with pytest.raises(ConfigurationError, match=rf"{name}.*half-written"):
            replay(_loops(), folder)


# --------------------------------------------------------------------------------------------
# The synchronous driver
# --------------------------------------------------------------------------------------------


class TestSync:
    def test_every_call_is_written_as_it_is_made(self, tmp_path: Path) -> None:
        folder = tmp_path / "run"
        loops = _loops()
        client = ScriptedClient(_sync_replies(_scripts()))
        drive_sync(loops, client, folder=folder, now=Clock())
        assert client.calls == 10
        rows = _replies(folder)
        assert [(r.case_id, r.call_index) for r in rows] == [
            *[(A, n) for n in range(8)],
            *[(B, n) for n in range(2)],
        ]
        assert {r.batch_id for r in rows} == {None}
        assert {r.error for r in rows} == {None}
        assert all(r.sent_at < r.returned_at for r in rows)
        assert not (folder / ROUNDS_FILE).exists()
        for call, row in zip(loops[0].outcome.calls, rows, strict=False):  # the trail's times
            assert (call.sent_at, call.returned_at, call.batch_id) == (
                row.sent_at,
                row.returned_at,
                None,
            )
        assert [o.stop_reason for o in _outcomes(loops)] == ["done", "done"]

    def test_sync_and_batch_give_equal_outcomes_for_the_same_replies(self, tmp_path: Path) -> None:
        batch_loops = _uninterrupted(tmp_path / "batch")
        sync_loops = _loops()
        drive_sync(
            sync_loops,
            ScriptedClient(_sync_replies(_scripts())),
            folder=tmp_path / "sync",
            now=Clock(),
        )
        assert [_core(o) for o in _outcomes(sync_loops)] == [
            _core(o) for o in _outcomes(batch_loops)
        ]

    def test_the_replies_are_the_same_rows_either_way_but_for_times_and_batch_ids(
        self, tmp_path: Path
    ) -> None:
        _uninterrupted(tmp_path / "batch")
        drive_sync(
            _loops(),
            ScriptedClient(_sync_replies(_scripts())),
            folder=tmp_path / "sync",
            now=Clock(),
        )

        def kernel(folder: Path) -> list[tuple[str, int, ModelReply | None, str | None]]:
            rows = _replies(folder)
            return sorted((r.case_id, r.call_index, r.reply, r.error) for r in rows)

        assert kernel(tmp_path / "sync") == kernel(tmp_path / "batch")

    def test_a_failed_call_is_recorded_and_the_step_re_issued_once(self, tmp_path: Path) -> None:
        folder = tmp_path / "run"
        scripts = _scripts([None, *B_REPLIES])
        loops = _loops()
        drive_sync(loops, ScriptedClient(_sync_replies(scripts)), folder=folder, now=Clock())
        failed = next(r for r in _replies(folder) if (r.case_id, r.call_index) == (B, 0))
        assert (failed.reply, failed.error) == (None, "model: boom")
        assert loops[1].outcome.stop_reason == "done"
        assert loops[1].outcome.calls[0].protocol_error == "model: boom"

    def test_two_failures_in_a_row_stop_the_case(self, tmp_path: Path) -> None:
        scripts = _scripts([None, None])
        loops = _loops()
        drive_sync(
            loops, ScriptedClient(_sync_replies(scripts)), folder=tmp_path / "run", now=Clock()
        )
        assert loops[1].outcome.stop_reason == "failed: h0"

    def test_an_error_that_is_not_a_model_error_ends_the_run_and_keeps_finished_calls(
        self, tmp_path: Path
    ) -> None:
        folder = tmp_path / "run"
        client = ScriptedClient(_sync_replies(_scripts()), die_at=4)
        with pytest.raises(_KilledError):
            drive_sync(_loops(), client, folder=folder, now=Clock())
        assert [(r.case_id, r.call_index) for r in _replies(folder)] == [(A, 0), (A, 1), (A, 2)]

    def test_a_reply_is_on_disk_before_its_loop_sees_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        whole, cut = tmp_path / "whole", tmp_path / "cut"
        reference = _loops()
        drive_sync(reference, ScriptedClient(_sync_replies(_scripts())), folder=whole, now=Clock())
        _accept_fails_at(monkeypatch, B, 0)
        with pytest.raises(_KilledError):
            drive_sync(_loops(), ScriptedClient(_sync_replies(_scripts())), folder=cut, now=Clock())
        assert [(r.case_id, r.call_index) for r in _replies(cut)][-1] == (B, 0)

        client = ScriptedClient(_sync_replies(_scripts())[9:])  # only B's second call is left
        loops = _loops()
        drive_sync(loops, client, folder=cut, now=Clock(ticks=100))
        assert client.calls == 1
        assert [_core(o) for o in _outcomes(loops)] == [_core(o) for o in _outcomes(reference)]

    def test_a_crashed_sync_run_resumes_to_the_same_outcomes_and_replies(
        self, tmp_path: Path
    ) -> None:
        whole, cut = tmp_path / "whole", tmp_path / "cut"
        reference = _loops()
        drive_sync(reference, ScriptedClient(_sync_replies(_scripts())), folder=whole, now=Clock())
        with pytest.raises(_KilledError):
            drive_sync(
                _loops(),
                ScriptedClient(_sync_replies(_scripts()), die_at=4),
                folder=cut,
                now=Clock(),
            )
        client = ScriptedClient(_sync_replies(_scripts())[3:])
        loops = _loops()
        drive_sync(loops, client, folder=cut, now=Clock(ticks=100))
        assert client.calls == 7  # the three answered calls are not made again
        assert [_core(o) for o in _outcomes(loops)] == [_core(o) for o in _outcomes(reference)]
        assert [(r.case_id, r.call_index, r.reply) for r in _replies(cut)] == [
            (r.case_id, r.call_index, r.reply) for r in _replies(whole)
        ]

    def test_a_folder_with_an_open_batch_round_is_not_continued_synchronously(
        self, tmp_path: Path
    ) -> None:
        folder = tmp_path / "cut"
        _interrupt_after_round_two_is_submitted(folder)
        client = ScriptedClient(_sync_replies(_scripts()))
        with pytest.raises(ConfigurationError, match="batch round"):
            drive_sync(_loops(), client, folder=folder, now=Clock())
        assert client.calls == 0

    def test_replay_restores_a_sync_run(self, tmp_path: Path) -> None:
        folder = tmp_path / "run"
        live = _loops()
        drive_sync(live, ScriptedClient(_sync_replies(_scripts())), folder=folder, now=Clock())
        rebuilt = _loops()
        assert replay(rebuilt, folder) is None
        assert _outcomes(rebuilt) == _outcomes(live)


# --------------------------------------------------------------------------------------------
# The rows, and what the drivers refuse to start with
# --------------------------------------------------------------------------------------------


class TestRows:
    def test_a_reply_row_survives_json_exactly(self) -> None:
        reply = _script(HAPPY)[3]
        assert reply is not None
        assert reply.usage.cached_tokens is not None
        row = ReplyRow(
            case_id=A,
            call_index=3,
            reply=reply,
            error=None,
            sent_at=T0,
            returned_at=T0 + timedelta(seconds=7),
            batch_id="b4",
        )
        again = ReplyRow.model_validate_json(row.model_dump_json())
        assert again == row
        assert again.reply == reply
        assert again.reply is not None
        assert again.reply.reasoning_details == reply.reasoning_details
        assert again.reply.usage == reply.usage
        assert again.reply.tool_calls == reply.tool_calls

    def test_a_failed_reply_row_survives_json(self) -> None:
        row = ReplyRow(
            case_id=A,
            call_index=0,
            reply=None,
            error="status 500",
            sent_at=T0,
            returned_at=T0,
            batch_id=None,
        )
        assert ReplyRow.model_validate_json(row.model_dump_json()) == row

    def test_a_round_row_has_no_finish_until_it_is_finished(self) -> None:
        row = RoundRow(round=1, batch_id="b1", submitted_at=T0, custom_ids=(custom_id(A, 0),))
        assert (row.finished_at, row.status, row.reported_cost_usd) == (None, None, None)
        assert RoundRow.model_validate_json(row.model_dump_json()) == row


class TestRefusals:
    def _loop_named(self, case_id: str) -> CaseLoop:
        return CaseLoop({**_raw(), "ntsbNumber": case_id}, None, _config())

    def test_a_case_id_holding_the_separator_is_refused_by_the_batch_driver(
        self, tmp_path: Path
    ) -> None:
        loops = [self._loop_named("ANC09#CA024")]
        fake = FakeBatchClient(handlers=[])
        with pytest.raises(ConfigurationError, match=r"'#'"):
            drive_batch(loops, fake, folder=tmp_path / "run", now=Clock())

    def test_and_by_the_sync_driver(self, tmp_path: Path) -> None:
        loops = [self._loop_named("ANC09#CA024")]
        with pytest.raises(ConfigurationError, match=r"'#'"):
            drive_sync(loops, ScriptedClient([]), folder=tmp_path / "run", now=Clock())

    def test_two_loops_for_one_case_are_refused(self, tmp_path: Path) -> None:
        loops = [self._loop_named("ANC09CA024"), self._loop_named("ANC09CA024")]
        with pytest.raises(ConfigurationError, match="twice"):
            drive_batch(loops, FakeBatchClient(handlers=[]), folder=tmp_path / "run", now=Clock())
