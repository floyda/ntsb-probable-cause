"""scoring/checkpass.py: the ordering check as a post-pass (decision 0096; plan W2)."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest
import respx
from tests.test_occurrence_misses import _case, _step

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.model.client import RecordingFakeClient, Usage
from ntsb_probable_cause.model.typesafe import TypeSafeClient
from ntsb_probable_cause.scoring import checkpass, ordering
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import PoolCase, build
from ntsb_probable_cause.scoring.hypothesis import FindingGuess
from ntsb_probable_cause.scoring.records import (
    CaseResult,
    RunRecord,
    StepRecord,
    read_jsonl,
    write_jsonl,
)

NOW = datetime(2026, 9, 28, tzinfo=UTC)
LOC, STALL = "452240", "452241"
STATS = build(
    [PoolCase(2012, "Maneuvering", (LOC, STALL))] * 30
    + [PoolCase(2016, "Maneuvering", (STALL, LOC))] * 5,
    built_from="test",
)


def _source(
    runs: Path,
    run_id: str = "20260926T000000-abc1234-dev-400-B",
    *,
    finished: datetime | None = NOW,
) -> Path:
    folder = runs / run_id
    folder.mkdir(parents=True)
    record = RunRecord(
        run_id=run_id,
        sample="dev-400",
        arm="B",
        exclusions=(),
        includes=(),
        prompt_version="s1-v5",
        model="openai/gpt-6-luna",
        price_variant="batch",
        cap_usd=0.05,
        budget_usd=40.0,
        commit_sha="abc1234",
        dirty=False,
        started=NOW,
        finished=finished,
        cases=2,
        cost_usd=1.0,
    )
    write_jsonl(folder / "run.jsonl", [record])
    write_jsonl(
        folder / "cases.jsonl",
        [
            _case("C1", (LOC, STALL), (STALL,)),  # stall first; LOC is defining
            _case("C2", (LOC, STALL), (LOC,), abstain=True),  # abstained: unchanged
        ],
    )
    return folder


def test_the_rule_pass_writes_a_derived_run_with_a_check_step(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    source = _source(runs)
    record = checkpass.check_run(
        source,
        "rule",
        checkpass.rule_checker(STATS),
        runs_dir=runs,
        groups={"C1": "Maneuvering", "C2": "Maneuvering"},
        seen_pairs=frozenset({LOC}),
        commit=("def5678", False),
        now=lambda: NOW,
    )
    assert record.run_id == "20260926T000000-abc1234-dev-400-B-check-rule"
    assert record.cost_usd == 0.0
    assert record.prompt_version == "s1-v5+check-rule"
    cases = {c.case_id: c for c in read_jsonl(runs / record.run_id / "cases.jsonl", CaseResult)}
    step = cases["C1"].steps[-1]
    assert step.tool == checkpass.CHECK_TOOL
    assert next(g.phase + g.event for g in step.hypothesis.occurrence) == LOC
    assert step.arguments["toward_more_common"] is True  # stall (5) -> loss of control (30), 0101
    assert cases["C1"].scores is not None
    assert cases["C1"].scores.occurrence_top1
    assert len(cases["C2"].steps) == 1


def test_a_derived_run_is_refused_twice_and_a_held_out_source_is_refused(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    source = _source(runs)

    def run(folder: Path) -> RunRecord:
        return checkpass.check_run(
            folder,
            "rule",
            checkpass.rule_checker(STATS),
            runs_dir=runs,
            groups={},
            seen_pairs=frozenset(),
            commit=("d", False),
            now=lambda: NOW,
        )

    run(source)
    with pytest.raises(ConfigurationError, match="exists"):
        run(source)
    held = _source(runs, "20260926T000000-abc1234-heldout-400-B")
    with pytest.raises(ConfigurationError, match="development"):
        run(held)


def test_the_luna_checker_sends_only_the_check_text_and_retries_a_bad_ranking() -> None:
    client = RecordingFakeClient(
        [json.dumps({"ranking": ["111111"]}), json.dumps({"ranking": [LOC, STALL]})]
    )
    checker = checkpass.luna_checker(client, STATS, load_tables())
    hypothesis = _case("C1", (LOC,), (STALL,)).steps[-1].hypothesis
    outcome = checker(hypothesis, "Maneuvering")
    assert outcome.ranking == (LOC, STALL)
    assert len(client.systems) == 2
    assert "rejected" in client.systems[1]
    assert client.payloads[0].text == "{}"  # everything is in the system text; no evidence payload
    assert client.settings[0].price_variant == "standard"


def test_the_luna_checker_leaves_the_answer_unchanged_when_both_replies_fail() -> None:
    client = RecordingFakeClient(["not json", "still not json"])
    checker = checkpass.luna_checker(client, STATS, load_tables())
    hypothesis = _case("C1", (LOC,), (STALL,)).steps[-1].hypothesis
    outcome = checker(hypothesis, "Maneuvering")
    assert outcome.ranking == (STALL,)
    assert outcome.note.startswith("check failed")


def _run(folder: Path, runs: Path) -> RunRecord:
    return checkpass.check_run(
        folder,
        "rule",
        checkpass.rule_checker(STATS),
        runs_dir=runs,
        groups={},
        seen_pairs=frozenset(),
        commit=("d", False),
        now=lambda: NOW,
    )


def test_check_run_refuses_a_source_that_has_not_finished(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    source = _source(runs, finished=None)
    with pytest.raises(ConfigurationError, match="finished"):
        _run(source, runs)


def test_check_run_refuses_a_source_that_is_itself_a_derived_check_run(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    source = _source(runs, "20260926T000000-abc1234-dev-400-B-check-rule")
    with pytest.raises(ConfigurationError, match="stacked"):
        _run(source, runs)


def test_the_suffix_names_the_statistics_unless_they_are_s27s() -> None:
    """Every S2.7 check keeps ``+check-<way>``; another file is named after the way."""
    assert checkpass.STATS_DEFAULT == "s27"
    assert checkpass.TOOLS_STATS == "s3"
    for way in checkpass.CHECK_WAYS:
        assert checkpass.suffix(way) == f"+check-{way}"
        assert checkpass.suffix(way, "s27") == f"+check-{way}"
        assert checkpass.suffix(way, "s3") == f"+check-{way}-s3"


@pytest.mark.parametrize(("stats", "suffix"), [("s27", "+check-rule"), ("s3", "+check-rule-s3")])
def test_the_derived_prompt_version_records_the_statistics_read(
    tmp_path: Path, stats: str, suffix: str
) -> None:
    runs = tmp_path / "runs"
    source = _source(runs)
    record = checkpass.check_run(
        source,
        "rule",
        checkpass.rule_checker(STATS),
        runs_dir=runs,
        groups={},
        seen_pairs=frozenset(),
        commit=("d", False),
        now=lambda: NOW,
        stats=stats,  # type: ignore[arg-type]
    )
    assert record.prompt_version == f"s1-v5{suffix}"
    assert record.run_id == "20260926T000000-abc1234-dev-400-B-check-rule"  # the id is the way's


def _tools_source(runs: Path) -> Path:
    """A finished arm B tool post-pass (``agent/armb.py`` writes ``+tools-s3+p<12>``)."""
    run_id = "20260926T000000-abc1234-dev-400-B-tools"
    folder = _source(runs, run_id)
    (record,) = read_jsonl(folder / "run.jsonl", RunRecord)
    tools = record.model_copy(update={"prompt_version": "s1-v6+gabc+tools-s3+p0123456789ab"})
    (folder / "run.jsonl").write_text(tools.model_dump_json() + "\n")  # replaced, not appended
    return folder


def test_a_tool_post_pass_is_checked_with_s3s_statistics_only(tmp_path: Path) -> None:
    """Decision 0129 item 4: the tools counted in S3's file, so the check over their answer must
    too. S2.7's default is refused before anything is written; ``s3`` runs and says so."""
    runs = tmp_path / "runs"
    source = _tools_source(runs)
    before = {p.name for p in runs.iterdir()}
    for refused in (
        lambda: checkpass.preflight(source, "luna", runs),
        lambda: checkpass.preflight(source, "rule", runs, stats="s27"),
        lambda: _run(source, runs),
    ):
        with pytest.raises(ConfigurationError, match="--stats s3, not s27") as caught:
            refused()
        assert "decision 0129 item 4" in str(caught.value)
    assert {p.name for p in runs.iterdir()} == before  # no derived folder
    record = checkpass.check_run(
        source,
        "rule",
        checkpass.rule_checker(STATS),
        runs_dir=runs,
        groups={},
        seen_pairs=frozenset(),
        commit=("d", False),
        now=lambda: NOW,
        stats="s3",
    )
    # The check's suffix goes after the post-pass's text fingerprint (decision 0133).
    assert record.prompt_version == "s1-v6+gabc+tools-s3+p0123456789ab+check-rule-s3"


JEV_BASE = "https://api.typesafe.ai"
JEV_URL = f"{JEV_BASE}/v1/systemone"


@respx.mock
def test_the_jev_checker_ranks_reports_the_model_and_prices_input_tokens() -> None:
    respx.post(JEV_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "usage": {"input_tokens": 1000, "output_tokens": 0},
                "answers": {
                    "defining": {
                        "type": "choice",
                        "choice": LOC,
                        "confidence": 0.9,
                        "probabilities": {LOC: 0.7, STALL: 0.3},
                    }
                },
            },
        )
    )
    tables = load_tables()
    hypothesis = _case("C1", (LOC,), (STALL,)).steps[-1].hypothesis
    with TypeSafeClient("k", base_url=JEV_BASE) as client:
        checker = checkpass.jev_checker(client, STATS, tables)
        outcome = checker(hypothesis, "Maneuvering")
    assert outcome.ranking == (LOC, STALL)
    assert outcome.model == "jev-1.13.0"
    assert outcome.cost_usd == pytest.approx(1000 * sources.JEV.input_usd_per_mtok / 1_000_000)


# --- jev2, the registered second Jev check (decision 0103) ---


def _jev2_reply(probabilities: dict[str, float], choice: str, confidence: float) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "jev-1.13.0",
            "usage": {"input_tokens": 2000, "output_tokens": 0},
            "answers": {
                "defining": {
                    "type": "choice",
                    "choice": choice,
                    "confidence": confidence,
                    "probabilities": probabilities,
                }
            },
        },
    )


def test_jev2_is_a_way_with_jevs_cost_estimate_and_round1s_ways_are_unchanged() -> None:
    assert "jev2" in checkpass.CHECK_WAYS
    assert checkpass.WAYS == ("rule", "luna", "jev")  # Round 1's report reads these
    assert (
        checkpass.EXPECTED_COST_PER_CASE_USD["jev2"] == checkpass.EXPECTED_COST_PER_CASE_USD["jev"]
    )


@respx.mock
def test_the_jev2_checker_sends_the_registered_state_and_question_to_the_pinned_model() -> None:
    route = respx.post(JEV_URL).mock(
        return_value=_jev2_reply(
            {STALL: 0.3, LOC: 0.6, ordering.NONE_OF_THESE: 0.1}, choice=LOC, confidence=0.8
        )
    )
    tables = load_tables()
    hypothesis = _case("C1", (LOC,), (STALL,)).steps[-1].hypothesis
    with TypeSafeClient("k", base_url=JEV_BASE) as client:
        outcome = checkpass.jev2_checker(client, STATS, tables)(hypothesis, "Maneuvering")
    options = ordering.candidates((STALL,), "Maneuvering", STATS)
    body = json.loads(route.calls[0].request.content)
    assert body == {
        "state": ordering.jev2_state(
            (STALL,), options, "Maneuvering", hypothesis.evidence_narrative, STATS, tables
        ),
        "model": "jev-1.13.0",
        "questions": {"defining": ordering.jev2_question(options, tables)},
    }
    assert outcome.ranking == (LOC, STALL)
    assert outcome.model == "jev-1.13.0"
    assert outcome.toward_more_common is True  # stall (5) -> loss of control (30) in the group
    assert outcome.cost_usd == pytest.approx(2000 * sources.JEV.input_usd_per_mtok / 1_000_000)
    assert outcome.prompt_tokens == 2000
    assert outcome.details == {
        "choice": LOC,
        "confidence": 0.8,
        "jev_order": [LOC, STALL, ordering.NONE_OF_THESE],
        # every option's probability, in the ranked order (ties broken by the model's order)
        "probabilities": {LOC: 0.6, STALL: 0.3, ordering.NONE_OF_THESE: 0.1},
    }
    assert list(cast("dict[str, float]", outcome.details["probabilities"])) == [
        LOC,
        STALL,
        ordering.NONE_OF_THESE,
    ]


@respx.mock
def test_the_jev2_checker_leaves_the_answer_unchanged_when_none_of_these_ranks_first() -> None:
    respx.post(JEV_URL).mock(
        return_value=_jev2_reply(
            {STALL: 0.2, LOC: 0.2, ordering.NONE_OF_THESE: 0.6},
            choice=ordering.NONE_OF_THESE,
            confidence=0.5,
        )
    )
    hypothesis = _case("C1", (LOC,), (STALL,)).steps[-1].hypothesis
    with TypeSafeClient("k", base_url=JEV_BASE) as client:
        outcome = checkpass.jev2_checker(client, STATS, load_tables())(hypothesis, "Maneuvering")
    assert outcome.ranking == (STALL,)  # the model's own guesses
    assert outcome.toward_more_common is False
    assert outcome.details["choice"] == ordering.NONE_OF_THESE
    assert "none_of_these" in outcome.note


@respx.mock
def test_a_jev2_pass_records_choice_confidence_and_probabilities_in_the_steps_arguments(
    tmp_path: Path,
) -> None:
    respx.post(JEV_URL).mock(
        return_value=_jev2_reply(
            {STALL: 0.2, LOC: 0.2, ordering.NONE_OF_THESE: 0.6},
            choice=ordering.NONE_OF_THESE,
            confidence=0.5,
        )
    )
    runs = tmp_path / "runs"
    source = _source(runs)
    with TypeSafeClient("k", base_url=JEV_BASE) as client:
        record = checkpass.check_run(
            source,
            "jev2",
            checkpass.jev2_checker(client, STATS, load_tables()),
            runs_dir=runs,
            groups={"C1": "Maneuvering", "C2": "Maneuvering"},
            seen_pairs=frozenset(),
            commit=("def5678", False),
            now=lambda: NOW,
        )
    assert record.run_id.endswith("-check-jev2")
    cases = {c.case_id: c for c in read_jsonl(runs / record.run_id / "cases.jsonl", CaseResult)}
    step = cases["C1"].steps[-1]
    assert step.tool == checkpass.CHECK_TOOL  # the checked step is still written
    assert step.model == "jev-1.13.0"
    assert step.arguments == {
        "ranking": [STALL],
        "toward_more_common": False,
        "choice": ordering.NONE_OF_THESE,
        "confidence": 0.5,
        "jev_order": [ordering.NONE_OF_THESE, STALL, LOC],
        "probabilities": {ordering.NONE_OF_THESE: 0.6, STALL: 0.2, LOC: 0.2},
    }
    assert [g.phase + g.event for g in step.hypothesis.occurrence] == [STALL]


def test_a_rule_steps_arguments_hold_only_the_ranking_and_the_push(tmp_path: Path) -> None:
    """The free-form details default to empty: rule, luna and jev steps are as before."""
    runs = tmp_path / "runs"
    record = _run(_source(runs), runs)
    cases = {c.case_id: c for c in read_jsonl(runs / record.run_id / "cases.jsonl", CaseResult)}
    assert set(cases["C1"].steps[-1].arguments) == {"ranking", "toward_more_common"}


# --- arm C: the ordering check as a diagnostic (decision 0137) ---

ARM_C_RUN = "20261001T201506-fd6053f-dev-400-C"
ARM_C_PROMPT = "s3-v1+ge17fecdc66ec+p947fac1c86a4"
_FINDING = FindingGuess(category6="010203", modifier="01", probability=0.5)
# Each checkpoint's own account, so the test can tell which one the check was sent.
_ACCOUNTS = {
    "h0": "the first look at the start facts",
    "h1": "after the documents were read",
    "answer": "the loop's own account at its answer",
}


def _checkpoint(number: int, kind: str, guesses: tuple[str, ...]) -> StepRecord:
    """One arm C step: ``agent/run.py`` writes one per checkpoint, named ``checkpoint:<kind>``.

    The refinement keeps the answer's codes and account and attaches each finding's item
    (``Hypothesis.with_items``), so the two differ only in the item: the check must re-order
    the refined one, the answer as scored.
    """
    base = _step(guesses, abstain=False)
    account = _ACCOUNTS["answer" if kind == "refine" else kind]
    finding = _FINDING.model_copy(update={"item8": "01020304"}) if kind == "refine" else _FINDING
    hypothesis = base.hypothesis.model_copy(
        update={"evidence_narrative": account, "findings": (finding,)}
    )
    return base.model_copy(
        update={
            "case_id": "C1",
            "step": number,
            "arm": "C",
            "tool": f"checkpoint:{kind}",
            "hypothesis": hypothesis,
            "stop_reason": "answered" if kind == "refine" else "",
            "cost_usd": 0.001,
        }
    )


def _arm_c_source(runs: Path, run_id: str = ARM_C_RUN, *, sample: str = "dev-400") -> Path:
    """A finished arm C run: one case answered after four checkpoints, one failed case.

    The NTSB's first code is loss of control (LOC). The first look and the documents put LOC
    first; the answer, and so its refinement, put stall first: wrong as scored.
    """
    folder = runs / run_id
    folder.mkdir(parents=True)
    record = RunRecord(
        run_id=run_id,
        sample=sample,
        arm="C",
        exclusions=(),
        includes=(),
        prompt_version=ARM_C_PROMPT,
        guidance=("r3-loc-stall", "r6-aircraft-control"),
        model="openai/gpt-6-luna",
        price_variant="batch",
        cap_usd=0.15,
        budget_usd=50.0,
        commit_sha="fd6053f",
        dirty=False,
        started=NOW,
        finished=NOW,
        batch_ids=("b1", "b2"),
        cases=2,
        cost_usd=4.5711,
        reported_batch_cost_usd=1.84,
    )
    write_jsonl(folder / "run.jsonl", [record])
    steps = (
        _checkpoint(0, "h0", (LOC,)),
        _checkpoint(1, "h1", (LOC, STALL)),
        _checkpoint(2, "answer", (STALL, LOC)),
        _checkpoint(3, "refine", (STALL, LOC)),
    )
    answered = _case("C1", (LOC, STALL), (STALL, LOC)).model_copy(update={"steps": steps})
    failed = _case("C2", (LOC,), (LOC,), scored=False).model_copy(
        update={"failure": "failed: coding"}
    )
    write_jsonl(folder / "cases.jsonl", [answered, failed])
    return folder


def test_an_arm_c_run_is_checked_by_luna_on_its_final_answer_in_s3s_statistics(
    tmp_path: Path,
) -> None:
    """Decision 0137 items 1-3: the derived run is the usual one, labelled with S3's counts."""
    runs = tmp_path / "runs"
    source = _arm_c_source(runs)
    client = RecordingFakeClient(
        [json.dumps({"ranking": [LOC, STALL]})],
        usage=[Usage(prompt_tokens=1500, completion_tokens=900, reported_cost_usd=0.0003)],
    )
    record = checkpass.check_run(
        source,
        "luna",
        checkpass.luna_checker(client, STATS, load_tables()),
        runs_dir=runs,
        groups={"C1": "Maneuvering", "C2": "Maneuvering"},
        seen_pairs=frozenset({LOC}),
        commit=("abc9999", False),
        now=lambda: NOW,
        stats="s3",
    )
    assert record.run_id == f"{ARM_C_RUN}-check-luna"
    assert record.prompt_version == f"{ARM_C_PROMPT}+check-luna-s3"
    assert record.arm == "C"
    # The check's own cost, and no billed total: the loop's batch rounds are the source's.
    assert record.cost_usd == pytest.approx(0.0003)
    assert record.reported_batch_cost_usd is None
    assert record.batch_ids == ()
    # One call, for the answered case only; it saw the final answer's codes and account.
    (system,) = client.systems
    assert f"The analyst's guesses, in order: {STALL} (" in system
    assert _ACCOUNTS["answer"] in system
    assert _ACCOUNTS["h0"] not in system
    assert _ACCOUNTS["h1"] not in system
    cases = {c.case_id: c for c in read_jsonl(runs / record.run_id / "cases.jsonl", CaseResult)}
    source_cases = {c.case_id: c for c in read_jsonl(source / "cases.jsonl", CaseResult)}
    checked = cases["C1"]
    assert checked.steps[:4] == source_cases["C1"].steps  # the loop's steps, unchanged
    step = checked.steps[-1]
    assert (step.step, step.tool) == (4, checkpass.CHECK_TOOL)
    assert [g.phase + g.event for g in step.hypothesis.occurrence] == [LOC, STALL]
    # The refinement's finding item is carried: the step re-ordered is the refined answer.
    assert step.hypothesis.findings == source_cases["C1"].steps[-1].hypothesis.findings
    assert step.hypothesis.findings[0].item8 == "01020304"
    assert checked.scores is not None
    assert checked.scores.occurrence_top1
    assert cases["C2"] == source_cases["C2"]  # a failed case passes through unchanged


@pytest.mark.parametrize("way", ["rule", "jev", "jev2"])
def test_an_arm_c_run_is_refused_every_way_but_luna_before_anything_is_written(
    tmp_path: Path, way: checkpass.Way
) -> None:
    """Decision 0137 item 1: refused in ``preflight``, before any reservation or client."""
    runs = tmp_path / "runs"
    source = _arm_c_source(runs)
    before = {p.name for p in runs.iterdir()}
    with pytest.raises(ConfigurationError, match="decision 0137 item 1") as caught:
        checkpass.preflight(source, way, runs, stats="s3")
    assert f"with way luna only, not {way}" in str(caught.value)
    with pytest.raises(ConfigurationError, match="decision 0137 item 1"):
        checkpass.check_run(
            source,
            way,
            checkpass.rule_checker(STATS),
            runs_dir=runs,
            groups={},
            seen_pairs=frozenset(),
            commit=("d", False),
            now=lambda: NOW,
            stats="s3",
        )
    assert {p.name for p in runs.iterdir()} == before  # no derived folder


def test_an_arm_c_run_is_checked_in_s3s_statistics_only(tmp_path: Path) -> None:
    """Decision 0137 item 2: the file the loop's tools read, named as a tool post-pass names it."""
    runs = tmp_path / "runs"
    source = _arm_c_source(runs)
    with pytest.raises(ConfigurationError, match="--stats s3, not s27") as default:
        checkpass.preflight(source, "luna", runs)  # S2.7's file is the default
    with pytest.raises(ConfigurationError, match="--stats s3, not s27") as named:
        checkpass.preflight(source, "luna", runs, stats="s27")
    for caught in (default, named):
        assert "decision 0137 item 2" in str(caught.value)
    assert checkpass.preflight(source, "luna", runs, stats="s3").run_id == f"{ARM_C_RUN}-check-luna"


@pytest.mark.parametrize(
    ("sample", "message"),
    [
        ("heldout-400", "development"),
        ("heldout-40", "development"),
        ("dev-seal-400", "decision 0137 item 5"),
        ("dev-seal-s3-400", "decision 0137 item 5"),
    ],
)
def test_a_held_out_or_sealed_arm_c_run_is_refused(
    tmp_path: Path, sample: str, message: str
) -> None:
    """Decision 0137 item 5. A sealed sample is refused even once its registration is
    committed: this check has no ``is_committed`` to ask."""
    runs = tmp_path / "runs"
    source = _arm_c_source(runs, f"20261001T201506-fd6053f-{sample}-C", sample=sample)
    with pytest.raises(ConfigurationError, match=message):
        checkpass.preflight(source, "luna", runs, stats="s3")


@pytest.mark.parametrize("arm", ["A", "ceiling"])
def test_only_arms_b_and_c_are_checked(tmp_path: Path, arm: str) -> None:
    runs = tmp_path / "runs"
    source = _source(runs)
    (record,) = read_jsonl(source / "run.jsonl", RunRecord)
    (source / "run.jsonl").write_text(record.model_copy(update={"arm": arm}).model_dump_json())
    assert {"B", "C"} == checkpass.CHECKED_ARMS
    with pytest.raises(ConfigurationError, match=f"arm {arm} "):
        checkpass.preflight(source, "rule", runs)
