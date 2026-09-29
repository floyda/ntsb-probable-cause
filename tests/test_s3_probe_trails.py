"""Tests for ``scripts/s3_probe/trails_md.py``, offline, from synthetic ``CaseTrail`` objects.

Builds the same three cases as ``test_s3_probe_report.py`` (a full case, one that fails at H0,
and one where H_all is "not needed") independently rather than importing them: this project's
``mypy`` configuration (``pyproject.toml``, ``[tool.mypy]``) checks every file under ``tests/``
but does not add ``tests/`` itself to ``mypy_path``, so a test module cannot import a sibling
test module by name under ``mypy --strict``. Unlike the report, these files are meant to carry
the case ID and the agent's own words; the tests check the opposite direction -- that a marker
placed in every text field is *present* -- and that every file lands under the job folder's own
``trails/`` directory, in run order, and nowhere else.
"""

from pathlib import Path

from scripts.s3_probe.prompts import DocumentChoice
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
from scripts.s3_probe.trails_md import render_trail, write_trails

from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import FindingGuess, Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring.records import write_jsonl

TABLES = load_tables()
TRUTH, OTHER = "552230", "552090"
CATEGORY, MODIFIER, ITEM = "010620", "20", "01062000"
FINDING_CODE = f"{ITEM}{MODIFIER}"

MARKER = "NEVER_LEAK_MARKER_7f3a"
CASE_A_ID = "DEV-MARKER-CASE-ALPHA"
CASE_B_ID = "DEV-MARKER-CASE-BRAVO"
CASE_C_ID = "DEV-MARKER-CASE-CHARLIE"


def _guess(code: str, p: float) -> OccurrenceGuess:
    return OccurrenceGuess(phase=code[:3], event=code[3:], probability=p)


def _hyp(*, top: str = TRUTH, findings: bool = True, abstain: bool = False) -> Hypothesis:
    return Hypothesis(
        evidence_narrative=f"{MARKER}: evidence narrative.",
        occurrence=(_guess(top, 0.6),),
        findings=(FindingGuess(category6=CATEGORY, modifier=MODIFIER, probability=0.5),)
        if findings
        else (),
        probable_cause=f"{MARKER}: probable cause.",
        lay_explanation=f"{MARKER}: lay explanation.",
        confidence=0.5,
        abstain=abstain,
        evidence_used=(),
    )


def _scores(*, top1: bool, top3: bool) -> StageScores:
    return StageScores(occurrence_top1=top1, occurrence_top3=top3)


def _stage(hyp: Hypothesis | None, note: str | None, scores: StageScores | None) -> Stage:
    return Stage(hypothesis=hyp, note=note, scores=scores)


def _call(phase: str, prompt_tokens: int) -> CallRecord:
    return CallRecord(
        phase=phase,
        prompt_tokens=prompt_tokens,
        completion_tokens=50,
        reasoning_tokens=10,
        cost_usd=0.001,
        estimated_usd=0.001,
        seconds=1.5,
        finish_reason="stop",
        parse_retry=False,
    )


def _doc(index: int, kind: str, tokens: int) -> TrailDocument:
    return TrailDocument(
        index=index,
        kind=kind,
        pages=2,
        readable_pages=2,
        estimated_tokens=tokens,
        transcribed_pages=0,
        attachable=True,
    )


def _choice(offered: tuple[int, ...], read: tuple[int, ...]) -> ReadChoiceRecord:
    documents = tuple(
        DocumentChoice(index=i, read=i in read, expected_effect=f"{MARKER}: expected effect")
        for i in offered
    )
    return ReadChoiceRecord(offered=offered, documents=documents, reason=f"{MARKER}: reason")


def _step(tool: str | None) -> CodingStep:
    return CodingStep(
        done=tool is None,
        tool=tool,
        kind=None if tool is None else "occurrence",
        codes=() if tool is None else (TRUTH,),
        reason=f"{MARKER}: coding reason",
        expected_effect=f"{MARKER}: coding expected effect",
        top3=(_guess(TRUTH, 0.5),),
        result_text=None if tool is None else f"{MARKER}: tool result text",
        result_chars=0,
        argument_errors=0,
    )


def _case_a() -> CaseTrail:
    """Reaches every stage; H_all runs."""
    h = _hyp(top=TRUTH)
    return CaseTrail(
        case_id=CASE_A_ID,
        fatal=True,
        has_scan=True,
        documents=(_doc(1, "born-digital", 500), _doc(2, "scan", 5000)),
        calls=(_call("h0", 100), _call("choice1", 150)),
        choice1=_choice((1, 2), (1,)),
        choice1_note=None,
        choice2=_choice((2,), (2,)),
        choice2_note=None,
        h0=_stage(h, None, _scores(top1=True, top3=True)),
        h1=_stage(h, None, _scores(top1=True, top3=True)),
        h2=_stage(h, None, _scores(top1=True, top3=True)),
        h_all=_stage(h, None, _scores(top1=True, top3=True)),
        final=_stage(h, None, _scores(top1=True, top3=True)),
        refined=_stage(h, None, _scores(top1=True, top3=True)),
        coding_steps=(_step("describe_codes"), _step(None)),
        pool_top=TRUTH,
        follows_pool=True,
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
        calls=(_call("h0", 90),),
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
    h = _hyp(top=OTHER, abstain=True, findings=False)
    return CaseTrail(
        case_id=CASE_C_ID,
        fatal=False,
        has_scan=False,
        documents=(_doc(4, "born-digital", 800),),
        calls=(_call("h0", 120),),
        choice1=_choice((4,), (4,)),
        choice1_note=None,
        choice2=None,
        choice2_note="skipped: nothing left to offer",
        h0=_stage(h, None, _scores(top1=False, top3=False)),
        h1=_stage(h, None, _scores(top1=False, top3=False)),
        h2=_stage(h, "skipped: nothing more chosen", _scores(top1=False, top3=False)),
        h_all=_stage(None, "not needed", None),
        final=_stage(h, None, _scores(top1=False, top3=False)),
        refined=_stage(None, "not run: abstained", None),
        coding_steps=(_step(None),),
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
    write_jsonl(job_dir / "trails.jsonl", [_case_a(), _case_b(), _case_c()])
    return job_dir


def test_render_trail_carries_the_case_id_and_the_agents_own_words() -> None:
    text = render_trail(TABLES, _case_a())
    assert text.startswith(f"# {CASE_A_ID}\n")
    assert MARKER in text  # the case's own reasons, expected effects and tool results


def test_render_trail_on_a_case_that_failed_at_h0() -> None:
    text = render_trail(TABLES, _case_b())
    assert f"# {CASE_B_ID}" in text
    assert "(absent: not reached)" in text
    assert "(not reached: not reached)" in text  # neither read choice was ever reached
    assert "### Coding checks" in text
    assert "(none)" in text  # the coding checks were never reached either


def test_render_trail_on_a_case_where_h_all_was_not_needed() -> None:
    text = render_trail(TABLES, _case_c())
    assert f"# {CASE_C_ID}" in text
    assert "(absent: not needed)" in text
    assert "true flagged findings: none" in text


def test_write_trails_writes_one_file_per_case_in_run_order(tmp_path: Path) -> None:
    job_dir = _write_job(tmp_path)
    n = write_trails(job_dir)
    assert n == 3
    out_dir = job_dir / "trails"
    names = sorted(p.name for p in out_dir.iterdir())
    assert names == ["1.md", "2.md", "3.md"]
    assert (out_dir / "1.md").read_text().startswith(f"# {CASE_A_ID}\n")
    assert (out_dir / "2.md").read_text().startswith(f"# {CASE_B_ID}\n")
    assert (out_dir / "3.md").read_text().startswith(f"# {CASE_C_ID}\n")


def test_write_trails_writes_only_under_the_job_folder(tmp_path: Path) -> None:
    job_dir = _write_job(tmp_path)
    write_trails(job_dir)
    for path in tmp_path.rglob("*.md"):
        assert job_dir in path.parents
