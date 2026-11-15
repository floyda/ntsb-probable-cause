"""The counts-only cloud report (S4 Task 14, decisions 0170, 0181): no case number."""

import hashlib
import json
import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import scripts.s4_live_report as module
from tests.test_live_records import _record

from ntsb_probable_cause.agent.version import VERSION_1
from ntsb_probable_cause.live.ledger import LedgerLine
from ntsb_probable_cause.live.names import NAMES_LIMIT
from ntsb_probable_cause.live.records import Backfill
from ntsb_probable_cause.scoring.records import RunRecord, write_jsonl

ROOT = Path(__file__).resolve().parent
EXPORT = ROOT / "fixtures" / "board"  # the invented export: all six grades
PATTERN = re.compile(r"[A-Z]{3}\d{2}[A-Z]{2}\d{3}")
TODAY = date(2026, 10, 12)
BACKFILL = ("BBB26LA001", "BBB26LA002")
RUN_A, RUN_B = "20261009-a-live", "20261010-b-live"
CONTINUITY = f"version 1 label: x\nmatch: yes\n+t {VERSION_1.rsplit('+t', 1)[-1]}\n"
ATTEST = {
    "alert_email_received": "2026-10-11",
    "alarm_test_fired": "2026-10-11",
    "mac_key_removed": "2026-10-12",
}


def _run_record(run_id: str, started: datetime, cost: float, reported: float | None) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        sample="live",
        arm="C",
        exclusions=(),
        includes=(),
        prompt_version=VERSION_1,
        model="openai/gpt-6-luna",
        price_variant="standard",
        cap_usd=0.3,
        budget_usd=9.0,
        commit_sha="abc",
        dirty=False,
        started=started,
        finished=started,
        cost_usd=cost,
        reported_batch_cost_usd=reported,
    )


def _closure(case_id: str, **changes: Any) -> str:
    base = _record().model_copy(
        update={
            "case_id": case_id,
            "prompt_version": VERSION_1,
            "outcome": "coded",
            "scored": True,
            "top1": True,
            "top3": True,
            "abstained": False,
            "waited_days": 0,
            "first_sent": datetime(2026, 10, 9, 1, tzinfo=UTC),
            "last_returned": datetime(2026, 10, 9, 2, tzinfo=UTC),
            **changes,
        }
    )
    return base.model_dump_json() + "\n"


def _write_run(
    mirror: Path, run_id: str, started: datetime, closures: list[str], costs: tuple[float, float]
) -> str:
    cost, reported = costs
    folder = mirror / "runs" / run_id
    folder.mkdir(parents=True)
    write_jsonl(folder / "run.jsonl", [_run_record(run_id, started, cost, reported)])
    (folder / "closures.jsonl").write_text("".join(closures))
    rows = [
        {"reply_model": "openai/gpt-6-luna", "reply_provider": "OpenAI"},
        {"reply_model": "openai/gpt-6-luna-2", "reply_provider": "Azure"},
        {"reply_model": None, "reply_provider": None},
    ]
    (folder / "trail.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    manifest = folder / "manifest.json"
    manifest.write_text(json.dumps({"format": "live-manifest/1", "files": []}))
    return hashlib.sha256(manifest.read_bytes()).hexdigest()


def _night(
    mirror: Path, day: str, *, alerts: list[str], finished: bool | None, runs: list[str]
) -> None:
    folder = mirror / "nights" / day
    folder.mkdir(parents=True)
    (folder / "started").write_text("")
    if finished is None:
        return
    (folder / "night.json").write_text(
        json.dumps({"format": "live-night/1", "date": day, "later_scored": 1, "alerts": alerts})
    )
    files = [{"path": f"runs/{r}/closures.jsonl", "size": 1, "sha256": "0" * 64} for r in runs]
    (folder / "manifest.json").write_text(
        json.dumps({"format": "live-night-manifest/1", "finished": finished, "night_files": files})
    )


def _world(tmp_path: Path, *, fresh: bool = True) -> tuple[Path, Path, list[LedgerLine]]:
    mirror = tmp_path / "mirror"
    sha_a = _write_run(
        mirror,
        RUN_A,
        datetime(2026, 10, 9, 6, tzinfo=UTC),
        [_closure(c) for c in BACKFILL],
        (1.0, 0.5),
    )
    backfill = Backfill(fixed_on=date(2026, 10, 9), case_ids=BACKFILL, sha256="ab" * 32)
    (mirror / "runs" / RUN_A / "backfill.json").write_text(backfill.model_dump_json())
    sha_b = _write_run(
        mirror,
        RUN_B,
        datetime(2026, 10, 10, 6, tzinfo=UTC),
        [_closure("FFF26LA003", waited_days=1)] if fresh else [],
        (0.2, 0.1),
    )
    _night(mirror, "2026-10-09", alerts=[], finished=True, runs=[RUN_A])
    _night(mirror, "2026-10-10", alerts=["money-held-back"], finished=True, runs=[RUN_B])
    _night(mirror, "2026-10-11", alerts=["recorder-not-finished"], finished=False, runs=[])
    _night(mirror, "2026-10-12", alerts=[], finished=None, runs=[])
    (mirror / "scores").mkdir()
    (mirror / "scores" / "2026-10-10.jsonl").write_text('{"case_id": "BBB26LA001"}\n')
    now = datetime(2026, 10, 10, 10, tzinfo=UTC)
    ledger = [
        LedgerLine(
            appended_at=now, key=f"runs/{run}/manifest.json", sha256=sha, size=1, counts=None
        )
        for run, sha in ((RUN_A, sha_a), (RUN_B, sha_b))
    ]
    return mirror, EXPORT, ledger


def _report(mirror: Path, export: Path, ledger: Any, **options: Any) -> str:
    """``report_text`` with the night's export defaulting to the same invented export."""
    options.setdefault("night_export", export)
    return module.report_text(mirror, export, ledger, **options)


def _text(tmp_path: Path, **changes: Any) -> str:
    mirror, export, ledger = _world(tmp_path)
    options: dict[str, Any] = {
        "today": TODAY,
        "dev_spend": ["development spend, S4: $0.00"],
        "attest": ATTEST,
        "continuity": CONTINUITY,
    }
    return _report(mirror, export, changes.pop("ledger", ledger), **options | changes)


def test_every_section_prints_and_no_case_number_does(tmp_path: Path) -> None:
    text = _text(tmp_path)
    for heading in (
        "nights",
        "alerts, by kind",
        "cases",
        "grades",
        "replies (decision 0169)",
        "names (",
        "money",
        "backfill",
        "closures per night (UTC), since 2026-09-23",
        "closing rule (decision 0181)",
    ):
        assert heading in text, heading
    assert not PATTERN.search(text)
    assert "only as counts" in text.splitlines()[0]


def test_nights_alerts_cases_and_grades_are_counted_from_the_files(tmp_path: Path) -> None:
    lines = _text(tmp_path).splitlines()
    assert "nights started: 4" in lines
    assert "nights finished: 2" in lines
    assert "nights stopped, recorder-not-finished: 1" in lines
    assert "nights started with no record (killed, crashed or still running): 1" in lines
    assert "alert, money-held-back: 1" in lines
    assert "alert, recorder-not-finished: 1" in lines
    assert "cases coded: 5" in lines
    assert "unreachable (not coded, final): 1" in lines
    assert "awaiting the NTSB's codes: 1" in lines
    assert "later scores written (night records): 3" in lines
    assert "later scores held (score files): 1" in lines
    for grade, count in (
        ("same_first", 1),
        ("same_codes_other_order", 1),
        ("different", 1),
        ("abstained", 1),
        ("not_coded", 2),
        ("awaiting_ntsb", 1),
    ):
        assert f"grade, {grade}: {count}" in lines
    assert any(x.startswith("95% interval for same first code (1 of 6 cases") for x in lines)
    assert any(x.startswith("finding recall@10, mean over") for x in lines)
    assert "closures per night: " not in lines  # the section is a dated list
    assert "2026-10-09: 2" in lines
    assert "2026-10-12: 0" in lines


def test_replies_names_money_and_the_backfill(tmp_path: Path) -> None:
    lines = _text(tmp_path).splitlines()
    assert "replies, provider OpenAI: 2" in lines
    assert "replies, provider Azure: 2" in lines
    assert "replies whose model differs from the one asked for: 2" in lines
    assert "calls with no reply model recorded: 2" in lines
    assert any(x.startswith("words replaced with a name marker in the export: ") for x in lines)
    assert f"limit: {NAMES_LIMIT}" in lines  # the published limit, as decision 0184 states it
    first = next(x for x in lines if x.startswith("live key, first cloud nights"))
    later = next(x for x in lines if x.startswith("live key, later nights"))
    assert "$0.5000 over 1 run records" in first  # the billed total of the backfill's run
    assert "$0.1000 over 1 run records" in later
    assert "development spend, S4: $0.00" in lines
    assert f"backfill: 2 cases, SHA-256 {'ab' * 32}" in lines


def test_all_seven_conditions_read_met_from_the_files(tmp_path: Path) -> None:
    lines = _text(tmp_path).splitlines()
    conditions = [x for x in lines if re.match(r"[1-7]\. ", x)]
    assert len(conditions) == 7
    for line in conditions:
        assert line.split(": ")[-1].startswith("met"), line
    assert lines[-1] == "closing rule: all seven conditions met"


def test_each_condition_reads_not_met_when_its_file_is_missing(tmp_path: Path) -> None:
    mirror, export, ledger = _world(tmp_path)

    def verdicts(**changes: Any) -> dict[str, str]:
        options: dict[str, Any] = {
            "today": TODAY,
            "attest": ATTEST,
            "continuity": CONTINUITY,
            "ledger": ledger,
        } | changes
        text = _report(mirror, options.pop("export", export), options.pop("ledger"), **options)
        return {x[0]: x.split(": ")[-1] for x in text.splitlines() if re.match(r"[1-7]\. ", x)}

    assert verdicts(continuity=None)["1"] == "not met"
    assert verdicts(continuity="match: no")["1"] == "not met"
    assert verdicts(ledger=[])["4"] == "not met"
    assert verdicts(ledger=[ledger[0]])["4"] == "not met"  # run B's manifest is not in it
    changed = [ledger[0], ledger[1].model_copy(update={"sha256": "f" * 64})]
    assert verdicts(ledger=changed)["4"] == "not met"  # the manifest changed since it was hashed
    assert verdicts(attest={})["5"] == "not met"
    assert verdicts(attest={})["7"] == "not met"
    assert verdicts(attest={"alert_email_received": "x"})["5"] == "not met"
    assert verdicts(export=tmp_path / "nowhere")["6"] == "not met"


def test_a_closure_that_waited_two_days_is_not_a_fresh_one(tmp_path: Path) -> None:
    mirror, export, ledger = _world(tmp_path)
    path = mirror / "runs" / RUN_B / "closures.jsonl"
    path.write_text(_closure("FFF26LA003", waited_days=2))
    text = _report(mirror, export, ledger, today=TODAY, attest=ATTEST, continuity=CONTINUITY)
    assert "(0 such cases): not met" in text
    assert text.splitlines()[-1] == "closing rule: 5 of 7 conditions met"


def test_the_time_limit_closes_on_the_rest_and_says_so(tmp_path: Path) -> None:
    mirror, export, ledger = _world(tmp_path, fresh=False)
    text = _report(
        mirror, export, ledger, today=date(2026, 10, 24), attest=ATTEST, continuity=CONTINUITY
    )
    lines = text.splitlines()
    assert "days since the backfill drained: 15" in lines
    assert any(x.startswith("time limit") and x.endswith("reached") for x in lines)
    assert lines[-1].startswith("closing rule: the six others met and the time limit reached")
    early = _report(
        mirror, export, ledger, today=date(2026, 10, 12), attest=ATTEST, continuity=CONTINUITY
    )
    assert early.splitlines()[-1] == "closing rule: 5 of 7 conditions met"


def test_a_backfill_not_yet_drained_is_not_met(tmp_path: Path) -> None:
    mirror, export, ledger = _world(tmp_path)
    (mirror / "runs" / RUN_A / "closures.jsonl").write_text(_closure(BACKFILL[0]))
    text = _report(mirror, export, ledger, today=TODAY, attest=ATTEST, continuity=CONTINUITY)
    assert "2. backfill drained by scheduled nights (2 cases): not met" in text
    assert "days since the backfill drained: not drained" in text


def test_an_empty_world_reports_zeroes_and_not_met(tmp_path: Path) -> None:
    (tmp_path / "m").mkdir()
    (tmp_path / "e").mkdir()
    text = _report(tmp_path / "m", tmp_path / "e", [], today=TODAY)
    assert "nights started: 0" in text
    assert "alerts: none" in text
    assert "backfill: not yet fixed" in text
    assert "no export was found" in text
    assert text.splitlines()[-1] == "closing rule: 0 of 7 conditions met"
    assert not PATTERN.search(text)


def test_a_damaged_export_is_not_valid(tmp_path: Path) -> None:
    mirror, _, ledger = _world(tmp_path)
    broken = tmp_path / "broken"
    shutil.copytree(EXPORT, broken)
    (broken / "index.json").write_text('{"format": "board/1"}')
    text = _report(mirror, broken, ledger, today=TODAY, attest=ATTEST, continuity=CONTINUITY)
    assert "holds at least one case: not met" in text.split("6. ")[1].splitlines()[0]


def test_main_writes_the_report_and_refuses_a_case_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror, export, _ = _world(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("")
    attest = tmp_path / "attest.json"
    attest.write_text(json.dumps(ATTEST | {"ignored": "x"}))
    monkeypatch.setattr(module, "development_spend", lambda: ["development spend, S4: $0.00"])
    out = tmp_path / "s4-live.txt"
    args = ["--mirror", str(mirror), "--export", str(export), "--ledger", str(ledger)]
    assert module.main([*args, "--attest", str(attest), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert out.read_text() == printed
    assert not PATTERN.search(printed)
    monkeypatch.setattr(module, "report_text", lambda *a, **k: "AAA26LA001\n")
    out.unlink()
    assert module.main([*args, "--out", str(out)]) == 1
    assert not out.exists()
    assert "nothing was printed or written" in capsys.readouterr().err


def test_main_refuses_missing_inputs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = tmp_path / "f"
    folder.mkdir()
    assert (
        module.main(["--mirror", str(tmp_path / "no"), "--export", str(folder), "--ledger", "x"])
        == 1
    )
    assert (
        module.main(["--mirror", str(folder), "--export", str(tmp_path / "no"), "--ledger", "x"])
        == 1
    )
    assert module.main(["--mirror", str(folder), "--export", str(folder), "--ledger", "x"]) == 1
    assert capsys.readouterr().err.count("s4_live_report:") == 3


def test_the_attestation_file_must_be_an_object(tmp_path: Path) -> None:
    from ntsb_probable_cause.errors import ConfigurationError  # noqa: PLC0415

    path = tmp_path / "a.json"
    path.write_text("[1]")
    with pytest.raises(ConfigurationError):
        module._attestations(path)
    assert module._attestations(None) == {}
    assert module._attestations(tmp_path / "missing.json") == {}


def test_development_spend_prints_the_s4_line_or_says_it_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import scripts.stage_spend as spend  # noqa: PLC0415

    from ntsb_probable_cause.errors import ConfigurationError  # noqa: PLC0415

    monkeypatch.setenv("NTSB_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(spend, "stage_branches", lambda stage, repo=Path(): ("s4-x",))
    monkeypatch.setattr(spend, "stage_commits", lambda stage, branches, repo=Path(): frozenset())
    lines = module.development_spend()
    assert lines[1].startswith("S4 spend so far: $0.00")

    def broken(stage: object, repo: Path = Path()) -> tuple[str, ...]:
        raise ConfigurationError("git")

    monkeypatch.setattr(spend, "stage_branches", broken)
    assert "not available here" in module.development_spend()[0]


def _local_export_without_the_store(tmp_path: Path) -> Path:
    """The Mac's export: built with no store, so it holds no closures per night or open cases."""
    local = tmp_path / "local-export"
    shutil.copytree(EXPORT, local)
    index = json.loads((local / "index.json").read_text())
    index["counts"]["closures_per_night"] = {}
    index["counts"]["open_watched"] = 0
    index["counts"]["open_with_docket"] = 0
    (local / "index.json").write_text(json.dumps(index))
    return local


def test_closures_per_night_and_condition_6_read_the_nights_own_export(tmp_path: Path) -> None:
    mirror, export, ledger = _world(tmp_path)
    local = _local_export_without_the_store(tmp_path)
    both = _report(
        mirror,
        local,
        ledger,
        night_export=export,
        today=TODAY,
        attest=ATTEST,
        continuity=CONTINUITY,
    ).splitlines()
    assert "2026-10-09: 2" in both  # from the night's copy, not the empty local build
    assert "cases coded: 5" in both  # the cases section still reads the local export
    assert "open cases watched, counts only: 212" in both  # but its open counts, the night's
    assert "open cases holding a docket, counts only: 187" in both
    assert any(x.startswith("6. the night's export") and x.endswith(": met") for x in both)
    alone = _report(
        mirror, local, ledger, night_export=None, today=TODAY, attest=ATTEST, continuity=CONTINUITY
    )
    assert "no night export was found" in alone
    assert "open cases: no night export was found, so they are not counted here" in alone
    assert "open cases watched" not in alone
    assert "2026-10-09: 2" not in alone
    assert "case: not met" in alone.split("6. ")[1].splitlines()[0]


def _drain_world(tmp_path: Path, edit: Any) -> str:
    mirror, export, ledger = _world(tmp_path)
    edit(mirror)
    return _report(mirror, export, ledger, today=TODAY, attest=ATTEST, continuity=CONTINUITY)


def test_a_backfill_case_with_a_closure_but_no_dates_is_settled(tmp_path: Path) -> None:
    def edit(mirror: Path) -> None:
        both = [_closure(c, first_sent=None, last_returned=None) for c in BACKFILL]
        (mirror / "runs" / RUN_A / "closures.jsonl").write_text("".join(both))

    text = _drain_world(tmp_path, edit)
    assert "2. backfill drained by scheduled nights (2 cases): met" in text
    assert "days since the backfill drained: 3" in text  # the run started on 2026-10-09


def test_a_not_coded_backfill_case_with_no_first_sent_is_settled(tmp_path: Path) -> None:
    def edit(mirror: Path) -> None:
        sent = _closure(BACKFILL[0])
        gone = _closure(BACKFILL[1], outcome="not coded", failure="x", first_sent=None)
        (mirror / "runs" / RUN_A / "closures.jsonl").write_text(sent + gone)

    assert "(2 cases): met" in _drain_world(tmp_path, edit)


def test_a_backfill_case_settled_unreachable_counts_as_settled(tmp_path: Path) -> None:
    def edit(mirror: Path) -> None:
        (mirror / "runs" / RUN_A / "closures.jsonl").write_text(
            _closure(BACKFILL[0], first_sent=None, last_returned=None)
        )
        state = {
            "format": "live-state/1",
            "failures": {},
            "unreachable": {
                BACKFILL[1]: {"mkey": 2, "event_date": "2026-09-20", "closed_on": "2026-09-24"}
            },
        }
        (mirror / "nights" / "state.json").write_text(json.dumps(state))

    text = _drain_world(tmp_path, edit)
    assert "(2 cases): met" in text
    assert "days since the backfill drained: 0" in text  # the last night folder is 2026-10-12
    assert "(upper bound: unreachable cases are dated by the last night in the mirror)" in text


def test_condition_2_says_it_counts_any_night_manifest(tmp_path: Path) -> None:
    text = _text(tmp_path)
    assert "it counts any night manifest, so a hand-started night cannot be told apart" in text


def test_an_attestation_that_is_not_a_date_is_not_met_and_dates_are_printed(
    tmp_path: Path,
) -> None:
    mirror, export, ledger = _world(tmp_path)
    template = dict.fromkeys(ATTEST, "YYYY-MM-DD")
    bad = _report(mirror, export, ledger, today=TODAY, attest=template, continuity=CONTINUITY)
    lines = bad.splitlines()
    assert any(x.startswith("5. ") and x.endswith(": not met") for x in lines)
    assert any(x.startswith("7. ") and x.endswith(": not met") for x in lines)
    assert "attestation value is not a date" in bad
    good = _report(mirror, export, ledger, today=TODAY, attest=ATTEST, continuity=CONTINUITY)
    assert "2026-10-11; 2026-10-11" in good
    assert "Andy's attestation: 2026-10-12" in good


def test_no_upper_bound_note_when_every_case_has_a_closure_record(tmp_path: Path) -> None:
    text = _text(tmp_path)
    assert "days since the backfill drained: 3" in text
    assert "upper bound" not in text
