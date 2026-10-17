"""The dev-400 confirmation's reading (decision 0212). Offline: invented runs on fixture records."""

import json
from pathlib import Path

import pytest
from scripts import memory_confirm_result as cr
from scripts import memory_pilot_result as pr
from scripts.memory_coding_test import CodingCase
from tests.conftest import coded_record, write_cases

from ntsb_probable_cause import fields
from ntsb_probable_cause.memory import snapshots
from ntsb_probable_cause.memory.lessons import Memory
from ntsb_probable_cause.scoring.hypothesis import Hypothesis
from ntsb_probable_cause.settings import Settings

IDS = ("ZZZ10LA001", "ZZZ10LA002", "ZZZ10LA003")
FOLDERS = {
    "tables-a": "ta",
    "counts-a": "ca",
    "counts-b": "cb",
    "cause-lookup": "cl",
}


def _hypothesis(phase: str, event: str) -> Hypothesis:
    return Hypothesis.model_validate(
        {
            "evidence_narrative": "x",
            "occurrence": [{"phase": phase, "event": event, "probability": 0.9}],
            "findings": [],
            "probable_cause": "x",
            "lay_explanation": "x",
            "confidence": 0.5,
            "abstain": False,
            "evidence_used": [],
        }
    )


class ConfirmRuns:
    """A consistent set of the test's runs on disk: the cause lookup answers, the rest fail."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.settings = Settings(data_dir=tmp_path / "data", runs_dir=tmp_path / "runs")
        base = coded_record()
        self.cause = fields.probable_cause(base)
        write_cases(
            self.settings.data_dir / "processed",
            [(i, "2010-05-01", "dev", "LA", {**base, "ntsbNumber": i}) for i in IDS],
        )
        code = fields.occurrence_codes(base)[0]
        right = _hypothesis(code[:3], code[3:])
        snaps = tmp_path / "snaps"
        snaps.mkdir()
        monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", snaps)
        sha = snapshots.sha256_of(
            snapshots.save(Memory(name="pilot-2010-recount", periods=(2009, 2010)), snaps)
        )
        for label, folder in FOLDERS.items():
            condition, repeat, snapshot = cr.LABELS[label]
            spec: dict[str, object] = {"sample": "dev-400", "condition": condition}
            spec |= {"repeat": repeat, "snapshot": snapshot}
            if label != "tables-a":
                spec |= {"source_run": "ta", "snapshot_sha256": sha if snapshot else None}
            if snapshot:
                spec |= {
                    "lookup_k": 5,
                    "lookup_min_applies": 10,
                    "lookup_lessons": {IDS[0]: ["L001", "L002"], IDS[1]: ["L001"], IDS[2]: []},
                }
            if label == "cause-lookup":
                spec |= {"lookup_by": "cause", "apply_run": "apply-run"}
            answer = right if label == "cause-lookup" else None
            rows = [
                CodingCase(
                    case_id=i, hypothesis=answer, failure=None if answer else "cap", cost_usd=0
                )
                for i in IDS
            ]
            path = self.settings.runs_dir / folder
            path.mkdir(parents=True)
            (path / "spec.json").write_text(json.dumps(spec))
            (path / "cases.jsonl").write_text("".join(r.model_dump_json() + "\n" for r in rows))
        self.out = tmp_path / "result.txt"

    def argv(self) -> list[str]:
        pairs = [(f"--{label}", folder) for label, folder in FOLDERS.items()]
        return [*(x for pair in pairs for x in pair), "--out", str(self.out)]

    def edit_spec(self, run: str, **changes: object) -> None:
        path = self.settings.runs_dir / run / "spec.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), **changes}))


def test_the_rule_is_the_pilots_rule_read_on_dev_400() -> None:
    noise = pr.Diff3(top1=0.01, top3=0.01, recall10=0.003)
    assert cr.confirm_rule(pr.Diff3(top1=0.0, top3=0.0, recall10=0.004), noise)[0]
    assert not cr.confirm_rule(pr.Diff3(top1=0.0, top3=0.0, recall10=0.003), noise)[0]
    assert not cr.confirm_rule(pr.Diff3(top1=-0.02, top3=0.0, recall10=0.05), noise)[0]
    assert not cr.confirm_rule(pr.Diff3(top1=0.0, top3=-0.02, recall10=0.05), noise)[0]


def test_main_writes_a_counts_only_reading_that_ends_with_the_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test = ConfirmRuns(tmp_path, monkeypatch)
    assert cr.main(test.argv(), settings=test.settings) == 0
    text = test.out.read_text()
    assert cr.RULE_PAIR in text
    assert "code lookup" not in text
    assert "cause lookup: 3 cases sent; mean 1.00 lessons a case; 1 with none" in text
    assert "cause lookup's apply run: apply-run" in text
    assert not any(i in text for i in IDS)
    assert test.cause is not None
    assert test.cause not in text
    # The fixture's answers flag no findings, so there is no finding gain to pass on.
    assert text.strip().splitlines()[-1] == "rule on dev-400: FAIL"
    assert "not passed: finding recall@10" in text


@pytest.mark.parametrize(
    "case",
    [
        ("ca", {"source_run": "other"}, "counts-a"),
        ("cb", {"repeat": "a"}, "counts-b"),
        ("cl", {"snapshot": "pilot-2010"}, "cause-lookup"),
        ("cl", {"snapshot_sha256": "0" * 64}, "cause-lookup"),
        ("cl", {"lookup_k": 3}, "K=5"),
        ("cl", {"lookup_min_applies": 5}, "floor 10"),
        ("ca", {"sample": "dev-steer-400"}, "not a dev-400 run"),
        ("cl", {"condition": "lookup"}, "cause-lookup run expected"),
        ("cl", {"lookup_by": None}, "names no apply run"),
        ("cl", {"apply_run": ""}, "names no apply run"),
        ("cl", {"model": "another/model"}, "cause-lookup differs from tables-a in model"),
        ("cb", {"guidance_sha256": "0" * 12}, "counts-b differs from tables-a in guidance"),
    ],
)
def test_main_refuses_runs_that_do_not_belong_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: tuple[str, dict[str, object], str],
) -> None:
    run, changes, label = case
    test = ConfirmRuns(tmp_path, monkeypatch)
    test.edit_spec(run, **changes)
    assert cr.main(test.argv(), settings=test.settings) == 1
    out = capsys.readouterr().out
    assert out.startswith("refused: ")
    assert label in out
    assert not test.out.exists()
