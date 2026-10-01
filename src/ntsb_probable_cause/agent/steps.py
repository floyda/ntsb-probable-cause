"""The step table: what each step of the loop forces, accepts, and sends back (S3.1 Task 8).

The plan's flow table ("The flow for one trigger") in code, apart from the loop's state. For each
step: the ``tool_choice`` it sends, the tools a reply may call, and, once a call is accepted,
the next step and the tool text that says so. Also the protocol's refusals: what the loop says
about a reply it does not accept, in field names and error types, never the model's own values.

Everything here is a pure function of numbers, step names and document facts. Like
``agent/texts.py``, this module imports no ``records``, ``docket`` or ``data`` module: the
payloads (the listing, the documents read) are the loop's, built through ``split_record``. The
texts it sends are fixed texts of ``agent/texts.py``, the refusals' words included, so the prompt
version's text fingerprint covers them (Andy, 2026-10-01); only the joins of a list (``", "``,
``" or "``, ``"; "``) and of a step's parts (a blank line) are written here.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, get_args

from pydantic import ValidationError

from ntsb_probable_cause.agent.facts import DocumentFacts
from ntsb_probable_cause.agent.schemas import REQUIRED, ExtraDecision, ToolName, force
from ntsb_probable_cause.agent.texts import (
    ALL_READ,
    ANSWER_NOW,
    CHOOSE,
    CHOOSE_AGAIN,
    CODE_NOW,
    NO_DOCUMENTS,
    NONE_READABLE,
    NOT_JSON,
    RECORD_NOW,
    UNKNOWN_TOOL,
    WHOLE_ARGUMENTS,
    WRONG_TOOL,
    extras_lines,
    menu,
    read_summary,
)
from ntsb_probable_cause.agent.trail import StepKind
from ntsb_probable_cause.errors import SchemaError

_TOOL_NAMES: Final = frozenset(get_args(ToolName))

# The one tool each step forces. ``coding`` forces none (any tool the run sends), and ``refine``
# sends no tools at all.
FORCED: Final[dict[StepKind, ToolName]] = {
    "h0": "record_hypothesis",
    "choice1": "choose_documents",
    "h1": "record_hypothesis",
    "choice2": "choose_documents",
    "h2": "record_hypothesis",
    "answer": "submit_answer",
}


def tool_choice(step: StepKind) -> str | dict[str, object] | None:
    """The ``tool_choice`` a step sends (spec §5.3).

    This is the one place to change if the native-tool shape probe (Task 4) finds forced calls
    unusable: every step would then send ``"required"``, and the tool text before it would name
    the step's tool.

    Args:
        step: the step the call is made for.

    Returns:
        ``force(<tool>)`` for a step with one tool, ``"required"`` for coding, None for
        refinement.
    """
    if step == "refine":
        return None
    forced = FORCED.get(step)
    return REQUIRED if forced is None else force(forced)


def allowed(step: StepKind, coding: Sequence[str]) -> tuple[str, ...]:
    """The tools a reply may call at a step; for coding, the run's coding tools and the answer."""
    return (*coding, "submit_answer") if step == "coding" else (FORCED[step],)


def wrong_tool(options: Sequence[str], name: str) -> str:
    """Why a call to ``name`` is not accepted. A name that is no tool of ours is not repeated."""
    shown = name if name in _TOOL_NAMES else UNKNOWN_TOOL
    wanted = options[0] if len(options) == 1 else f"{', '.join(options[:-1])} or {options[-1]}"
    return WRONG_TOOL.format(wanted=wanted, called=shown)


def sanitised(error: SchemaError) -> str:
    """What was wrong with a reply, as field paths and error types, never the model's values.

    ``parse_hypothesis`` and ``parse_refinement`` put pydantic's whole message, input included,
    into their ``SchemaError``. The model's words can quote a document, and they must not come
    back in a ``ToolText`` or a trail row (Task 6 review). An extra field's name is the model's
    too, so it is not repeated. A ``SchemaError`` with no pydantic cause names codes or document
    numbers only (the code tables' checks, ``parse_call``'s decision check).

    Args:
        error: the error a parse raised.

    Returns:
        ``path: type`` for each problem, joined by ``; ``; ``not valid JSON``; or the error's own
        text when it has no pydantic cause.
    """
    cause = error.__cause__
    if isinstance(cause, ValidationError):
        problems = []
        for problem in cause.errors(include_url=False, include_context=False, include_input=False):
            where = problem["loc"][:-1] if problem["type"] == "extra_forbidden" else problem["loc"]
            path = ".".join(str(part) for part in where) or WHOLE_ARGUMENTS
            problems.append(f"{path}: {problem['type']}")
        return "; ".join(problems)
    if isinstance(cause, ValueError):
        return NOT_JSON
    return str(error)


@dataclass(frozen=True)
class Shelf:
    """The documents at one moment, as facts: what is left to read, what cannot be read, what was.

    Attributes:
        rest: the offered documents not read yet, in offer order.
        not_readable: the documents that cannot be read.
        read: the listing indices read so far, in the order they were read.
    """

    rest: tuple[DocumentFacts, ...] = ()
    not_readable: tuple[DocumentFacts, ...] = ()
    read: tuple[int, ...] = ()

    @property
    def none_readable(self) -> bool:
        """Whether the docket lists documents and none of them can be read, or was read before."""
        return not self.rest and not self.read and bool(self.not_readable)

    def menu(self) -> str:
        """The menu of what is left, with what was read and what cannot be."""
        return menu(self.rest, self.not_readable, already_read=self.read)


def to_coding(coding: bool, *before: str) -> tuple[StepKind, str]:
    """The move to coding, or straight to the answer when the run has no coding step.

    Args:
        coding: whether the run has a coding step (not so for ``without={"coding"}``).
        before: text to put first, each part followed by a blank line.

    Returns:
        The next step and its tool text.
    """
    if coding:
        return "coding", "\n\n".join((*before, CODE_NOW))
    return "answer", "\n\n".join((*before, ANSWER_NOW))


def after_hypothesis(step: StepKind, shelf: Shelf, coding: bool) -> tuple[StepKind, str]:
    """The step after a hypothesis at ``h0``, ``h1`` or ``h2``, and its tool text.

    ``h0`` offers every readable document (``choice1``); ``h1`` offers what is left (``choice2``);
    otherwise coding follows. With nothing on offer at ``h0``, the text says, on a later trigger
    that read every document on offer before, that all were read; when the docket lists
    documents none of which can be read, which they are (the menu's not-readable lines) and
    ``NONE_READABLE`` (Andy, 2026-10-01); and when there is no docket, or it lists nothing,
    ``NO_DOCUMENTS``.

    Args:
        step: the checkpoint just recorded.
        shelf: the documents now.
        coding: whether the run has a coding step.

    Returns:
        The next step and its tool text.
    """
    if step in ("h0", "h1") and shelf.rest:
        if step == "h0":
            return "choice1", f"{shelf.menu()}\n\n{CHOOSE}"
        return "choice2", f"{shelf.menu()}\n\n{CHOOSE_AGAIN}"
    if step == "h0":
        if shelf.read:
            return to_coding(coding, ALL_READ)
        if shelf.none_readable:
            return to_coding(coding, shelf.menu(), NONE_READABLE)
        return to_coding(coding, NO_DOCUMENTS)
    return to_coding(coding)


def lists(step: StepKind, shelf: Shelf) -> bool:
    """Whether the docket listing goes back with the result of a hypothesis at ``step``.

    At ``h0`` only, and only when the docket lists something not read before: a read choice
    follows, or every listed document is unreadable (Andy, 2026-10-01: the agent sees the
    listing arm B's payload holds; decision 0074). The listing itself is the loop's payload,
    through the split and the guard; this table only says when it is sent.

    Args:
        step: the checkpoint just recorded.
        shelf: the documents at that checkpoint, before its result.

    Returns:
        True when the result carries the listing.
    """
    return step == "h0" and (bool(shelf.rest) or shelf.none_readable)


def after_choice(  # noqa: PLR0913 -- the choice, the documents after it, the run, the extras.
    step: StepKind,
    read: Sequence[int],
    skipped: Sequence[int],
    shelf: Shelf,
    coding: bool,
    *,
    extras: Sequence[ExtraDecision] = (),
) -> tuple[StepKind, str]:
    """The step after a read choice, and the tool text that goes with the documents read.

    Anything read: a hypothesis (``h1`` or ``h2``). Nothing read at the first choice: the second
    look, over everything still unread. Nothing read at the second: coding. The text opens with
    the read summary; then, when the choice decided on documents not on offer, a line for each
    (``extras_lines``, decision 0134); then what comes next.

    Args:
        step: ``choice1`` or ``choice2``.
        read: the listing indices chosen to read, in offer order.
        skipped: the listing indices chosen to skip, in offer order.
        shelf: the documents after this choice.
        coding: whether the run has a coding step.
        extras: the choice's decisions on documents not on offer, each once.

    Returns:
        The next step and its tool text.
    """
    said = [read_summary(read, skipped)]
    if extras:
        said.append(extras_lines(extras))
    if read:
        return ("h1" if step == "choice1" else "h2"), "\n\n".join((*said, RECORD_NOW))
    if step == "choice1":
        return "choice2", "\n\n".join((*said, shelf.menu(), CHOOSE_AGAIN))
    return to_coding(coding, *said)
