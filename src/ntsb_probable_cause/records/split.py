"""The only place a case record is split (CLAUDE.md rule 1; decisions 0013, 0016)."""

from collections.abc import Mapping

from ntsb_probable_cause import fields
from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.fields import EvidenceRole, VerdictRole
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.guard import (
    MIN_SENTENCE_CHARS,
    NARRATIVE_COVERAGE_MARK,
    narrative_shares,
    screen,
)
from ntsb_probable_cause.records.marks import CaseMark
from ntsb_probable_cause.records.synthesis import Synthesis
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.sources import docket_url


def split_record(
    raw: Mapping[str, object],
    *,
    exclude: frozenset[EvidenceRole] = frozenset(),
    min_sentence_chars: int = MIN_SENTENCE_CHARS,
) -> tuple[Evidence, Synthesis, Verdict]:
    """Split a raw record into evidence, synthesis and verdict, failing closed on any leak.

    Marks (S2.6 spec §4) are computed here, from the same screen, and returned on the
    evidence as bookkeeping.
    """
    case_id = raw.get("ntsbNumber")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("record has no ntsbNumber")
    mkey = raw.get("mKey")
    values = {f.role.value: f.extract(raw) for f in fields.EVIDENCE_FIELDS if f.role not in exclude}
    evidence = Evidence.model_validate(
        {
            "case_id": case_id,
            "docket_url": docket_url(mkey) if isinstance(mkey, int) else None,
            "excluded": exclude,
            **values,
        }
    )
    synthesis = Synthesis(
        factual_narrative=fields.factual_narrative(raw),
        analysis_narrative=fields.analysis_narrative(raw),
    )
    verdict = Verdict(
        probable_cause=fields.probable_cause(raw),
        occurrence_codes=fields.occurrence_codes(raw),
        finding_codes=fields.finding_codes(raw),
        finding_codes_in_cause=fields.finding_codes_in_cause(raw),
    )
    withheld = {**synthesis.texts(), VerdictRole.PROBABLE_CAUSE: verdict.probable_cause}
    role_values = {role.value: value for role, value in evidence.role_values().items()}
    screened = screen(role_values, withheld, verdict.codes(), min_sentence_chars=min_sentence_chars)
    if screened.leaks:
        summary = "; ".join(str(leak) for leak in screened.leaks[:5])
        raise LeakageError(f"{case_id}: {summary}", leaks=screened.leaks)
    marks: list[CaseMark] = []
    if screened.marked:
        marks.append(CaseMark(kind="analysis_sentence", count=len(screened.marked)))
    shares = narrative_shares(
        evidence.docket_documents or (),
        synthesis.factual_narrative,
        min_sentence_chars=min_sentence_chars,
    )
    covering = sum(1 for share in shares if share >= NARRATIVE_COVERAGE_MARK)
    if covering:
        marks.append(CaseMark(kind="narrative_coverage", count=covering))
    marked = evidence.model_copy(
        update={"marks": tuple(marks), "narrative_share": max(shares, default=None)}
    )
    return marked, synthesis, verdict
