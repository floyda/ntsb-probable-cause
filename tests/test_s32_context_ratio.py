"""scripts/s32_context_ratio.py: the estimate's undercount and the ceiling (S3.2 Task 15a).

Made-up run folders under ``tmp_path``; no real data. Offline. Decision 152.
"""

from pathlib import Path

import pytest
from scripts import s32_context_ratio as cr
from tests.test_s3_noise_floor import _IDS, _RUN_A, _RUN_B, _call, _plain, _record, _write

from ntsb_probable_cause import sources
from ntsb_probable_cause.agent.run import TRAIL_FILE
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, write_jsonl

_ARMB = "20261002T040000-abc1234-dev-400-B"
_TOOLS = _ARMB + "-tools"
# GPT-6 Luna at the batch price, and the test record's 2,000-token reply budget.
_IN, _OUT, _REPLY = 0.05, 0.25, 2000


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The runs folder, with ``dev-400`` taken to be the made-up ids ``_IDS``."""
    folder = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(folder))
    monkeypatch.setattr(samples, "sample_ids", lambda name: _IDS if name == "dev-400" else ())
    return folder


def _usd(tokens: float) -> float:
    return (tokens * _IN + _REPLY * _OUT) / 1e6


def _sized(case_id: str, estimate: float, real: int, index: int = 0) -> AgentCall:
    """A call whose estimate is ``estimate`` tokens and whose reply counted ``real``."""
    row = _call(case_id, "describe_codes", index=index, prompt_tokens=real)
    return row.model_copy(update={"estimated_usd": _usd(estimate)})


def _armb_record(run_id: str, **changes: object) -> RunRecord:
    return _record(run_id, len(_IDS), arm="B").model_copy(update=changes)


def _write_armb(
    runs: Path, cases: list[CaseResult], post_pass: list[AgentCall], **changes: object
) -> None:
    for run_id in (_ARMB, _TOOLS):
        folder = runs / run_id
        folder.mkdir(parents=True)
        write_jsonl(folder / "run.jsonl", [_armb_record(run_id, **changes)])
    write_jsonl(runs / _ARMB / "cases.jsonl", cases)
    write_jsonl(runs / _TOOLS / TRAIL_FILE, post_pass)


def test_the_estimate_is_recovered_from_the_estimated_cost() -> None:
    record = _record(_RUN_A, 1)
    assert cr.estimated_tokens(_sized("c1", 12_345, 1), record) == pytest.approx(12_345)


def test_the_estimate_follows_the_runs_price_variant_and_reply_budget() -> None:
    record = _record(_RUN_A, 1, price_variant="standard", max_output_tokens=8000)
    usd = (1000 * 0.10 + 8000 * 0.50) / 1e6  # GPT-6 Luna at the standard price
    call = _call("c1", None).model_copy(update={"estimated_usd": usd})
    assert cr.estimated_tokens(call, record) == pytest.approx(1000)


def test_ratios_leave_out_a_call_with_no_reply_and_are_sorted() -> None:
    record = _record(_RUN_A, 1)
    calls = [_sized("c1", 1000, 2000), _sized("c2", 1000, 0), _sized("c3", 1000, 900)]
    assert cr.ratios(calls, record) == pytest.approx([0.9, 2.0])


def test_the_percentile_is_nearest_rank() -> None:
    values = [float(n) for n in range(1, 101)]
    assert cr.percentile(values, 0.99) == 99.0
    assert cr.percentile(values, 0.5) == 50.0
    assert cr.percentile([3.0], 0.99) == 3.0


def test_the_ceiling_rule_and_its_rounding() -> None:
    assert cr.ceiling(2.4303) == (345_636, 345_000)
    assert cr.ceiling(1.0) == (840_000, 840_000)


def test_arm_b_is_bounded_by_the_post_pass_first_call_else_by_real_tokens() -> None:
    record = _record(_TOOLS, 1)
    plain = _plain(_IDS[:3])
    no_steps = plain[2].model_copy(update={"steps": ()})
    (step,) = plain[1].steps
    answered = plain[1].model_copy(
        update={"steps": (step.model_copy(update={"prompt_tokens": 120}),) * 2}
    )
    post = [_sized(_IDS[0], 500, 1, index=1), _sized(_IDS[0], 300, 1, index=0)]
    bound = cr.armb_bound([plain[0], answered, no_steps], post, record, min_ratio=0.5, limit=400)
    assert (bound.by_post_pass, bound.by_real, bound.sent_none) == (1, 1, 1)
    assert bound.by_post_pass_largest == pytest.approx(300)  # the first call, not the larger
    assert bound.by_real_largest == pytest.approx(480)  # both steps' 240 tokens / 0.5
    assert bound.over == 1  # 480 > 400; the post-pass case's 300 is not


def test_arm_b_over_the_limit_is_counted() -> None:
    record = _record(_TOOLS, 1)
    post = [_sized(_IDS[0], 500, 1), _sized(_IDS[1], 100, 1)]
    bound = cr.armb_bound(_plain(_IDS[:2]), post, record, min_ratio=1.0, limit=400)
    assert bound.over == 1


def test_main_writes_every_line_and_names_no_case(
    runs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(runs, _RUN_A, _plain(), [_sized(_IDS[0], 1000, 1200), _sized(_IDS[1], 1000, 0)])
    _write(runs, _RUN_B, _plain(), [_sized(_IDS[0], 2000, 1000)])
    _write_armb(runs, _plain(), [_sized(i, 3000, 3100) for i in _IDS])
    out_path = tmp_path / "results" / "ratio.txt"
    assert cr.main([_RUN_A, _RUN_B, "--armb", _ARMB, "--out", str(out_path)]) == 0
    text = out_path.read_text()
    assert text.rstrip() == capsys.readouterr().out.rstrip()
    assert "run a: 1 calls with a reply of 2; ratio real/estimated: min 1.2000" in text
    assert "run b: 1 calls with a reply of 1" in text
    assert "both runs: 2 calls; ratio median 0.8500, p99 1.2000, max 1.2000; above 1.5: 0" in text
    assert "ceiling: floor(0.8 x 1,050,000 / 1.2000) = 700,000 -> 700,000" in text
    assert "DIFFERENT: correct the literal" in text  # the literal is the real one, 345,000
    assert "over the ceiling: noise-floor calls 0 of 3 (largest estimate 2,000)" in text
    assert "over the ceiling: arm B dev-400 prompts 0 of 20 cases that sent one; 20" in text
    assert "over the ceiling: arm B post-pass calls 0 of 20 (largest estimate 3,000)" in text
    assert "ZQX" not in text


def test_main_counts_calls_over_the_literal_and_says_when_it_matches(
    runs: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sources, "PROMPT_TOKEN_CEILING", 1500)
    # max ratio 0.56 -> floor(840,000 / 0.56) = 1,500,000; the literal is 1,500 here, so it differs.
    _write(runs, _RUN_A, _plain(), [_sized(_IDS[0], 2000, 1120)])
    _write(runs, _RUN_B, _plain(), [_sized(_IDS[0], 1000, 500)])
    _write_armb(runs, _plain(_IDS[:1]), [_sized(_IDS[0], 1600, 1)])
    assert cr.main([_RUN_A, _RUN_B, "--armb", _ARMB]) == 0
    out = capsys.readouterr().out
    assert "noise-floor calls 1 of 2" in out
    assert "arm B dev-400 prompts 1 of 1" in out
    assert "arm B post-pass calls 1 of 1" in out


def test_the_literal_matching_the_rule_reads_the_same(
    runs: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sources, "PROMPT_TOKEN_CEILING", 700_000)
    _write(runs, _RUN_A, _plain(), [_sized(_IDS[0], 1000, 1200)])
    _write(runs, _RUN_B, _plain(), [_sized(_IDS[0], 1000, 1000)])
    _write_armb(runs, _plain(), [])
    cr.main([_RUN_A, _RUN_B, "--armb", _ARMB])
    assert "sources.PROMPT_TOKEN_CEILING = 700,000 (the same)" in capsys.readouterr().out


def test_a_held_out_arm_b_run_is_refused(runs: Path) -> None:
    _write(runs, _RUN_A, _plain(), [_sized(_IDS[0], 1000, 1200)])
    _write(runs, _RUN_B, _plain(), [_sized(_IDS[0], 1000, 1000)])
    with pytest.raises(SystemExit, match="held-out"):
        cr.main([_RUN_A, _RUN_B, "--armb", "20261002T040000-abc1234-heldout-400-B"])


def test_an_arm_b_run_that_is_not_arm_b_on_dev_400_is_refused(runs: Path) -> None:
    _write(runs, _RUN_A, _plain(), [_sized(_IDS[0], 1000, 1200)])
    _write(runs, _RUN_B, _plain(), [_sized(_IDS[0], 1000, 1000)])
    _write_armb(runs, _plain(), [], arm="C")
    with pytest.raises(SystemExit, match="not arm B on dev-400"):
        cr.main([_RUN_A, _RUN_B, "--armb", _ARMB])


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("missing", r"no run\.jsonl"),
        ("renamed", "names run"),
        ("unfinished", "has not finished"),
        ("no_trail", r"no trail\.jsonl"),
        ("held_out_case", "outside the dev split"),
    ],
)
def test_arm_b_refusals(runs: Path, change: str, message: str) -> None:
    _write(runs, _RUN_A, _plain(), [_sized(_IDS[0], 1000, 1200)])
    _write(runs, _RUN_B, _plain(), [_sized(_IDS[0], 1000, 1000)])
    if change != "missing":
        cases = _plain()
        if change == "held_out_case":
            cases[0] = cases[0].model_copy(update={"split": "heldout"})
        _write_armb(runs, cases, [])
        record = runs / _ARMB / "run.jsonl"
        if change == "renamed":
            record.unlink()  # write_jsonl appends
            write_jsonl(record, [_armb_record("another-run")])
        if change == "unfinished":
            record.unlink()
            write_jsonl(record, [_armb_record(_ARMB, finished=None)])
        if change == "no_trail":
            (runs / _TOOLS / TRAIL_FILE).unlink()
    with pytest.raises(SystemExit, match=message):
        cr.main([_RUN_A, _RUN_B, "--armb", _ARMB])
