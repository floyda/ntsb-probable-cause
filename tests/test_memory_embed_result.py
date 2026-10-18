"""The embedding lookup's reading and rule (decision 0213). Offline: invented runs on fixtures."""

import json
import re
import textwrap
from pathlib import Path

import pytest
from scripts import memory_embed
from scripts import memory_embed_result as er
from scripts import memory_pilot_result as pr
from scripts.memory_coding_test import CodingCase
from tests.conftest import coded_record, write_cases

from ntsb_probable_cause import fields, gitinfo
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
    "embed-lookup": "el",
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


class EmbedRuns:
    """A consistent set of runs on disk: the embed lookup answers right, the others fail."""

    def __init__(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sample: str = "dev-steer-400"
    ) -> None:
        monkeypatch.setattr(gitinfo, "is_committed", lambda path, repo=Path(): True)
        self.settings = Settings(data_dir=tmp_path / "data", runs_dir=tmp_path / "runs")
        self.sample = sample
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
            condition, repeat, snapshot = er.LABELS[label]
            spec: dict[str, object] = {"sample": sample, "condition": condition}
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
            if label == "embed-lookup":
                spec |= {
                    "lookup_by": "embedding",
                    "choices_run": "choices-run",
                    "embedding_model": "qwen/qwen3-embedding-8b",
                }
            answer = right if label == "embed-lookup" else None
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
        sample = [] if self.sample == "dev-steer-400" else ["--sample", self.sample]
        return [*(x for pair in pairs for x in pair), *sample, "--out", str(self.out)]

    def edit_spec(self, run: str, **changes: object) -> None:
        path = self.settings.runs_dir / run / "spec.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), **changes}))


def test_the_rule_reads_embed_minus_cause_lookup_against_the_noise() -> None:
    noise = pr.Diff3(top1=0.01, top3=0.01, recall10=-0.003)
    assert er.embed_rule(pr.Diff3(top1=0.0, top3=0.0, recall10=0.004), noise)[0]
    assert not er.embed_rule(pr.Diff3(top1=0.0, top3=0.0, recall10=0.003), noise)[0]
    assert not er.embed_rule(pr.Diff3(top1=-0.02, top3=0.0, recall10=0.05), noise)[0]
    assert not er.embed_rule(pr.Diff3(top1=0.0, top3=-0.02, recall10=0.05), noise)[0]


def test_rule_docstring_matches_the_registration() -> None:
    text = Path("docs/rounds/memory-embed-lookup.md").read_text()
    section = text.split("## 6. The rule, word for word", 1)[1]
    block = re.search(r"```text\n(.*?)\n```", section, re.DOTALL)
    assert block is not None
    assert textwrap.dedent(er.embed_rule.__doc__ or "").strip() == block.group(1).strip()


def test_output_path_by_sample() -> None:
    assert er.OUTS["dev-steer-400"] == Path("docs/results/memory-embed-lookup-dev.txt")
    assert er.OUTS["dev-seal-400"] == Path("docs/results/memory-embed-confirm-devseal.txt")


def test_main_writes_a_counts_only_reading_that_ends_with_the_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test = EmbedRuns(tmp_path, monkeypatch)
    assert er.main(test.argv(), settings=test.settings) == 0
    text = test.out.read_text()
    assert er.RULE_PAIR in text
    assert er.NOISE_PAIR in text
    assert "embed lookup - counts(a)" in text
    assert "embed lookup: 3 cases sent; mean 1.00 lessons a case; 1 with none" in text
    assert "embed lookup's choices run: choices-run (qwen/qwen3-embedding-8b, embedding)" in text
    assert not any(i in text for i in IDS)
    assert test.cause is not None
    assert test.cause not in text
    # The fixture's answers flag no findings, so there is no finding gain to pass on.
    assert text.strip().splitlines()[-1] == "rule on dev-steer-400: FAIL"
    assert "not passed: finding recall@10" in text


def _steering_winner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, model: str) -> None:
    path = tmp_path / "memory-coverage-dev.txt"
    path.write_text(f"lesson coverage ...\nwinner: {model}\n")
    monkeypatch.setattr(memory_embed, "STEERING_READING", path)


def test_dev_seal_reading_refuses_a_model_other_than_the_steering_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    test = EmbedRuns(tmp_path, monkeypatch, sample="dev-seal-400")
    _steering_winner(tmp_path, monkeypatch, "openai/text-embedding-3-small")
    assert er.main(test.argv(), settings=test.settings) == 1
    assert "only the steering winner openai/text-embedding-3-small" in capsys.readouterr().out
    assert not test.out.exists()


def test_main_reads_dev_seal_400_once_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test = EmbedRuns(tmp_path, monkeypatch, sample="dev-seal-400")
    _steering_winner(tmp_path, monkeypatch, "qwen/qwen3-embedding-8b")
    assert er.main(test.argv(), settings=test.settings) == 0
    assert test.out.read_text().strip().splitlines()[-1] == "rule on dev-seal-400: FAIL"
    monkeypatch.setattr(gitinfo, "is_committed", lambda path, repo=Path(): False)
    test.out.unlink()
    assert er.main(test.argv(), settings=test.settings) == 1
    assert not test.out.exists()


@pytest.mark.parametrize(
    "case",
    [
        ("el", {"source_run": "other"}, "embed-lookup was not made from the tables-a run"),
        ("el", {"repeat": "a"}, "embed-lookup is not the repeat"),
        ("el", {"snapshot": "pilot-2010"}, "embed-lookup does not name the snapshot"),
        ("el", {"snapshot_sha256": "0" * 64}, "embed-lookup's snapshot hash"),
        ("el", {"lookup_k": 3}, "K=5"),
        ("el", {"lookup_min_applies": 5}, "floor 10"),
        ("el", {"lookup_by": "cause"}, "names no choices run"),
        ("el", {"choices_run": ""}, "names no choices run"),
        ("el", {"model": "another/model"}, "embed-lookup differs from tables-a in model"),
        ("el", {"condition": "cause-lookup"}, "embed-lookup run expected"),
        ("cl", {"apply_run": ""}, "names no apply run"),
        ("ca", {"sample": "dev-seal-400"}, "not a dev-steer-400 run"),
    ],
)
def test_main_refuses_runs_that_do_not_belong_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: tuple[str, dict[str, object], str],
) -> None:
    run, changes, label = case
    test = EmbedRuns(tmp_path, monkeypatch)
    test.edit_spec(run, **changes)
    assert er.main(test.argv(), settings=test.settings) == 1
    out = capsys.readouterr().out
    assert out.startswith("refused: ")
    assert label in out
    assert not test.out.exists()


def test_dev_seal_reading_refuses_the_lookup_alone_when_the_picking_call_won(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    test = EmbedRuns(tmp_path, monkeypatch, sample="dev-seal-400")
    _steering_winner(tmp_path, monkeypatch, "pick:qwen/qwen3-embedding-8b")
    assert er.main(test.argv(), settings=test.settings) == 1
    assert "the picking call" in capsys.readouterr().out
    test.edit_spec("el", lookup_by="pick")
    assert er.main(test.argv(), settings=test.settings) == 0
