"""scripts/s3_noise_floor.py: the loop's noise floor, format gate and third-run rule (S3.1 Task 13).

Synthetic run folders are built from ``CaseResult``, ``AgentCall`` and ``RunRecord`` objects and
the ``spec.json`` arm C writes; one test reads two folders a real ``AgentRunner`` wrote. Offline.
"""

import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import occurrence_misses as om
from scripts import s3_noise_floor as nf
from tests.test_agent_drive import Clock, _answers, _scripts
from tests.test_agent_run import RAWS, _runner, _spec
from tests.test_occurrence_misses import _SCORES, _case
from tests.test_runner import FakeBatchClient

from ntsb_probable_cause.agent import texts
from ntsb_probable_cause.agent.run import GUIDANCE, TRAIL_FILE
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, write_jsonl
from ntsb_probable_cause.scoring.runner import RunSpec, spec_json

_WHEN = datetime(2026, 10, 2, tzinfo=UTC)
_SHA = "abc1234"
# Case ids no other text in the report can contain, so "no case id in the output" is testable.
_IDS = tuple(f"ZQX{n:03d}" for n in range(20))
_RUN_A = "20261002T010000-abc1234-dev-400-C"
_RUN_B = "20261002T020000-abc1234-dev-400-C"
_RUN_C = "20261002T030000-abc1234-dev-400-C"
# A guard message as ``records/guard.py`` words it: role, kind and source, never the text.
_LEAK = "verbatim from probable_cause in docket_documents (40 chars withheld)"


# --------------------------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------------------------


def _spec_json(ids: Sequence[str], **changes: object) -> dict[str, object]:
    """What ``AgentRunner`` writes to ``spec.json`` for a plain arm C batch run."""
    spec = RunSpec(
        sample="dev-400",
        arm="C",
        guidance=GUIDANCE,
        cap_usd=0.15,
        expected_cost_per_case_usd=0.012,
    )
    extra: dict[str, object] = {
        "agent_prompt_version": texts.prompt_version(GUIDANCE),
        "stats": "s3",
        "max_rounds": 40,
        "max_coding_calls": 6,
        "without": [],
        "pass_reasoning": False,
    }
    recorded = spec_json(spec, commit_sha=_SHA, dirty=False, case_ids=ids, extra=extra)
    return recorded | changes


def _record(run_id: str, cases: int, **changes: object) -> RunRecord:
    record = RunRecord(
        run_id=run_id,
        sample="dev-400",
        arm="C",
        evidence_version="v1",
        exclusions=(),
        includes=(),
        prompt_version=texts.prompt_version(GUIDANCE),
        guidance=GUIDANCE,
        model="openai/gpt-6-luna",
        price_variant="batch",
        cap_usd=0.15,
        budget_usd=40.0,
        commit_sha=_SHA,
        dirty=False,
        started=_WHEN,
        finished=_WHEN,
        cases=cases,
        cost_usd=0.5,
    )
    return record.model_copy(update=changes)


def _scored(  # noqa: PLR0913 -- a test-only builder, one keyword per varied field.
    case_id: str,
    *,
    top1: bool = False,
    first: str = "552240",
    confidence: float = 0.5,
    fatal: bool = False,
    abstain: bool = False,
) -> CaseResult:
    base = _case(case_id, ("552240",), (first,), abstain=abstain)
    scores = replace(
        _SCORES,
        occurrence_top1=top1,
        occurrence_top3=top1,
        confidence=confidence,
        abstained=abstain,
        finding_recall_10=0.5 if top1 else 0.0,
    )
    return base.model_copy(update={"fatal": fatal, "scores": scores})


def _failed(case_id: str, failure: str) -> CaseResult:
    return _case(case_id, ("552240",), (), scored=False).model_copy(update={"failure": failure})


def _call(  # noqa: PLR0913 -- a test-only builder, one keyword per varied field.
    case_id: str,
    tool: str | None,
    arguments: dict[str, object] | None = None,
    *,
    index: int = 0,
    error: str | None = None,
    prompt_tokens: int = 100,
    cached: int | None = None,
) -> AgentCall:
    return AgentCall(
        run_id="r",
        case_id=case_id,
        trigger=1,
        docket_state="all",
        call_index=index,
        step="coding",
        retry=False,
        tool=tool,
        arguments=arguments or {},
        protocol_error=error,
        result_chars=0,
        argument_errors=0,
        hypothesis=None,
        prompt_tokens=prompt_tokens,
        cached_tokens=cached,
        completion_tokens=10,
        reasoning_tokens=None,
        finish_reason="tool_calls",
        cost_usd=0.001,
        estimated_usd=0.002,
        sent_at=_WHEN,
        returned_at=_WHEN,
        batch_id="b1",
        commit_sha=_SHA,
        dirty=False,
    )


def _choose(case_id: str, decisions: dict[int, bool], *, index: int = 1) -> AgentCall:
    arguments: dict[str, object] = {
        "decisions": [
            {"document": n, "read": read, "expected_effect": "what it shows"}
            for n, read in decisions.items()
        ],
        "reason": "why",
    }
    return _call(case_id, "choose_documents", arguments, index=index)


def _describe(
    case_id: str, codes: Sequence[str], *, reason: str = "r", index: int = 5
) -> AgentCall:
    arguments: dict[str, object] = {
        "kind": "occurrence",
        "codes": list(codes),
        "reason": reason,
        "expected_effect": f"{reason} expected",
    }
    return _call(case_id, "describe_codes", arguments, index=index)


def _write(  # noqa: PLR0913 -- a test-only builder: the run, then what may vary.
    runs: Path,
    run_id: str,
    cases: Sequence[CaseResult],
    calls: Sequence[AgentCall] = (),
    *,
    spec: dict[str, object] | None = None,
    record: RunRecord | None = None,
) -> Path:
    folder = runs / run_id
    folder.mkdir(parents=True)
    ids = [c.case_id for c in cases]
    (folder / "spec.json").write_text(json.dumps(spec if spec is not None else _spec_json(ids)))
    write_jsonl(folder / "run.jsonl", [record or _record(run_id, len(cases))])
    write_jsonl(folder / "cases.jsonl", cases)
    write_jsonl(folder / TRAIL_FILE, calls)
    return folder


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The runs folder, and ``dev-400`` taken to be the synthetic ids ``_IDS``."""
    folder = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(folder))
    monkeypatch.setattr(samples, "sample_ids", lambda name: _IDS if name == "dev-400" else ())
    return folder


def _plain(ids: Sequence[str] = _IDS, *, hits: int = 0) -> list[CaseResult]:
    return [_scored(case_id, top1=n < hits) for n, case_id in enumerate(ids)]


# --------------------------------------------------------------------------------------------
# The whole report, on a synthetic pair
# --------------------------------------------------------------------------------------------


def _pair_a() -> tuple[list[CaseResult], list[AgentCall]]:
    cases = [
        _scored(_IDS[0], top1=True, confidence=0.9, fatal=True),
        _scored(_IDS[1], top1=True, confidence=0.7),
        _scored(_IDS[2], top1=False, confidence=0.3, first="552241"),
        _scored(_IDS[3], top1=False, confidence=0.4, abstain=True),
        *(_scored(i, confidence=0.5) for i in _IDS[4:17]),
        _failed(_IDS[17], "failed: coding"),
        _failed(_IDS[18], "cap"),
        _failed(_IDS[19], f"leak: {_IDS[19]}: {_LEAK}"),
    ]
    calls = [
        _choose(_IDS[0], {1: True, 2: False}),
        _choose(_IDS[0], {2: False}, index=3),
        _choose(_IDS[1], {1: False}),
        _describe(_IDS[0], ["552240"]),
        _describe(_IDS[1], ["552241"]),
        _call(_IDS[2], "describe_codes", error="no tool call"),
        _call(_IDS[4], "record_hypothesis", prompt_tokens=1000, cached=600),
        _call(_IDS[5], "record_hypothesis", prompt_tokens=1000, cached=None),
    ]
    return cases, calls


def _pair_b() -> tuple[list[CaseResult], list[AgentCall]]:
    cases = [
        _scored(_IDS[0], top1=True, confidence=0.9, fatal=True),
        _scored(_IDS[1], top1=False, confidence=0.7, first="552241"),
        _scored(_IDS[2], top1=False, confidence=0.3, first="552241"),
        _scored(_IDS[3], top1=False, confidence=0.4, abstain=True),
        *(_scored(i, confidence=0.5) for i in _IDS[4:17]),
        _scored(_IDS[17], confidence=0.5),
        _failed(_IDS[18], "failed: rounds"),
        _failed(_IDS[19], "failed: h0"),
    ]
    calls = [
        _choose(_IDS[0], {1: False, 2: True}),
        _choose(_IDS[1], {1: False}),
        _describe(_IDS[0], ["552240"], reason="other words"),
        _describe(_IDS[1], ["552240"]),
        _call(_IDS[4], "record_hypothesis", prompt_tokens=2000, cached=1500),
    ]
    return cases, calls


def _report(runs: Path, capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    assert nf.main(list(argv)) == 0
    return capsys.readouterr().out


def test_the_report_prints_every_figure_with_its_denominator(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(runs, _RUN_A, *_pair_a())
    _write(runs, _RUN_B, *_pair_b())
    out = _report(runs, capsys, _RUN_A, _RUN_B)
    assert f"run a = {_RUN_A}" in out
    assert f"run b = {_RUN_B}" in out
    # the format gate: a's failed: coding; b's failed: h0 (failed: rounds is listed apart)
    assert "format gate, run a: PASS -- 1 of 20 cases failed for format or tool reasons" in out
    assert "(failed: coding 1)" in out
    assert "format gate, run b: PASS -- 1 of 20 cases failed for format or tool reasons" in out
    assert "(failed: h0 1)" in out
    assert "round limit (failed: rounds), run a: 0 of 20 cases" in out
    assert "round limit (failed: rounds), run b: 1 of 20 cases" in out
    # failures by reason, reused from report.failure_summary
    assert "failures by reason: cap 1, failed 1, leak (probable_cause) 1" in out
    assert "failures by reason: failed 2" in out
    # the paired differences, reused from report.compare_by_fatal: 17 cases scored in both
    assert "paired difference (a - b) on 17 shared, scored cases:" in out
    assert "occurrence top-1: +5.9% [" in out
    assert "fatal: paired difference (a - b) on 1 shared, scored cases:" in out
    # the first occurrence code changed on one case of 17 (ZQX001), as churn counts it
    assert "first occurrence code changed: 1 of 17 cases scored in both runs" in out
    assert "same first guess: 16 of 17" in out
    # read or skip: ZQX000's two documents (read 1 / skip 2 in a, the other way in b), ZQX001's one
    assert "read-or-skip agreement: 1 of 3 documents offered in both runs" in out
    assert "read in both 0, skipped in both 1; read in run a only 1, in run b only 1" in out
    assert "over 2 cases; 0 documents offered in one run only" in out
    # coding calls: ZQX000 the same (reason and expected effect differ), ZQX001 not
    assert "coding-call agreement: 16 of 17 cases scored in both runs" in out
    assert "15 of those 16 made no coding call in either run" in out
    # cost and the cached share, from run.jsonl and trail.jsonl
    assert "cost, run a: $0.5000 for 20 cases, $0.0250 per case" in out
    assert "cached share of prompt tokens, run a: 600 of 2600 (23.1%) over 8 model calls" in out
    assert "7 calls reported no cached count" in out
    assert "cached share of prompt tokens, run b: 1500 of 2400 (62.5%) over 5 model calls" in out
    # raw stated confidence, over the scored cases: (0.9 + 0.7 + 0.3 + 0.4 + 13 x 0.5) / 17
    assert "confidence at the answer, run a: mean 0.518 over 17 scored cases of 20" in out
    assert "- <0.4: right 0, wrong 1, of 1" in out
    assert "- 0.4-0.6: right 0, wrong 14, of 14" in out
    assert "- 0.6-0.8: right 1, wrong 0, of 1" in out
    assert "- ≥0.8: right 1, wrong 0, of 1" in out
    assert "abstained, run a: 1 of 17 scored cases" in out
    # the third-run rule: +1 net hit of 17 is 5.88 points, larger than 4.0
    assert "third run: needed -- " in out
    assert "+5.88 points (net +1 of 17 cases scored in both)" in out
    assert "ZQX" not in out  # no case id anywhere, not even inside a leak message


def test_no_case_id_reaches_the_output_file(
    runs: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _write(runs, _RUN_A, *_pair_a())
    _write(runs, _RUN_B, *_pair_b())
    out_path = tmp_path / "results" / "s3-noise-floor-dev.txt"
    printed = _report(runs, capsys, _RUN_A, _RUN_B, "--out", str(out_path))
    written = out_path.read_text()
    assert written == printed
    assert "ZQX" not in written


def test_a_third_run_adds_every_pair_and_the_rule_still_reads_the_first_two(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(runs, _RUN_A, _plain())
    _write(runs, _RUN_B, _plain())
    _write(runs, _RUN_C, _plain(hits=5))
    out = _report(runs, capsys, _RUN_A, _RUN_B, _RUN_C)
    assert f"run c = {_RUN_C}" in out
    for pair in ("run a against run b", "run a against run c", "run b against run c"):
        assert f"## {pair}" in out
    # compare_by_fatal says "(a - b)" in every block; each block names what a and b are there.
    blocks = out.split("\n## run ")
    for first, second in (("a", "b"), ("a", "c"), ("b", "c")):
        (block,) = [b for b in blocks if b.startswith(f"{first} against run {second}\n")]
        assert f"\n(a - b) here is run {first} minus run {second}\n" in block
        assert block.index("(a - b) here is") < block.index("paired difference (a - b)")
    assert "list order inside the arguments kept" in out
    assert "format gate, run c: PASS -- 0 of 20 cases" in out
    assert "third run: not needed -- " in out  # a and b are identical
    assert "+0.00 points (net +0 of 20 cases scored in both)" in out
    assert f"a third run was given: run c = {_RUN_C}" in out


# --------------------------------------------------------------------------------------------
# The format gate (spec §10.4, decision 0130 item 5)
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("failures", "verdict"), [(8, "PASS"), (9, "FAIL")])
def test_the_gate_passes_eight_format_failures_and_fails_nine(
    runs: Path, capsys: pytest.CaptureFixture[str], failures: int, verdict: str
) -> None:
    steps = ("h0", "choice1", "h1", "choice2", "h2", "coding", "answer", "refine", "coding")
    failed = [_failed(i, f"failed: {steps[n]}") for n, i in enumerate(_IDS[:failures])]
    # none of these is a format or tool failure; they never move the gate
    others = [
        _failed(_IDS[9], "cap"),
        _failed(_IDS[10], "failed: rounds"),
        _failed(_IDS[11], "leak: docket_documents holds text from probable_cause"),
        _failed(_IDS[12], "failed: leak"),
    ]
    cases = [*failed, *(_scored(i) for i in _IDS[failures:9]), *others, *_plain(_IDS[13:])]
    _write(runs, _RUN_A, cases)
    _write(runs, _RUN_B, _plain())
    out = _report(runs, capsys, _RUN_A, _RUN_B)
    expected = f"format gate, run a: {verdict} -- {failures} of 20 cases failed for format or tool"
    assert expected in out
    assert "at most 8 pass (2% of dev-400's 401 cases" in out
    assert "round limit (failed: rounds), run a: 1 of 20 cases" in out


def _no_reply(case_id: str, index: int) -> AgentCall:
    """A call that came back with no reply (a provider error, or no result in a batch)."""
    return _call(case_id, None, index=index, error="no result in the completed batch").model_copy(
        update={
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "finish_reason": None,
            "cost_usd": 0.0,
        }
    )


def test_the_gate_says_how_many_counted_failures_had_no_reply_on_the_failing_call(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A batch item that fails twice with no reply ends ``failed: <step>`` and is counted (the
    gate fails closed); the line says how many of the counted failures were that, read from
    the case's last call in ``trail.jsonl``."""
    cases = [
        _failed(_IDS[0], "failed: coding"),  # its failing call had no reply
        _failed(_IDS[1], "failed: h0"),  # its failing call was a reply that broke the protocol
        _failed(_IDS[2], "failed: refine"),  # a reply, then no reply: the last call decides
        _failed(_IDS[3], "failed: rounds"),  # not counted, whatever its calls
        *_plain(_IDS[4:]),
    ]
    calls = [
        _call(_IDS[0], "describe_codes", index=0),
        _no_reply(_IDS[0], 1),
        _no_reply(_IDS[0], 2),
        _call(_IDS[1], None, index=0, error="no tool call"),
        _call(_IDS[1], None, index=1, error="no tool call"),
        _call(_IDS[2], None, index=0, error="items: list_type"),
        _no_reply(_IDS[2], 1),
        _no_reply(_IDS[3], 0),
    ]
    gate = nf.format_gate(cases, calls)
    assert (gate.count, gate.no_reply, gate.passed) == (3, 2, True)
    assert nf.format_gate(cases).no_reply == 0  # no trail given, nothing read from it
    _write(runs, _RUN_A, cases, calls)
    _write(runs, _RUN_B, _plain())
    out = _report(runs, capsys, _RUN_A, _RUN_B)
    line = next(x for x in out.splitlines() if x.startswith("format gate, run a: "))
    assert line.startswith("format gate, run a: PASS -- 3 of 20 cases failed for format or tool")
    assert "; of which 2 had no reply on the failing call;" in line
    assert "format gate, run b: PASS -- 0 of 20 cases" in out
    assert "; of which 0 had no reply on the failing call;" in out


def test_the_gate_counts_every_failed_step_and_fails_closed_on_an_unknown_one() -> None:
    cases = [
        _failed("x1", "failed: refine"),
        _failed("x2", "failed: refine"),
        _failed("x3", "failed: something new"),
        _failed("x4", "failed: rounds"),
        _failed("x5", "failed: leak"),
        _failed("x6", "leak: a message"),
        _failed("x7", "cap"),
        _failed("x8", "aborted: "),
        _scored("x9"),
    ]
    gate = nf.format_gate(cases)
    assert dict(gate.failed) == {"failed: refine": 2, "failed: something new": 1}
    assert (gate.count, gate.rounds, gate.cases, gate.passed) == (3, 1, 9, True)


# --------------------------------------------------------------------------------------------
# The third-run rule (spec §10.2, decision 0130 item 2)
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("net", "n", "needed"),
    [
        (40, 1000, False),  # 4.0 points: not larger than 4.0
        (41, 1000, True),  # 4.1 points
        (-40, 1000, False),
        (-41, 1000, True),  # the absolute difference
        (16, 400, False),  # 4.0 exactly, where a float can round the wrong way
        (2, 50, False),
        (2, 49, True),  # 4.08 points
        (0, 0, False),
    ],
)
def test_the_third_run_rule_at_its_boundary(net: int, n: int, needed: bool) -> None:
    assert nf.third_run_needed(net, n) is needed


@pytest.mark.parametrize(
    ("ids", "line"),
    [
        (tuple(f"ZQX{n:03d}" for n in range(50)), "third run: not needed -- "),
        (tuple(f"ZQX{n:03d}" for n in range(49)), "third run: needed -- "),
    ],
)
def test_the_third_run_line_at_4_0_and_4_1_points(
    runs: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    ids: tuple[str, ...],
    line: str,
) -> None:
    monkeypatch.setattr(samples, "sample_ids", lambda _name: ids)
    _write(runs, _RUN_A, _plain(ids, hits=2))
    _write(runs, _RUN_B, _plain(ids))
    out = _report(runs, capsys, _RUN_A, _RUN_B)
    assert line in out
    points = "+4.00" if len(ids) == 50 else "+4.08"
    assert f"{points} points (net +2 of {len(ids)} cases scored in both)" in out


def test_the_third_run_is_not_decided_when_no_case_was_scored_in_both(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(runs, _RUN_A, [_failed(i, "failed: h0") for i in _IDS])
    _write(runs, _RUN_B, _plain())
    out = _report(runs, capsys, _RUN_A, _RUN_B)
    assert "third run: not decided -- no case was scored in both run a and run b" in out
    assert "format gate, run a: FAIL -- 20 of 20 cases" in out


def test_the_top_1_difference_is_paired_on_the_cases_scored_in_both() -> None:
    first = [_scored("c1", top1=True), _scored("c2", top1=True), _scored("c3")]
    second = [_scored("c1", top1=True), _failed("c2", "failed: coding"), _scored("c4", top1=True)]
    assert nf.top1_net(first, second) == (0, 1)  # c2 and c4 are scored in one run only
    assert nf.top1_net(second, first) == (0, 1)


# --------------------------------------------------------------------------------------------
# Agreement, confidence, cached share
# --------------------------------------------------------------------------------------------


def test_read_agreement_takes_a_documents_final_decision_and_skips_refused_calls() -> None:
    first = [
        _choose("c1", {1: False, 2: False, 3: True}),
        _choose("c1", {1: True, 2: False}, index=3),  # the second look reads 1
        _choose("c2", {1: True}),
        _choose("c2", {1: False}, index=3),  # read at any choice is read, whatever came after
        _call("c3", "choose_documents", {}, error="choose_documents must decide every ..."),
    ]
    second = [
        _choose("c1", {1: True, 2: True, 3: True}),
        _choose("c2", {1: True}),
        _choose("c3", {1: True}),
        _choose("c4", {5: False}),
    ]
    agreement = nf.read_agreement(first, second)
    # c1: 1 and 3 read in both, 2 read in the second only; c2's 1 read in both; c3, c4 once
    assert (agreement.both_read, agreement.both_skipped) == (3, 0)
    assert (agreement.first_only, agreement.second_only) == (0, 1)
    assert (agreement.same, agreement.offered) == (3, 4)
    assert (agreement.cases, agreement.one_run_only) == (2, 2)


def test_coding_agreement_compares_multisets_without_reason_and_expected_effect() -> None:
    cases = [_scored(i) for i in ("c1", "c2", "c3", "c4", "c5")]
    first = [
        _describe("c1", ["552240"], reason="one"),
        _describe("c1", ["552241"], reason="two"),
        _describe("c2", ["552240"]),
        _describe("c3", ["552240"]),
        _call(
            "c4", "past_findings", {"occurrence": "552240", "reason": "r", "expected_effect": "e"}
        ),
        _call("c5", "describe_codes", error="the tool could not run (KeyError)"),
    ]
    second = [
        _describe("c1", ["552241"], reason="three"),  # the same two calls, the other way round
        _describe("c1", ["552240"], reason="four"),
        _describe("c2", ["552240"]),
        _describe("c2", ["552240"]),  # twice: a multiset, so not the same
        _describe("c3", ["552241"]),  # other codes
        _call(
            "c4", "past_findings", {"occurrence": "552240", "reason": "x", "expected_effect": "y"}
        ),
        _describe("x9", ["552240"]),  # a case not scored in the first run
    ]
    other = [*cases[:4], _failed("c5", "failed: coding")]
    agreement = nf.coding_agreement(cases, other, first, second)
    # c5 is scored in one run only: c1 and c4 agree, c2 and c3 do not
    assert (agreement.same, agreement.cases, agreement.none) == (2, 4, 0)


def test_coding_agreement_counts_cases_that_made_no_coding_call_in_either_run() -> None:
    cases = [_scored("c1"), _scored("c2")]
    agreement = nf.coding_agreement(cases, cases, [_describe("c1", ["552240"])], [])
    assert (agreement.same, agreement.cases, agreement.none) == (1, 2, 1)


def test_confidence_bands_are_half_open_and_cover_one() -> None:
    cases = [
        _scored("c1", confidence=0.0),
        _scored("c2", confidence=0.399, top1=True),
        _scored("c3", confidence=0.4),
        _scored("c4", confidence=0.6, top1=True),
        _scored("c5", confidence=0.8),
        _scored("c6", confidence=1.0, top1=True),
        _failed("c7", "failed: answer"),
    ]
    lines = nf.confidence_lines("a", cases)
    assert lines[0].startswith("confidence at the answer, run a: mean 0.533 over 6 scored cases")
    assert lines[1:5] == [
        "- <0.4: right 1, wrong 1, of 2",
        "- 0.4-0.6: right 0, wrong 1, of 1",
        "- 0.6-0.8: right 1, wrong 0, of 1",
        "- ≥0.8: right 1, wrong 1, of 2",
    ]


def test_confidence_with_no_scored_case_says_so() -> None:
    lines = nf.confidence_lines("a", [_failed("c1", "cap")])
    assert lines[0] == "confidence at the answer, run a: no scored case, of 1"


def test_the_cost_line_gives_the_batch_rounds_own_total_when_every_round_reported_one() -> None:
    record = _record(_RUN_A, 401, cost_usd=3.208, reported_batch_cost_usd=3.1)
    assert nf.cost_line("a", record) == (
        "cost, run a: $3.2080 for 401 cases, $0.0080 per case "
        "(the batch rounds' own reports: $3.1000)"
    )
    assert nf.cost_line("b", _record(_RUN_B, 401)).endswith(
        "(the batch rounds' own reports: no total)"
    )


def test_the_cached_share_of_a_run_with_no_prompt_tokens() -> None:
    assert nf.cached_line("a", []) == (
        "cached share of prompt tokens, run a: 0 of 0 over 0 model calls; "
        "0 calls reported no cached count (counted as none)"
    )


# --------------------------------------------------------------------------------------------
# Refusals: before any case or trail is read
# --------------------------------------------------------------------------------------------


def _refused(argv: list[str], match: str) -> None:
    with pytest.raises(SystemExit, match=match):
        nf.main(argv)


def test_a_run_on_another_sample_is_refused_before_its_cases_are_read(runs: Path) -> None:
    folder = _write(runs, _RUN_A, _plain(), record=_record(_RUN_A, 20, sample="dev-seal-s3-400"))
    _write(runs, _RUN_B, _plain())
    (folder / "cases.jsonl").write_text("not json\n")  # read it, and the test fails otherwise
    _refused([_RUN_A, _RUN_B], "dev-400 only")


def test_a_held_out_run_is_refused_by_its_id_alone(runs: Path) -> None:
    _write(runs, _RUN_A, _plain())
    _refused([_RUN_A, "20261002T020000-abc1234-heldout-400-C"], "held-out")


def test_an_unfinished_run_is_refused(runs: Path) -> None:
    _write(runs, _RUN_A, _plain(), record=_record(_RUN_A, 20, finished=None))
    _write(runs, _RUN_B, _plain())
    _refused([_RUN_A, _RUN_B], "has not finished")


def test_a_run_of_another_arm_is_refused(runs: Path) -> None:
    _write(runs, _RUN_A, _plain())
    _write(runs, _RUN_B, _plain(), record=_record(_RUN_B, 20, arm="B"))
    _refused([_RUN_A, _RUN_B], "arm B, not arm C")


def test_differently_configured_runs_are_refused_naming_the_setting(runs: Path) -> None:
    _write(runs, _RUN_A, _plain())
    _write(runs, _RUN_B, _plain(), spec=_spec_json(_IDS, cap_usd=0.2))
    _refused([_RUN_A, _RUN_B], r"differs at 'cap_usd' \(.*0\.15.*0\.2")


def test_runs_on_two_agent_texts_are_refused(runs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Andy, 2026-10-01: the prompt version's ``+p`` part differs when the agent's text does."""
    _write(runs, _RUN_A, _plain())
    with monkeypatch.context() as patched:
        patched.setattr(texts, "PROTOCOL", f"{texts.PROTOCOL} (changed)")
        other = texts.prompt_version(GUIDANCE)
    assert other != texts.prompt_version(GUIDANCE)
    assert other.partition("+p")[0] == texts.prompt_version(GUIDANCE).partition("+p")[0]
    _write(runs, _RUN_B, _plain(), spec=_spec_json(_IDS, agent_prompt_version=other))
    _refused([_RUN_A, _RUN_B], "'agent_prompt_version'")


def test_runs_on_two_commits_are_refused(runs: Path) -> None:
    _write(runs, _RUN_A, _plain())
    _write(runs, _RUN_B, _plain(), spec=_spec_json(_IDS, commit_sha="def5678"))
    _refused([_RUN_A, _RUN_B], "commit_sha")


def test_a_setting_only_one_run_records_is_a_difference(runs: Path) -> None:
    _write(runs, _RUN_A, _plain())
    _write(runs, _RUN_B, _plain(), spec=_spec_json(_IDS, round=1))
    _refused([_RUN_A, _RUN_B], "'round'")


def test_the_budget_settings_differ_without_refusal_and_are_printed(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(runs, _RUN_A, _plain())
    _write(runs, _RUN_B, _plain(), spec=_spec_json(_IDS, budget_usd=50.0))
    out = _report(runs, capsys, _RUN_A, _RUN_B)
    assert "spec.json: identical in the 2 runs apart from budget_usd" in out
    assert f"budget_usd: 40.0 in {_RUN_A}; 50.0 in {_RUN_B}" in out


def test_identical_specs_are_reported_with_the_count_of_settings_compared(
    runs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(runs, _RUN_A, _plain())
    _write(runs, _RUN_B, _plain())
    out = _report(runs, capsys, _RUN_A, _RUN_B)
    compared = len(_spec_json(_IDS)) - 2
    assert f"spec.json: identical in the 2 runs ({compared} settings compared" in out


def test_a_run_from_a_dirty_tree_is_refused(runs: Path) -> None:
    dirty = _spec_json(_IDS, dirty=True)
    _write(runs, _RUN_A, _plain(), spec=dirty)
    _write(runs, _RUN_B, _plain(), spec=dirty)
    _refused([_RUN_A, _RUN_B], "uncommitted changes")


def test_a_run_on_part_of_dev_400_is_refused(runs: Path) -> None:
    _write(runs, _RUN_A, _plain(_IDS[:5]))
    _write(runs, _RUN_B, _plain(_IDS[:5]))
    _refused([_RUN_A, _RUN_B], "not the whole of dev-400")


def test_a_copied_folder_is_refused_by_its_record(runs: Path) -> None:
    _write(runs, _RUN_A, _plain())
    _write(runs, _RUN_B, _plain(), record=_record(_RUN_A, 20))
    _refused([_RUN_A, _RUN_B], "names run")


def test_a_run_named_twice_is_refused(runs: Path) -> None:
    _write(runs, _RUN_A, _plain())
    _refused([_RUN_A, _RUN_A], "named twice")


def test_a_missing_folder_spec_or_trail_is_refused(runs: Path) -> None:
    _write(runs, _RUN_A, _plain())
    _refused([_RUN_A, _RUN_B], "no run.jsonl")
    folder = _write(runs, _RUN_B, _plain())
    (folder / "spec.json").unlink()
    _refused([_RUN_A, _RUN_B], "no readable spec.json")
    (folder / "spec.json").write_text("[1]")
    _refused([_RUN_A, _RUN_B], "no readable spec.json")
    (folder / "spec.json").write_text(json.dumps(_spec_json(_IDS)))
    (folder / TRAIL_FILE).unlink()
    _refused([_RUN_A, _RUN_B], "no trail.jsonl")


def test_a_case_outside_the_development_split_is_refused(runs: Path) -> None:
    _write(runs, _RUN_A, _plain())
    cases = [*_plain(_IDS[:19]), _scored(_IDS[19]).model_copy(update={"split": "heldout"})]
    _write(runs, _RUN_B, cases)
    _refused([_RUN_A, _RUN_B], "outside the dev split")


@pytest.mark.parametrize("count", [1, 4])
def test_two_or_three_runs_only(runs: Path, count: int) -> None:
    ids = [f"20261002T0{n}0000-abc1234-dev-400-C" for n in range(count)]
    with pytest.raises(SystemExit) as raised:
        nf.main(ids)
    assert raised.value.code == 2  # argparse's usage error


# --------------------------------------------------------------------------------------------
# Folders a real AgentRunner wrote
# --------------------------------------------------------------------------------------------


def test_the_report_reads_what_the_agent_runner_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    ids = tuple(str(raw["ntsbNumber"]) for raw in RAWS)
    monkeypatch.setattr(samples, "sample_ids", lambda _name: ids)
    made = []
    for start in (0, 1000):
        batch = FakeBatchClient(handlers=[_answers(_scripts())] * 8)
        runner = _runner(runs, batch=batch, clock=Clock(ticks=start))
        made.append(runner.run(_spec(), RAWS).run_id)
    out = _report(runs, capsys, *made)
    assert "format gate, run a: PASS -- 0 of 2 cases" in out
    assert "paired difference (a - b) on 2 shared, scored cases:" in out
    assert "first occurrence code changed: 0 of 2 cases scored in both runs" in out
    # the first case reads 1 and skips 2, then skips 2 again; the second is offered nothing
    assert "read-or-skip agreement: 2 of 2 documents offered in both runs" in out
    assert "coding-call agreement: 2 of 2 cases scored in both runs" in out
    assert "third run: not needed -- " in out
    assert all(case_id not in out for case_id in ids)


def test_first_code_changes_agree_with_churn() -> None:
    first = [_scored("c1"), _scored("c2", first="552241"), _scored("c3"), _failed("c4", "cap")]
    second = [_scored("c1", first="552241"), _scored("c2", first="552241"), _scored("c4")]
    changed, both = nf.first_code_changes(first, second)
    assert (changed, both) == (1, 2)
    assert f"same first guess: {both - changed} of {both}" in om.churn(first, second)


# --------------------------------------------------------------------------------------------
# The Makefile targets
# --------------------------------------------------------------------------------------------


def _recipe(target: str) -> list[str]:
    text = Path("Makefile").read_text()
    block = text.split(f"\n{target}:\n", 1)[1].split("\n\n", 1)[0]
    return [line.strip() for line in block.splitlines() if line.startswith("\t")]


def test_the_paid_targets_check_the_stage_line_first() -> None:
    assert _recipe("s3-smoke-sync") == [
        "uv run python -m scripts.stage_spend --stage s3 --estimate 0.05",
        "uv run ntsb-eval run --arm C --sample dev-400 --limit 1 --sync --price-variant standard "
        "--expected-cost-per-case-usd 0.05",
    ]
    assert _recipe("s3-smoke-batch") == [
        "uv run python -m scripts.stage_spend --stage s3 --estimate 0.40",
        "uv run ntsb-eval run --arm C --sample dev-400 --limit 20 "
        "--expected-cost-per-case-usd 0.02",
    ]
    assert _recipe("s3-noise-floor") == [
        "uv run python -m scripts.stage_spend --stage s3 --estimate 5.00",
        "uv run ntsb-eval run --arm C --sample dev-400 --expected-cost-per-case-usd 0.012",
    ]
    round_recipe = _recipe("s3-round")
    assert round_recipe[0].startswith("$(if $(N),,$(error N is required")
    assert round_recipe[1:] == [
        "uv run python -m scripts.stage_spend --stage s3 --estimate 5.00",
        "uv run ntsb-eval run --arm C --sample dev-400 --round $(N) "
        "--expected-cost-per-case-usd 0.012",
    ]


def test_the_free_targets_refuse_missing_variables() -> None:
    report = _recipe("s3-noise-report")
    assert report[0].startswith("$(if $(RUNS),,$(error RUNS is required")
    assert report[1] == (
        "uv run python -m scripts.s3_noise_floor $(RUNS) --out docs/results/s3-noise-floor-dev.txt"
    )
    result = _recipe("s3-round-result")
    assert result[0].startswith("$(if $(N),,$(error N is required")
    for variable in ("RUN", "REFERENCE", "NOISE"):
        assert f"$(if $({variable}),,$(error {variable} is required" in result[1]
    assert result[2] == (
        "uv run python -m scripts.round_result --run $(RUN) --reference $(REFERENCE) "
        "--noise $(NOISE) --append docs/rounds/s3-round-$(N).md"
    )
