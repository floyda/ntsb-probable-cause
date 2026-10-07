"""The open-split fence (S3.3 spec 9, decision 0024): no evaluation command reads a live run.

A live run folder is built in ``tmp_path`` from invented data. Every command that reads a run's
record refuses it with a message naming decision 0024; the spend still counts, and the upload
function of the store is named nowhere under ``live`` (import-linter forbids modules, not names).
"""

import json
import re
from pathlib import Path

import apps.eval.__main__ as app
import pytest
from scripts import _s3_runs, reply_budget, sealed_report
from tests.test_live_local import NOW, _run_record

from ntsb_probable_cause.agent import armb
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring import checkpass
from ntsb_probable_cause.scoring.budget import month_spent
from ntsb_probable_cause.scoring.records import CaseResult, write_jsonl

RUN_ID = "20261007T010000Z-abc1234-live-C"
ROOT = Path(__file__).resolve().parent.parent


def _live_run(runs: Path, *, sample: str = "live", run_id: str = RUN_ID) -> Path:
    folder = runs / run_id
    folder.mkdir(parents=True)
    write_jsonl(folder / "run.jsonl", [_run_record(run_id, sample, cost=2.0)])
    (folder / "spec.json").write_text(json.dumps({"sample": sample}))
    case = CaseResult(
        case_id="XXX26LA000",
        split="open",
        fatal=False,
        investigation_class=None,
        report_flavour=None,
        verdict_occurrence=(),
        verdict_findings=(),
        verdict_findings_in_cause=(),
        steps=(),
        scores=None,
        cost_usd=2.0,
        failure=None,
    )
    write_jsonl(folder / "cases.jsonl", [case])
    return folder


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    path = tmp_path / "data" / "runs"
    path.mkdir(parents=True)
    _live_run(path)
    return path


def _refusal(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    try:
        code = app.main(argv)
    except SystemExit as stop:
        return str(stop.code)
    assert code == 1, argv
    return capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [
        ["report", RUN_ID],
        ["report", "--latest", "C", "live"],
        ["report", RUN_ID, "--against", RUN_ID],
        ["judge", RUN_ID],
        ["check", RUN_ID, "--way", "rule"],
        ["tools", RUN_ID],
    ],
)
def test_every_command_that_reads_a_run_refuses_a_live_one(
    runs: Path, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert "0024" in _refusal(argv, capsys)


def test_answering_run_record_refuses_live_and_reads_others(runs: Path) -> None:
    with pytest.raises(ConfigurationError, match="0024"):
        app.answering_run_record(runs / RUN_ID)
    other = "20261007T020000Z-abc1234-dev-400-C"
    _live_run(runs, sample="dev-400", run_id=other)
    assert app.answering_run_record(runs / other).sample == "dev-400"


def test_resolve_latest_never_returns_a_live_run(runs: Path) -> None:
    # a live record in a folder whose name says another sample is skipped, not returned
    _live_run(runs, sample="live", run_id="20261007T030000Z-abc1234-dev-400-C")
    with pytest.raises(SystemExit, match="no completed run"):
        app.resolve_latest(runs, "C", "dev-400")


def test_a_live_run_is_not_readable_by_the_s3_scripts(runs: Path) -> None:
    with pytest.raises(SystemExit, match="noise floor is measured on dev-400"):
        _s3_runs.load_runs("prog", [RUN_ID])


def test_the_live_runs_spend_still_counts_against_the_month(runs: Path) -> None:
    assert month_spent(runs, now=NOW) == 2.0


def test_nothing_under_live_names_the_stores_upload() -> None:
    files = [
        *(ROOT / "src" / "ntsb_probable_cause" / "live").rglob("*.py"),
        *(ROOT / "apps" / "live").rglob("*.py"),
    ]
    assert files
    for path in files:
        assert not re.search(r"\bpush\b", path.read_text()), path


def test_the_evaluation_commands_spell_the_live_sample_as_the_live_package_does() -> None:
    from ntsb_probable_cause.live.local import LIVE_SAMPLE  # noqa: PLC0415

    assert app.LIVE_SAMPLE == LIVE_SAMPLE


def test_threshold_refuses_a_live_run_before_reading_its_cases(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (runs / RUN_ID / "cases.jsonl").unlink()
    assert "0024" in _refusal(["threshold", RUN_ID], capsys)


def test_against_a_live_run_is_refused_before_its_cases_are_read(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dev = "20261007T020000Z-abc1234-dev-400-C"
    _live_run(runs, sample="dev-400", run_id=dev)
    (runs / RUN_ID / "cases.jsonl").unlink()
    assert "0024" in _refusal(["report", dev, "--against", RUN_ID], capsys)


def test_checkpass_and_armb_refuse_a_live_run_without_the_fence_in_front(runs: Path) -> None:
    """The plan's "(test it)": the existing development-only refusals cover `check` and `tools`."""
    with pytest.raises(ConfigurationError, match="development"):
        checkpass.preflight(runs / RUN_ID, "rule", runs)
    with pytest.raises(ConfigurationError, match="development"):
        armb.preflight(runs / RUN_ID, runs)


def test_the_two_report_scripts_refuse_a_live_run_before_reading_its_cases(runs: Path) -> None:
    (runs / RUN_ID / "cases.jsonl").unlink()
    with pytest.raises(SystemExit, match="0024"):
        reply_budget.main(["--run", RUN_ID])
    with pytest.raises(SystemExit, match="0024"):
        reply_budget.main(["--confirm", RUN_ID, "--size", RUN_ID])
    with pytest.raises(SystemExit, match="0024"):
        sealed_report._scored(RUN_ID)
