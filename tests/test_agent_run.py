"""Tests for arm C in the harness (S3.1 Task 10): ``agent/run.py``.

Two cases, as in the drivers' tests: ``ANC09CA024`` with a two-document docket (the eight calls
of the loop's happy path) and a second fixture record whose docket has nothing readable (two
calls). The batch tests use ``FakeBatchClient`` from ``tests/test_runner.py``; the sync tests a
client scripted in the order ``drive_sync`` asks. Offline; no model is called.
"""

import copy
import dataclasses
import inspect
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal

import pytest
from tests.test_agent_documents import CAUSE, ONE, TWO, _raw, _withheld
from tests.test_agent_drive import (
    B_REPLIES,
    A,
    B,
    Clock,
    ScriptedClient,
    _answers,
    _die,
    _ended,
    _KilledError,
    _other,
    _resumer,
    _script,
    _scripts,
    _sync_replies,
)
from tests.test_agent_loop import HAPPY, STATS, T0, TABLES, _choose, _hyp
from tests.test_attach import _docket as small_docket
from tests.test_marks import FACTUAL, S1, S2
from tests.test_runner import FakeBatchClient

from ntsb_probable_cause import sources
from ntsb_probable_cause.agent import loop as agent_loop
from ntsb_probable_cause.agent import run as run_module
from ntsb_probable_cause.agent import texts
from ntsb_probable_cause.agent.documents import case_marks, docket_view, evidence_payload
from ntsb_probable_cause.agent.drive import REPLIES_FILE, ROUNDS_FILE
from ntsb_probable_cause.agent.loop import LoopConfig
from ntsb_probable_cause.agent.run import GUIDANCE, TRAIL_FILE, AgentRunner
from ntsb_probable_cause.agent.schemas import CODING_TOOLS, Without
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.docket.manifest import Docket
from ntsb_probable_cause.errors import (
    BatchCancelledError,
    BudgetError,
    ConfigurationError,
    DocketError,
    LeakageError,
)
from ntsb_probable_cause.fields import EvidenceRole, occurrence_codes
from ntsb_probable_cause.model.batch import BatchRequest, BatchStatus
from ntsb_probable_cause.model.client import (
    ModelClient,
    ModelReply,
    ModelSettings,
    Payload,
    Turn,
    Usage,
)
from ntsb_probable_cause.model.client import tool_reply as reply_calling
from ntsb_probable_cause.records.marks import CaseMark
from ntsb_probable_cause.scoring import claims, prompt
from ntsb_probable_cause.scoring.budget import month_spent, open_reservations
from ntsb_probable_cause.scoring.records import (
    CONTEXT_FAILURE,
    CaseResult,
    RunRecord,
    StepRecord,
    fingerprint,
    read_jsonl,
)
from ntsb_probable_cause.scoring.runner import Runner, RunSpec, project_cost

RAWS = (_raw(), _other())
# What every reply of ``_scripts()`` reports it cost: 0.0011 x (position + 1), per case.
A_COSTS = tuple(0.0011 * (n + 1) for n in range(8))
B_COSTS = tuple(0.0011 * (n + 1) for n in range(2))


def keyed(docket: Docket, mkey: int) -> Docket:
    """``docket`` as the docket of ``mkey``: its own key and its listing's (``small_docket`` is
    built with key 1 for every case, and the runner's pairing guard reads the key)."""
    listing = docket.listing.model_copy(update={"mkey": mkey})
    return docket.model_copy(update={"mkey": mkey, "listing": listing})


class Dockets:
    """A ``DocketReader`` over fixed dockets, by ``mKey``; it records what it was asked for.

    Each docket is given the key it is stored under, as a real reader returns a case's own.
    """

    def __init__(
        self, by_mkey: Mapping[int, Docket] | None = None, version: Literal["v1", "v2"] = "v1"
    ) -> None:
        given = dict(by_mkey) if by_mkey is not None else _default_dockets()
        self.by_mkey = {mkey: keyed(docket, mkey) for mkey, docket in given.items()}
        self.version: Literal["v1", "v2"] = version
        self.reads: list[int] = []

    def read(self, mkey: int) -> Docket:
        self.reads.append(mkey)
        return self.by_mkey[mkey]


def _mkey(raw: Mapping[str, object]) -> int:
    mkey = raw["mKey"]
    assert isinstance(mkey, int)
    return mkey


def _default_dockets() -> dict[int, Docket]:
    """A's docket offers two documents; B's has nothing readable, so B is offered none."""
    return {_mkey(RAWS[0]): small_docket({1: ONE, 2: TWO}), _mkey(RAWS[1]): small_docket({})}


def _spec(**changes: object) -> RunSpec:
    base = RunSpec(
        sample="dev-400",
        arm="C",
        guidance=GUIDANCE,
        cap_usd=1.0,
        expected_cost_per_case_usd=0.01,
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def _sync_spec(**changes: object) -> RunSpec:
    return _spec(sync=True, price_variant="standard", **changes)


def _runner(  # noqa: PLR0913 -- every parameter is a seam a test needs.
    runs_dir: Path,
    *,
    client: ModelClient | None = None,
    batch: FakeBatchClient | None = None,
    docket: Dockets | None = None,
    spent: float = 0.0,
    dirty: bool = False,
    clock: Clock | None = None,
    round_number: int | None = None,
    pass_reasoning: bool = False,
    without: frozenset[Without] = frozenset(),
    max_rounds: int = 40,
    ledger_path: Path | None = None,
    # S3.2 Task 6: a `heldout-400` run needs the registration committed; these tests are about
    # the other rules, so the registration is committed unless a test says it is not.
    is_committed: Callable[[Path], bool] = lambda _path: True,
) -> AgentRunner:
    return AgentRunner(
        client if client is not None else ScriptedClient([]),
        batch=batch,
        tables=TABLES,
        stats=STATS,
        seen_pairs=frozenset({"552230"}),
        runs_dir=runs_dir,
        month_spent_usd=spent,
        commit=("abc1234", dirty),
        docket=docket if docket is not None else Dockets(),
        now=clock if clock is not None else Clock(),
        round_number=round_number,
        pass_reasoning=pass_reasoning,
        without=without,
        max_rounds=max_rounds,
        ledger_path=ledger_path,
        is_committed=is_committed,
    )


def _sync_run(runs_dir: Path, **changes: object) -> tuple[RunRecord, Path]:
    client = ScriptedClient(_sync_replies(_scripts()))
    record = _runner(runs_dir, client=client).run(_sync_spec(**changes), RAWS)
    return record, runs_dir / record.run_id


def _batch_run(runs_dir: Path) -> tuple[RunRecord, Path]:
    fake = FakeBatchClient(handlers=[_answers(_scripts())] * 8)
    record = _runner(runs_dir, batch=fake).run(_spec(), RAWS)
    return record, runs_dir / record.run_id


def _cases(folder: Path) -> list[CaseResult]:
    return read_jsonl(folder / "cases.jsonl", CaseResult)


def _record(folder: Path) -> RunRecord:
    (record,) = read_jsonl(folder / "run.jsonl", RunRecord)
    return record


def _spec_file(folder: Path) -> dict[str, object]:
    recorded = json.loads((folder / "spec.json").read_text())
    assert isinstance(recorded, dict)
    return recorded


def _untimed(calls: Sequence[AgentCall]) -> list[AgentCall]:
    return [c.model_copy(update={"sent_at": T0, "returned_at": T0}) for c in calls]


# --------------------------------------------------------------------------------------------
# A run, its files and its records
# --------------------------------------------------------------------------------------------


class TestSyncRun:
    def test_a_two_case_sync_run_writes_every_file_with_arm_c(self, tmp_path: Path) -> None:
        record, folder = _sync_run(tmp_path / "runs")
        for name in ("spec.json", REPLIES_FILE, TRAIL_FILE, "cases.jsonl", "steps.jsonl"):
            assert (folder / name).is_file(), name
        assert not (folder / ROUNDS_FILE).exists()  # a sync run has no rounds
        assert _record(folder) == record
        assert record.run_id == folder.name
        assert record.run_id.endswith("-abc1234-dev-400-C")
        assert (record.arm, record.sample, record.evidence_version) == ("C", "dev-400", "v1")
        assert record.finished is not None
        assert record.cases == 2
        assert record.prompt_version == texts.prompt_version(GUIDANCE)
        assert (record.guidance, record.guidance_sha256) == (
            GUIDANCE,
            prompt.guidance_sha256(GUIDANCE),
        )
        assert (record.batch_ids, record.reported_batch_cost_usd) == ((), None)
        assert record.cost_usd == pytest.approx(sum(A_COSTS) + sum(B_COSTS))
        assert (record.commit_sha, record.dirty) == ("abc1234", False)

    def test_every_case_is_scored_and_carries_its_cost_and_replies(self, tmp_path: Path) -> None:
        _, folder = _sync_run(tmp_path / "runs")
        a, b = _cases(folder)
        assert (a.case_id, b.case_id) == (A, B)
        assert (a.failure, b.failure) == (None, None)
        assert a.scores is not None
        assert b.scores is not None
        assert a.scores.occurrence_top1 == (a.verdict_occurrence[:1] == ("552230",))
        assert a.scores.pair_unseen is False  # the answer's 552230 is among the seen pairs
        assert a.cost_usd == pytest.approx(sum(A_COSTS))
        assert b.cost_usd == pytest.approx(sum(B_COSTS))
        assert a.reply_completion_tokens == tuple(100 + n for n in range(8))
        assert a.reply_reasoning_tokens == tuple(range(8))
        assert a.reply_finish_reasons == ("tool_calls",) * 7 + (None,)
        assert a.verdict_occurrence == occurrence_codes(RAWS[0])
        assert (a.split, a.investigation_class) == ("dev", "C")

    def test_the_documents_not_read_are_the_offered_ones_the_agent_skipped(
        self, tmp_path: Path
    ) -> None:
        _, folder = _sync_run(tmp_path / "runs")
        a, b = _cases(folder)
        assert a.documents_not_read == ("2: skipped",)  # read 1, skipped 2 twice
        assert b.documents_not_read == ()  # nothing was offered

    def test_the_marks_are_the_split_over_every_document_read(self, tmp_path: Path) -> None:
        _, folder = _sync_run(tmp_path / "runs")
        a, b = _cases(folder)
        view = docket_view(RAWS[0], small_docket({1: ONE, 2: TWO}))
        assert (a.marks, a.narrative_share) == case_marks(view, RAWS[0], (1,), frozenset())
        assert (b.marks, b.narrative_share) == ((), None)

    def test_a_document_read_holding_half_the_narrative_marks_the_case(
        self, tmp_path: Path
    ) -> None:
        """S2.6's marks mean the same in both arms (0078): here, from the document read."""
        raw = copy.deepcopy(_raw())
        narratives = raw["narratives"]
        assert isinstance(narratives, list)
        narratives[0]["concatenatedFactualNarrative"] = FACTUAL
        docket = Dockets(
            {
                _mkey(raw): small_docket({1: f"[page 1 of 3]\n{S1}. {S2}.\n", 2: TWO}),
                _mkey(RAWS[1]): small_docket({}),
            }
        )
        client = ScriptedClient(_sync_replies(_scripts()))
        record = _runner(tmp_path / "runs", client=client, docket=docket).run(
            _sync_spec(), (raw, RAWS[1])
        )
        a, _ = _cases(tmp_path / "runs" / record.run_id)
        assert a.failure is None
        assert a.marks == (CaseMark(kind="narrative_coverage", count=1),)
        assert a.narrative_share == 0.5

    def test_the_trail_holds_every_call_of_every_case(self, tmp_path: Path) -> None:
        record, folder = _sync_run(tmp_path / "runs")
        trail = read_jsonl(folder / TRAIL_FILE, AgentCall)
        assert [(c.case_id, c.call_index) for c in trail] == [
            *[(A, n) for n in range(8)],
            (B, 0),
            (B, 1),
        ]
        assert {c.run_id for c in trail} == {record.run_id}
        assert {(c.commit_sha, c.dirty) for c in trail} == {("abc1234", False)}

    def test_spec_json_records_every_setting_the_loop_depends_on(self, tmp_path: Path) -> None:
        _, folder = _sync_run(tmp_path / "runs")
        recorded = _spec_file(folder)
        assert recorded["arm"] == "C"
        assert recorded["agent_prompt_version"] == texts.prompt_version(GUIDANCE)
        assert recorded["stats"] == "s3"
        assert (recorded["max_rounds"], recorded["max_coding_calls"]) == (40, 6)
        assert (recorded["without"], recorded["pass_reasoning"]) == ([], False)
        assert recorded["cap_usd"] == 1.0
        assert recorded["guidance"] == list(GUIDANCE)
        assert "round" not in recorded
        assert list(recorded)[-3:] == ["commit_sha", "dirty", "case_ids"]
        assert recorded["case_ids"] == [A, B]


def _edit_covered_source(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """What an edit to a covered file looks like to a reader once it is made: a callback that
    makes ``texts.source_text`` return every file with a comment line added."""
    original = texts.source_text

    def edit() -> None:
        monkeypatch.setattr(
            texts, "source_text", lambda package, name: f"{original(package, name)}# an edit\n"
        )

    return edit


class _EditingClient(ScriptedClient):
    """A scripted client that has a covered file edited at its first call, as an editor would
    while the run is in flight."""

    def __init__(self, replies: Sequence[ModelReply | None], edit: Callable[[], None]) -> None:
        super().__init__(replies)
        self._edit = edit

    def complete(
        self,
        payload: Payload,
        settings: ModelSettings,
        *,
        system: str = "",
        history: Sequence[Turn] = (),
    ) -> ModelReply:
        if self.calls == 0:
            self._edit()
        return super().complete(payload, settings, system=system, history=history)


class TestPromptVersionIsFixedAtTheStart:
    """Decision 0133: ``run.jsonl`` names the text the run sent, never an edit made meanwhile."""

    def test_a_covered_file_edited_after_the_run_starts_is_not_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        version = texts.prompt_version(GUIDANCE)
        client = _EditingClient(_sync_replies(_scripts()), _edit_covered_source(monkeypatch))
        record = _runner(tmp_path / "runs", client=client).run(_sync_spec(), RAWS)
        assert texts.prompt_version(GUIDANCE) != version, "the edit is in force at the end"
        folder = tmp_path / "runs" / record.run_id
        assert record.prompt_version == version
        assert _record(folder).prompt_version == version
        assert _spec_file(folder)["agent_prompt_version"] == version

    def test_spec_json_and_run_jsonl_carry_the_same_version(self, tmp_path: Path) -> None:
        record, folder = _sync_run(tmp_path / "runs")
        assert _spec_file(folder)["agent_prompt_version"] == _record(folder).prompt_version
        assert record.prompt_version == _record(folder).prompt_version

    def test_a_run_that_dies_records_the_version_it_started_with(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The records written on the way out of a dead run are the start's too."""
        version = texts.prompt_version(GUIDANCE)
        edit = _edit_covered_source(monkeypatch)

        def edit_then_die(_batch_id: str, _requests: Sequence[BatchRequest]) -> BatchStatus:
            edit()
            raise _KilledError

        runs = tmp_path / "runs"
        with pytest.raises(_KilledError):
            _runner(runs, batch=FakeBatchClient(handlers=[edit_then_die])).run(_spec(), RAWS)
        (folder,) = [p for p in runs.iterdir() if p.is_dir()]
        assert texts.prompt_version(GUIDANCE) != version
        assert _record(folder).prompt_version == version
        assert _spec_file(folder)["agent_prompt_version"] == version

    def test_a_resume_compares_the_recorded_version_with_the_current_code(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Computing the version once must not weaken the resume check."""
        runs = tmp_path / "runs"
        with pytest.raises(_KilledError):
            _runner(runs, batch=FakeBatchClient(handlers=[_die])).run(_spec(), RAWS)
        (folder,) = [p for p in runs.iterdir() if p.is_dir()]
        _edit_covered_source(monkeypatch)()
        with pytest.raises(ConfigurationError, match="agent_prompt_version"):
            _runner(runs, batch=FakeBatchClient(handlers=[])).run(_spec(), RAWS, resume=folder.name)


class TestSteps:
    def test_one_step_per_checkpoint_named_by_its_kind(self, tmp_path: Path) -> None:
        _, folder = _sync_run(tmp_path / "runs")
        a, b = _cases(folder)
        assert [s.tool for s in a.steps] == [
            "checkpoint:h0",
            "checkpoint:h1",
            "checkpoint:answer",
            "checkpoint:refine",
        ]
        assert [s.step for s in a.steps] == [0, 1, 2, 3]
        assert [s.tool for s in b.steps] == ["checkpoint:h0", "checkpoint:answer"]
        assert {(s.arm, s.condition, s.day) for s in [*a.steps, *b.steps]} == {("C", "full", None)}
        steps = read_jsonl(folder / "steps.jsonl", StepRecord)
        assert steps == [*a.steps, *b.steps]

    def test_the_last_step_says_how_the_case_answered(self, tmp_path: Path) -> None:
        _, folder = _sync_run(tmp_path / "runs")
        a, b = _cases(folder)
        assert [s.stop_reason for s in a.steps] == ["", "", "", "answered"]
        assert [s.stop_reason for s in b.steps] == ["", "answered"]
        assert a.steps[-1].hypothesis.findings[0].item8 == "02063015"  # the refined answer

    def test_an_abstention_is_scored_and_its_last_step_says_so(self, tmp_path: Path) -> None:
        abstains = [
            reply_calling("record_hypothesis", _hyp()),
            reply_calling("submit_answer", _hyp(abstain=True, findings=[])),
        ]
        client = ScriptedClient([*_script(HAPPY), *_script(abstains)])
        record = _runner(tmp_path / "runs", client=client).run(_sync_spec(), RAWS)
        _, b = _cases(tmp_path / "runs" / record.run_id)
        assert (b.failure, b.scores is not None) == (None, True)
        assert [s.stop_reason for s in b.steps] == ["", "abstained"]

    def test_tokens_and_cost_are_summed_over_the_calls_since_the_previous_checkpoint(
        self, tmp_path: Path
    ) -> None:
        _, folder = _sync_run(tmp_path / "runs")
        a, _ = _cases(folder)
        groups = [(0,), (1, 2), (3, 4, 5, 6), (7,)]  # h0 | choice1, h1 | choice2, 2 coding, answer
        for step, calls in zip(a.steps, groups, strict=True):
            assert step.cost_usd == pytest.approx(sum(A_COSTS[n] for n in calls))
            assert step.prompt_tokens == sum(1000 + n for n in calls)
            assert step.completion_tokens == sum(100 + n for n in calls)
            assert step.reasoning_tokens == sum(calls)
            assert step.reply_completion_tokens == tuple(100 + n for n in calls)
        assert a.steps[-1].cumulative_cost_usd == pytest.approx(sum(A_COSTS))
        assert a.steps[1].cumulative_cost_usd == pytest.approx(sum(A_COSTS[:3]))

    def test_each_step_says_what_the_agent_had_seen_by_then(self, tmp_path: Path) -> None:
        _, folder = _sync_run(tmp_path / "runs")
        a, b = _cases(folder)
        evidence = evidence_payload(RAWS[0], frozenset())
        roles = tuple(sorted(evidence.fields()))
        assert a.steps[0].returned_roles == roles  # h0: the evidence only
        assert a.steps[0].documents_attached == ()
        seen = tuple(sorted({*roles, "docket_listing", "docket_documents"}))
        for step in a.steps[1:]:  # after the listing and document 1
            assert step.returned_roles == seen
            assert step.documents_attached == (f"1: exam_site, {len(ONE) // 4} tokens",)
        assert {s.payload_fingerprint for s in a.steps} == {fingerprint(evidence)}
        assert {s.not_available for s in a.steps} == {("3: unreadable: scan",)}
        # Case B's docket lists three documents, none readable: the listing went back with H0's
        # result all the same (Andy, 2026-10-01), so every step after H0 has seen it.
        b_roles = tuple(sorted(evidence_payload(RAWS[1], frozenset()).fields()))
        assert b.steps[0].returned_roles == b_roles
        assert {s.returned_roles for s in b.steps[1:]} == {
            tuple(sorted({*b_roles, "docket_listing"}))
        }
        assert {s.documents_attached for s in b.steps} == {()}
        assert {s.not_available for s in b.steps} == {
            ("1: unreadable: scan", "2: unreadable: scan", "3: unreadable: scan")
        }
        assert {(s.model, s.price_variant) for s in a.steps} == {("openai/gpt-6-luna", "standard")}

    def test_decisions_on_documents_not_on_offer_change_no_record_but_the_trails_count(
        self, tmp_path: Path
    ) -> None:
        """Decision 0134: [3] cannot be read and [1] was already read; both decisions are
        tolerated and counted, and the steps and the documents not read stay as without them."""
        replies = list(HAPPY)
        replies[1] = reply_calling("choose_documents", _choose({1: True, 2: False, 3: True}))
        replies[3] = reply_calling("choose_documents", _choose({2: False, 1: True}))
        client = ScriptedClient(_sync_replies(_scripts(a=replies)))
        record = _runner(tmp_path / "runs", client=client).run(_sync_spec(), RAWS)
        folder = tmp_path / "runs" / record.run_id
        a, _ = _cases(folder)
        _, plain = _sync_run(tmp_path / "plain")
        a_plain, _ = _cases(plain)
        assert (a.failure, a.documents_not_read) == (None, ("2: skipped",))
        assert [s.documents_attached for s in a.steps] == [
            s.documents_attached for s in a_plain.steps
        ]
        trail = [c for c in read_jsonl(folder / TRAIL_FILE, AgentCall) if c.case_id == A]
        chosen = [c for c in trail if c.tool == "choose_documents"]
        assert [(c.offered, c.argument_errors, c.retry) for c in chosen] == [
            ((1, 2), 1, False),
            ((2,), 1, False),
        ]
        assert chosen[0].arguments == json.loads(_choose({1: True, 2: False, 3: True}))


class TestBatchRun:
    def test_a_batch_run_writes_the_same_records_and_its_batch_ids(self, tmp_path: Path) -> None:
        record, folder = _batch_run(tmp_path / "batch")
        _, sync_folder = _sync_run(tmp_path / "sync")
        assert record.batch_ids == tuple(f"b{n}" for n in range(1, 9))
        assert record.reported_batch_cost_usd == pytest.approx(2 * 0.5 + 6 * 0.25)
        assert record.cost_usd == pytest.approx(sum(A_COSTS) + sum(B_COSTS))
        assert (folder / ROUNDS_FILE).is_file()
        batch_cases = _cases(folder)
        sync_cases = _cases(sync_folder)
        assert [(c.case_id, c.scores, c.failure, c.cost_usd) for c in batch_cases] == [
            (c.case_id, c.scores, c.failure, c.cost_usd) for c in sync_cases
        ]
        assert [len(c.steps) for c in batch_cases] == [4, 2]
        assert {s.price_variant for c in batch_cases for s in c.steps} == {"batch"}
        trail = read_jsonl(folder / TRAIL_FILE, AgentCall)
        assert [c.batch_id for c in trail if c.case_id == B] == ["b1", "b2"]

    def test_a_dead_round_counts_in_the_cost_and_the_batch_ids(self, tmp_path: Path) -> None:
        fake = FakeBatchClient(
            handlers=[_ended("expired", cost=0.125), *[_answers(_scripts())] * 8]
        )
        record = _runner(tmp_path / "runs", batch=fake).run(_spec(), RAWS)
        assert record.batch_ids == tuple(f"b{n}" for n in range(1, 10))
        # No case prices a dead batch's replies: the run's cost carries it, as the runner's does.
        assert record.cost_usd == pytest.approx(sum(A_COSTS) + sum(B_COSTS) + 0.125)
        assert record.reported_batch_cost_usd == pytest.approx(0.125 + 2.5)

    def test_a_round_that_reported_no_cost_leaves_the_reported_total_unknown(
        self, tmp_path: Path
    ) -> None:
        fake = FakeBatchClient(handlers=[_ended("expired"), *[_answers(_scripts())] * 8])
        record = _runner(tmp_path / "runs", batch=fake).run(_spec(), RAWS)
        assert record.reported_batch_cost_usd is None
        assert record.cost_usd == pytest.approx(sum(A_COSTS) + sum(B_COSTS))
        # Decision 0135: with no billed total, the monthly guard counts the computed price.
        assert month_spent(tmp_path / "runs", now=record.started) == pytest.approx(record.cost_usd)

    def test_the_monthly_guard_counts_a_batch_run_billed_and_a_sync_run_computed(
        self, tmp_path: Path
    ) -> None:
        """Decision 0135: what the provider billed, when every round reported it."""
        batch, _ = _batch_run(tmp_path / "batch")
        billed = 2 * 0.5 + 6 * 0.25
        assert batch.reported_batch_cost_usd == pytest.approx(billed)
        assert batch.cost_usd == pytest.approx(sum(A_COSTS) + sum(B_COSTS))  # both kept
        assert month_spent(tmp_path / "batch", now=batch.started) == pytest.approx(billed)
        sync, _ = _sync_run(tmp_path / "sync")
        assert month_spent(tmp_path / "sync", now=sync.started) == pytest.approx(
            sum(A_COSTS) + sum(B_COSTS)
        )

    def test_progress_goes_to_stderr_one_line_when_a_round_goes_out_and_one_when_it_ends(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        record, _ = _batch_run(tmp_path / "runs")
        captured = capsys.readouterr()
        assert captured.out == ""
        lines = captured.err.splitlines()
        assert f"run {record.run_id} FRESH sample=dev-400 arm=C cases=2" in lines[0]
        rounds = lines[1:]
        assert len(rounds) == 16
        assert "round 1 sent b1: 2 calls; 2 cases running" in rounds[0]
        assert "round 1 completed b1: cost $0.5000; 2 cases running" in rounds[1]
        assert "round 8 completed b8: cost $0.2500; 0 cases running" in rounds[-1]
        for text in (A, B, ONE.strip(), TWO.strip()):
            assert text not in captured.err  # counts and ids of batches only

    def test_a_failing_progress_line_never_stops_the_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class Broken:
            def write(self, _text: str) -> int:
                raise OSError("closed pipe")

        monkeypatch.setattr("sys.stderr", Broken())
        record, _ = _batch_run(tmp_path / "runs")
        assert record.finished is not None


class TestResume:
    def test_a_resume_after_an_interrupted_round_gives_identical_cases(
        self, tmp_path: Path
    ) -> None:
        _, whole = _batch_run(tmp_path / "whole")
        runs = tmp_path / "cut"
        dead = FakeBatchClient(handlers=[_answers(_scripts()), _die])
        with pytest.raises(_KilledError):
            _runner(runs, batch=dead).run(_spec(), RAWS)
        (folder,) = [p for p in runs.iterdir() if p.is_dir()]
        assert folder.name == whole.name  # the same clock, commit, sample and arm
        aborted = _record(folder)
        assert aborted.finished is None
        assert aborted.cost_usd == pytest.approx(A_COSTS[0] + B_COSTS[0])  # round 1 is paid
        assert [c.failure for c in _cases(folder)] == ["aborted: ", "aborted: "]
        assert open_reservations(runs) == {}

        resumer = _resumer(dead, "b2", [_answers(_scripts())] * 7)
        record = _runner(runs, batch=resumer, clock=Clock(ticks=100)).run(
            _spec(), RAWS, resume=folder.name
        )
        assert record.finished is not None
        assert resumer.waited[0] == "b2"  # the recorded batch, waited on, not submitted again
        assert (folder / "cases.jsonl").read_text() == (whole / "cases.jsonl").read_text()
        assert (folder / "steps.jsonl").read_text() == (whole / "steps.jsonl").read_text()
        trail = read_jsonl(folder / TRAIL_FILE, AgentCall)
        assert _untimed(trail) == _untimed(read_jsonl(whole / TRAIL_FILE, AgentCall))
        assert record.batch_ids == tuple(f"b{n}" for n in range(1, 9))
        assert record.cost_usd == pytest.approx(_record(whole).cost_usd)
        for name in ("cases", "steps", "run", "trail"):
            assert (folder / f"{name}.aborted-1.jsonl").is_file(), name

    def test_a_resume_says_it_waits_on_the_round_sent_before_it_and_does_not_send_it_again(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """S3.1 Task 14: the progress line said "round 2 sent b2" for a batch only waited on."""
        runs = tmp_path / "cut"
        dead = FakeBatchClient(handlers=[_answers(_scripts()), _die])
        with pytest.raises(_KilledError):
            _runner(runs, batch=dead).run(_spec(), RAWS)
        (folder,) = [p for p in runs.iterdir() if p.is_dir()]
        capsys.readouterr()
        resumer = _resumer(dead, "b2", [_answers(_scripts())] * 7)
        _runner(runs, batch=resumer, clock=Clock(ticks=100)).run(_spec(), RAWS, resume=folder.name)
        lines = capsys.readouterr().err.splitlines()
        assert f"run {folder.name} RESUMED" in lines[0]
        assert lines[1].endswith(
            "round 2 waiting on b2 (sent before the resume): 2 calls; 2 cases running"
        )
        assert lines[2].endswith("round 2 completed b2: cost $0.5000; 1 cases running")
        assert lines[3].endswith("round 3 sent b3: 1 calls; 1 cases running")
        assert not any("sent b2" in line for line in lines)

    def test_the_monthly_guard_counts_a_cut_run_computed_and_its_resume_billed(
        self, tmp_path: Path
    ) -> None:
        """Decision 0135. Cut with round 2 sent and not back, the run has no billed total, so the
        guard counts what round 1's replies cost; the resume's record, once every round reported,
        counts what all eight billed, the earlier attempt's rounds included."""
        runs = tmp_path / "cut"
        dead = FakeBatchClient(handlers=[_answers(_scripts()), _die])
        with pytest.raises(_KilledError):
            _runner(runs, batch=dead).run(_spec(), RAWS)
        (folder,) = [p for p in runs.iterdir() if p.is_dir()]
        aborted = _record(folder)
        assert aborted.reported_batch_cost_usd is None
        assert month_spent(runs, now=aborted.started) == pytest.approx(A_COSTS[0] + B_COSTS[0])
        resumer = _resumer(dead, "b2", [_answers(_scripts())] * 7)
        record = _runner(runs, batch=resumer, clock=Clock(ticks=100)).run(
            _spec(), RAWS, resume=folder.name
        )
        assert record.reported_batch_cost_usd == pytest.approx(2 * 0.5 + 6 * 0.25)
        assert month_spent(runs, now=record.started) == pytest.approx(2 * 0.5 + 6 * 0.25)

    def test_a_resume_cut_short_in_its_turn_resumes_again_to_the_same_cases(
        self, tmp_path: Path
    ) -> None:
        _, whole = _batch_run(tmp_path / "whole")
        runs = tmp_path / "cut"
        first = FakeBatchClient(handlers=[_answers(_scripts()), _die])
        with pytest.raises(_KilledError):
            _runner(runs, batch=first).run(_spec(), RAWS)
        (folder,) = [p for p in runs.iterdir() if p.is_dir()]
        second = _resumer(first, "b2", [_answers(_scripts()), _die])
        with pytest.raises(_KilledError):
            _runner(runs, batch=second, clock=Clock(ticks=100)).run(
                _spec(), RAWS, resume=folder.name
            )
        assert _record(folder).cost_usd == pytest.approx(sum(A_COSTS[:2]) + sum(B_COSTS[:2]))
        third = _resumer(second, "b3", [_answers(_scripts())] * 6)
        record = _runner(runs, batch=third, clock=Clock(ticks=200)).run(
            _spec(), RAWS, resume=folder.name
        )
        assert record.finished is not None
        assert (folder / "cases.jsonl").read_text() == (whole / "cases.jsonl").read_text()
        for attempt in (1, 2):
            assert (folder / f"trail.aborted-{attempt}.jsonl").is_file()
            assert (folder / f"run.aborted-{attempt}.jsonl").is_file()

    def test_a_resume_that_dies_before_it_replays_keeps_the_spend_already_recorded(
        self, tmp_path: Path
    ) -> None:
        """The superseded record's cost is a floor: a resume never files less than it replaced."""
        runs = tmp_path / "runs"
        dead = FakeBatchClient(handlers=[_answers(_scripts()), _die])
        with pytest.raises(_KilledError):
            _runner(runs, batch=dead).run(_spec(), RAWS)
        (folder,) = [p for p in runs.iterdir() if p.is_dir()]
        paid = _record(folder).cost_usd
        assert paid > 0

        class Unreachable(Dockets):
            def read(self, mkey: int) -> Docket:
                raise DocketError("the docket cache is unreachable")

        resumer = _resumer(dead, "b2", [])
        with pytest.raises(DocketError):
            _runner(runs, batch=resumer, docket=Unreachable(), clock=Clock(ticks=50)).run(
                _spec(), RAWS, resume=folder.name
            )
        record = _record(folder)
        assert (record.cases, record.finished) == (0, None)
        assert record.cost_usd == pytest.approx(paid)
        assert open_reservations(runs) == {}

    def test_a_resume_with_changed_loop_settings_is_refused(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        dead = FakeBatchClient(handlers=[_die])
        with pytest.raises(_KilledError):
            _runner(runs, batch=dead).run(_spec(), RAWS)
        (folder,) = [p for p in runs.iterdir() if p.is_dir()]
        changes: list[tuple[str, dict[str, object]]] = [
            ("max_rounds", {"max_rounds": 41}),
            ("without", {"without": frozenset({"suggest_codes"})}),
            ("pass_reasoning", {"pass_reasoning": True}),
            ("agent_prompt_version", {"round_number": 2}),
        ]
        for field, change in changes:
            runner = _runner(runs, batch=FakeBatchClient(handlers=[]), **change)  # type: ignore[arg-type]
            with pytest.raises(ConfigurationError, match=f"cannot resume {folder.name}: {field}"):
                runner.run(_spec(), RAWS, resume=folder.name)

    def test_a_resume_after_the_agents_text_changed_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Andy, 2026-10-01: the prompt version fingerprints the text, and spec.json holds it."""
        runs = tmp_path / "runs"
        dead = FakeBatchClient(handlers=[_die])
        with pytest.raises(_KilledError):
            _runner(runs, batch=dead).run(_spec(), RAWS)
        (folder,) = [p for p in runs.iterdir() if p.is_dir()]
        original = texts.source_text
        monkeypatch.setattr(
            texts, "source_text", lambda package, name: f"{original(package, name)}# an edit\n"
        )
        runner = _runner(runs, batch=FakeBatchClient(handlers=[]))
        with pytest.raises(
            ConfigurationError, match=f"cannot resume {folder.name}: agent_prompt_version"
        ):
            runner.run(_spec(), RAWS, resume=folder.name)

    def test_a_finished_run_is_not_resumed(self, tmp_path: Path) -> None:
        record, _ = _batch_run(tmp_path / "runs")
        with pytest.raises(ConfigurationError, match="already finished"):
            _runner(tmp_path / "runs", batch=FakeBatchClient(handlers=[])).run(
                _spec(), RAWS, resume=record.run_id
            )

    def test_two_runs_in_the_same_second_cannot_share_a_folder(self, tmp_path: Path) -> None:
        _batch_run(tmp_path / "runs")
        with pytest.raises(ConfigurationError, match="already exists"):
            _batch_run(tmp_path / "runs")


# --------------------------------------------------------------------------------------------
# Budget, aborts and the cancelled batch
# --------------------------------------------------------------------------------------------


class _WatchingClient(ScriptedClient):
    """Answers as scripted, and looks at the open reservations on every call."""

    def __init__(self, replies: Sequence[ModelReply | None], runs_dir: Path) -> None:
        super().__init__(replies)
        self.runs_dir = runs_dir
        self.seen: list[dict[str, float]] = []

    def complete(
        self,
        payload: Payload,
        settings: ModelSettings,
        *,
        system: str = "",
        history: Sequence[Turn] = (),
    ) -> ModelReply:
        self.seen.append(open_reservations(self.runs_dir))
        return super().complete(payload, settings, system=system, history=history)


class TestBudget:
    def test_the_projection_is_reserved_while_the_run_runs_and_settled_after(
        self, tmp_path: Path
    ) -> None:
        runs = tmp_path / "runs"
        client = _WatchingClient(_sync_replies(_scripts()), runs)
        record = _runner(runs, client=client).run(_sync_spec(), RAWS)
        projected = project_cost(_sync_spec(), 2)
        assert client.seen
        assert all(seen == {record.run_id: pytest.approx(projected)} for seen in client.seen)
        assert open_reservations(runs) == {}

    def test_the_reservation_is_settled_and_the_spend_recorded_when_the_run_dies(
        self, tmp_path: Path
    ) -> None:
        runs = tmp_path / "runs"
        client = ScriptedClient(_sync_replies(_scripts()), die_at=3)
        with pytest.raises(_KilledError):
            _runner(runs, client=client).run(_sync_spec(), RAWS)
        assert open_reservations(runs) == {}
        (folder,) = [p for p in runs.iterdir() if p.is_dir()]
        record = _record(folder)
        assert record.finished is None
        assert record.cost_usd == pytest.approx(A_COSTS[0] + A_COSTS[1])
        a, b = _cases(folder)
        assert a.failure == "aborted: "
        assert a.cost_usd == pytest.approx(A_COSTS[0] + A_COSTS[1])
        assert [s.tool for s in a.steps] == ["checkpoint:h0"]  # what it had recorded is kept
        assert (b.failure, b.cost_usd, b.steps) == ("aborted: ", 0.0, ())

    def test_an_over_budget_run_is_refused_before_any_call(self, tmp_path: Path) -> None:
        client = ScriptedClient([])
        with pytest.raises(BudgetError, match="exceeds"):
            _runner(tmp_path / "runs", client=client, spent=39.99).run(_sync_spec(), RAWS)
        assert client.calls == 0
        assert open_reservations(tmp_path / "runs") == {}

    def test_a_cancelled_batch_stops_the_run_and_says_how_to_resume_it(
        self, tmp_path: Path
    ) -> None:
        runs = tmp_path / "runs"
        fake = FakeBatchClient(handlers=[_answers(_scripts()), _ended("cancelled", cost=0.0625)])
        with pytest.raises(BatchCancelledError) as caught:
            _runner(runs, batch=fake).run(_spec(), RAWS)
        (folder,) = [p for p in runs.iterdir() if p.is_dir()]
        message = str(caught.value)
        assert f"--resume {folder.name}" in message
        assert "batch b2 (round 2) was cancelled" in message
        assert A not in message.replace(folder.name, "")
        assert B not in message
        record = _record(folder)
        assert record.finished is None
        assert record.batch_ids == ("b1", "b2")
        assert record.cost_usd == pytest.approx(A_COSTS[0] + B_COSTS[0] + 0.0625)
        assert open_reservations(runs) == {}


# --------------------------------------------------------------------------------------------
# Leaks, caps and the docket
# --------------------------------------------------------------------------------------------


class TestLeaks:
    def test_a_leak_in_a_chosen_document_fails_that_case_only(self, tmp_path: Path) -> None:
        raw = _withheld(_raw())
        leaky = small_docket({1: ONE, 2: f"[page 1 of 3]\nLetter.\n{CAUSE}\n"})
        docket = Dockets({_mkey(raw): leaky, _mkey(RAWS[1]): small_docket({})})
        a_replies = [
            reply_calling("record_hypothesis", _hyp()),
            reply_calling("choose_documents", _choose({1: False, 2: True})),
        ]
        client = ScriptedClient([*_script(a_replies), *_script(B_REPLIES)])
        record = _runner(tmp_path / "runs", client=client, docket=docket).run(
            _sync_spec(), (raw, RAWS[1])
        )
        folder = tmp_path / "runs" / record.run_id
        a, b = _cases(folder)
        assert a.failure is not None
        assert a.failure.startswith("leak: ")
        assert "probable_cause" in a.failure
        assert CAUSE not in a.failure
        assert (a.steps, a.scores, a.documents_not_read, a.marks) == ((), None, (), ())
        assert a.cost_usd == pytest.approx(A_COSTS[0] + A_COSTS[1])  # its calls were paid for
        assert a.reply_completion_tokens == (100, 101)
        assert (b.failure, b.scores is not None) == (None, True)
        trail = [c for c in read_jsonl(folder / TRAIL_FILE, AgentCall) if c.case_id == A]
        assert trail[-1].tool == "choose_documents"  # the trail keeps the choice
        assert trail[-1].arguments == json.loads(_choose({1: False, 2: True}))

    def test_a_leak_in_the_evidence_fails_the_case_before_any_call(self, tmp_path: Path) -> None:
        raw = _withheld(_raw())
        narratives = raw["narratives"]
        assert isinstance(narratives, list)
        narratives[0]["prelimNarrative"] = f"Report. {CAUSE}"
        client = ScriptedClient(_script(B_REPLIES))
        record = _runner(tmp_path / "runs", client=client).run(_sync_spec(), (raw, RAWS[1]))
        a, b = _cases(tmp_path / "runs" / record.run_id)
        assert a.failure is not None
        assert a.failure.startswith("leak: ")
        assert (a.cost_usd, a.reply_completion_tokens) == (0.0, ())
        assert a.verdict_occurrence == occurrence_codes(raw)
        assert b.failure is None

    def test_a_leak_while_preparing_the_docket_fails_that_case_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = docket_view

        def view(raw: Mapping[str, object], docket: Docket) -> object:
            if raw["ntsbNumber"] == A:
                raise LeakageError(f"{A}: docket_listing holds text from probable_cause")
            return real(raw, docket)

        monkeypatch.setattr(run_module, "docket_view", view)
        client = ScriptedClient(_script(B_REPLIES))
        record = _runner(tmp_path / "runs", client=client).run(_sync_spec(), RAWS)
        a, b = _cases(tmp_path / "runs" / record.run_id)
        assert a.failure == f"leak: {A}: docket_listing holds text from probable_cause"
        assert b.failure is None
        assert client.calls == 2  # B's calls only

        # The same case, in a run that is then cut short: it keeps its leak, B is aborted.
        monkeypatch.setattr(run_module, "docket_view", view)
        dying = ScriptedClient(_script(B_REPLIES), die_at=1)
        with pytest.raises(_KilledError):
            _runner(tmp_path / "cut", client=dying).run(_sync_spec(), RAWS)
        (folder,) = [p for p in (tmp_path / "cut").iterdir() if p.is_dir()]
        a, b = _cases(folder)
        assert (a.failure or "").startswith("leak: ")
        assert b.failure == "aborted: "

    def test_a_leak_found_when_the_marks_are_split_fails_the_case_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every document was guarded when sent; the marks' split is guarded too, and a refusal
        there leaves the case unscored, with what it cost."""

        def leak(*_args: object, **_kwargs: object) -> object:
            raise LeakageError(f"{A}: docket_documents holds text from probable_cause")

        monkeypatch.setattr(run_module, "case_marks", leak)
        _, folder = _sync_run(tmp_path / "runs")
        a, b = _cases(folder)
        assert a.failure == f"leak: {A}: docket_documents holds text from probable_cause"
        assert (a.scores, a.steps) == (None, ())
        assert a.cost_usd == pytest.approx(sum(A_COSTS))
        assert b.failure is not None  # B's split leaks the same way under the patch
        assert _record(folder).cost_usd == pytest.approx(sum(A_COSTS) + sum(B_COSTS))


class TestCapAndDocket:
    def test_a_case_that_cannot_afford_its_first_call_fails_at_the_cap(
        self, tmp_path: Path
    ) -> None:
        client = ScriptedClient([])
        record = _runner(tmp_path / "runs", client=client).run(_sync_spec(cap_usd=1e-7), RAWS)
        a, b = _cases(tmp_path / "runs" / record.run_id)
        assert (a.failure, a.scores, a.steps, a.cost_usd) == ("cap", None, (), 0.0)
        assert a.documents_not_read == ("1: undecided", "2: undecided")
        assert b.failure == "cap"
        assert client.calls == 0

    def test_a_case_stopped_at_the_context_ceiling_is_recorded_with_that_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Decision 152: a call of A after its first is over the ceiling, so it is never sent. The
        case fails ``cap: context`` in ``cases.jsonl``, its last checkpoint says ``cap``, and
        the claims count it wrong; B, under the ceiling, is answered as before."""
        _, reference = _sync_run(tmp_path / "reference")
        price = sources.price_of("openai/gpt-6-luna")  # the sync run's standard price
        tokens = {
            (c.case_id, c.call_index): (c.estimated_usd * 1e6 - 8000 * price.output_usd_per_mtok)
            / price.input_usd_per_mtok
            for c in read_jsonl(reference / TRAIL_FILE, AgentCall)
        }
        # A's first call that is larger than every call before it and both of B's.
        stop = next(
            k
            for k in range(1, 8)
            if tokens[A, k] > max(*(tokens[A, n] for n in range(k)), tokens[B, 0], tokens[B, 1]) + 2
        )
        below = max(*(tokens[A, n] for n in range(stop)), tokens[B, 0], tokens[B, 1])
        monkeypatch.setattr(sources, "PROMPT_TOKEN_CEILING", int((below + tokens[A, stop]) / 2))
        scripts = _scripts()
        client = ScriptedClient([*scripts[A][:stop], *scripts[B]])
        record = _runner(tmp_path / "runs", client=client).run(_sync_spec(), RAWS)
        a, b = _cases(tmp_path / "runs" / record.run_id)
        assert client.calls == stop + 2
        assert (a.failure, a.scores) == (CONTEXT_FAILURE, None)
        assert a.steps[0].tool == "checkpoint:h0"
        assert a.steps[-1].stop_reason == "cap"
        assert b.failure is None
        assert claims.per_case([a, b], "top1")[A] == 0.0
        assert not claims.is_guard_refusal(a)

    def test_a_refinement_the_case_cannot_afford_leaves_it_unscored_like_arm_b(
        self, tmp_path: Path
    ) -> None:
        """Arm B never scores a case whose stage 2 could not run, so arm C does not either."""
        costly = Usage(prompt_tokens=0, completion_tokens=0, reported_cost_usd=0.9995)
        a_replies = [
            reply_calling("record_hypothesis", _hyp()),
            reply_calling("submit_answer", _hyp(), usage=costly),
        ]
        docket = Dockets({_mkey(RAWS[0]): small_docket({}), _mkey(RAWS[1]): small_docket({})})
        client = ScriptedClient([*a_replies, *_script(B_REPLIES)])
        record = _runner(tmp_path / "runs", client=client, docket=docket).run(_sync_spec(), RAWS)
        a, _ = _cases(tmp_path / "runs" / record.run_id)
        assert (a.failure, a.scores) == ("cap", None)
        assert [s.tool for s in a.steps] == ["checkpoint:h0", "checkpoint:answer"]
        assert [s.stop_reason for s in a.steps] == ["", "cap"]
        assert a.cost_usd == pytest.approx(0.9995)

    def test_excluding_a_docket_role_reads_no_docket(self, tmp_path: Path) -> None:
        docket = Dockets()
        client = ScriptedClient([*_script(B_REPLIES), *_script(B_REPLIES)])
        exclusions = frozenset({EvidenceRole.DOCKET_DOCUMENTS})
        record = _runner(tmp_path / "runs", client=client, docket=docket).run(
            _sync_spec(exclusions=exclusions), RAWS
        )
        assert docket.reads == []
        assert record.exclusions == ("docket_documents",)
        a, b = _cases(tmp_path / "runs" / record.run_id)
        assert (a.failure, b.failure) == (None, None)
        assert a.documents_not_read == ()

    def test_a_docket_whose_key_is_not_the_records_is_refused(self, tmp_path: Path) -> None:
        """The loop does not check that a docket and its record are one case; the runner does,
        by the docket's own key. A reader that answers for another key fails it."""
        docket = Dockets()
        other = _mkey(RAWS[1])
        docket.by_mkey[_mkey(RAWS[0])] = keyed(small_docket({1: ONE, 2: TWO}), other)
        client = ScriptedClient([])
        match = f"the docket read for {A} is docket {other}, not its own {_mkey(RAWS[0])}"
        with pytest.raises(ConfigurationError, match=match) as caught:
            _runner(tmp_path / "runs", client=client, docket=docket).run(_sync_spec(), RAWS)
        assert ONE.strip() not in str(caught.value)
        assert client.calls == 0
        assert open_reservations(tmp_path / "runs") == {}

    def test_every_case_is_given_a_docket_with_its_own_key(self, tmp_path: Path) -> None:
        """The stub keys each docket as a real reader would, so the guard passes a real run."""
        docket = Dockets()
        assert {key: d.mkey for key, d in docket.by_mkey.items()} == {
            _mkey(RAWS[0]): _mkey(RAWS[0]),
            _mkey(RAWS[1]): _mkey(RAWS[1]),
        }
        assert small_docket({}).mkey == 1  # the shared builder's key, which the stub replaces
        record, _ = _sync_run(tmp_path / "runs")
        assert record.finished is not None

    def test_a_record_with_no_mkey_is_refused(self, tmp_path: Path) -> None:
        raw = copy.deepcopy(_raw())
        del raw["mKey"]
        with pytest.raises(ConfigurationError, match=f"{A}: no mKey"):
            _runner(tmp_path / "runs").run(_sync_spec(), (raw,))


# --------------------------------------------------------------------------------------------
# The settings a run passes to its loops
# --------------------------------------------------------------------------------------------


class TestSettings:
    def test_pass_reasoning_and_the_ablation_reach_every_request(self, tmp_path: Path) -> None:
        fake = FakeBatchClient(handlers=[_answers(_scripts())])
        runner = _runner(
            tmp_path / "runs",
            batch=fake,
            pass_reasoning=True,
            without=frozenset({"coding"}),
            max_rounds=1,
        )
        record = runner.run(_spec(), RAWS)
        requests: list[BatchRequest] = fake.submitted[0]
        assert all(r.settings.pass_reasoning for r in requests)
        names = {t["function"]["name"] for r in requests for t in r.settings.tools}  # type: ignore[index]
        assert not names & CODING_TOOLS
        recorded = _spec_file(tmp_path / "runs" / record.run_id)
        assert (recorded["without"], recorded["pass_reasoning"]) == (["coding"], True)
        assert recorded["max_rounds"] == 1
        assert {c.failure for c in _cases(tmp_path / "runs" / record.run_id)} == {"failed: rounds"}

    def test_pass_reasoning_defaults_to_the_one_setting(self) -> None:
        """``loop.PASS_REASONING`` is the default of the loop's settings and of the runner.

        The command and the post-pass pass it explicitly (``tests/test_eval_app.py`` and
        ``tests/test_agent_armb.py`` each flip it and see it reach the calls).
        """
        assert agent_loop.PASS_REASONING is False  # until the shape probe's check 4 says
        default = LoopConfig.__dataclass_fields__["pass_reasoning"].default
        assert default is agent_loop.PASS_REASONING
        parameter = inspect.signature(AgentRunner).parameters["pass_reasoning"]
        assert parameter.default is agent_loop.PASS_REASONING

    def test_a_round_may_change_the_guidance_and_is_recorded(self, tmp_path: Path) -> None:
        client = ScriptedClient(_sync_replies(_scripts()))
        record = _runner(tmp_path / "runs", client=client, round_number=3).run(
            _sync_spec(guidance=("r3-loc-stall",)), RAWS
        )
        assert record.prompt_version == texts.prompt_version(("r3-loc-stall",), 3)
        assert record.prompt_version.endswith("+r3")
        recorded = _spec_file(tmp_path / "runs" / record.run_id)
        assert recorded["round"] == 3
        assert recorded["agent_prompt_version"] == record.prompt_version

    def test_a_held_out_run_from_a_clean_tree_appends_the_ledger(self, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.md"
        client = ScriptedClient(_sync_replies(_scripts()))
        record = _runner(tmp_path / "runs", client=client, ledger_path=ledger).run(
            _sync_spec(sample="heldout-400"), RAWS
        )
        assert "| heldout-400 | C | v1 |" in ledger.read_text()
        assert record.run_id in ledger.read_text()


# --------------------------------------------------------------------------------------------
# Refusals: each before any folder, reservation or call
# --------------------------------------------------------------------------------------------


def _refused(tmp_path: Path, spec: RunSpec, match: str, **runner: object) -> None:
    client = ScriptedClient([])
    with pytest.raises(ConfigurationError, match=match):
        _runner(tmp_path / "runs", client=client, **runner).run(  # type: ignore[arg-type]
            spec, RAWS, resume=None
        )
    assert client.calls == 0
    assert not (tmp_path / "runs").exists()


class TestRefusals:
    @pytest.mark.parametrize("arm", ["A", "B", "ceiling"])
    def test_another_arm_is_refused(self, tmp_path: Path, arm: str) -> None:
        _refused(tmp_path, _sync_spec(arm=arm), "arm C only")

    @pytest.mark.parametrize("version", ["v2", "v3"])
    def test_a_version_past_v1_is_refused(self, tmp_path: Path, version: str) -> None:
        _refused(tmp_path, _sync_spec(evidence_version=version), "v1 only")

    @pytest.mark.parametrize("guidance", [(), ("r3-loc-stall",), tuple(reversed(GUIDANCE))])
    def test_changed_guidance_without_a_round_is_refused(
        self, tmp_path: Path, guidance: tuple[str, ...]
    ) -> None:
        _refused(tmp_path, _sync_spec(guidance=guidance), "guidance")

    def test_the_case_number_probe_is_refused(self, tmp_path: Path) -> None:
        _refused(tmp_path, _sync_spec(include_case_number=True), "case number")

    def test_a_v1_run_naming_a_transcriber_is_refused(self, tmp_path: Path) -> None:
        _refused(tmp_path, _sync_spec(transcriber="qwen"), "transcriber")

    def test_sync_at_the_batch_price_is_refused(self, tmp_path: Path) -> None:
        _refused(tmp_path, _spec(sync=True), "--sync cannot use --price-variant batch")

    def test_a_held_out_run_from_a_dirty_tree_is_refused(self, tmp_path: Path) -> None:
        _refused(tmp_path, _sync_spec(sample="heldout-400"), "uncommitted", dirty=True)

    def test_a_held_out_run_with_no_ledger_is_refused(self, tmp_path: Path) -> None:
        _refused(tmp_path, _sync_spec(sample="heldout-400"), "ledger")

    def test_a_v2_docket_reader_is_refused(self, tmp_path: Path) -> None:
        _refused(tmp_path, _sync_spec(), "v1 docket reader", docket=Dockets(version="v2"))

    def test_a_batch_run_with_no_batch_client_is_refused(self, tmp_path: Path) -> None:
        _refused(tmp_path, _spec(), "batch client")

    @pytest.mark.parametrize("sync", [True, False])
    def test_the_sample_s27_used_once_is_refused_before_any_docket_is_read(
        self, tmp_path: Path, sync: bool
    ) -> None:
        """dev-seal-400 was used once (decision 0095). Its registration is committed and S3's
        pool leaves it out, so neither ``refuse_sealed`` nor ``refuse_pool_holding`` stops it:
        the runner does, before any docket read, folder, reservation or call."""
        docket = Dockets()
        spec = _sync_spec(sample="dev-seal-400") if sync else _spec(sample="dev-seal-400")
        batch = None if sync else FakeBatchClient(handlers=[])
        _refused(tmp_path, spec, "dev-seal-400.*decision 0095", docket=docket, batch=batch)
        assert docket.reads == []
        if batch is not None:
            assert batch.submitted == []

    def test_a_sync_resume_is_refused(self, tmp_path: Path) -> None:
        client = ScriptedClient([])
        with pytest.raises(ConfigurationError, match="--resume cannot be used with --sync"):
            _runner(tmp_path / "runs", client=client).run(_sync_spec(), RAWS, resume="x")

    def test_no_docket_reader_is_refused_unless_the_docket_is_excluded(
        self, tmp_path: Path
    ) -> None:
        runner = AgentRunner(
            ScriptedClient([]),
            batch=None,
            tables=TABLES,
            stats=STATS,
            seen_pairs=frozenset(),
            runs_dir=tmp_path / "runs",
            month_spent_usd=0.0,
            commit=("abc1234", False),
            docket=None,
            now=Clock(),
        )
        with pytest.raises(ConfigurationError, match="docket reader"):
            runner.run(_sync_spec(), RAWS)
        assert not (tmp_path / "runs").exists()

    def test_the_one_shot_runner_refuses_arm_c(self, tmp_path: Path) -> None:
        runner = Runner(
            ScriptedClient([]),
            batch=None,
            tables=TABLES,
            seen_pairs=frozenset(),
            runs_dir=tmp_path / "runs",
            ledger_path=tmp_path / "ledger.md",
            month_spent_usd=0.0,
            commit=("abc1234", False),
        )
        with pytest.raises(ConfigurationError, match="AgentRunner"):
            runner.run(_sync_spec(), RAWS)
