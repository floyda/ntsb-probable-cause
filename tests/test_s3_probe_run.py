"""Tests for ``scripts/s3_probe/run.py``: the ``run`` command, offline.

Every test builds a temporary ``NTSB_DATA_DIR``/``NTSB_RUNS_DIR`` and monkeypatches the three
seams that would otherwise touch real data -- ``load_cases``, ``seen_pairs_of`` (both read
``cases.parquet``) and ``docket_reader`` (which would build a real cache-backed
``DocketClient``) -- with fakes built from ``tests/test_s3_probe_loop``'s own fixtures
(a real development record relabelled to a ``dev-400`` case ID, and an in-memory docket).
``load_tables`` and ``load_stats`` are the real, offline, packaged functions: no network or
parquet file is needed for either.
"""

import json
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from pathlib import Path

import pytest
from scripts.s3_probe import run
from scripts.s3_probe.trail import CaseTrail
from tests.test_s3_probe_loop import DEV_ID, _docket, _raw

from ntsb_probable_cause.docket.manifest import Docket
from ntsb_probable_cause.errors import BudgetError, ConfigurationError
from ntsb_probable_cause.model.client import (
    ModelClient,
    ModelReply,
    ModelSettings,
    Payload,
    Turn,
    Usage,
)
from ntsb_probable_cause.scoring import budget as budget_mod
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.samples import sample_ids
from ntsb_probable_cause.settings import Settings

DEV_ID_2 = sample_ids("dev-400")[1]


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    data_dir = tmp_path / "data"
    fields: dict[str, object] = {
        "data_dir": data_dir,
        "runs_dir": data_dir / "runs",
        "docket_dir": data_dir / "docket",
        "transcription_dir": data_dir / "transcriptions",
    }
    fields.update(overrides)
    return Settings(**fields)  # type: ignore[arg-type]


def _write_cases(settings: Settings, ids: Sequence[str]) -> None:
    cells = {case_id: {"fatal": False, "has_scan": False} for case_id in ids}
    path = settings.data_dir / run.CASES_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cells))


def _job_dirs(settings: Settings) -> list[Path]:
    """Every job subdirectory of ``probes/s3-probe/`` -- excluding the ``cases.json`` file
    ``select`` writes as a sibling in the same directory."""
    root = settings.data_dir / run.PROBE_ROOT
    if not root.is_dir():
        return []
    return [p for p in root.iterdir() if p.is_dir()]


class _FakeReader:
    """A docket reader that always returns the loop tests' in-memory fixture docket."""

    def read(self, mkey: int) -> Docket:
        return _docket()


def _patch_case_loading(monkeypatch: pytest.MonkeyPatch, ids: Sequence[str]) -> None:
    """Replace the three seams that would otherwise touch ``cases.parquet`` or a real cache."""
    wanted = set(ids)

    def fake_load_cases(_processed: Path, requested: Sequence[str]) -> list[dict[str, object]]:
        assert set(requested) <= wanted
        return [_raw(case_id) for case_id in requested]

    monkeypatch.setattr(run, "load_cases", fake_load_cases)
    monkeypatch.setattr(run, "seen_pairs_of", lambda _processed: frozenset())
    monkeypatch.setattr(run, "docket_reader", lambda _settings: _FakeReader())


class _PaidFakeClient(run.DryRunClient):
    """``DryRunClient``'s canned replies, but with billable usage, for paid-path tests.

    Deterministic and stateless -- unlike ``RecordingFakeClient``'s scripted list, it never
    runs out of replies, so one instance can safely answer any number of calls across any
    number of cases.
    """

    def complete(
        self,
        payload: Payload,
        settings: ModelSettings,
        *,
        system: str = "",
        history: Sequence[Turn] = (),
    ) -> ModelReply:
        reply = super().complete(payload, settings, system=system, history=history)
        return reply.model_copy(update={"usage": Usage(prompt_tokens=1000, completion_tokens=100)})


def _paid_builder(_settings: Settings) -> Callable[[ExitStack], Callable[[], ModelClient]]:
    """A stand-in for ``_openrouter_factory``: one billable fake client, no key, no network."""
    tables = load_tables()

    def per_run(_stack: ExitStack) -> Callable[[], ModelClient]:
        return lambda: _PaidFakeClient(tables)

    return per_run


class _BoomClient:
    """A ``ModelClient`` whose first call always raises -- never a parse or leak failure."""

    def complete(
        self,
        payload: Payload,
        settings: ModelSettings,
        *,
        system: str = "",
        history: Sequence[Turn] = (),
    ) -> ModelReply:
        raise RuntimeError("boom: the transport failed")


def _boom_builder(_settings: Settings) -> Callable[[ExitStack], Callable[[], ModelClient]]:
    def per_run(_stack: ExitStack) -> Callable[[], ModelClient]:
        return _BoomClient

    return per_run


class _FlakyClient(run.DryRunClient):
    """Billable like ``_PaidFakeClient``, but its ``fail_at``-th call (1-indexed, shared
    across every case this one instance answers) raises once; every other call succeeds."""

    def __init__(self, tables: object, fail_at: int) -> None:
        super().__init__(tables)  # type: ignore[arg-type]
        self._n = 0
        self._fail_at = fail_at

    def complete(
        self,
        payload: Payload,
        settings: ModelSettings,
        *,
        system: str = "",
        history: Sequence[Turn] = (),
    ) -> ModelReply:
        self._n += 1
        if self._n == self._fail_at:
            raise RuntimeError("boom: transport failed mid-case")
        reply = super().complete(payload, settings, system=system, history=history)
        return reply.model_copy(update={"usage": Usage(prompt_tokens=1000, completion_tokens=100)})


def _flaky_builder(
    fail_at: int,
) -> Callable[[Settings], Callable[[ExitStack], Callable[[], ModelClient]]]:
    """One shared ``_FlakyClient`` for the whole run (so ``fail_at`` counts across cases)."""
    tables = load_tables()
    client = _FlakyClient(tables, fail_at)

    def builder(_settings: Settings) -> Callable[[ExitStack], Callable[[], ModelClient]]:
        def per_run(_stack: ExitStack) -> Callable[[], ModelClient]:
            return lambda: client

        return per_run

    return builder


# ------------------------------------------------------------------------------------------
# Refusals before any model call
# ------------------------------------------------------------------------------------------


def test_refuses_without_cases_json(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(ConfigurationError, match=r"run `python -m scripts\.s3_probe select`"):
        run.cmd_run(settings, limit=None, workers=1, dry_run=True)


def test_refuses_a_case_outside_dev_400(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_cases(settings, [DEV_ID, "NOT00000A"])
    with pytest.raises(ValueError, match="not in dev-400"):
        run.cmd_run(settings, limit=None, workers=1, dry_run=True)
    # Refused before any job folder was written.
    assert _job_dirs(settings) == []


def test_refuses_when_the_month_is_nearly_spent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A key is set: the client factory is built (and its key checked) before the reservation,
    # so this test needs a key present to reach the budget guard at all -- key absence has its
    # own test below.
    settings = _settings(tmp_path, monthly_budget_usd=0.01, openrouter_api_key="test-key")
    _write_cases(settings, [DEV_ID])
    _patch_case_loading(monkeypatch, [DEV_ID])
    with pytest.raises(BudgetError):
        run.cmd_run(settings, limit=None, workers=1, dry_run=False)
    assert _job_dirs(settings) == []


def test_refuses_before_reserving_when_the_key_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing ``OPENROUTER_API_KEY`` must fail before any reservation is made.

    The client factory (and so, for OpenRouter, its key check) is built before
    ``reserve_within_budget`` precisely so this refusal never leaves an open reservation with
    nothing left to settle it (fix round 1, finding 1).
    """
    settings = _settings(tmp_path, openrouter_api_key=None)
    _write_cases(settings, [DEV_ID])
    _patch_case_loading(monkeypatch, [DEV_ID])
    with pytest.raises(ConfigurationError, match="OPENROUTER_API_KEY"):
        run.cmd_run(settings, limit=None, workers=1, dry_run=False)
    assert budget_mod.open_reservations(settings.runs_dir) == {}
    assert not list(settings.runs_dir.glob("*/spend.jsonl"))
    assert _job_dirs(settings) == []


# ------------------------------------------------------------------------------------------
# The reservation, and a case that fails mid-run
# ------------------------------------------------------------------------------------------


def test_a_failing_case_settles_the_reservation_and_does_not_abort_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """One case raising must not hide the reservation's settlement, nor other cases' results.

    Every call of this run's single case raises, so it produces no trail; the run still
    finishes, settles its reservation, and reports itself failed rather than crashing out
    (fix round 1, finding 2).
    """
    settings = _settings(tmp_path)
    _write_cases(settings, [DEV_ID])
    _patch_case_loading(monkeypatch, [DEV_ID])
    monkeypatch.setattr(run, "_openrouter_factory", _boom_builder)

    result = run.cmd_run(settings, limit=None, workers=1, dry_run=False)

    assert result == 1
    assert "failed: exception RuntimeError" in capsys.readouterr().out
    assert budget_mod.open_reservations(settings.runs_dir) == {}
    (job_dir,) = _job_dirs(settings)
    # No case finished, so trails.jsonl was never written at all.
    assert not (job_dir / "trails.jsonl").exists()


# ------------------------------------------------------------------------------------------
# Spend rows
# ------------------------------------------------------------------------------------------


def test_spend_rows_carry_kind_probe_and_the_job_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    ids = [DEV_ID]
    _write_cases(settings, ids)
    _patch_case_loading(monkeypatch, ids)
    monkeypatch.setattr(run, "_openrouter_factory", _paid_builder)

    result = run.cmd_run(settings, limit=None, workers=1, dry_run=False)

    assert result == 0
    spend_files = list(settings.runs_dir.glob("*/spend.jsonl"))
    assert len(spend_files) == 1
    job_id = spend_files[0].parent.name
    rows = [json.loads(line) for line in spend_files[0].read_text().splitlines()]
    # One case, fewer than a chunk of 5: exactly one remainder row.
    assert len(rows) == 1
    assert rows[0]["kind"] == "probe"
    assert rows[0]["job_id"] == job_id
    assert rows[0]["cost_usd"] > 0
    assert rows[0]["calls"] > 0
    assert budget_mod.open_reservations(settings.runs_dir) == {}

    trails_path = settings.data_dir / run.PROBE_ROOT / job_id / "trails.jsonl"
    lines = trails_path.read_text().splitlines()
    assert len(lines) == 1
    trail = CaseTrail.model_validate_json(lines[0])
    assert trail.cost_usd > 0


def test_spend_reconciles_when_a_case_fails_after_some_paid_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A case's paid calls before it fails must still be billed, even with no trail of its own.

    One shared, stateful fake client answers both cases in submission order (``workers=1``):
    the first case's first call (its H0) succeeds and is billed, its second call (choice 1)
    raises, so it produces no trail; the second case then runs to completion normally. The
    spend rows must still sum to every dollar ``RunBudget`` recorded, including the failed
    case's orphaned H0 cost (fix round 1, finding 2).
    """
    settings = _settings(tmp_path)
    ids = sorted([DEV_ID, DEV_ID_2])
    _write_cases(settings, ids)
    _patch_case_loading(monkeypatch, ids)
    monkeypatch.setattr(run, "_openrouter_factory", _flaky_builder(fail_at=2))

    result = run.cmd_run(settings, limit=None, workers=1, dry_run=False)

    assert result == 1
    assert "failed: exception RuntimeError" in capsys.readouterr().out
    assert budget_mod.open_reservations(settings.runs_dir) == {}

    spend_files = list(settings.runs_dir.glob("*/spend.jsonl"))
    assert len(spend_files) == 1
    rows = [json.loads(line) for line in spend_files[0].read_text().splitlines()]
    total_spend = sum(r["cost_usd"] for r in rows)

    job_id = spend_files[0].parent.name
    trails_path = settings.data_dir / run.PROBE_ROOT / job_id / "trails.jsonl"
    lines = trails_path.read_text().splitlines()
    assert len(lines) == 1  # only the surviving case produced a trail
    trail = CaseTrail.model_validate_json(lines[0])

    # The failed case's own successful H0 call was billed too; that money is folded into the
    # reconciled spend even though it never became part of any trail.
    assert total_spend > trail.cost_usd


def test_spend_rows_chunk_at_five_and_sum_to_the_trails_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    ids = list(sample_ids("dev-400")[:6])
    _write_cases(settings, ids)
    _patch_case_loading(monkeypatch, ids)
    monkeypatch.setattr(run, "_openrouter_factory", _paid_builder)

    result = run.cmd_run(settings, limit=None, workers=1, dry_run=False)

    assert result == 0
    spend_files = list(settings.runs_dir.glob("*/spend.jsonl"))
    assert len(spend_files) == 1
    rows = [json.loads(line) for line in spend_files[0].read_text().splitlines()]
    assert len(rows) == 2  # a chunk of 5, then the remainder of 1

    job_id = spend_files[0].parent.name
    trails_path = settings.data_dir / run.PROBE_ROOT / job_id / "trails.jsonl"
    trails = [CaseTrail.model_validate_json(line) for line in trails_path.read_text().splitlines()]
    assert len(trails) == 6

    total_spend = sum(r["cost_usd"] for r in rows)
    total_trails = sum(t.cost_usd for t in trails)
    assert total_spend == pytest.approx(total_trails)


# ------------------------------------------------------------------------------------------
# --dry-run
# ------------------------------------------------------------------------------------------


def test_dry_run_produces_trails_and_no_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    ids = [DEV_ID, DEV_ID_2]
    _write_cases(settings, ids)
    _patch_case_loading(monkeypatch, ids)

    result = run.cmd_run(settings, limit=None, workers=2, dry_run=True)

    assert result == 0
    assert not settings.runs_dir.exists()  # nothing at all written to runs_dir
    job_dirs = _job_dirs(settings)
    assert len(job_dirs) == 1
    job_dir = job_dirs[0]
    lines = (job_dir / "trails.jsonl").read_text().splitlines()
    assert len(lines) == 2
    for line in lines:
        trail = CaseTrail.model_validate_json(line)
        assert trail.cost_usd == 0.0
        assert trail.stop_reason == "done"
    probe = json.loads((job_dir / "probe.json").read_text())
    assert probe["job_id"] == job_dir.name
    assert probe["cases_run"] == 2
    assert "finished" in probe


def test_dry_run_limit_runs_only_the_first_n_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    ids = sorted([DEV_ID, DEV_ID_2])
    _write_cases(settings, ids)
    _patch_case_loading(monkeypatch, ids)

    run.cmd_run(settings, limit=1, workers=1, dry_run=True)

    (job_dir,) = _job_dirs(settings)
    lines = (job_dir / "trails.jsonl").read_text().splitlines()
    assert len(lines) == 1
    probe = json.loads((job_dir / "probe.json").read_text())
    assert probe["cases_run"] == 1
    assert probe["cases_selected"] == 2
