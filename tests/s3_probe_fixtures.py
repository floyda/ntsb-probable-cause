"""Synthetic ``CaseTrail`` fixtures shared by ``tests/test_s3_probe_report.py`` and
``tests/test_s3_probe_trails.py``.

Not a ``test_*`` module, so pytest never collects it on its own; imported by both test modules
as ``from tests.s3_probe_fixtures import ...`` -- the package-qualified form, not a bare
``from s3_probe_fixtures import ...``, because this project's ``mypy --strict`` config
(``pyproject.toml``, ``[tool.mypy]``) does not add ``tests/`` itself to ``mypy_path``, only
``files``; ``tests/test_boundary.py``, ``tests/test_checkpass.py`` and
``tests/test_contamination.py`` already import their own shared helpers the same qualified way.
Three cases, built by hand rather than run through the loop, so every count in the report can
be checked against a value worked out on paper: ``case_a`` reaches every stage, with H_all a
genuine skip-regret comparison (it read only 2 of 3 attachable documents); ``case_b`` fails at
H0, before any stage or read choice is reached; ``case_c`` reads everything offered at choice
1, so H_all runs as the noise-only control (F7), with the note ``"control: all read"``. Every
text field that must never reach the report (the case ID, a document-choice reason, a tool
result, a hypothesis's own prose) carries a distinctive marker.
"""

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

from ntsb_probable_cause.scoring.hypothesis import FindingGuess, Hypothesis, OccurrenceGuess

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


def case_a() -> CaseTrail:
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


def case_b() -> CaseTrail:
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


def case_c() -> CaseTrail:
    """Reads the only attachable document at choice 1; H_all runs as the "all read" control."""
    h0 = _hyp(top=TRUTH)
    h1 = _hyp(top=TRUTH)
    h_all = _hyp(top=OTHER)
    final = _hyp(top=OTHER, abstain=True, findings=False)
    return CaseTrail(
        case_id=CASE_C_ID,
        fatal=False,
        has_scan=False,
        documents=(_doc(4, "born-digital", 800),),
        calls=(
            _call("h0", 120),
            _call("choice1", 130),
            _call("h1", 140),
            _call("h_all", 145),
            _call("final", 160),
        ),
        choice1=_choice((4,), (4,)),
        choice1_note=None,
        choice2=None,
        choice2_note="skipped: nothing left to offer",
        h0=_stage(h0, None, _scores(top1=True, top3=True)),
        h1=_stage(h1, None, _scores(top1=True, top3=True)),
        h2=_stage(h1, "skipped: nothing more chosen", _scores(top1=True, top3=True)),
        h_all=_stage(h_all, "control: all read", _scores(top1=False, top3=False)),
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
