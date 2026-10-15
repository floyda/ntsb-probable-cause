"""The pilot's reading and its registered stop rule (decision 0204). Made-up numbers; offline."""

import json
from pathlib import Path

import pytest
from scripts import memory_pilot_result as pr
from scripts.memory_coding_test import CodingCase
from tests.conftest import coded_record, write_cases

from ntsb_probable_cause import fields
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import claude, snapshots
from ntsb_probable_cause.memory.lessons import Memory
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis
from ntsb_probable_cause.settings import Settings


def test_a_finding_gain_beyond_the_noise_with_no_harm_passes() -> None:
    noise = pr.Diff3(top1=-0.01, top3=0.02, recall10=0.015)
    ok, reasons = pr.stop_rule(pr.Diff3(top1=0.0, top3=-0.01, recall10=0.03), noise)
    assert ok, reasons


def test_a_finding_gain_inside_the_noise_does_not_pass() -> None:
    noise = pr.Diff3(top1=0.0, top3=0.0, recall10=0.02)
    ok, _ = pr.stop_rule(pr.Diff3(top1=0.05, top3=0.05, recall10=0.02), noise)
    assert not ok


def test_harm_beyond_the_noise_on_top1_fails_even_with_a_finding_gain() -> None:
    noise = pr.Diff3(top1=0.01, top3=0.01, recall10=0.01)
    ok, reasons = pr.stop_rule(pr.Diff3(top1=-0.02, top3=0.0, recall10=0.05), noise)
    assert not ok
    assert any("top-1" in r for r in reasons)


def test_a_failed_case_counts_as_wrong() -> None:
    got = pr.measure_failed(flags_findings=True)
    assert (got.top1, got.top3, got.recall10) == (False, False, 0.0)
    assert pr.measure_failed(flags_findings=False).recall10 is None


def _hypothesis(phase: str, event: str) -> Hypothesis:
    return Hypothesis.model_validate(
        {
            "evidence_narrative": "x",
            "occurrence": [{"phase": phase, "event": event, "probability": 0.6}],
            "findings": [],
            "probable_cause": "x",
            "lay_explanation": "x",
            "confidence": 0.6,
            "abstain": False,
            "evidence_used": [],
        }
    )


def test_measures_scores_answered_cases_and_counts_failed_ones_as_wrong() -> None:
    tables = load_tables()
    code = tables.compose_occurrence("552", "230")
    verdicts = {
        "A": Verdict(
            probable_cause="c",
            occurrence_codes=(code,),
            finding_codes=(),
            finding_codes_in_cause=(),
        ),
        "B": Verdict(
            probable_cause="c",
            occurrence_codes=(code,),
            finding_codes=("0206301544",),
            finding_codes_in_cause=("0206301544",),
        ),
    }
    rows = [
        CodingCase(case_id="A", hypothesis=_hypothesis("552", "230"), failure=None, cost_usd=0.0),
        CodingCase(case_id="B", hypothesis=None, failure="cap", cost_usd=0.0),
    ]
    got = pr.measures(rows, verdicts, tables, frozenset({code}))
    assert (got["A"].top1, got["A"].top3, got["A"].recall10) == (True, True, None)
    assert (got["B"].top1, got["B"].top3, got["B"].recall10) == (False, False, 0.0)


def test_paired_rows_use_only_cases_in_both_runs() -> None:
    a = {
        "1": pr.CaseMeasures(True, True, 0.5),
        "2": pr.CaseMeasures(False, True, None),
        "3": pr.CaseMeasures(True, True, 1.0),
    }
    b = {"1": pr.CaseMeasures(True, False, 1.0), "2": pr.CaseMeasures(True, True, 0.0)}
    diff, text = pr.paired(b, a)
    assert diff.top1 == pytest.approx(0.5)
    assert diff.top3 == pytest.approx(-0.5)
    assert diff.recall10 == pytest.approx(0.5)  # only case 1 has a recall in both
    assert "n=2" in text
    assert "n=1" in text


def test_learner_refusals_are_counted_by_category(tmp_path: Path) -> None:
    def row(key: str, stop: str | None, category: str | None, text: str | None) -> str:
        reply = claude.Reply(
            key=key,
            role="apply",
            model="m",
            effort="low",
            batch=True,
            text=text,
            stop_reason=stop,
            stop_category=category,
            error=None,
            input_tokens=1,
            output_tokens=1,
            cache_write_tokens=0,
            cache_read_tokens=0,
            cost_usd=0.0,
        )
        return reply.model_dump_json()

    folder = tmp_path / "learn"
    folder.mkdir()
    (folder / "calls.jsonl").write_text(
        "\n".join(
            [
                row("1", "refusal", "cyber", None),
                row("2", "refusal", None, None),
                row("3", "refusal", "cyber", None),
                row("4", "max_tokens", None, None),
                row("5", "end_turn", None, "{}"),
            ]
        )
        + "\n"
    )
    assert pr.refusals_by_category([folder]) == {"cyber": 2, "none": 1}
    assert json.loads(json.dumps(pr.refusals_by_category([folder])))


# Boundaries of the stop rule (decision 0204 item 5). ---------------------------------------


def test_top3_harm_beyond_the_noise_fails() -> None:
    noise = pr.Diff3(top1=0.0, top3=0.01, recall10=0.01)
    ok, reasons = pr.stop_rule(pr.Diff3(top1=0.0, top3=-0.02, recall10=0.05), noise)
    assert not ok
    assert any("top-3" in r for r in reasons)


def test_a_finding_gain_equal_to_the_noise_fails() -> None:
    noise = pr.Diff3(top1=0.0, top3=0.0, recall10=-0.02)
    ok, _ = pr.stop_rule(pr.Diff3(top1=0.0, top3=0.0, recall10=0.02), noise)
    assert not ok


def test_a_fall_exactly_equal_to_the_noise_passes() -> None:
    noise = pr.Diff3(top1=0.02, top3=0.02, recall10=0.01)
    ok, reasons = pr.stop_rule(pr.Diff3(top1=-0.02, top3=-0.02, recall10=0.03), noise)
    assert ok, reasons


# Wiring: load_run, report, main. -----------------------------------------------------------

SAMPLE = "dev-steer-400"


def _write_run(root: Path, name: str, rows: list[CodingCase], **spec: object) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    body = {"sample": SAMPLE, "condition": "tables", **spec}
    (folder / "spec.json").write_text(json.dumps(body))
    (folder / "cases.jsonl").write_text("".join(row.model_dump_json() + "\n" for row in rows))
    return folder


def test_load_run_refuses_another_sample(tmp_path: Path) -> None:
    folder = _write_run(tmp_path, "r-dev-400", [], sample="dev-400")
    with pytest.raises(ConfigurationError, match="dev-steer-400"):
        pr.load_run(folder, "tables")


def test_load_run_refuses_the_wrong_condition_and_a_memory_run_with_no_snapshot(
    tmp_path: Path,
) -> None:
    folder = _write_run(tmp_path, "r1", [], condition="counts")
    with pytest.raises(ConfigurationError, match="not the tables run"):
        pr.load_run(folder, "tables")
    memory = _write_run(tmp_path, "r2", [], condition="memory")
    with pytest.raises(ConfigurationError, match="no snapshot"):
        pr.load_run(memory, "memory")


def test_a_live_folder_is_fenced_before_anything_is_read(tmp_path: Path) -> None:
    folder = tmp_path / "20261015T000000Z-abc-live-C"
    folder.mkdir()  # no spec.json and no cases.jsonl: a read would raise ConfigurationError
    with pytest.raises(SystemExit, match="live run"):
        pr.load_run(folder, "tables")
    (folder / "spec.json").write_text(json.dumps({"sample": "live"}))
    with pytest.raises(SystemExit, match="live run"):
        pr.load_run(folder, "tables")


def test_learner_refusals_fence_live_folders_and_refuse_a_missing_one(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match=r"no calls\.jsonl"):
        pr.refusals_by_category([tmp_path / "typo"])
    live = tmp_path / "x-live-y"
    live.mkdir()
    (live / "run.jsonl").write_text(json.dumps({"sample": "live"}))
    with pytest.raises(SystemExit):
        pr.refusals_by_category([live])


def _case(case_id: str) -> CodingCase:
    return CodingCase(case_id=case_id, hypothesis=None, failure="cap", cost_usd=0.0)


def test_runs_with_different_cases_are_refused_with_counts_only(tmp_path: Path) -> None:
    one = pr.load_run(_write_run(tmp_path, "a", [_case("SECRET1"), _case("SECRET2")]), "tables")
    two = pr.load_run(_write_run(tmp_path, "b", [_case("SECRET1")]), "tables")
    with pytest.raises(ConfigurationError) as caught:
        pr.refuse_unequal_cases({"tables-a": one, "tables-b": two})
    assert "SECRET" not in str(caught.value)
    assert "2" in str(caught.value)


def _scored(top1: bool, recall: float) -> dict[str, pr.CaseMeasures]:
    return {str(i): pr.CaseMeasures(top1, top1, recall) for i in range(10)}


def test_the_stop_rule_line_names_the_last_memory_run_and_follows_it(tmp_path: Path) -> None:
    names = ["tables-a", "tables-b", "counts-a", "counts-b", "memory-1", "memory-2"]
    runs = {n: pr.RunRead(tmp_path / n, {"snapshot": None}, ()) for n in names}
    base = _scored(False, 0.0)

    def verdict(second_recall: float) -> str:
        scored = {
            "tables-a": base,
            "tables-b": base,
            "counts-a": base,
            "counts-b": base,
            "memory-1": _scored(False, 1.0),  # would pass on its own
            "memory-2": _scored(False, second_recall),
        }
        text = pr.report(
            runs,
            scored,
            memory_ids=["memory-1", "memory-2"],
            learn_runs=[],
            snapshot_dir=tmp_path,
            agreement=tmp_path / "none.txt",
        )
        return text.splitlines()[-1]

    assert verdict(0.0) == "stop rule on the last memory run (memory-2): FAIL"
    assert verdict(1.0) == "stop rule on the last memory run (memory-2): PASS"


IDS = ("ZZZ09LA001", "ZZZ09LA002", "ZZZ09LA003")


class Pilot:
    """A consistent set of the pilot's runs, a learner folder and two snapshots, on disk."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.settings = Settings(data_dir=tmp_path / "data", runs_dir=tmp_path / "runs")
        base = coded_record()
        self.cause = fields.probable_cause(base)
        write_cases(
            self.settings.data_dir / "processed",
            [(i, "2009-05-01", "dev", "LA", {**base, "ntsbNumber": i}) for i in IDS],
        )
        code = fields.occurrence_codes(base)[0]
        right = _hypothesis(code[:3], code[3:])
        snaps = tmp_path / "snaps"
        snaps.mkdir()
        monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", snaps)
        # The stamp is load_checked's own concern (tests above); here it reads the file.
        monkeypatch.setattr(snapshots, "load_checked", snapshots.load)
        sha = {}
        for name, periods in (("s1", (2009,)), ("s2", (2009, 2010))):
            sha[name] = snapshots.sha256_of(
                snapshots.save(Memory(name=name, periods=periods), snaps)
            )
        runs = self.settings.runs_dir
        for name, cond, repeat, answer, snapshot in (
            ("ta", "tables", "a", None, None),
            ("tb", "tables", "b", None, None),
            ("ca", "counts", "a", None, None),
            ("cb", "counts", "b", None, None),
            ("m1", "memory", None, right, "s1"),
            ("m2", "memory", None, right, "s2"),
        ):
            spec: dict[str, object] = {"condition": cond, "repeat": repeat}
            if cond != "tables":
                spec |= {
                    "source_run": "ta",
                    "snapshot": snapshot,
                    "snapshot_sha256": sha[snapshot] if snapshot else None,
                }
            rows = [
                CodingCase(
                    case_id=i, hypothesis=answer, failure=None if answer else "cap", cost_usd=0.0
                )
                for i in IDS
            ]
            _write_run(runs, name, rows, **spec)
        learn = runs / "learn"
        learn.mkdir()
        (learn / "calls.jsonl").write_text("")
        self.out = tmp_path / "result.txt"
        self.agreement = tmp_path / "none.txt"

    def argv(self, memory: tuple[str, ...] = ("m1", "m2")) -> list[str]:
        return [
            *("--tables-a", "ta", "--tables-b", "tb", "--counts-a", "ca", "--counts-b", "cb"),
            *("--memory", *memory, "--learn-runs", "learn"),
            *("--agreement", str(self.agreement), "--out", str(self.out)),
        ]

    def edit_spec(self, run: str, **changes: object) -> None:
        path = self.settings.runs_dir / run / "spec.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), **changes}))

    def main(self, argv: list[str]) -> int:
        return pr.main(argv, settings=self.settings)


def test_main_writes_a_counts_only_reading_that_ends_with_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pilot = Pilot(tmp_path, monkeypatch)
    assert pilot.main(pilot.argv()) == 0
    text = pilot.out.read_text()
    assert not any(i in text for i in IDS)
    assert pilot.cause is not None
    assert pilot.cause not in text
    last = text.strip().splitlines()[-1]
    assert last.startswith("stop rule on the last memory run (memory-2): ")


def test_main_refuses_missing_cases_without_naming_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pilot = Pilot(tmp_path, monkeypatch)
    for name in ("ta", "tb", "ca", "cb", "m1", "m2"):
        cases = pilot.settings.runs_dir / name / "cases.jsonl"
        cases.write_text(cases.read_text().replace("ZZZ09LA003", "ZZZ09LA999"))
    assert pilot.main(pilot.argv()) == 1
    out = capsys.readouterr().out
    assert "refused:" in out
    assert "ZZZ09LA999" not in out


@pytest.mark.parametrize(
    "case",
    [
        ("ca", {"source_run": "tb"}, "counts-a"),
        ("cb", {"source_run": None}, "counts-b"),
        ("m1", {"source_run": "other"}, "memory-1"),
        ("ta", {"repeat": "b"}, "tables-a"),
        ("tb", {"repeat": None}, "tables-b"),
        ("cb", {"repeat": "a"}, "counts-b"),
        ("m2", {"repeat": "a"}, "memory-2"),
        ("m2", {"snapshot_sha256": "0" * 64}, "memory-2"),
    ],
)
def test_main_refuses_runs_that_do_not_belong_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: tuple[str, dict[str, object], str],
) -> None:
    # Final review I3: sources, repeats and snapshot hashes tie the runs together.
    run, changes, label = case
    pilot = Pilot(tmp_path, monkeypatch)
    pilot.edit_spec(run, **changes)
    assert pilot.main(pilot.argv()) == 1
    out = capsys.readouterr().out
    assert out.startswith("refused: ")
    assert label in out
    assert not any(i in out for i in IDS)
    assert not pilot.out.exists()


def test_main_refuses_memory_runs_out_of_period_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pilot = Pilot(tmp_path, monkeypatch)
    assert pilot.main(pilot.argv(memory=("m2", "m1"))) == 1
    out = capsys.readouterr().out
    assert "memory-2" in out
    assert "period" in out
    assert pilot.main(pilot.argv(memory=("m1", "m1"))) == 1


def test_the_learner_runs_are_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pilot = Pilot(tmp_path, monkeypatch)
    argv = pilot.argv()
    at = argv.index("--learn-runs")
    with pytest.raises(SystemExit) as stopped:
        pilot.main(argv[:at] + argv[at + 2 :])
    assert stopped.value.code == 2
    with pytest.raises(SystemExit):
        pilot.main([*argv[: at + 1], *argv[at + 2 :]])
