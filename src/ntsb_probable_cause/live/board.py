"""The ``board/1`` export builder: run folders and later scores in, the public JSON out.

Everything this module writes is published, so it reads each source for the fields the format
holds and no others (decisions 0173, 0180, 0182; specification S4 section 10).

Sources, from the bucket mirror (``<mirror>/runs/<run>/`` and ``<mirror>/scores/*.jsonl``,
``<mirror>/nights/state.json``):

- ``closures.jsonl``: the grade inputs, documents, titles, timing and commit;
- ``inputs.jsonl``: the raw record, for the facts, the aircraft and the NTSB's verdict (through
  ``split_record``, never read by hand);
- ``cases.jsonl``: the checkpoints' hypotheses, from which the beliefs and the answer come;
- ``trail.jsonl``: each call's step, tool, arguments and cost;
- ``scores/*.jsonl``: a later score, when the NTSB's codes arrived after the case was coded;
- ``nights/state.json``: the cases settled unreachable.

The names step: every title passes ``names.board_title``; every cause, account, note, reason and
free-text lookup argument passes ``names.board_text`` with that case's own ``CaseNames``.

Open cases appear only as three counts, read from the store (decision 0024).

Only closure record version 2 is read. S3.3's version 1 folders stay on Andy's Mac and are never
uploaded; its cases are coded again in the cloud (decision 0179), so a version 1 record in the
mirror means something is wrong and the build raises ``ConfigurationError``.

Fail closed: a case with no ``inputs.jsonl``, no raw record, a coded record with no result in
``cases.jsonl``, or a raw record that ``split_record`` refuses, means the mirror is damaged or
half pulled. The build raises ``ConfigurationError`` with counts only and writes nothing; the
files are built in a temporary folder and moved into place on success, so a failed build leaves
the previous export intact.

Costs are assigned by tool and hypothesis, not by step: a ``submit_answer`` call at any step is
the answer's, a refinement is the answer's, a failed coding call goes to the next lookup. Any
cost left over is added to the last belief, so the trail's total is the sum of every call.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final

from ntsb_probable_cause.agent.run import TRAIL_FILE
from ntsb_probable_cause.agent.schemas import CODING_TOOLS, ChooseDocuments, DocumentDecision
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.docket.title_vocab import known_title_words
from ntsb_probable_cause.errors import ConfigurationError, LeakageError
from ntsb_probable_cause.live.closure import CASES_FILE
from ntsb_probable_cause.live.export import (
    BOARD_FORMAT,
    NOT_CODED_SENTENCES,
    Aircraft,
    Answer,
    Belief,
    BoardIndex,
    BoardRow,
    BuildStamp,
    CaseFile,
    Code,
    CodeMark,
    Comparison,
    Counts,
    DocumentChoice,
    Facts,
    Grade,
    Lookup,
    MarkedCode,
    NotCoded,
    ReadChoice,
    Trail,
    Verdict,
    Withheld,
)
from ntsb_probable_cause.live.later import LaterScore
from ntsb_probable_cause.live.morning import MODEL_ID, live_spec
from ntsb_probable_cause.live.names import CaseNames, board_text, board_title, case_names
from ntsb_probable_cause.live.queue import build_queue, closures_per_night
from ntsb_probable_cause.live.records import (
    CLOSURES_FILE,
    INPUTS_FILE,
    ClosureRecord,
    ClosureRecordV1,
    failure_kind,
    read_closure_records,
)
from ntsb_probable_cause.live.state import Closed, NightState
from ntsb_probable_cause.paths import resolve_path
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis
from ntsb_probable_cause.scoring.records import CaseResult, read_jsonl
from ntsb_probable_cause.sources import TRAINING_CUTOFFS
from ntsb_probable_cause.store import Store

INDEX_FILE: Final = "index.json"
CASES_DIR: Final = "cases"
STATE_PATH: Final = Path("nights") / "state.json"
_EXCLUSIONS: Final = live_spec(1.0).exclusions
_ENGINE_CHECKPOINT: Final = "checkpoint:"
_BELIEF_KINDS: Final = ("h0", "h1", "h2", "answer")
_SCAN_ONLY: Final = "unreadable: scan"
_ANSWER_TOOL: Final = "submit_answer"
_COST_EPSILON: Final = 1e-9


_NO_INPUTS: Final = "no inputs file"
_NO_RAW: Final = "no raw record"
_NO_RESULT: Final = "coded with no result"
_SPLIT_REFUSED: Final = "raw record refused by the split"


class _Damaged(Exception):  # noqa: N818 -- internal signal, turned into ConfigurationError
    """One case's sources are missing or unusable; ``args[0]`` is the kind (never a case)."""


@dataclass(frozen=True)
class ExportReport:
    """What one export wrote: numbers only, never a case."""

    cases: int
    unreachable: int
    grades: Mapping[str, int]


def occurrence_marks(
    agent: Sequence[str], ntsb: Sequence[str]
) -> tuple[list[CodeMark], list[CodeMark]]:
    """Mark each code of each list against the other: same place, other place, or absent."""

    def mark(own: Sequence[str], other: Sequence[str]) -> list[CodeMark]:
        out: list[CodeMark] = []
        for place, code in enumerate(own):
            if code not in other:
                out.append("not_in_other")
            elif other[place : place + 1] == [code]:
                out.append("same_place")
            else:
                out.append("other_place")
        return out

    return mark(agent, ntsb), mark(ntsb, agent)


def grade(
    record: ClosureRecord, later: LaterScore | None, *, abstained: bool | None = None
) -> Grade:
    """The board's grade of a case, from its closure record and any later score (spec 10.3).

    The order is: not coded, abstained, awaiting the NTSB's codes, then the codes' agreement.
    An abstain is Ellery's own judgement, known when the case was coded, so it outranks waiting.

    Args:
        record: the closure record.
        later: a later score, when the NTSB's codes arrived after the case was coded.
        abstained: the final answer's abstain flag (``cases.jsonl``). The record holds none for
            an unscored case, so the builder passes it; when None, the later score's or the
            record's flag is used.
    """
    if record.outcome == "not coded":
        return "not_coded"
    if abstained is None:
        abstained = later.abstained if later is not None else bool(record.abstained)
    if abstained:
        return "abstained"
    if later is not None:
        top1, top3 = later.top1, later.top3
    elif not record.scored:
        return "awaiting_ntsb"
    else:
        top1, top3 = bool(record.top1), bool(record.top3)
    if top1:
        return "same_first"
    return "same_codes_other_order" if top3 else "different"


def _occurrence_code(code: str, tables: CodeTables) -> Code:
    phase = tables.phases.get(code[:3])
    event = tables.events.get(code[3:])
    label = f"{phase} / {event}" if phase is not None and event is not None else code
    return Code(code=code, label=label)


def _finding_code(code: str, tables: CodeTables) -> Code:
    item = tables.items.get(code[:8])
    modifier = tables.modifiers.get(code[8:])
    label = f"{item} - {modifier}" if item is not None and modifier is not None else code
    return Code(code=code, label=label)


def _text(raw: Mapping[str, object], path: str) -> str | None:
    value = resolve_path(raw, path)
    return value if isinstance(value, str) and value else None


def _aircraft(raw: Mapping[str, object] | None) -> Aircraft:
    """Category and engines; the engine type too unless the aircraft is amateur-built."""
    if raw is None:
        return Aircraft(category=None, engines=None, engine_type=None)
    engines = resolve_path(raw, "aircrafts[0].aircraftNumberOfEngines")
    number = engines if isinstance(engines, int) and not isinstance(engines, bool) else None
    if number is None and isinstance(engines, str) and engines.strip().isdigit():
        number = int(engines.strip())
    # Fail closed, as fields.py does: anything but False or absent counts as amateur-built.
    flag = resolve_path(raw, "aircrafts[0].aircraftAmateurBuilt")
    amateur = not (flag is False or flag is None)
    return Aircraft(
        category=_text(raw, "aircrafts[0].aircraftCategory"),
        engines=number,
        engine_type=None if amateur else _text(raw, "aircrafts[0].engines[0].engineType"),
    )


_Codes = tuple[tuple[str, ...], tuple[str, ...], str | None]


def _record_verdict(raw: Mapping[str, object], *, coded: bool) -> _Codes | None:
    """The NTSB's occurrence codes, finding codes and cause in ``raw``, through ``split_record``.

    None when the record holds no occurrence codes. A record the split refuses is an ordinary
    outcome for a case that was not coded ("not coded: leak"): its verdict is None, and it is
    never read another way. For a coded case it is damage: the build fails closed
    (:class:`_Damaged`).
    """
    try:
        verdict = split_record(raw, exclude=_EXCLUSIONS)[2]
    except LeakageError:
        if coded:
            raise _Damaged(_SPLIT_REFUSED) from None
        return None
    if not verdict.occurrence_codes:
        return None
    return verdict.occurrence_codes, verdict.finding_codes, verdict.probable_cause


def _verdict(
    record_verdict: _Codes | None,
    later: LaterScore | None,
    names: CaseNames,
    tables: CodeTables,
) -> Verdict | None:
    if later is not None:
        occurrence, findings, cause = (
            later.verdict_occurrence,
            later.verdict_findings,
            later.ntsb_cause,
        )
    elif record_verdict is not None:
        occurrence, findings, cause = record_verdict
    else:
        return None
    return Verdict(
        occurrence=tuple(_occurrence_code(c, tables) for c in occurrence),
        findings=tuple(_finding_code(c, tables) for c in findings),
        cause=None if cause is None else board_text(cause, names),
    )


def _comparison(
    answer: Answer,
    verdict: Verdict,
    precision: float | None,
    recall: float | None,
) -> Comparison:
    agent_marks, ntsb_marks = occurrence_marks(
        [c.code for c in answer.occurrence], [c.code for c in verdict.occurrence]
    )
    agent_set = {c.code for c in answer.findings}
    ntsb_set = {c.code for c in verdict.findings}
    return Comparison(
        agent_occurrence=tuple(
            MarkedCode(code=c.code, label=c.label, mark=m)
            for c, m in zip(answer.occurrence, agent_marks, strict=True)
        ),
        ntsb_occurrence=tuple(
            MarkedCode(code=c.code, label=c.label, mark=m)
            for c, m in zip(verdict.occurrence, ntsb_marks, strict=True)
        ),
        findings_both=tuple(c for c in answer.findings if c.code in ntsb_set),
        findings_ntsb_only=tuple(c for c in verdict.findings if c.code not in agent_set),
        findings_agent_only=tuple(c for c in answer.findings if c.code not in ntsb_set),
        finding_precision_10=precision,
        finding_recall_10=recall,
    )


def _first(hypothesis: Hypothesis, tables: CodeTables) -> Code:
    return _occurrence_code(hypothesis.occurrence_codes(tables)[0], tables)


def _answer(hypothesis: Hypothesis, names: CaseNames, tables: CodeTables) -> Answer:
    return Answer(
        occurrence=tuple(_occurrence_code(c, tables) for c in hypothesis.occurrence_codes(tables)),
        findings=tuple(_finding_code(c, tables) for c in hypothesis.finding_codes(tables)),
        cause=board_text(hypothesis.probable_cause, names),
        confidence=hypothesis.confidence,
        abstained=hypothesis.abstain,
    )


def _belief_costs(calls: Sequence[AgentCall]) -> dict[str, float]:
    """Each call's cost to the hypothesis it belongs to, by tool and step.

    A ``submit_answer`` call at any step, and a refinement, belong to the answer; a hypothesis
    step's calls (failed ones too) to that hypothesis. Read choices and coding lookups are
    costed apart (:func:`_read_choices`, :func:`_lookups`).
    """
    cost: defaultdict[str, float] = defaultdict(float)
    for call in calls:
        if call.tool == _ANSWER_TOOL or call.step == "refine":
            cost["answer"] += call.cost_usd
        elif call.step in _BELIEF_KINDS:
            cost[call.step] += call.cost_usd
    return cost


def _beliefs(
    result: CaseResult, calls: Sequence[AgentCall], names: CaseNames, tables: CodeTables
) -> tuple[Belief, ...]:
    """One belief per checkpoint; the refinement is folded into the answer it refines."""
    cost = _belief_costs(calls)
    beliefs: list[Belief] = []
    for step in result.steps:
        kind = step.tool.removeprefix(_ENGINE_CHECKPOINT)
        hypothesis = step.hypothesis
        if kind == "refine" and beliefs and beliefs[-1].kind == "answer":
            before = beliefs[-2].first.code if len(beliefs) > 1 else None
            first = _first(hypothesis, tables)
            beliefs[-1] = beliefs[-1].model_copy(
                update={
                    "first": first,
                    "cause": board_text(hypothesis.probable_cause, names),
                    "account": board_text(hypothesis.evidence_narrative, names),
                    "confidence": hypothesis.confidence,
                    "changed": before is not None and first.code != before,
                }
            )
            continue
        if kind not in _BELIEF_KINDS:
            continue
        first = _first(hypothesis, tables)
        beliefs.append(
            Belief.model_validate(
                {
                    "kind": kind,
                    "first": first,
                    "cause": board_text(hypothesis.probable_cause, names),
                    "account": board_text(hypothesis.evidence_narrative, names),
                    "confidence": hypothesis.confidence,
                    "changed": bool(beliefs) and first.code != beliefs[-1].first.code,
                    "cost_usd": round(cost[kind], 6),
                }
            )
        )
    return tuple(beliefs)


def _read_choices(
    record: ClosureRecord,
    calls: Sequence[AgentCall],
    names: CaseNames,
    known: frozenset[str],
) -> tuple[ReadChoice, ...]:
    choices: list[ReadChoice] = []
    for step in ("choice1", "choice2"):
        step_calls = [c for c in calls if c.step == step]
        accepted = [c for c in step_calls if c.protocol_error is None and c.tool is not None]
        if not accepted:
            continue
        call = accepted[-1]
        choice = ChooseDocuments.model_validate(call.arguments)
        decided: dict[int, DocumentDecision] = {}
        for each in choice.decisions:
            decided.setdefault(each.document, each)
        offered = set(call.offered)
        documents: list[DocumentChoice] = []
        for line in sorted(record.documents, key=lambda d: d.position):
            title = board_title(line.title, known, names)
            if line.position in offered:
                d = decided.get(line.position)
                read = d is not None and d.read
                note = d.expected_effect if d is not None and d.expected_effect else None
                documents.append(
                    DocumentChoice(
                        position=line.position,
                        title=title,
                        decision="read" if read else "skipped",
                        note=None if note is None else board_text(note, names),
                    )
                )
            else:
                documents.append(
                    DocumentChoice(
                        position=line.position,
                        title=title,
                        decision="scan_only" if line.status == _SCAN_ONLY else "not_offered",
                        note=None,
                    )
                )
        choices.append(
            ReadChoice.model_validate(
                {
                    "step": step,
                    "reason": board_text(choice.reason, names),
                    "documents": tuple(documents),
                    "cost_usd": round(sum(c.cost_usd for c in step_calls), 6),
                }
            )
        )
    return tuple(choices)


def _clean(value: object, names: CaseNames) -> object:
    """``value`` with every string passed through the names step, recursively."""
    if isinstance(value, str):
        return board_text(value, names)
    if isinstance(value, list | tuple):
        return [_clean(v, names) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v, names) for k, v in value.items()}
    return value


def _lookups(calls: Sequence[AgentCall], names: CaseNames) -> tuple[Lookup, ...]:
    lookups: list[Lookup] = []
    pending: float = 0.0
    for call in (c for c in calls if c.step == "coding" and c.tool != _ANSWER_TOOL):
        if call.tool in CODING_TOOLS and call.protocol_error is None:
            lookups.append(
                Lookup(
                    tool=call.tool,
                    arguments={k: _clean(v, names) for k, v in call.arguments.items()},
                    cost_usd=round(call.cost_usd + pending, 6),
                )
            )
            pending = 0.0
        else:
            pending += call.cost_usd
    if pending and lookups:
        last = lookups[-1]
        lookups[-1] = last.model_copy(update={"cost_usd": round(last.cost_usd + pending, 6)})
    return tuple(lookups)


def _trail(  # noqa: PLR0913, PLR0917 -- one case's sources
    record: ClosureRecord,
    result: CaseResult,
    calls: Sequence[AgentCall],
    names: CaseNames,
    tables: CodeTables,
    known: frozenset[str],
) -> Trail:
    beliefs = _beliefs(result, calls, names, tables)
    choices = _read_choices(record, calls, names, known)
    lookups = _lookups(calls, names)
    parts = sum(b.cost_usd for b in beliefs)
    parts += sum(c.cost_usd for c in choices) + sum(x.cost_usd for x in lookups)
    left = sum(c.cost_usd for c in calls) - parts
    if beliefs and abs(left) > _COST_EPSILON:
        # A call no part claimed (a failed read choice, a failed coding call with no lookup after
        # it): its cost is never dropped, it goes to the last belief.
        last = beliefs[-1]
        beliefs = (
            *beliefs[:-1],
            last.model_copy(update={"cost_usd": round(last.cost_usd + left, 6)}),
        )
        parts += left
    return Trail(beliefs=beliefs, read_choices=choices, lookups=lookups, total_usd=round(parts, 4))


def _took_days(closed_on: date, event_date: date) -> int:
    return (closed_on - event_date).days


def _not_coded(kind: str) -> NotCoded:
    return NotCoded(kind=kind, sentence=NOT_CODED_SENTENCES.get(kind, NOT_CODED_SENTENCES["other"]))


def _agent_first(case: CaseFile) -> Code | None:
    answer = case.answer
    if answer is None or answer.abstained or not answer.occurrence:
        return None
    return answer.occurrence[0]


def _row(case: CaseFile) -> BoardRow:
    verdict = case.verdict
    return BoardRow(
        case_number=case.case_number,
        closed_on=case.closed_on,
        took_days=case.took_days,
        aircraft=case.aircraft,
        agent_first=_agent_first(case),
        ntsb_first=verdict.occurrence[0] if verdict is not None and verdict.occurrence else None,
        grade=case.grade,
    )


@dataclass(frozen=True)
class _Run:
    folder: Path
    has_inputs: bool
    raws: Mapping[str, Mapping[str, object]]
    results: Mapping[str, CaseResult]
    calls: Mapping[str, Sequence[AgentCall]]


def _load_run(folder: Path) -> _Run:
    raws: dict[str, Mapping[str, object]] = {}
    inputs = folder / INPUTS_FILE
    if inputs.is_file():
        for line in inputs.read_text().splitlines():
            if line.strip():
                raw = json.loads(line)
                if isinstance(raw, dict) and isinstance(raw.get("ntsbNumber"), str):
                    raws[raw["ntsbNumber"]] = raw
    cases = folder / CASES_FILE
    results = {r.case_id: r for r in read_jsonl(cases, CaseResult)} if cases.is_file() else {}
    trail = folder / TRAIL_FILE
    by_case: dict[str, list[AgentCall]] = {}
    if trail.is_file():
        for call in read_jsonl(trail, AgentCall):
            by_case.setdefault(call.case_id, []).append(call)
    for case_calls in by_case.values():
        case_calls.sort(key=lambda c: c.call_index)
    return _Run(
        folder=folder, has_inputs=inputs.is_file(), raws=raws, results=results, calls=by_case
    )


def _later_scores(mirror: Path) -> dict[str, LaterScore]:
    """Every later score in ``scores/*.jsonl``; the first written for a case stands."""
    found: dict[str, LaterScore] = {}
    folder = mirror / "scores"
    for path in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        for score in read_jsonl(path, LaterScore):
            found.setdefault(score.case_id, score)
    return found


def _coded_case(
    record: ClosureRecord,
    run: _Run,
    later: LaterScore | None,
    known: frozenset[str],
    tables: CodeTables,
) -> CaseFile:
    """One case's file; raises :class:`_Damaged` when its sources are missing."""
    if not run.has_inputs:
        raise _Damaged(_NO_INPUTS)
    raw = run.raws.get(record.case_id)
    if raw is None:
        raise _Damaged(_NO_RAW)
    names = case_names(raw)
    result = run.results.get(record.case_id)
    coded = record.outcome == "coded"
    if coded and (result is None or not result.steps):
        raise _Damaged(_NO_RESULT)
    calls = run.calls.get(record.case_id, ())
    final = result.steps[-1].hypothesis if coded and result is not None else None
    the_grade = grade(record, later, abstained=None if final is None else final.abstain)
    verdict = _verdict(_record_verdict(raw, coded=coded), later, names, tables)
    facts = Facts(
        state=_text(raw, "eventStateOrRegion"),
        kind_of_flight=_text(raw, "aircrafts[0].ownerOperators[0].flightOperationType"),
        injury_level=_text(raw, "highestInjuryLevel"),
        documents_read=sum(1 for d in record.documents if d.ellery == "read"),
        documents_listed=len(record.documents),
    )
    base: dict[str, Any] = {
        "case_number": record.case_id,
        "closed_on": record.closed_on,
        "took_days": _took_days(record.closed_on, record.event_date),
        "aircraft": _aircraft(raw),
        "grade": the_grade,
        "facts": facts,
    }
    if final is None or result is None:
        kind = failure_kind(record.failure)
        return CaseFile(
            **base,
            withheld=None,
            answer=None,
            verdict=verdict,
            comparison=None,
            trail=None,
            not_coded=_not_coded(kind),
        )
    answer = _answer(final, names, tables)
    if later is not None:
        precision, recall = later.finding_precision_10, later.finding_recall_10
    elif result.scores is not None:
        precision, recall = result.scores.finding_precision_10, result.scores.finding_recall_10
    else:
        precision = recall = None
    return CaseFile(
        **base,
        withheld=Withheld(
            coded_at=record.first_sent,
            commit=record.commit_sha,
            prompt_version=record.prompt_version,
            model=record.model,
            replied_models=record.replied_models,
            providers=record.providers,
        ),
        answer=answer,
        verdict=verdict,
        comparison=None if verdict is None else _comparison(answer, verdict, precision, recall),
        trail=_trail(record, result, calls, names, tables, known),
        not_coded=None,
    )


def _unreachable_case(case_number: str, closed: Closed) -> CaseFile:
    return CaseFile(
        case_number=case_number,
        closed_on=closed.closed_on,
        took_days=_took_days(closed.closed_on, closed.event_date),
        aircraft=_aircraft(None),
        grade="not_coded",
        facts=None,
        withheld=None,
        answer=None,
        verdict=None,
        comparison=None,
        trail=None,
        not_coded=_not_coded("unreachable"),
    )


def _store_counts(store: Store | None, today: date) -> tuple[int, int, dict[date, int]]:
    """Open watched, open with a docket, and closures per night: counts only (decision 0024).

    The per-night counts are the closures the queue takes (``queue.build_queue``'s own
    selection: closed on or after the declared start), not every closure the store holds.
    """
    if store is None:
        return 0, 0, {}
    closures = store.closures()
    closed = {c.mkey for c in closures}
    open_mkeys = [m for m in store.watched_mkeys(today=today.isoformat()) if m not in closed]
    taken = {q.mkey for q in build_queue(closures, frozenset())}
    per_night = closures_per_night([c for c in closures if c.mkey in taken])
    with_docket = sum(1 for m in open_mkeys if store.documents_recorded(m) > 0)
    return len(open_mkeys), with_docket, dict(sorted(per_night.items()))


def _night_state(mirror: Path) -> NightState:
    path = mirror / STATE_PATH
    return NightState.model_validate_json(path.read_text()) if path.is_file() else NightState()


def _collect(mirror: Path) -> Iterable[tuple[ClosureRecord, _Run]]:
    runs = mirror / "runs"
    for folder in sorted(p for p in runs.iterdir() if p.is_dir()) if runs.is_dir() else []:
        closures = folder / CLOSURES_FILE
        if not closures.is_file():
            continue
        run = _load_run(folder)
        version_1 = 0
        for record in read_closure_records(closures):
            if isinstance(record, ClosureRecordV1):
                version_1 += 1
                continue
            yield record, run
        if version_1:
            raise ConfigurationError(
                f"export refused: {version_1} closure records in the mirror are version 1; "
                "S3.3's runs are never uploaded (decision 0179), so the mirror is wrong. "
                "Nothing was written."
            )


def _damaged_error(damage: Counter[str]) -> ConfigurationError:
    kinds = ", ".join(f"{count} {kind}" for kind, count in sorted(damage.items()))
    return ConfigurationError(
        f"export refused: the mirror is damaged or half pulled ({sum(damage.values())} cases: "
        f"{kinds}). Nothing was written; the previous export is unchanged."
    )


def _build_files(  # noqa: PLR0913 -- the builder's fixed interface
    mirror: Path,
    work: Path,
    *,
    store: Store | None,
    today: date,
    commit: str,
    now: datetime,
) -> ExportReport:
    """Write the whole export under ``work``, or raise before it is complete."""
    tables = load_tables()
    known, _ = known_title_words()
    later_scores = _later_scores(mirror)
    state = _night_state(mirror)
    cases: dict[str, CaseFile] = {}
    damage: Counter[str] = Counter()
    models: list[tuple[date, str]] = []
    for record, run in _collect(mirror):
        if record.case_id in cases:
            continue
        try:
            cases[record.case_id] = _coded_case(
                record, run, later_scores.get(record.case_id), known, tables
            )
        except _Damaged as error:
            damage[str(error.args[0])] += 1
            continue
        models.append((record.closed_on, record.model))
    if damage:
        raise _damaged_error(damage)
    for case_number, closed in state.unreachable.items():
        cases.setdefault(case_number, _unreachable_case(case_number, closed))

    model = max(models)[1] if models and max(models)[1] in TRAINING_CUTOFFS else MODEL_ID
    cutoff = TRAINING_CUTOFFS[model]
    rows = sorted(
        (_row(c) for c in cases.values()), key=lambda r: (-r.closed_on.toordinal(), r.case_number)
    )
    not_coded = Counter(c.not_coded.kind for c in cases.values() if c.not_coded is not None)
    grades = Counter(c.grade for c in cases.values())
    open_watched, open_with_docket, per_night = _store_counts(store, today)
    index = BoardIndex(
        stamp=BuildStamp(
            built_at=now,
            commit=commit,
            model=model,
            training_cutoff=cutoff.day,
            training_cutoff_source=cutoff.source,
        ),
        counts=Counts(
            open_watched=open_watched,
            open_with_docket=open_with_docket,
            closures_per_night=per_night,
            coded=len(cases) - sum(not_coded.values()),
            not_coded=dict(sorted(not_coded.items())),
            awaiting_ntsb=grades["awaiting_ntsb"],
        ),
        rows=tuple(rows),
    )
    cases_dir = work / CASES_DIR
    cases_dir.mkdir()
    for case in cases.values():
        (cases_dir / f"{case.case_number}.json").write_text(case.model_dump_json(indent=2) + "\n")
    (work / INDEX_FILE).write_text(index.model_dump_json(indent=2) + "\n")
    return ExportReport(
        cases=len(cases),
        unreachable=len(state.unreachable),
        grades=dict(sorted(grades.items())),
    )


def _move_into_place(work: Path, out: Path) -> None:
    """Replace ``out``'s ``cases/`` and ``index.json`` with the finished ones in ``work``."""
    out.mkdir(parents=True, exist_ok=True)
    old = work / "previous"
    old.mkdir()
    aside: list[str] = []
    try:
        for name in (CASES_DIR, INDEX_FILE):
            if (out / name).exists():
                shutil.move(out / name, old / name)
                aside.append(name)
            shutil.move(work / name, out / name)
    except BaseException:
        # Put the previous files back before the caller removes ``work``.
        for name in (CASES_DIR, INDEX_FILE):
            if (out / name).exists() and name in aside:
                shutil.rmtree(out / name) if (out / name).is_dir() else (out / name).unlink()
            if name in aside:
                shutil.move(old / name, out / name)
        raise


def write_export(  # noqa: PLR0913 -- the builder's fixed interface plus the report
    mirror: Path,
    out: Path,
    *,
    store: Store | None,
    today: date,
    commit: str,
    now: datetime,
) -> ExportReport:
    """Write the export under ``out`` and say what it holds, as numbers.

    Raises:
        ConfigurationError: when the mirror is damaged or holds a version 1 record. The message
            holds counts only, nothing is written, and a previous export under ``out`` stays.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{out.name}-build-", dir=out.parent))
    try:
        report = _build_files(mirror, work, store=store, today=today, commit=commit, now=now)
        _move_into_place(work, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return report


def build_export(  # noqa: PLR0913 -- the interface Task 10 calls
    mirror: Path,
    out: Path,
    *,
    store: Store | None,
    today: date,
    commit: str,
    now: datetime,
) -> Path:
    """Write ``index.json`` and ``cases/<case>.json`` under ``out``; return ``out``.

    The runs and scores come from the mirror, the open-case counts from the store's existing
    methods (counts only); ``store=None`` writes zero counts.

    Raises:
        ConfigurationError: as :func:`write_export`.
    """
    write_export(mirror, out, store=store, today=today, commit=commit, now=now)
    return out


__all__ = [
    "BOARD_FORMAT",
    "ExportReport",
    "build_export",
    "grade",
    "occurrence_marks",
    "write_export",
]
