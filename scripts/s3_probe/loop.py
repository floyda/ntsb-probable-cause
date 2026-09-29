"""scripts/s3_probe/loop.py: one case's hypothesis, read choices, coding checks and answer.

Status
    One-shot learning probe for S3 (2026-09-29). Output is not a result; it sets no bar and
    tunes nothing.

:func:`run_case` implements the eight steps of "The flow for one case" (``constraints.md``):
H0 from the structured evidence; a first read choice over the attachable documents; H1 from
what was chosen; a second read choice over what is left; H2; H_all, the read-everything
comparison (skip regret); up to six coding-tool checks; and the final answer, refined and
scored exactly as ``scoring/runner.py``'s ``_two_turns`` refines one.

Every payload is ``Payload.from_evidence(split_record(context)[0])`` -- ``context`` being the
record (docket subtree removed) or ``Attachment.context_for(indices).context`` -- and nothing
else (the "one payload route"). System text carries the existing prompt texts, this probe's
instructions, per-document numbers keyed by listing index, and tool results (code labels and
pool counts). History carries only the agent's own earlier replies.

Cost is checked before every call (:class:`CaseBudget`): the per-case cap stops the case with
``stop_reason="cap"``, the run-wide cap -- shared across the threads Task 5 runs cases on --
with ``"run_cap"``. A reply that fails to parse after its one retry ends the case with
``"failed: <phase>"``; a ``LeakageError`` from the split ends it with ``"failed: leak"``, the
guard's message recorded in the trail. Any other exception propagates.
"""

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from functools import cache

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.attach import DOCKET_KEY, Attachment, prepare_attachment
from ntsb_probable_cause.docket.manifest import Docket
from ntsb_probable_cause.errors import LeakageError, SchemaError
from ntsb_probable_cause.model.client import ModelClient, ModelSettings, Payload, Turn, cost_usd
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.coding_stats import CodingStats
from ntsb_probable_cause.scoring.hypothesis import (
    HYPOTHESIS_SCHEMA,
    REFINEMENT_SCHEMA,
    Hypothesis,
    parse_hypothesis,
    parse_refinement,
)
from ntsb_probable_cause.scoring.metrics import primary_occurrence, score_case
from ntsb_probable_cause.scoring.samples import sample_ids
from scripts.s3_probe.cases import DocketFacts, facts, has_scan
from scripts.s3_probe.prompts import (
    CODING_ACTION_SCHEMA,
    CODING_INSTRUCTIONS,
    FINAL_INSTRUCTION,
    READ_CHOICE_INSTRUCTIONS,
    READ_CHOICE_SCHEMA,
    CodingAction,
    base_system,
    menu,
    parse_coding_action,
    parse_read_choice,
)
from scripts.s3_probe.tools import TOOL_DESCRIPTIONS, run_tool
from scripts.s3_probe.trail import (
    NOT_REACHED,
    CallRecord,
    CaseTrail,
    CodingStep,
    Phase,
    ReadChoiceRecord,
    Stage,
    StageScores,
    TrailDocument,
)

CASE_CAP_USD = 0.15
RUN_CAP_USD = 3.00
# Held back for the coding checks and the final answer when deciding whether H_all runs.
CODING_RESERVE_USD = 0.03
MAX_CODING_CALLS = 6
MAX_OUTPUT_TOKENS = 8000  # decision 0084
_CHARS_PER_TOKEN = 4
_STAGES = ("h0", "h1", "h2", "h_all", "final", "refined")


def call_settings(schema: dict[str, object], name: str) -> ModelSettings:
    """The settings every probe call uses; only the reply schema and its name vary."""
    return ModelSettings(
        model=sources.DEFAULT_MODEL,
        price_variant="standard",
        reasoning_effort=sources.DEFAULT_REASONING_EFFORT,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        temperature=0.0,
        json_schema=schema,
        schema_name=name,
    )


class RunBudget:
    """The run-wide spend, shared by every case thread, and both caps.

    A call reserves its estimate before it is made and settles to its actual cost after, all
    under one lock, so threads checking at the same moment cannot together pass the run cap.
    """

    def __init__(
        self, *, run_cap_usd: float = RUN_CAP_USD, case_cap_usd: float = CASE_CAP_USD
    ) -> None:
        """Start a run with nothing spent."""
        self.run_cap_usd = run_cap_usd
        self.case_cap_usd = case_cap_usd
        self._lock = threading.Lock()
        self._spent = 0.0
        self._reserved = 0.0

    @property
    def spent(self) -> float:
        """Actual dollars spent by settled calls."""
        with self._lock:
            return self._spent

    def reserve(self, estimate: float) -> bool:
        """Hold ``estimate`` against the run cap; ``False`` (nothing held) if it would pass it."""
        with self._lock:
            if self._spent + self._reserved + estimate > self.run_cap_usd:
                return False
            self._reserved += estimate
            return True

    def settle(self, estimate: float, actual: float) -> None:
        """Release a reservation and add the call's actual cost."""
        with self._lock:
            self._reserved -= estimate
            self._spent += actual


class _Stop(Exception):  # noqa: N818 -- a signal, not an error
    """A cap refused the next call; ``reason`` is ``"cap"`` or ``"run_cap"``."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Failed(Exception):  # noqa: N818 -- a signal, not an error
    """A reply failed to parse after its one retry."""

    def __init__(self, phase: str, detail: str) -> None:
        super().__init__(detail)
        self.phase = phase
        self.detail = detail


class CaseBudget:
    """One case's spend, checked with the run's before every call."""

    def __init__(self, run: RunBudget) -> None:
        """Start a case with nothing spent, against ``run``'s caps."""
        self.run = run
        self.spent = 0.0

    @staticmethod
    def estimate(
        system: str, payload: Payload, history: Sequence[Turn], settings: ModelSettings
    ) -> float:
        """Estimated dollars: all input text at 4 characters a token, plus the full reply budget."""
        chars = len(system) + len(payload.text) + sum(len(t.content or "") for t in history)
        price = sources.price_of(settings.model_id())
        return (
            chars / _CHARS_PER_TOKEN * price.input_usd_per_mtok
            + settings.max_output_tokens * price.output_usd_per_mtok
        ) / 1e6

    def fits(self, estimate: float, *, reserve: float = 0.0) -> bool:
        """Whether a call of ``estimate``, with ``reserve`` held back, stays under the case cap."""
        return self.spent + estimate + reserve <= self.run.case_cap_usd

    def check(self, estimate: float) -> None:
        """Reserve ``estimate`` or stop the case: the case cap first, then the run cap."""
        if not self.fits(estimate):
            raise _Stop("cap")
        if not self.run.reserve(estimate):
            raise _Stop("run_cap")

    def settle(self, estimate: float, actual: float) -> None:
        """Record a finished (or failed) call's actual cost, here and on the run."""
        self.spent += actual
        self.run.settle(estimate, actual)


@cache
def _dev_ids() -> frozenset[str]:
    return frozenset(sample_ids("dev-400"))


def _payload(context: Mapping[str, object]) -> Payload:
    """The one payload route: the split's evidence, rendered."""
    return Payload.from_evidence(split_record(context)[0])


def _settings_by_phase() -> dict[str, ModelSettings]:
    hypothesis = call_settings(HYPOTHESIS_SCHEMA, "hypothesis")
    choice = call_settings(READ_CHOICE_SCHEMA, "read_choice")
    return {
        **dict.fromkeys(("h0", "h1", "h2", "h_all", "final"), hypothesis),
        "choice1": choice,
        "choice2": choice,
        "coding": call_settings(CODING_ACTION_SCHEMA, "coding_action"),
        "refine": call_settings(REFINEMENT_SCHEMA, "refinement"),
    }


_SETTINGS = _settings_by_phase()


@dataclass
class _State:
    """What a case has recorded so far; turned into a :class:`CaseTrail` however it ends."""

    documents: tuple[TrailDocument, ...]
    calls: list[CallRecord] = field(default_factory=list)
    choices: dict[str, ReadChoiceRecord] = field(default_factory=dict)
    choice_notes: dict[str, str] = field(default_factory=dict)
    stages: dict[str, Stage] = field(default_factory=lambda: dict.fromkeys(_STAGES, NOT_REACHED))
    coding_steps: list[CodingStep] = field(default_factory=list)
    verdict: Verdict | None = None
    leak: str | None = None
    failure: str | None = None


class _Case:
    """One case's flow. Holds the collaborators so each step reads as the design states it."""

    def __init__(  # noqa: PLR0913 -- run_case's parameters, fixed by the plan's Task 4.
        self,
        raw: Mapping[str, object],
        docket: Docket,
        *,
        client: ModelClient,
        tables: CodeTables,
        stats: CodingStats,
        seen_pairs: AbstractSet[str],
        budget: CaseBudget,
    ) -> None:
        self.raw = {k: v for k, v in raw.items() if k != DOCKET_KEY}
        self.docket = docket
        self.client = client
        self.tables = tables
        self.stats = stats
        self.seen_pairs = seen_pairs
        self.budget = budget
        self.system = base_system(tables)
        self.facts: tuple[DocketFacts, ...] = facts(docket)
        self.state = _State(
            documents=tuple(
                TrailDocument(
                    index=f.index,
                    kind=f.kind,
                    pages=f.pages,
                    readable_pages=f.readable_pages,
                    estimated_tokens=f.estimated_tokens,
                    transcribed_pages=f.transcribed_pages,
                    attachable=f.status == "read",
                )
                for f in self.facts
            )
        )

    # --- calls ---

    def _call(
        self, phase: Phase, payload: Payload, system: str, history: Sequence[Turn], *, retry: bool
    ) -> str:
        settings = _SETTINGS[phase]
        estimate = CaseBudget.estimate(system, payload, history, settings)
        self.budget.check(estimate)
        start = time.monotonic()
        try:
            reply = self.client.complete(payload, settings, system=system, history=history)
        except BaseException:
            self.budget.settle(estimate, 0.0)
            raise
        seconds = time.monotonic() - start
        dollars, _ = cost_usd(reply, settings)
        self.budget.settle(estimate, dollars)
        self.state.calls.append(
            CallRecord(
                phase=phase,
                prompt_tokens=reply.usage.prompt_tokens,
                completion_tokens=reply.usage.completion_tokens,
                reasoning_tokens=reply.usage.reasoning_tokens,
                cost_usd=dollars,
                estimated_usd=estimate,
                seconds=seconds,
                finish_reason=reply.finish_reason,
                parse_retry=retry,
            )
        )
        return reply.content or ""

    def _ask[T](
        self,
        phase: Phase,
        payload: Payload,
        system: str,
        history: Sequence[Turn],
        parse: Callable[[str], T],
    ) -> tuple[T, str]:
        """One call and, on a parse error, one retry naming the error (as the runner does)."""
        text = self._call(phase, payload, system, history, retry=False)
        try:
            return parse(text), text
        except SchemaError as error:
            retry_system = f"{system}\n\nYour previous reply was rejected: {error}"
            text = self._call(phase, payload, retry_system, history, retry=True)
            try:
                return parse(text), text
            except SchemaError as second:
                raise _Failed(phase, str(second)) from second

    def _hypothesis(
        self, phase: Phase, payload: Payload, history: Sequence[Turn], system: str | None = None
    ) -> tuple[Hypothesis, str]:
        """A hypothesis call; the system text is the H0 system unless given."""
        return self._ask(
            phase,
            payload,
            self.system if system is None else system,
            history,
            lambda text: parse_hypothesis(text, self.tables),
        )

    def _stage(self, name: str, hypothesis: Hypothesis | None, note: str | None = None) -> None:
        scores = None
        if hypothesis is not None and self.state.verdict is not None:
            s = score_case(hypothesis, self.state.verdict, self.tables, seen_pairs=self.seen_pairs)
            scores = StageScores(
                occurrence_top1=s.occurrence_top1,
                occurrence_top3=s.occurrence_top3,
                finding_recall_10=s.finding_recall_10 if name == "refined" else None,
            )
        self.state.stages[name] = Stage(hypothesis=hypothesis, note=note, scores=scores)

    def _choose(
        self,
        phase: Phase,
        attachment: Attachment,
        offered: tuple[int, ...],
        already_read: tuple[int, ...],
        turns: Sequence[Turn],
    ) -> tuple[tuple[int, ...], str]:
        """A read choice over ``offered``; the payload carries what has been read so far."""
        choice, text = self._ask(
            phase,
            _payload(attachment.context_for(already_read).context),
            f"{self.system}\n\n{READ_CHOICE_INSTRUCTIONS}\n\n"
            f"{menu(self.facts, offered, already_read=already_read)}",
            turns,
            lambda reply: parse_read_choice(reply, offered),
        )
        record = ReadChoiceRecord(offered=offered, documents=choice.documents, reason=choice.reason)
        self.state.choices[phase] = record
        return record.chosen, text

    # --- the flow ---

    def flow(self) -> str:
        """Steps 1-8; returns the stop reason (``"done"`` or ``"max_calls"``)."""
        evidence, _, verdict = split_record(self.raw)
        self.state.verdict = verdict
        # 1. H0 from the structured evidence.
        h0, text = self._hypothesis("h0", Payload.from_evidence(evidence), ())
        self._stage("h0", h0)
        turns = [Turn(role="assistant", content=text)]

        attachment = prepare_attachment(self.raw, self.docket)
        attachable = tuple(d.index for d in self.state.documents if d.attachable)
        # 2. Read choice 1 over every attachable document.
        chosen1: tuple[int, ...] = ()
        if attachable:
            chosen1, text = self._choose("choice1", attachment, attachable, (), turns)
            turns.append(Turn(role="assistant", content=text))
        else:
            self.state.choice_notes["choice1"] = "skipped: nothing to offer"
        # 3. H1 from what was chosen; H0 again, with no call, when nothing was.
        h1 = h0
        if chosen1:
            h1, text = self._hypothesis(
                "h1", _payload(attachment.context_for(chosen1).context), turns
            )
            self._stage("h1", h1)
            turns.append(Turn(role="assistant", content=text))
        else:
            self._stage("h1", h0, "skipped: nothing chosen")
        # 4. Read choice 2 over what is left.
        remaining = tuple(i for i in attachable if i not in chosen1)
        chosen2: tuple[int, ...] = ()
        if remaining:
            chosen2, text = self._choose("choice2", attachment, remaining, chosen1, turns)
            turns.append(Turn(role="assistant", content=text))
        else:
            self.state.choice_notes["choice2"] = "skipped: nothing left to offer"
        read = tuple(sorted({*chosen1, *chosen2}))
        payload = _payload(attachment.context_for(read).context)
        # 5. H2 from everything chosen; H1 again, with no call, when nothing more was.
        if chosen2:
            h2, text = self._hypothesis("h2", payload, turns)
            self._stage("h2", h2)
            turns.append(Turn(role="assistant", content=text))
        else:
            self._stage("h2", h1, "skipped: nothing more chosen")
        # 6. H_all: the read-everything answer on the H0 system, no history.
        self._h_all(attachment, attachable, read)
        # 7-8. Coding checks, then the final answer and its refinement.
        return self._coding_and_final(payload, turns)

    def _h_all(
        self, attachment: Attachment, attachable: tuple[int, ...], read: tuple[int, ...]
    ) -> None:
        if set(read) == set(attachable):
            self._stage("h_all", None, "not needed")
            return
        payload = _payload(attachment.context_for(attachable).context)
        estimate = CaseBudget.estimate(self.system, payload, (), _SETTINGS["h_all"])
        if not self.budget.fits(estimate, reserve=CODING_RESERVE_USD):
            self._stage("h_all", None, "not run: cap")
            return
        h_all, _ = self._hypothesis("h_all", payload, ())
        self._stage("h_all", h_all)

    def _coding_and_final(self, payload: Payload, turns: list[Turn]) -> str:
        base = f"{self.system}\n\n{CODING_INSTRUCTIONS}\n\n{TOOL_DESCRIPTIONS}"
        results: list[str] = []
        stop = "done"
        while True:
            action, text = self._ask(
                "coding",
                payload,
                _coding_system(base, results),
                turns,
                lambda reply: parse_coding_action(reply, self.tables),
            )
            turns.append(Turn(role="assistant", content=text))
            if action.done or action.tool is None:
                self.state.coding_steps.append(_step(action, None, 0))
                break
            result = run_tool(
                action.tool, action.kind, action.codes, tables=self.tables, stats=self.stats
            )
            results.append(
                f"{len(results) + 1}. {action.tool}(kind={action.kind}, "
                f"codes={list(action.codes)}):\n{result.text}"
            )
            self.state.coding_steps.append(_step(action, result.text, result.argument_errors))
            if len(results) >= MAX_CODING_CALLS:
                stop = "max_calls"
                break
        final_system = f"{_coding_system(base, results)}\n\n{FINAL_INSTRUCTION}"
        final, final_text = self._hypothesis("final", payload, turns, final_system)
        self._stage("final", final)
        if final.abstain or not final.findings:
            self._stage(
                "refined", final, f"not run: {'abstained' if final.abstain else 'no findings'}"
            )
            return stop
        # Stage 2 exactly as the runner's _two_turns: the final reply as the one history turn.
        refined, _ = self._ask(
            "refine",
            payload,
            f"{prompt.SYSTEM_REFINE}\n\n{prompt.refine_message(final, self.tables)}",
            (Turn(role="assistant", content=final_text),),
            lambda reply: parse_refinement(reply, self.tables, final),
        )
        self._stage("refined", refined)
        return stop

    # --- the record ---

    def trail(self, case_id: str, stop_reason: str) -> CaseTrail:
        """The case's trail, from whatever was recorded before it stopped."""
        st = self.state
        final = st.stages["final"].hypothesis
        pool_top: str | None = None
        follows: bool | None = None
        if final is not None:
            codes = final.occurrence_codes(self.tables)
            pool_top = min(codes, key=lambda code: (-self.stats.defining_n(code), code))
            follows = codes[0] == pool_top
        truth = primary_occurrence(st.verdict) if st.verdict is not None else None
        true_in_arguments = (
            None
            if truth is None
            else any(
                truth in step.codes for step in st.coding_steps if step.kind in ("occurrence", None)
            )
        )
        return CaseTrail(
            case_id=case_id,
            fatal=self.raw.get("highestInjuryLevel") == "Fatal",
            has_scan=has_scan(self.facts),
            documents=st.documents,
            calls=tuple(st.calls),
            choice1=st.choices.get("choice1"),
            choice1_note=st.choice_notes.get("choice1"),
            choice2=st.choices.get("choice2"),
            choice2_note=st.choice_notes.get("choice2"),
            h0=st.stages["h0"],
            h1=st.stages["h1"],
            h2=st.stages["h2"],
            h_all=st.stages["h_all"],
            final=st.stages["final"],
            refined=st.stages["refined"],
            coding_steps=tuple(st.coding_steps),
            pool_top=pool_top,
            follows_pool=follows,
            true_primary=truth,
            true_in_arguments=true_in_arguments,
            leak=st.leak,
            failure=st.failure,
            stop_reason=stop_reason,
            cost_usd=sum(call.cost_usd for call in st.calls),
        )


def _coding_system(base: str, results: Sequence[str]) -> str:
    """The coding-check system text: base, then every earlier tool result in order."""
    return f"{base}\n\nTool results so far:\n" + ("\n\n".join(results) if results else "none")


def _step(action: CodingAction, result: str | None, argument_errors: int) -> CodingStep:
    return CodingStep(
        done=action.done,
        tool=action.tool,
        kind=action.kind,
        codes=action.codes,
        reason=action.reason,
        expected_effect=action.expected_effect,
        top3=action.top3,
        result_text=result,
        result_chars=len(result or ""),
        argument_errors=argument_errors,
    )


def run_case(  # noqa: PLR0913 -- fixed by the plan's Task 4.
    raw: Mapping[str, object],
    docket: Docket,
    *,
    client: ModelClient,
    tables: CodeTables,
    stats: CodingStats,
    seen_pairs: AbstractSet[str],
    budget: RunBudget,
) -> CaseTrail:
    """Run one ``dev-400`` case through the eight steps and return its trail.

    Args:
        raw: the case's raw record (any ``docket`` subtree is dropped before use).
        docket: the case's docket at evidence version v2.
        client: the model client (one per worker thread in Task 5).
        tables: the code tables.
        stats: the statistics pool the coding tools read.
        seen_pairs: occurrence codes seen in training, for ``score_case``'s ``pair_unseen``.
        budget: the run's shared budget; this case gets its own :class:`CaseBudget` on it.

    Returns:
        The case's :class:`CaseTrail`, however the case ended.

    Raises:
        ValueError: the case is not in ``dev-400`` (refused before any call).
    """
    case_id = raw.get("ntsbNumber")
    if not isinstance(case_id, str) or case_id not in _dev_ids():
        raise ValueError(f"not in dev-400: {case_id!r}")
    case = _Case(
        raw,
        docket,
        client=client,
        tables=tables,
        stats=stats,
        seen_pairs=seen_pairs,
        budget=CaseBudget(budget),
    )
    try:
        stop_reason = case.flow()
    except _Stop as stop:
        stop_reason = stop.reason
    except _Failed as failed:
        case.state.failure = failed.detail
        stop_reason = f"failed: {failed.phase}"
    except LeakageError as error:
        # The guard's message names role, kind and source, never the withheld text itself.
        case.state.leak = str(error)
        stop_reason = "failed: leak"
    return case.trail(case_id, stop_reason)
