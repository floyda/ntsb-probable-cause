"""Tests for the live morning (S3.3 Task 8): ``live/morning.py``.

Every dependency is a fake: the clock, the store, the spend counter, the sink, the three client
factories, the commit and the lockfile checksum. The runner is a stub that writes the files an
``AgentRunner`` run folder holds, except in one test (n) that runs the real ``AgentRunner`` on a
scripted batch client. No test reaches the network, OpenRouter, the NTSB API or AWS.
"""

import dataclasses
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import pytest
from tests.test_agent_drive import _answers, _scripts
from tests.test_agent_loop import STATS, TABLES
from tests.test_agent_run import RAWS, Dockets, _mkey
from tests.test_runner import FakeBatchClient

from ntsb_probable_cause.agent import loop as agent_loop
from ntsb_probable_cause.agent import run as agent_run
from ntsb_probable_cause.agent.run import GUIDANCE, AgentRunner
from ntsb_probable_cause.agent.schemas import ChooseDocuments, DocumentDecision
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.agent.version import VERSION_1
from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord
from ntsb_probable_cause.errors import BudgetError, ConfigurationError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.live import morning
from ntsb_probable_cause.live.fetch import FetchError
from ntsb_probable_cause.live.local import LocalFolderSink
from ntsb_probable_cause.live.morning import (
    EXPECTED_COST_PER_CASE_USD,
    LATE_START_UTC,
    LIVE_CAP_USD,
    MONTHLY_CAP_USD,
    VERSION_1_SETTINGS,
    MorningDeps,
    current_settings,
    run_morning,
    settings_differences,
)
from ntsb_probable_cause.live.queue import DAILY_LIMIT, backfill_digest
from ntsb_probable_cause.live.records import (
    BACKFILL_FILE,
    CLOSURES_FILE,
    INPUTS_FILE,
    Backfill,
    ClosureRecord,
    portability_problems,
    verify_manifest,
)
from ntsb_probable_cause.model.client import ModelClient
from ntsb_probable_cause.scoring.metrics import CaseScores
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, write_jsonl
from ntsb_probable_cause.scoring.runner import RunSpec
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.store import Closure

NOW = datetime(2026, 10, 7, 6, 0, tzinfo=UTC)
TODAY = NOW.date()
PENDING = "live-pending-inputs.jsonl"


def _scores(top1: bool = True) -> CaseScores:
    return CaseScores(
        occurrence_top1=top1,
        occurrence_top3=True,
        event_match=True,
        pair_unseen=False,
        finding_precision_10=None,
        finding_recall_10=None,
        finding_precision_8=None,
        finding_recall_8=None,
        finding_precision_6=None,
        finding_recall_6=None,
        finding_precision_all_10=None,
        finding_recall_all_10=None,
        abstained=False,
        confidence=0.5,
    )


def _result(case_id: str, **changes: Any) -> CaseResult:
    base = CaseResult(
        case_id=case_id,
        split="dev",
        fatal=False,
        investigation_class="LA",
        report_flavour=None,
        verdict_occurrence=("100",),
        verdict_findings=(),
        verdict_findings_in_cause=(),
        steps=(),
        scores=_scores(),
        cost_usd=0.01,
        failure=None,
    )
    return base.model_copy(update=changes)


def _call(case_id: str, step: str, n: int, **changes: Any) -> AgentCall:
    base = AgentCall(
        run_id="r",
        case_id=case_id,
        trigger=1,
        docket_state="some",
        call_index=n,
        step=step,
        retry=False,
        tool=None,
        arguments={},
        protocol_error=None,
        result_chars=0,
        argument_errors=0,
        hypothesis=None,
        prompt_tokens=1,
        cached_tokens=None,
        completion_tokens=1,
        reasoning_tokens=None,
        finish_reason="stop",
        cost_usd=0.001,
        estimated_usd=0.001,
        sent_at=NOW + timedelta(minutes=n),
        returned_at=NOW + timedelta(minutes=n, seconds=30),
        batch_id=None,
        commit_sha="abc1234",
        dirty=False,
    )
    return base.model_copy(update=changes)


def _entry(index: int, title: str) -> ListingEntry:
    return ListingEntry(
        index=index,
        title=title,
        pages=2,
        photos=0,
        doc_type="Report",
        extension="pdf",
        href=f"/d/{index}",
    )


def _docket(mkey: int, statuses: Mapping[int, str]) -> Docket:
    records = tuple(
        DocumentRecord(
            entry=_entry(i, f"Doc {i}"),
            category="other",
            status=status,
            pages=2,
            readable_pages=2,
            estimated_tokens=10,
            kind="born-digital",
        )
        for i, status in statuses.items()
    )
    entries = tuple(r.entry for r in records)
    listing = Listing(mkey=mkey, declared_items=len(records), entries=entries)
    return Docket(mkey=mkey, listing=listing, documents=records, texts={})


def _closure(n: int, *, run: int | None = None, closed_on: str = "2026-10-05") -> Closure:
    return Closure(
        mkey=1000 + n,
        ntsb_number=f"ERA26LA{n:03d}",
        event_date="2026-09-01",
        closure_run=run if run is not None else n,
        closed_on=closed_on,
        closed_as="Completed",
    )


class _Source:
    def __init__(self, events: list[str], store: Any) -> None:
        self.events = events
        self.store = store

    def open(self) -> Any:
        self.events.append("open")
        return self.store

    def discard(self) -> None:
        self.events.append("discard")
        self.store.path.unlink(missing_ok=True)


class _Store:
    def __init__(self, path: Path, closures: Sequence[Closure], *, finished: bool = True) -> None:
        self.path = path
        self._closures = list(closures)
        self._finished = finished
        self.known: dict[int, int] = {}

    def closures(self) -> list[Closure]:
        return list(self._closures)

    def run_finished_on(self, day: date) -> bool:
        return self._finished

    def documents_recorded(self, mkey: int) -> int:
        return self.known.get(mkey, 0)


class _Spend:
    def __init__(self, usd: float = 0.0) -> None:
        self.usd = usd

    def live_month_usd(self, now: datetime) -> float:
        return self.usd


class _Sink:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.fail_write = False
        self.done: frozenset[str] = frozenset()
        self.coded = 0
        self.unfinished: str | None = None
        self.held: Backfill | None = None
        self.writes: list[tuple[str, list[ClosureRecord], Backfill | None]] = []

    def done_case_ids(self) -> frozenset[str]:
        return self.done

    def coded_on(self, day: date) -> int:
        return self.coded

    def unfinished_run(self) -> str | None:
        return self.unfinished

    def backfill(self) -> Backfill | None:
        return self.held

    def write(
        self, run_id: str, records: Sequence[ClosureRecord], backfill: Backfill | None
    ) -> None:
        if self.fail_write:
            self.fail_write = False
            raise RuntimeError("sink down")
        self.events.append("write")
        self.writes.append((run_id, list(records), backfill))


class _Client:
    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, _k: type[BaseException] | None, _v: BaseException | None, _t: TracebackType | None
    ) -> None:
        return None

    def close(self) -> None:
        return None


class _StubRunner:
    """Writes the files a run folder holds, from a script; records how it was built and run."""

    instances: list[_StubRunner] = []  # noqa: RUF012 -- a test double's log
    script: dict[str, Any] = {}  # noqa: RUF012
    raises: Exception | None = None
    side_folder: str | None = None

    def __init__(self, client: ModelClient, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.runs: list[tuple[RunSpec, list[Mapping[str, object]], str | None]] = []
        _StubRunner.instances.append(self)

    def run(
        self, spec: RunSpec, raws: Sequence[Mapping[str, object]], *, resume: str | None = None
    ) -> RunRecord:
        self.runs.append((spec, list(raws), resume))
        started = self.kwargs["now"]()
        run_id = resume or f"{started:%Y%m%dT%H%M%S}-abc1234-live-C"
        runs_dir: Path = self.kwargs["runs_dir"]
        folder = runs_dir / run_id
        folder.mkdir(parents=True, exist_ok=resume is not None)
        ids = [str(r["ntsbNumber"]) for r in raws]
        aborted = {"failure": f"aborted: {self.raises}", "scores": None} if self.raises else {}
        results = [
            _result(i, **{**aborted, **self.script.get(i, {}).get("result", {})}) for i in ids
        ]
        calls = [c for i in ids for c in self.script.get(i, {}).get("calls", [])]
        write_jsonl(folder / "cases.jsonl", results)
        write_jsonl(folder / "trail.jsonl", calls)
        failed = self.raises is not None
        record = RunRecord(
            run_id=run_id,
            sample=spec.sample,
            arm="C",
            exclusions=("prelim_narrative",),
            includes=(),
            prompt_version=VERSION_1,
            model=spec.model,
            reasoning_effort=spec.reasoning_effort,
            price_variant=spec.price_variant,
            cap_usd=spec.cap_usd,
            budget_usd=spec.budget_usd,
            commit_sha="abc1234",
            dirty=False,
            started=started,
            finished=None if failed else started + timedelta(minutes=30),
            cases=len(ids),
            cost_usd=sum(r.cost_usd for r in results),
            reported_batch_cost_usd=0.5,
        )
        write_jsonl(folder / "run.jsonl", [record])
        (folder / "spec.json").write_text(json.dumps({"sample": spec.sample}))
        if self.side_folder is not None:
            side = runs_dir / self.side_folder
            side.mkdir()
            (side / "spec.json").write_text(json.dumps({"sample": "dev-400"}))
        if self.raises is not None:
            raise self.raises
        return record


@dataclass
class Rig:
    tmp: Path
    events: list[str] = field(default_factory=list)
    store: _Store = field(init=False)
    source: _Source = field(init=False)
    sink: _Sink = field(init=False)
    spend: _Spend = field(default_factory=_Spend)
    settings: Settings = field(init=False)
    label: str = VERSION_1
    fetched: list[str] = field(default_factory=list)
    dockets: list[tuple[int, int]] = field(default_factory=list)
    model_calls: int = 0
    fetch_fails: set[str] = field(default_factory=set)
    docket_statuses: dict[int, str] = field(default_factory=lambda: {1: "read", 2: "read"})
    now: datetime = NOW

    def deps(self, **changes: Any) -> MorningDeps:
        def models() -> tuple[ModelClient, None]:
            self.model_calls += 1
            return (None, None)  # type: ignore[return-value]

        base = MorningDeps(
            settings=self.settings,
            now=lambda: self.now,
            store=self.source,
            spend=self.spend,
            sink=self.sink,
            ntsb=_Client,  # type: ignore[arg-type]
            docket=_Client,  # type: ignore[arg-type]
            models=models,
            commit=lambda: ("abc1234", False),
            uv_lock_sha256=lambda: "f" * 64,
            label=lambda: self.label,
        )
        return dataclasses.replace(base, **changes)

    @property
    def runs_dir(self) -> Path:
        return self.settings.runs_dir

    def refusals(self) -> list[dict[str, str]]:
        path = self.runs_dir / "live-refusals.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]


def _raw(case_id: str, mkey: int) -> dict[str, object]:
    return {"ntsbNumber": case_id, "mKey": mkey}


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    r = Rig(tmp_path)
    r.settings = Settings(data_dir=tmp_path / "data")
    r.runs_dir.mkdir(parents=True)
    work = tmp_path / "work.sqlite"
    work.write_bytes(b"x" * 1000)
    r.store = _Store(work, [_closure(n) for n in range(1, 4)])
    r.source = _Source(r.events, r.store)
    r.sink = _Sink(r.events)
    _StubRunner.instances = []
    _StubRunner.script = {}
    _StubRunner.raises = None
    _StubRunner.side_folder = None

    def fetch_record(client: object, case: Any) -> dict[str, object]:
        r.events.append(f"fetch {case.case_id}")
        r.fetched.append(case.case_id)
        if case.case_id in r.fetch_fails:
            raise FetchError("down")
        return _raw(case.case_id, case.mkey)

    def prefetch_docket(client: object, mkey: int, *, known_documents: int) -> Docket:
        r.dockets.append((mkey, known_documents))
        return _docket(mkey, r.docket_statuses)

    monkeypatch.setattr(morning, "fetch_record", fetch_record)
    monkeypatch.setattr(morning, "prefetch_docket", prefetch_docket)
    monkeypatch.setattr(morning, "AgentRunner", _StubRunner)
    monkeypatch.setattr(morning, "CachedDocketReader", lambda client, readings: object())
    monkeypatch.setattr(morning, "load_tables", lambda: TABLES)
    monkeypatch.setattr(morning, "load_stats", lambda name: STATS)
    monkeypatch.setattr(morning, "seen_pairs", lambda processed: frozenset())
    return r


def test_constants() -> None:
    assert (LIVE_CAP_USD, MONTHLY_CAP_USD, EXPECTED_COST_PER_CASE_USD) == (0.30, 5.0, 0.015)
    assert LATE_START_UTC.hour == 9


def test_a_wrong_label_is_refused_before_the_store_is_opened(rig: Rig) -> None:
    rig.label = "s3-v1+gOTHER"
    with pytest.raises(ConfigurationError) as caught:
        run_morning(rig.deps())
    assert VERSION_1 in str(caught.value)
    assert "s3-v1+gOTHER" in str(caught.value)
    assert "open" not in rig.events


def test_b_no_finished_recorder_run_today_is_refused_and_nothing_is_fetched(rig: Rig) -> None:
    rig.store._finished = False
    with pytest.raises(ConfigurationError, match="recorder"):
        run_morning(rig.deps())
    assert rig.fetched == []
    assert rig.model_calls == 0
    assert "discard" in rig.events


def test_c_an_unfinished_run_is_resumed_with_its_inputs_and_no_new_run_starts(rig: Rig) -> None:
    run_id = "20261007T050000-abc1234-live-C"
    folder = rig.runs_dir / run_id
    folder.mkdir(exist_ok=True)
    raws = [_raw("ERA26LA002", 1002), _raw("ERA26LA001", 1001)]
    (folder / INPUTS_FILE).write_text("".join(json.dumps(r) + "\n" for r in raws))
    rig.sink.unfinished = run_id
    rig.sink.held = Backfill(
        fixed_on=date(2026, 10, 1), case_ids=("X",), sha256=backfill_digest(["X"])
    )
    summary = run_morning(rig.deps())
    (runner,) = _StubRunner.instances
    assert len(runner.runs) == 1
    _spec, got, resume = runner.runs[0]
    assert got == raws
    assert resume == run_id
    assert rig.fetched == []
    assert summary.run_id == run_id
    assert [w[0] for w in rig.sink.writes] == [run_id]


def test_c_a_pending_inputs_file_is_moved_into_the_unfinished_run_first(rig: Rig) -> None:
    run_id = "20261007T050000-abc1234-live-C"
    (rig.runs_dir / run_id).mkdir()
    raws = [_raw("ERA26LA001", 1001)]
    (rig.runs_dir / PENDING).write_text(json.dumps(raws[0]) + "\n")
    rig.sink.unfinished = run_id
    rig.sink.held = Backfill(
        fixed_on=date(2026, 10, 1), case_ids=("X",), sha256=backfill_digest(["X"])
    )
    run_morning(rig.deps())
    assert not (rig.runs_dir / PENDING).exists()
    assert _StubRunner.instances[0].runs[0][1] == raws


def test_c_an_unfinished_run_with_no_inputs_is_refused(rig: Rig) -> None:
    (rig.runs_dir / "20261007T050000-abc1234-live-C").mkdir()
    rig.sink.unfinished = "20261007T050000-abc1234-live-C"
    with pytest.raises(ConfigurationError, match="inputs"):
        run_morning(rig.deps())


def test_d_the_daily_limit_takes_nothing(rig: Rig) -> None:
    rig.sink.coded = DAILY_LIMIT
    summary = run_morning(rig.deps())
    assert summary.coded == 0
    assert any("limit" in w for w in summary.warnings)
    assert rig.fetched == []
    assert _StubRunner.instances == []
    assert [r["reason"] for r in rig.refusals()] == ["daily-limit"]


def test_e_the_monthly_cap_refuses_before_any_fetch(rig: Rig) -> None:
    rig.spend.usd = 4.95
    with pytest.raises(BudgetError):
        run_morning(rig.deps())
    assert rig.fetched == []
    assert rig.model_calls == 0
    assert [r["reason"] for r in rig.refusals()] == ["monthly-cap"]


def test_e_a_smaller_take_fits_under_the_cap(rig: Rig) -> None:
    rig.spend.usd = 4.95
    summary = run_morning(rig.deps(), limit=1)
    assert summary.coded == 1


def test_f_a_fetch_failure_leaves_the_case_out_and_counts_it_returned(rig: Rig) -> None:
    rig.fetch_fails = {"ERA26LA001"}
    summary = run_morning(rig.deps())
    assert summary.returned == 1
    assert summary.coded == 2
    (runner,) = _StubRunner.instances
    assert [str(r["ntsbNumber"]) for r in runner.runs[0][1]] == ["ERA26LA002", "ERA26LA003"]
    assert summary.queued == 1


def test_f_the_stores_document_count_reaches_the_docket_fetch(rig: Rig) -> None:
    rig.store.known[1002] = 4
    run_morning(rig.deps())
    assert (1002, 4) in rig.dockets
    assert (1001, 0) in rig.dockets


def test_g_the_run_spec(rig: Rig) -> None:
    run_morning(rig.deps())
    (runner,) = _StubRunner.instances
    spec = runner.runs[0][0]
    assert spec.sample == "live"
    assert spec.arm == "C"
    assert spec.cap_usd == 0.30
    assert spec.exclusions == frozenset({EvidenceRole.PRELIM_NARRATIVE})
    assert spec.guidance == GUIDANCE
    assert spec.price_variant == "batch"
    assert spec.sync is False
    assert spec.evidence_version == "v1"
    assert spec.model == "openai/gpt-6-luna"
    assert spec.reasoning_effort == "medium"
    assert spec.max_output_tokens == 8000
    assert spec.expected_cost_per_case_usd == EXPECTED_COST_PER_CASE_USD
    assert runner.runs[0][2] is None
    assert runner.kwargs["commit"] == ("abc1234", False)
    assert runner.kwargs["runs_dir"] == rig.runs_dir


def test_h_a_closure_record_per_case(rig: Rig) -> None:
    choice = ChooseDocuments(
        decisions=(
            DocumentDecision(document=1, read=True, expected_effect="x"),
            DocumentDecision(document=2, read=False, expected_effect="y"),
        ),
        reason="r",
    )
    _StubRunner.script = {
        "ERA26LA001": {
            "calls": [
                _call("ERA26LA001", "h0", 0),
                _call(
                    "ERA26LA001",
                    "choice1",
                    1,
                    tool="choose_documents",
                    arguments=choice.model_dump(),
                    offered=(1, 2),
                ),
                _call("ERA26LA001", "answer", 2),
            ]
        },
        "ERA26LA002": {"result": {"verdict_occurrence": (), "scores": None}},
        "ERA26LA003": {"result": {"failure": "cap", "scores": None, "cost_usd": 0.31}},
    }
    rig.docket_statuses = {1: "read", 2: "read", 3: "unreadable: scan"}
    summary = run_morning(rig.deps())
    ((run_id, records, _bf),) = rig.sink.writes
    assert run_id == summary.run_id
    first, second, third = records
    assert first.case_id == "ERA26LA001"
    assert [(d.position, d.status, d.ellery) for d in first.documents] == [
        (1, "read", "read"),
        (2, "read", "skipped"),
        (3, "unreadable: scan", None),
    ]
    assert first.scored is True
    assert first.top1 is True
    assert first.top3 is True
    assert first.abstained is False
    assert first.outcome == "coded"
    assert first.first_sent == NOW
    assert first.last_returned == NOW + timedelta(minutes=2, seconds=30)
    assert (first.commit_sha, first.dirty, first.prompt_version) == ("abc1234", False, VERSION_1)
    assert first.uv_lock_sha256 == "f" * 64
    assert first.training_cutoff == date(2026, 5, 18)
    assert first.waited_days == 2
    assert first.closed_on == date(2026, 10, 5)
    assert first.prelim_present is False
    assert second.scored is False
    assert (second.top1, second.top3, second.abstained) == (None, None, None)
    assert second.outcome == "coded"
    assert second.first_sent is None
    assert second.last_returned is None
    assert third.outcome == "not coded"
    assert third.failure == "cap"
    assert summary.not_coded == {"cap": 1}
    assert summary.coded == 2
    assert summary.cost_usd == pytest.approx(0.01 + 0.01 + 0.31)
    assert summary.billed_usd == 0.5


def test_i_the_first_morning_writes_the_whole_queue_as_the_backfill(rig: Rig) -> None:
    summary = run_morning(rig.deps(), limit=1)
    ((_id, _records, backfill),) = rig.sink.writes
    assert backfill is not None
    ids = ("ERA26LA001", "ERA26LA002", "ERA26LA003")
    assert backfill.case_ids == ids
    assert backfill.fixed_on == TODAY
    assert backfill.sha256 == backfill_digest(ids)
    assert summary.queued == 2


def test_i_later_mornings_never_rewrite_it(rig: Rig) -> None:
    rig.sink.held = Backfill(
        fixed_on=date(2026, 10, 1), case_ids=("X",), sha256=backfill_digest(["X"])
    )
    run_morning(rig.deps())
    assert rig.sink.writes[0][2] is None


def _cache(mkey: int, root: Path) -> None:
    (root / str(mkey)).mkdir(parents=True)
    (root / str(mkey) / "listing.html").write_bytes(b"y" * 100)


def test_j_a_finished_run_frees_its_cases_cache_and_the_store_copy(rig: Rig) -> None:
    live, dev = rig.settings.live_docket_dir, rig.settings.docket_dir
    for mkey in (1001, 1002, 1003, 1999):
        _cache(mkey, live)
    _cache(1001, dev)
    summary = run_morning(rig.deps(), limit=2)
    assert not (live / "1001").exists()
    assert not (live / "1002").exists()
    assert (live / "1003").exists()
    assert (live / "1999").exists()
    assert (dev / "1001" / "listing.html").exists()
    assert not rig.store.path.exists()
    assert summary.freed_bytes == 100 + 100 + 1000


def test_j_an_interrupted_run_keeps_them(rig: Rig) -> None:
    live = rig.settings.live_docket_dir
    _cache(1001, live)
    _StubRunner.raises = RuntimeError("killed")
    with pytest.raises(RuntimeError, match="killed"):
        run_morning(rig.deps(), limit=1)
    assert (live / "1001").exists()
    assert rig.store.path.exists()
    assert "discard" not in rig.events
    # the inputs file moved into the run's folder, where a resume reads it
    assert not (rig.runs_dir / PENDING).exists()
    (folder,) = [p for p in rig.runs_dir.iterdir() if p.is_dir()]
    first = (folder / INPUTS_FILE).read_text().splitlines()[0]
    assert json.loads(first)["ntsbNumber"] == "ERA26LA001"


def test_k_a_dry_run_fetches_one_case_and_calls_no_model(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    summary = run_morning(rig.deps(), dry_run=True)
    assert rig.fetched == ["ERA26LA001"]
    assert len(rig.dockets) == 1
    assert rig.model_calls == 0
    assert _StubRunner.instances == []
    assert rig.sink.writes == []
    assert not (rig.runs_dir / PENDING).exists()
    assert list(rig.runs_dir.iterdir()) == []
    assert summary.run_id is None
    assert summary.coded == 0
    out = capsys.readouterr().out
    assert "dry run" in out
    assert "3" in out
    assert "ERA26LA001" not in out


def test_l_a_late_start_warns(rig: Rig) -> None:
    rig.now = datetime(2026, 10, 7, 9, 30, tzinfo=UTC)
    summary = run_morning(rig.deps())
    assert any("09:00" in w for w in summary.warnings)


def test_l_a_late_start_is_said_on_stderr_at_the_start_too(
    rig: Rig, capsys: pytest.CaptureFixture[str]
) -> None:
    rig.now = datetime(2026, 10, 7, 9, 30, tzinfo=UTC)
    rig.store._finished = False  # the morning refuses, so only the start can have said it
    with pytest.raises(ConfigurationError):
        run_morning(rig.deps())
    assert "warning: started after 09:00 UTC" in capsys.readouterr().err


def test_l_an_early_start_does_not(rig: Rig, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_morning(rig.deps()).warnings == ()
    assert "started after" not in capsys.readouterr().err


def test_m_limit_one_takes_one_case(rig: Rig) -> None:
    summary = run_morning(rig.deps(), limit=1)
    assert summary.coded == 1
    assert rig.fetched == ["ERA26LA001"]


def test_n_the_real_runners_folder_is_portable_and_its_manifest_sound(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    raws = {str(r["ntsbNumber"]): r for r in RAWS}
    rig.store._closures = [
        Closure(
            mkey=_mkey(r),
            ntsb_number=str(r["ntsbNumber"]),
            event_date="2026-09-01",
            closure_run=n,
            closed_on="2026-10-05",
            closed_as="Completed",
        )
        for n, r in enumerate(RAWS, start=1)
    ]
    fake = FakeBatchClient(handlers=[_answers(_scripts())] * 8)

    def build(client: ModelClient, **kwargs: Any) -> AgentRunner:
        return AgentRunner(
            client,
            batch=fake,
            tables=TABLES,
            stats=STATS,
            seen_pairs=frozenset({"552230"}),
            runs_dir=kwargs["runs_dir"],
            month_spent_usd=0.0,
            commit=kwargs["commit"],
            docket=Dockets(),
            now=kwargs["now"],
            pass_reasoning=False,
        )

    monkeypatch.setattr(morning, "AgentRunner", build)
    monkeypatch.setattr(morning, "fetch_record", lambda client, case: dict(raws[case.case_id]))
    ticks = iter(NOW + timedelta(seconds=n) for n in range(100000))
    sink = LocalFolderSink(rig.runs_dir)
    summary = run_morning(rig.deps(sink=sink, now=lambda: next(ticks)))
    assert summary.run_id is not None
    folder = rig.runs_dir / summary.run_id
    assert summary.coded == 2
    assert portability_problems(folder) == []
    assert verify_manifest(folder) == []
    names = {p.name for p in folder.iterdir()}
    assert {INPUTS_FILE, CLOSURES_FILE, BACKFILL_FILE, "spec.json"} <= names
    assert len((folder / CLOSURES_FILE).read_text().splitlines()) == 2


def test_o_every_refusal_appends_a_row_with_no_case_id(rig: Rig) -> None:
    rig.label = "other"
    with pytest.raises(ConfigurationError):
        run_morning(rig.deps())
    rig.label = VERSION_1
    rig.store._finished = False
    with pytest.raises(ConfigurationError):
        run_morning(rig.deps())
    rig.store._finished = True
    rig.sink.coded = DAILY_LIMIT
    run_morning(rig.deps())
    rig.sink.coded = 0
    rig.spend.usd = 5.0
    with pytest.raises(BudgetError):
        run_morning(rig.deps())
    rows = rig.refusals()
    assert [r["reason"] for r in rows] == [
        "label",
        "recorder-unfinished",
        "daily-limit",
        "monthly-cap",
    ]
    for row in rows:
        assert set(row) == {"at", "reason"}
        assert datetime.fromisoformat(row["at"]).utcoffset() == timedelta(0)


def _first_morning_interrupted(rig: Rig) -> str:
    _StubRunner.raises = RuntimeError("killed")
    with pytest.raises(RuntimeError, match="killed"):
        run_morning(rig.deps(), limit=1)
    _StubRunner.raises = None
    (folder,) = [p for p in rig.runs_dir.iterdir() if p.is_dir()]
    return folder.name


def test_backfill_survives_an_interrupted_first_run_and_a_later_queue(rig: Rig) -> None:
    run_id = _first_morning_interrupted(rig)
    assert (rig.runs_dir / run_id / BACKFILL_FILE).is_file()
    rig.store._closures.append(_closure(4))
    rig.sink.unfinished = run_id
    rig.now = datetime(2026, 10, 8, 6, 0, tzinfo=UTC)
    run_morning(rig.deps())
    backfill = rig.sink.writes[-1][2]
    ids = ("ERA26LA001", "ERA26LA002", "ERA26LA003")
    assert backfill is not None
    assert backfill.case_ids == ids
    assert backfill.sha256 == backfill_digest(ids)
    assert backfill.fixed_on == TODAY


def test_backfill_survives_a_morning_where_every_fetch_failed(rig: Rig) -> None:
    rig.fetch_fails = {"ERA26LA001", "ERA26LA002", "ERA26LA003"}
    summary = run_morning(rig.deps())
    assert summary.run_id is None
    rig.fetch_fails = set()
    rig.store._closures.append(_closure(4))
    rig.now = datetime(2026, 10, 8, 6, 0, tzinfo=UTC)
    run_morning(rig.deps())
    backfill = rig.sink.writes[-1][2]
    assert backfill is not None
    assert backfill.case_ids == ("ERA26LA001", "ERA26LA002", "ERA26LA003")
    assert backfill.fixed_on == TODAY


def test_resume_without_a_backfill_anywhere_is_refused(rig: Rig) -> None:
    run_id = _first_morning_interrupted(rig)
    (rig.runs_dir / run_id / BACKFILL_FILE).unlink()
    rig.sink.unfinished = run_id
    with pytest.raises(ConfigurationError, match="backfill"):
        run_morning(rig.deps())


def test_a_failed_write_is_completed_at_the_start_of_the_next_morning(rig: Rig) -> None:
    live = rig.settings.live_docket_dir
    _cache(1001, live)
    rig.sink.fail_write = True
    with pytest.raises(RuntimeError, match="sink down"):
        run_morning(rig.deps(), limit=1)
    assert (live / "1001").exists()
    (first,) = [p for p in rig.runs_dir.iterdir() if p.is_dir()]
    first_id = first.name
    rig.events.clear()
    rig.now = datetime(2026, 10, 8, 6, 0, tzinfo=UTC)
    run_morning(rig.deps(), limit=1)
    assert rig.sink.writes[0][0] == first_id
    assert [r.case_id for r in rig.sink.writes[0][1]] == ["ERA26LA001"]
    assert rig.events.index("write") < rig.events.index("fetch ERA26LA001")
    assert not (live / "1001").exists()


def test_the_lockfile_checksum_is_read_before_any_fetch_or_run(rig: Rig) -> None:
    def broken() -> str:
        raise OSError("no uv.lock")

    with pytest.raises(OSError, match=r"uv\.lock"):
        run_morning(rig.deps(uv_lock_sha256=broken))
    assert rig.fetched == []
    assert rig.model_calls == 0


def test_a_resume_is_held_to_the_monthly_cap(rig: Rig) -> None:
    run_id = _first_morning_interrupted(rig)
    _StubRunner.instances.clear()
    rig.sink.unfinished = run_id
    rig.spend.usd = 4.99
    with pytest.raises(BudgetError):
        run_morning(rig.deps())
    assert _StubRunner.instances == []
    assert rig.model_calls == 1  # only the first morning's
    assert [r["reason"] for r in rig.refusals()] == ["monthly-cap"]


def test_a_development_run_folder_made_meanwhile_is_never_written_to(rig: Rig) -> None:
    _StubRunner.raises = RuntimeError("killed")
    _StubRunner.side_folder = "20261007T000000-abc1234-dev-400-C"
    with pytest.raises(RuntimeError, match="killed"):
        run_morning(rig.deps(), limit=1)
    side = rig.runs_dir / _StubRunner.side_folder
    assert not (side / INPUTS_FILE).exists()
    assert not (side / BACKFILL_FILE).exists()
    live = [p for p in rig.runs_dir.iterdir() if p.is_dir() and p != side]
    assert (live[0] / INPUTS_FILE).is_file()


def _counts(rig: Rig) -> list[dict[str, Any]]:
    path = rig.runs_dir / "live-morning-counts.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_p_a_morning_appends_its_counts_and_no_case_id(rig: Rig) -> None:
    rig.fetch_fails = {"ERA26LA001"}
    summary = run_morning(rig.deps())
    (row,) = _counts(rig)
    assert row["format"] == "live-morning/1"
    assert datetime.fromisoformat(row["at"]).utcoffset() == timedelta(0)
    assert {k: v for k, v in row.items() if k not in {"format", "at"}} == {
        "run_id": summary.run_id,
        "queue_at_start": 3,
        "taken": 3,
        "coded": 2,
        "not_coded": 0,
        "returned": 1,
        "queued_after": 1,
    }
    assert "ERA26" not in json.dumps(row)


def test_p_a_morning_where_every_fetch_fails_still_appends_its_counts(rig: Rig) -> None:
    rig.fetch_fails = {"ERA26LA001", "ERA26LA002", "ERA26LA003"}
    run_morning(rig.deps())
    (row,) = _counts(rig)
    assert row["run_id"] is None
    assert (row["queue_at_start"], row["taken"], row["coded"], row["returned"]) == (3, 3, 0, 3)
    assert row["queued_after"] == 3


def test_p_a_refused_morning_and_a_dry_run_append_none(rig: Rig) -> None:
    rig.sink.coded = DAILY_LIMIT
    run_morning(rig.deps())
    rig.sink.coded = 0
    rig.spend.usd = 5.0
    with pytest.raises(BudgetError):
        run_morning(rig.deps())
    rig.spend.usd = 0.0
    run_morning(rig.deps(), dry_run=True)
    assert _counts(rig) == []


def test_p_a_resumed_morning_appends_its_counts(rig: Rig) -> None:
    run_id = _first_morning_interrupted(rig)
    rig.sink.unfinished = run_id
    rig.now = datetime(2026, 10, 8, 6, 0, tzinfo=UTC)
    run_morning(rig.deps())
    (row,) = _counts(rig)
    assert row["taken"] == 1


# --- the pinned settings (final review A2) ---


def test_the_pinned_settings_are_the_codes_today() -> None:
    assert current_settings() == dict(VERSION_1_SETTINGS)
    assert settings_differences() == []


@pytest.mark.parametrize(
    ("patch", "setting"),
    [
        ((agent_run, "MAX_CODING_CALLS", 7), "max_coding_calls"),
        ((agent_run, "STATS", "s27"), "stats"),
        ((agent_loop, "PASS_REASONING", True), "pass_reasoning"),
        ((morning, "MODEL_ID", "openai/gpt-6-luna-pro"), "model"),
        ((morning, "REASONING_EFFORT", "high"), "reasoning_effort"),
        ((morning, "MAX_OUTPUT_TOKENS", 2000), "max_output_tokens"),
        ((morning, "LIVE_CAP_USD", 0.5), "cap_usd"),
        ((morning, "WITHOUT", frozenset({"coding"})), "without"),
    ],
)
def test_a_changed_setting_is_refused_before_the_store_is_opened(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, patch: tuple[Any, str, object], setting: str
) -> None:
    target, name, value = patch
    monkeypatch.setattr(target, name, value)
    with pytest.raises(ConfigurationError, match=setting):
        run_morning(rig.deps())
    assert "open" not in rig.events
    assert rig.model_calls == 0
    assert [r["reason"] for r in rig.refusals()] == ["settings"]


def test_a_changed_temperature_default_is_refused(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    @dataclass
    class Warmer:
        temperature: float = 0.7

    monkeypatch.setattr(morning, "ModelSettings", Warmer)
    with pytest.raises(ConfigurationError, match="temperature"):
        run_morning(rig.deps())
    assert "open" not in rig.events


def test_a_changed_statistics_or_items_file_is_refused(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = morning._table_sha256
    monkeypatch.setattr(
        morning, "_table_sha256", lambda name: "0" * 64 if "items" in name else real(name)
    )
    with pytest.raises(ConfigurationError, match="items_csv_sha256"):
        run_morning(rig.deps())
    assert "open" not in rig.events


# --- the $40 guard (final review B2) ---


def _reserve(rig: Rig, run_id: str, usd: float) -> None:
    folder = rig.runs_dir / run_id
    folder.mkdir(exist_ok=True)
    (folder / "reservation.json").write_text(json.dumps({"projected_usd": usd}))


def test_the_monthly_guard_refuses_before_any_fetch_or_folder(rig: Rig) -> None:
    """B2: AgentRunner's own refusal comes after it made a folder; this one leaves nothing."""
    _reserve(rig, "20261007T000000-abc1234-dev-400-C", 39.98)  # 3 cases would be 0.045 more
    before = {p.name for p in rig.runs_dir.iterdir()}
    with pytest.raises(BudgetError, match="monthly guard"):
        run_morning(rig.deps())
    assert rig.fetched == []
    assert rig.model_calls == 0
    assert {p.name for p in rig.runs_dir.iterdir() if p.is_dir()} == before - {
        "live-refusals.jsonl"
    }
    assert [r["reason"] for r in rig.refusals()] == ["monthly-guard"]
    assert not (rig.runs_dir / PENDING).exists()


def test_a_smaller_take_fits_under_the_monthly_guard(rig: Rig) -> None:
    _reserve(rig, "20261007T000000-abc1234-dev-400-C", 39.98)  # room for one case, not three
    summary = run_morning(rig.deps(), limit=1)
    assert summary.coded == 1


def test_a_resume_does_not_count_its_own_reservation_against_the_guard(rig: Rig) -> None:
    run_id = _first_morning_interrupted(rig)
    _StubRunner.instances.clear()
    rig.sink.unfinished = run_id
    _reserve(rig, run_id, 39.99)  # the run's own: excluded; the guard sees spend 0 + 0 + cases
    run_morning(rig.deps())
    assert len(_StubRunner.instances) == 1
    assert rig.refusals() == []
