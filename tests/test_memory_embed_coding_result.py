"""Decision 0214's steering reading: four embed-lookup runs, one winner. Offline; invented runs."""

import json
import re
import shutil
import textwrap
from pathlib import Path

import pytest
from scripts import memory_embed
from scripts import memory_embed_coding_result as cr
from scripts import memory_pilot_result as pr
from tests.test_memory_embed_result import IDS, EmbedRuns

from ntsb_probable_cause import gitinfo

LARGE = "openai/text-embedding-3-large"
NOISE = pr.Diff3(top1=0.002, top3=0.007, recall10=-0.003)


def _diff(recall10: float, top1: float = 0.0, top3: float = 0.0) -> pr.Diff3:
    return pr.Diff3(top1=top1, top3=top3, recall10=recall10)


def test_the_largest_passing_finding_gain_goes_forward() -> None:
    results = {
        LARGE: (True, _diff(0.010)),
        f"pick:{LARGE}": (True, _diff(0.030)),
        f"fit:{LARGE}": (False, _diff(0.050)),  # failed the rule: its larger gain does not count
        f"fill:{LARGE}": (True, _diff(0.020)),
    }
    assert cr.selection_rule(results) == f"pick:{LARGE}"


def test_an_exact_tie_goes_to_the_earlier_in_the_registered_order() -> None:
    results = {f"fill:{LARGE}": (True, _diff(0.02)), f"fit:{LARGE}": (True, _diff(0.02))}
    assert cr.selection_rule(results) == f"fit:{LARGE}"
    assert (LARGE, f"pick:{LARGE}", f"fit:{LARGE}", f"fill:{LARGE}") == cr.ORDER


def test_none_passing_gives_none() -> None:
    assert cr.selection_rule({LARGE: (False, _diff(0.1))}) is None


def test_selection_rule_docstring_matches_the_registration() -> None:
    text = Path("docs/rounds/memory-embed-coding.md").read_text()
    section = text.split("## 6. The selection rule, word for word", 1)[1]
    block = re.search(r"```text\n(.*?)\n```", section, re.DOTALL)
    assert block is not None
    assert textwrap.dedent(cr.selection_rule.__doc__ or "").strip() == block.group(1).strip()


def test_the_output_is_what_dev_seal_400_reads_the_winner_from() -> None:
    assert cr.OUT == memory_embed.STEERING_READING


class FourRuns(EmbedRuns):
    """``EmbedRuns`` with its embed lookup copied once per decision 0214 candidate."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__(tmp_path, monkeypatch)
        self.embeds = []
        for method in ("embedding", "pick", "fit", "fill"):
            name = f"el-{method}"
            shutil.copytree(self.settings.runs_dir / "el", self.settings.runs_dir / name)
            self.edit_spec(
                name,
                lookup_by=method,
                embedding_model=LARGE,
                choices_run=f"choices-{method}",
            )
            self.embeds.append(name)

    def four(self, embeds: list[str] | None = None) -> list[str]:
        base = [x for label in cr.BASE for x in (f"--{label}", f"{self.folders[label]}")]
        return [*base, "--embed-lookups", *(embeds or self.embeds), "--out", str(self.out)]

    @property
    def folders(self) -> dict[str, str]:
        return {"tables-a": "ta", "counts-a": "ca", "counts-b": "cb", "cause-lookup": "cl"}


def test_main_reads_four_candidates_and_names_the_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test = FourRuns(tmp_path, monkeypatch)
    assert cr.main(test.four(), settings=test.settings) == 0
    text = test.out.read_text()
    for name in cr.ORDER:
        assert f"{name} - cause lookup, read by 0213's rule" in text
    assert "choices run: choices-fill" in text
    assert not any(i in text for i in IDS)
    # The fixture's answers flag no findings, so no candidate has a finding gain.
    assert text.strip().splitlines()[-1] == "winner: none"


@pytest.mark.parametrize("drop", [0, 3])
def test_fewer_than_the_four_candidates_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], drop: int
) -> None:
    test = FourRuns(tmp_path, monkeypatch)
    embeds = [e for n, e in enumerate(test.embeds) if n != drop]
    assert cr.main(test.four(embeds), settings=test.settings) == 1
    assert "four candidates" in capsys.readouterr().out
    assert not test.out.exists()


def test_a_candidate_named_twice_or_of_another_model_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    test = FourRuns(tmp_path, monkeypatch)
    assert cr.main(test.four([*test.embeds, test.embeds[0]]), settings=test.settings) == 1
    assert "four candidates" in capsys.readouterr().out
    test.edit_spec("el-fit", embedding_model="qwen/qwen3-embedding-8b")
    assert cr.main(test.four(), settings=test.settings) == 1
    assert "four candidates" in capsys.readouterr().out


def test_an_embed_lookup_that_does_not_belong_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    test = FourRuns(tmp_path, monkeypatch)
    test.edit_spec("el-fill", source_run="another-tables-run")
    assert cr.main(test.four(), settings=test.settings) == 1
    assert "was not made from the tables-a run" in capsys.readouterr().out


def test_the_reading_is_refused_until_the_registration_is_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    test = FourRuns(tmp_path, monkeypatch)
    monkeypatch.setattr(
        gitinfo, "is_committed", lambda path, repo=Path(): path.name != "memory-embed-coding.md"
    )
    assert cr.main(test.four(), settings=test.settings) == 1
    assert "memory-embed-coding.md is not committed" in capsys.readouterr().out


def test_spec_files_of_the_copies_differ_only_in_the_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test = FourRuns(tmp_path, monkeypatch)
    specs = [
        json.loads((test.settings.runs_dir / name / "spec.json").read_text())
        for name in test.embeds
    ]
    assert {s["lookup_by"] for s in specs} == {"embedding", "pick", "fit", "fill"}
