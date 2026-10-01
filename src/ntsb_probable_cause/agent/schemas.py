"""The agent's tool definitions, argument models and argument parsing (S3.1 Task 6, spec §5).

Seven tools, each defined once as a name, a fixed one-line description and a strict JSON schema
for its arguments, in the provider's native tool-calling form. The definitions are sent
identically on every model call of a run, so the provider's prompt cache holds (spec §5.3): the
tuple is built once at import, in a fixed order, from fixed strings and models whose fields are
declared in a fixed order, with no set iteration and no dict built from an unordered source. A
model's class docstring is stripped from its schema, so editing a docstring cannot change the
bytes the provider sees.

What the model may not get wrong is caught in code, not by the schema: a document number is only
a plain integer here, and :func:`parse_call` sorts each decision against the documents on offer
(spec §5.3, "what is given up"). Every offered document must be decided exactly once; a decision
on any other document is set aside as an extra, with its kind, and answered, never acted on
(decision 0134). This module imports nothing from ``records``, ``docket``, ``data`` or
``scoring.runner``; it holds names, descriptions and argument shapes, never case text.
"""

from collections import Counter
from collections.abc import Collection, Sequence
from copy import deepcopy
from typing import Final, Literal, get_args

from pydantic import BaseModel, ConfigDict, ValidationError

from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.hypothesis import (
    HYPOTHESIS_SCHEMA,
    Hypothesis,
    parse_hypothesis,
    strict_schema,
)

CodingToolName = Literal["describe_codes", "occurrence_usage", "past_findings", "suggest_codes"]
ToolName = Literal["record_hypothesis", "choose_documents", "submit_answer", CodingToolName]
DescribeKind = Literal["occurrence", "finding_category", "item"]
# Why a document decided on was not on offer (decision 0134): listed but it cannot be read; read
# at an earlier choice or trigger; or no document of the listing has that number.
ExtraKind = Literal["not_readable", "already_read", "unknown"]
# The two tool ablations (spec §7.2): one tool dropped, or all four coding tools dropped.
Without = Literal["suggest_codes", "coding"]

# The phase-of-flight groups the statistics pool keys its counts by: every group name in
# ``scoring/tables/coding_stats_s3.json`` (a test holds the two to each other). Written out as a
# ``Literal`` because ``Literal[*PHASE_GROUPS]`` is not a valid type; the tuple is read from it.
PhaseGroup = Literal[
    "Approach",
    "EmergencyDescent",
    "Enroute",
    "InitialClimb",
    "Landing",
    "Maneuvering",
    "Post-Impact",
    "Standing",
    "Takeoff",
    "Taxi",
    "UncontrolledDescent",
    "Unknown",
]
PHASE_GROUPS: tuple[str, ...] = get_args(PhaseGroup)

# The tool_choice value that lets the model call any one tool (the coding step, spec §5.3).
REQUIRED: Final = "required"
CODING_TOOLS: frozenset[str] = frozenset(get_args(CodingToolName))


class _Arguments(BaseModel):
    """Base of every tool's arguments: no extra fields, no change after parsing."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class _Why(_Arguments):
    """The two fields every coding tool's arguments carry: why it is called, and what for."""

    reason: str
    expected_effect: str


class DocumentDecision(_Arguments):
    """One offered document: read it or skip it, and what the agent expects it to show."""

    document: int
    read: bool
    expected_effect: str


class ChooseDocuments(_Arguments):
    """The arguments of ``choose_documents``, as the model sent them.

    One decision is wanted for every document on offer; decisions on other documents may be
    among them too (decision 0134), and :func:`parse_call` sets those apart.
    """

    decisions: tuple[DocumentDecision, ...]
    reason: str


class ExtraDecision(BaseModel):
    """A decision on a document that was not on offer: answered, counted, never acted on.

    Attributes:
        document: the listing index the decision named.
        kind: ``not_readable`` (listed, but it cannot be read), ``already_read`` (read at an
            earlier choice, or on an earlier trigger), or ``unknown`` (no listed document has
            that number).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    document: int
    kind: ExtraKind


class DocumentChoice(BaseModel):
    """A ``choose_documents`` call sorted against the offer (decision 0134).

    Attributes:
        arguments: the arguments as the model sent them, every decision kept: what the trail
            records.
        decisions: the decision on each offered document, exactly one each, in the order the
            model gave them: what the loop acts on and the read record keeps.
        extras: each document decided on that was not on offer, once, in the order the model
            first named it, whatever it asked for it (read or skip).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    arguments: ChooseDocuments
    decisions: tuple[DocumentDecision, ...]
    extras: tuple[ExtraDecision, ...]


class DescribeCodes(_Why):
    """The arguments of ``describe_codes``."""

    kind: DescribeKind
    codes: tuple[str, ...]


class OccurrenceUsage(_Why):
    """The arguments of ``occurrence_usage``."""

    codes: tuple[str, ...]


class PastFindings(_Why):
    """The arguments of ``past_findings``."""

    occurrence: str


class SuggestCodes(_Why):
    """The arguments of ``suggest_codes``."""

    phase_group: PhaseGroup


def _without_descriptions(node: object) -> None:
    """Drop the text pydantic copies from a class docstring into a schema, in place.

    A property *named* ``description`` holds a schema (a dict), not text, so only a string
    under ``description`` is removed.
    """
    if isinstance(node, dict):
        if isinstance(node.get("description"), str):
            del node["description"]
        for value in node.values():
            _without_descriptions(value)
    elif isinstance(node, list):
        for item in node:
            _without_descriptions(item)


def _parameters(model: type[BaseModel]) -> dict[str, object]:
    """The strict schema of ``model``'s fields, without the docstring text."""
    schema = strict_schema(model)
    _without_descriptions(schema)
    return schema


# Fixed order, fixed text: name, one-line description, parameters. Everything the provider sees
# about a tool is here.
_TOOLS: tuple[tuple[ToolName, str, dict[str, object]], ...] = (
    (
        "record_hypothesis",
        "Record your current hypothesis: up to three occurrence codes with probabilities, "
        "findings, a working cause, and your confidence.",
        HYPOTHESIS_SCHEMA,
    ),
    (
        "choose_documents",
        "Decide, for every document offered, whether to read it, and what you expect it to show.",
        _parameters(ChooseDocuments),
    ),
    (
        "describe_codes",
        "Look up the labels of occurrence codes, finding categories or finding items.",
        _parameters(DescribeCodes),
    ),
    (
        "occurrence_usage",
        "Count how often past accidents recorded each occurrence code, and each pair of them, "
        "and how often each was the defining event.",
        _parameters(OccurrenceUsage),
    ),
    (
        "past_findings",
        "List the findings most often recorded in past accidents whose defining event matches "
        "this occurrence code's event.",
        _parameters(PastFindings),
    ),
    (
        "suggest_codes",
        "List the five commonest defining events in past accidents of one phase-of-flight group.",
        _parameters(SuggestCodes),
    ),
    (
        "submit_answer",
        "Submit your final answer. This ends your work on the case.",
        HYPOTHESIS_SCHEMA,
    ),
)


def definitions(without: frozenset[Without] = frozenset()) -> tuple[dict[str, object], ...]:
    """The tool definitions for one run, in the fixed order, each a fresh copy.

    Within one run the definitions never change (spec §5.3): the same call, with the same
    ablation, on every model call of every case.

    Args:
        without: ``"suggest_codes"`` drops that one tool; ``"coding"`` drops the four coding
            tools (the loop then forces ``submit_answer`` straight after the last hypothesis).

    Returns:
        One ``{"type": "function", "function": {...}}`` entry per remaining tool, each function
        holding ``name``, ``description``, ``parameters`` and ``strict: True``.
    """
    dropped: set[str] = set()
    if "suggest_codes" in without:
        dropped.add("suggest_codes")
    if "coding" in without:
        dropped |= CODING_TOOLS
    return tuple(
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": deepcopy(parameters),
                "strict": True,
            },
        }
        for name, description, parameters in _TOOLS
        if name not in dropped
    )


TOOL_DEFINITIONS: tuple[dict[str, object], ...] = definitions()


def force(name: ToolName) -> dict[str, object]:
    """The ``tool_choice`` value that makes the model call the one tool ``name``."""
    return {"type": "function", "function": {"name": name}}


_ARGUMENT_MODELS: dict[str, type[BaseModel]] = {
    "choose_documents": ChooseDocuments,
    "describe_codes": DescribeCodes,
    "occurrence_usage": OccurrenceUsage,
    "past_findings": PastFindings,
    "suggest_codes": SuggestCodes,
}


def _problems(error: ValidationError) -> str:
    """Each field's problem as ``field: message``, never the value that caused it."""
    return "; ".join(
        f"{'.'.join(str(part) for part in problem['loc']) or 'arguments'}: {problem['msg']}"
        for problem in error.errors(include_url=False, include_context=False, include_input=False)
    )


def _sort_decisions(
    choice: ChooseDocuments,
    offered: Collection[int],
    already_read: Collection[int],
    not_readable: Collection[int],
) -> DocumentChoice:
    """Check the offered documents' decisions, and set every other decision apart.

    Every offered document must have exactly one decision: that choice is what the read step
    measures. A decision on any other document is an extra (decision 0134), reported once per
    document, of kind ``already_read``, else ``not_readable``, else ``unknown``.

    Raises:
        SchemaError: an offered document has no decision, or more than one. The message names
            the offered documents at fault, never an extra.
    """
    counts = Counter(d.document for d in choice.decisions if d.document in offered)
    missing = sorted(set(offered) - counts.keys())
    repeated = sorted(n for n, count in counts.items() if count > 1)
    faults = [
        f"{label} {numbers}"
        for label, numbers in (("missing", missing), ("repeated", repeated))
        if numbers
    ]
    if faults:
        raise SchemaError(
            f"choose_documents must decide every offered document exactly once: {'; '.join(faults)}"
        )
    extras: dict[int, ExtraKind] = {}
    for decision in choice.decisions:
        number = decision.document
        if number in offered or number in extras:
            continue
        extras[number] = (
            "already_read"
            if number in already_read
            else "not_readable"
            if number in not_readable
            else "unknown"
        )
    return DocumentChoice(
        arguments=choice,
        decisions=tuple(d for d in choice.decisions if d.document in offered),
        extras=tuple(ExtraDecision(document=n, kind=kind) for n, kind in extras.items()),
    )


def parse_call(  # noqa: PLR0913 -- the call, then the three facts of the documents at the step.
    name: str,
    arguments: str,
    tables: CodeTables,
    offered: Sequence[int] = (),
    *,
    already_read: Collection[int] = (),
    not_readable: Collection[int] = (),
) -> BaseModel | Hypothesis:
    """Parse and check one tool call's arguments.

    Args:
        name: the tool the model called.
        arguments: the call's arguments, as the JSON text the provider returned.
        tables: the code tables, for the two tools that take a hypothesis.
        offered: the document numbers on offer at this step; only ``choose_documents`` reads it.
        already_read: the document numbers read before this step, on any trigger; only
            ``choose_documents`` reads it, to name an extra's kind.
        not_readable: the listed document numbers that cannot be read; likewise.

    Returns:
        A :class:`~ntsb_probable_cause.scoring.hypothesis.Hypothesis` for ``record_hypothesis``
        and ``submit_answer``; a :class:`DocumentChoice` for ``choose_documents``, its
        arguments sorted into the offered decisions and the extras (decision 0134); otherwise
        the tool's argument model.

    Raises:
        SchemaError: the tool is unknown, the arguments are not valid JSON for it, or a
            ``choose_documents`` decision set misses or repeats an offered document. The
            message names the faults and never repeats the model's own values.
    """
    if name in ("record_hypothesis", "submit_answer"):
        return parse_hypothesis(arguments, tables)
    model = _ARGUMENT_MODELS.get(name)
    if model is None:
        raise SchemaError(f"unknown tool {name!r}")
    try:
        parsed = model.model_validate_json(arguments)
    except ValidationError as error:
        raise SchemaError(f"arguments of {name} are not valid: {_problems(error)}") from error
    if isinstance(parsed, ChooseDocuments):
        return _sort_decisions(parsed, frozenset(offered), already_read, not_readable)
    return parsed
