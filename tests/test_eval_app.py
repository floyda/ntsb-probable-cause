"""The ``ntsb-eval`` command: subcommand wiring and one real, fake-client end-to-end run."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from apps.eval.__main__ import main, month_spent, resolve_latest

from ntsb_probable_cause.model.client import ModelClient, RecordingFakeClient
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.records import RunRecord, write_jsonl
from ntsb_probable_cause.scoring.runner import BatchRunner
from ntsb_probable_cause.settings import Settings

GOOD = json.dumps(
    {
        "evidence_narrative": "n",
        "probable_cause": "p",
        "lay_explanation": "l",
        "confidence": 0.7,
        "abstain": False,
        "evidence_used": ["phase_of_flight"],
        "occurrence": [{"phase": "552", "event": "230", "probability": 0.7}],
        "findings": [{"category6": "020630", "modifier": "44", "probability": 0.6}],
    }
)
REFINE = json.dumps({"items": [{"index": 0, "item8": "02063040"}]})


def test_help_lists_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    for word in ("baseline", "run", "report", "judge", "threshold"):
        assert word in out


def test_month_spent_includes_aborted_runs_in_the_current_month(tmp_path: Path) -> None:
    now = datetime(2026, 9, 15, tzinfo=UTC)
    kwargs = {
        "run_id": "r1",
        "sample": "dev-400",
        "arm": "ceiling",
        "exclusions": (),
        "includes": (),
        "prompt_version": "v",
        "model": "m",
        "price_variant": "batch",
        "cap_usd": 0.05,
        "budget_usd": 25.0,
        "commit_sha": "abc",
        "dirty": False,
    }
    finished_run = RunRecord(**kwargs, started=now, finished=now, cost_usd=1.0)
    aborted_run = RunRecord(**{**kwargs, "run_id": "r2"}, started=now, finished=None, cost_usd=2.0)
    other_month = RunRecord(
        **{**kwargs, "run_id": "r3"},
        started=datetime(2026, 8, 1, tzinfo=UTC),
        finished=now,
        cost_usd=100.0,
    )
    write_jsonl(tmp_path / "r1" / "run.jsonl", [finished_run])
    write_jsonl(tmp_path / "r2" / "run.jsonl", [aborted_run])
    write_jsonl(tmp_path / "r3" / "run.jsonl", [other_month])
    assert month_spent(tmp_path, now=now) == pytest.approx(3.0)


def test_month_spent_of_a_missing_runs_dir_is_zero(tmp_path: Path) -> None:
    assert month_spent(tmp_path / "nope", now=datetime(2026, 9, 15, tzinfo=UTC)) == 0.0


def test_resolve_latest_picks_the_newest_matching_folder(tmp_path: Path) -> None:
    (tmp_path / "20260101T000000-abc-dev-400-ceiling").mkdir()
    (tmp_path / "20260901T000000-abc-dev-400-ceiling").mkdir()
    (tmp_path / "20260501T000000-abc-dev-400-A").mkdir()
    assert resolve_latest(tmp_path, "ceiling", "dev-400") == "20260901T000000-abc-dev-400-ceiling"


def test_resolve_latest_raises_when_nothing_matches(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="no run found"):
        resolve_latest(tmp_path, "ceiling", "dev-400")


def test_run_sync_then_report_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_fixtures: list[dict[str, object]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``run --sync`` with a fake client, then ``report`` prints an occurrence top-1 row."""
    raw = record_fixtures[0]
    case_id = str(raw["ntsbNumber"])
    event_date = str(raw["eventDate"])[:10]

    ids_dir = tmp_path / "eval_ids"
    ids_dir.mkdir()
    (ids_dir / "dev_ids.csv").write_text(f"case_id,event_date\n{case_id},{event_date}\n")
    monkeypatch.setattr(samples, "EVAL_DIR", ids_dir)
    monkeypatch.setitem(samples._FILES, "dev-400", "dev_ids.csv")

    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    schema = pa.schema(
        [
            ("ntsb_number", pa.string()),
            ("event_date", pa.date32()),
            ("split", pa.string()),
            ("investigation_class", pa.string()),
            ("raw_json", pa.string()),
        ]
    )
    table = pa.table(
        {
            "ntsb_number": pa.array([case_id], type=pa.string()),
            "event_date": pa.array([date.fromisoformat(event_date)], type=pa.date32()),
            "split": pa.array(["dev"], type=pa.string()),
            "investigation_class": pa.array(["C"], type=pa.string()),
            "raw_json": pa.array([json.dumps(raw)], type=pa.string()),
        },
        schema=schema,
    )
    pq.write_table(table, processed / "cases.parquet")

    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(tmp_path / "data" / "runs"))

    fake = RecordingFakeClient([GOOD, REFINE])

    def factory(_settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
        return fake, None

    exit_code = main(
        ["run", "--arm", "ceiling", "--sample", "dev-400", "--sync"], client_factory=factory
    )
    assert exit_code == 0
    runs_dir = tmp_path / "data" / "runs"
    (run_folder,) = list(runs_dir.iterdir())
    assert (run_folder / "cases.jsonl").exists()

    capsys.readouterr()  # discard the run command's own output
    main(["report", run_folder.name], client_factory=factory)
    out = capsys.readouterr().out
    assert "top-1" in out
    assert "| all |" in out
