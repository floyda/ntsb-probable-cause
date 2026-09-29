"""Tests for ``scripts/s3_probe/report.py``, offline, from synthetic ``CaseTrail`` objects.

Three cases, built by hand rather than run through the loop, so every count in the report can
be checked against a value worked out on paper: ``_case_a`` reaches every stage (H_all runs);
``_case_b`` fails at H0, before any stage or read choice is reached; ``_case_c`` reads
everything offered at choice 1, so H_all is "not needed". Every text field that must never
reach the report (the case ID, a document-choice reason, a tool result, a hypothesis's own
prose) carries a distinctive marker the tests assert is absent from the report text.

The same three cases are built again, independently, in ``test_s3_probe_trails.py`` (a cross-
test-module import falls outside this project's ``mypy`` configuration, which does not add
``tests/`` to ``mypy_path`` -- see that file's own docstring).
"""

import json
from pathlib import Path

from scripts.s3_probe.prompts import DocumentChoice
from scripts.s3_probe.report import build_report, cmd_report
from scripts.s3_probe.trail import (
    NOT_REACHED,
    CallRecord,
    CaseTrail,
    CodingStep,
    ReadChoiceRecord,
    Stage,
    StageScores,
    TrailDocument,
)

from ntsb_probable_cause.scoring.hypothesis import FindingGuess, Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring.records import write_jsonl

TRUTH, OTHER = "552230", "552090"
CATEGORY, MODIFIER, ITEM = "010620", "20", "01062000"
FINDING_CODE = f"{ITEM}{MODIFIER}"

MARKER = "NEVER_LEAK_MARKER_7f3a"
CASE_A_ID = "DEV-MARKER-CASE-ALPHA"
CASE_B_ID = "DEV-MARKER-CASE-BRAVO"
CASE_C_ID = "DEV-MARKER-CASE-CHARLIE"


def _guess(code: str, p: float) -> OccurrenceGuess:
    return OccurrenceGuess(phase=code[:3], event=code[3:], probability=p)


def _hyp(
    *,
    top: str = TRUTH,
    second: str | None = OTHER,
    findings: bool = True,
    abstain: bool = False,
) -> Hypothesis:
    occurrence = [_guess(top, 0.6)]
    if second is not None:
        occurrence.append(_guess(second, 0.2))
    return Hypothesis(
        evidence_narrative=f"{MARKER}: evidence narrative.",
        occurrence=tuple(occurrence),
        findings=(FindingGuess(category6=CATEGORY, modifier=MODIFIER, probability=0.5),)
        if findings
        else (),
        probable_cause=f"{MARKER}: probable cause.",
        lay_explanation=f"{MARKER}: lay explanation.",
        confidence=0.5,
        abstain=abstain,
        evidence_used=(),
    )


def _scores(*, top1: bool, top3: bool, recall: float | None = None) -> StageScores:
    return StageScores(occurrence_top1=top1, occurrence_top3=top3, finding_recall_10=recall)


def _stage(hyp: Hypothesis | None, note: str | None, scores: StageScores | None) -> Stage:
    return Stage(hypothesis=hyp, note=note, scores=scores)


def _call(phase: str, prompt_tokens: int, *, retry: bool = False) -> CallRecord:
    return CallRecord(
        phase=phase,
        prompt_tokens=prompt_tokens,
        completion_tokens=50,
        reasoning_tokens=10,
        cost_usd=0.001,
        estimated_usd=0.001,
        seconds=1.5,
        finish_reason="stop",
        parse_retry=retry,
    )


def _doc(index: int, kind: str, tokens: int, *, attachable: bool = True) -> TrailDocument:
    return TrailDocument(
        index=index,
        kind=kind,
        pages=2,
        readable_pages=2,
        estimated_tokens=tokens,
        transcribed_pages=0,
        attachable=attachable,
    )


def _choice(offered: tuple[int, ...], read: tuple[int, ...]) -> ReadChoiceRecord:
    documents = tuple(
        DocumentChoice(index=i, read=i in read, expected_effect=f"{MARKER}: expected effect")
        for i in offered
    )
    return ReadChoiceRecord(offered=offered, documents=documents, reason=f"{MARKER}: reason")


def _step(tool: str | None, codes: tuple[str, ...], *, errors: int = 0) -> CodingStep:
    return CodingStep(
        done=tool is None,
        tool=tool,
        kind=None if tool is None else "occurrence",
        codes=codes,
        reason=f"{MARKER}: coding reason",
        expected_effect=f"{MARKER}: coding expected effect",
        top3=(_guess(TRUTH, 0.5),),
        result_text=None if tool is None else f"{MARKER}: tool result text",
        result_chars=0 if tool is None else len(f"{MARKER}: tool result text"),
        argument_errors=errors,
    )


def _case_a() -> CaseTrail:
    """Reaches every stage; H_all runs (it read only 2 of 3 attachable documents)."""
    h0 = _hyp(top=TRUTH)
    h1 = _hyp(top=OTHER)
    h2 = _hyp(top=TRUTH)
    h_all = _hyp(top=OTHER)
    final = _hyp(top=TRUTH)
    refined = _hyp(top=TRUTH)
    return CaseTrail(
        case_id=CASE_A_ID,
        fatal=True,
        has_scan=True,
        documents=(
            _doc(1, "born-digital", 500),
            _doc(2, "scan", 5000),
            _doc(3, "scan", 15000),
        ),
        calls=(
            _call("h0", 100),
            _call("choice1", 150),
            _call("h1", 160),
            _call("choice2", 170),
            _call("h2", 180),
            _call("h_all", 190),
            _call("coding", 200),
            _call("coding", 210),
            _call("final", 220),
            _call("refine", 230),
        ),
        choice1=_choice((1, 2, 3), (1,)),
        choice1_note=None,
        choice2=_choice((2, 3), (2,)),
        choice2_note=None,
        h0=_stage(h0, None, _scores(top1=True, top3=True)),
        h1=_stage(h1, None, _scores(top1=False, top3=True)),
        h2=_stage(h2, None, _scores(top1=True, top3=True)),
        h_all=_stage(h_all, None, _scores(top1=False, top3=False)),
        final=_stage(final, None, _scores(top1=True, top3=True)),
        refined=_stage(refined, None, _scores(top1=True, top3=True, recall=0.5)),
        coding_steps=(
            _step("describe_codes", (TRUTH,)),
            _step("occurrence_usage", (TRUTH, OTHER), errors=1),
            _step(None, ()),
        ),
        pool_top=OTHER,
        follows_pool=False,
        true_primary=TRUTH,
        true_in_arguments=True,
        true_findings=(FINDING_CODE,),
        leak=None,
        failure=None,
        coding_stop="done",
        stop_reason="done",
        cost_usd=0.01,
    )


def _case_b() -> CaseTrail:
    """Fails at H0: no stage, no read choice and no coding step is ever reached."""
    return CaseTrail(
        case_id=CASE_B_ID,
        fatal=False,
        has_scan=False,
        documents=(_doc(1, "born-digital", 300),),
        calls=(_call("h0", 90), _call("h0", 95, retry=True)),
        choice1=None,
        choice1_note=None,
        choice2=None,
        choice2_note=None,
        h0=NOT_REACHED,
        h1=NOT_REACHED,
        h2=NOT_REACHED,
        h_all=NOT_REACHED,
        final=NOT_REACHED,
        refined=NOT_REACHED,
        coding_steps=(),
        pool_top=None,
        follows_pool=None,
        true_primary=TRUTH,
        true_in_arguments=None,
        true_findings=(FINDING_CODE,),
        leak=None,
        failure=f"{MARKER}: the model's reply would not parse",
        coding_stop=None,
        stop_reason="failed: h0",
        cost_usd=0.002,
    )


def _case_c() -> CaseTrail:
    """Reads the only attachable document at choice 1; H_all is "not needed"."""
    h0 = _hyp(top=TRUTH)
    h1 = _hyp(top=TRUTH)
    final = _hyp(top=OTHER, abstain=True, findings=False)
    return CaseTrail(
        case_id=CASE_C_ID,
        fatal=False,
        has_scan=False,
        documents=(_doc(4, "born-digital", 800),),
        calls=(_call("h0", 120), _call("choice1", 130), _call("h1", 140), _call("final", 160)),
        choice1=_choice((4,), (4,)),
        choice1_note=None,
        choice2=None,
        choice2_note="skipped: nothing left to offer",
        h0=_stage(h0, None, _scores(top1=True, top3=True)),
        h1=_stage(h1, None, _scores(top1=True, top3=True)),
        h2=_stage(h1, "skipped: nothing more chosen", _scores(top1=True, top3=True)),
        h_all=_stage(None, "not needed", None),
        final=_stage(final, None, _scores(top1=False, top3=False)),
        refined=_stage(None, "not run: abstained", None),
        coding_steps=(_step(None, ()),),  # the checks ran; the first call was already "done"
        pool_top=None,
        follows_pool=None,
        true_primary=OTHER,
        true_in_arguments=None,
        true_findings=(),
        leak=None,
        failure=None,
        coding_stop="done",
        stop_reason="done",
        cost_usd=0.004,
    )


def _write_job(tmp_path: Path) -> Path:
    job_dir = tmp_path / "s3-probe-20260929T000000-abc1234"
    job_dir.mkdir()
    probe = {
        "job_id": job_dir.name,
        "commit_sha": "abc1234",
        "dirty": False,
        "model": "openai/gpt-6-luna",
        "price_variant": "standard",
        "reasoning_effort": "medium",
        "max_output_tokens": 8000,
        "prompt_version": "s1-v6",
        "guidance": ["r3-loc-stall", "r6-aircraft-control"],
        "case_cap_usd": 0.15,
        "run_cap_usd": 3.0,
        "selection_seed": 20260929,
        "per_cell_counts": {
            "fatal=False has_scan=False": 1,
            "fatal=False has_scan=True": 0,
            "fatal=True has_scan=False": 0,
            "fatal=True has_scan=True": 1,
        },
        "cases_selected": 3,
        "cases_run": 3,
        "started": "2026-09-29T00:00:00+00:00",
        "finished": "2026-09-29T00:05:00+00:00",
    }
    (job_dir / "probe.json").write_text(json.dumps(probe))
    write_jsonl(job_dir / "trails.jsonl", [_case_a(), _case_b(), _case_c()])
    return job_dir


def test_report_first_line(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    assert text.splitlines()[0] == (
        "Learning probe, not a result: n=3; every figure below is a signal, not a finding."
    )


def test_report_never_names_a_case(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    for needle in (CASE_A_ID, CASE_B_ID, CASE_C_ID, MARKER):
        assert needle not in text


def test_report_settings_block(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    assert "model: openai/gpt-6-luna" in text
    assert "reasoning_effort: medium" in text
    assert "guidance: r3-loc-stall, r6-aircraft-control" in text
    assert "cases_selected: 3" in text


def test_documents_section_denominators(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    # Case A offers 3 at choice 1 (1 chosen) and 2 at choice 2 (1 chosen); case C offers 1 at
    # choice 1 (1 chosen) and 0 at choice 2; case B never reaches choice 1.
    assert "documents offered at choice 1: 4" in text
    assert "documents chosen at choice 1: 2 of 4 (50.0%)" in text
    assert "documents offered at choice 2: 2" in text
    assert "documents chosen at choice 2: 1 of 2 (50.0%)" in text
    # Read choice 2: ran in case A, skipped (nothing left) in case C, never reached in case B.
    assert "read choice 2 happened: 1 of 2 (50.0%) of cases with documents left" in text
    assert "nothing left to offer: 1; not reached: 1" in text


def test_hypotheses_section_denominators(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    # H0 is scored in cases A and C (case B never reaches it): both correct.
    assert "H0 occurrence top-1: 2 of 2 (100.0%)" in text
    assert "H0 occurrence top-3: 2 of 2 (100.0%)" in text
    # H_all is scored only in case A (not needed in C, never reached in B).
    assert "H_all occurrence top-1: 0 of 1 (0.0%)" in text
    assert "finding recall@10 mean at refined: 50.0% (n=1)" in text


def test_skip_regret_section(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    assert "H_all ran: 1 of 3 (33.3%)" in text
    assert "H_all top-1 differs from H2: 1 of 1 (100.0%)" in text
    assert "H2 right, H_all wrong: 1 of 1" in text


def test_coding_section(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    assert "cases that reached the coding checks: 2 of 3 (66.7%)" in text
    assert "tool calls by tool: describe_codes: 1, occurrence_usage: 1" in text
    assert "argument errors: 1 of 2 (50.0%) of tool calls" in text
    assert "distinct codes passed to coding tools: 2" in text


def test_cost_section(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    assert "total cost: $0.0160 (n=3 cases)" in text
    # phase "h0" appears on every call attempt: case A (100), case B's two failed attempts
    # (90, 95) and case C (120) -- mean (100+90+95+120)/4 = 101.25.
    assert "h0: mean 101, max 120 (n=4)" in text


def test_cmd_report_writes_out_file(tmp_path: Path) -> None:
    job_dir = _write_job(tmp_path)
    out = tmp_path / "out.txt"
    text = cmd_report(job_dir, out=out)
    assert out.read_text() == text
    for needle in (CASE_A_ID, CASE_B_ID, CASE_C_ID, MARKER):
        assert needle not in out.read_text()
