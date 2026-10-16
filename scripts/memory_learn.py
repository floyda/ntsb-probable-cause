"""The coding memory's learner: propose lessons, choose the applier, finish a snapshot.

Status
    Live tool for the coding memory's pilot (decisions 0200-0204), paid from plan credits (0202,
    0207). Writes run folders under ``NTSB_RUNS_DIR`` (never committed) and, from ``finish``, an
    unchecked snapshot. It refuses a dirty tree, so every run names a clean commit, and it
    checks the month's learner line (``NTSB_LEARNING_MONTHLY_BUDGET_USD``) before each phase.

What it reads
    The learning part (``memory.pool``: development cases of the statistics pool, outside every
    sample), each case's probable-cause sentence and codes, and, for ``propose --from NAME``,
    a stamped snapshot. ``finish`` also reads every development case's withheld texts and
    probable-cause sentences (``checks.development_texts``) to compare lessons against them,
    never to send them. The Claude key comes from the environment (``ANTHROPIC_API_KEY``).

What it writes
    ``<runs>/<run id>/``: ``calls.jsonl`` and ``batches.jsonl`` (the client's record, so a
    repeated call is never paid for twice), ``draft.json`` (the lessons so far) and
    ``finish.json`` (counts, the lessons the copying and withheld-text checks dropped among
    them). ``agreement`` writes a counts-only file, committed by hand;
    ``finish`` saves ``memory/snapshots/NAME.json`` without a stamp (``make mem-check`` stamps
    it). Only counts are printed.

Usage
    uv run python -m scripts.memory_learn propose --period YEAR --from {empty,NAME} --to NAME
        [--resume RUN_ID]
    uv run python -m scripts.memory_learn agreement --resume RUN_ID
        --out docs/results/memory-agreement-dev.txt
    uv run python -m scripts.memory_learn finish --resume RUN_ID --to NAME
"""

import argparse
import json
import random
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import ValidationError

from ntsb_probable_cause import gitinfo, sources
from ntsb_probable_cause.errors import BudgetError, ConfigurationError
from ntsb_probable_cause.memory import checks, claude, curate, pool, prompts, snapshots
from ntsb_probable_cause.memory.claude import HAIKU, SONNET, Call, Effort, LearningClient
from ntsb_probable_cause.memory.lessons import (
    Lesson,
    Memory,
    Prediction,
    Support,
    estimated_tokens,
    render_for_apply,
    render_lesson,
    render_memory,
)
from ntsb_probable_cause.memory.pool import LearningCase
from ntsb_probable_cause.scoring import budget
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.hypothesis import strict_schema
from ntsb_probable_cause.settings import Settings

Applier = Literal["haiku-low", "haiku-medium", "sonnet-high"]
APPLIERS: Final[dict[Applier, tuple[str, Effort]]] = {
    "haiku-low": (HAIKU, "low"),
    "haiku-medium": (HAIKU, "medium"),
    "sonnet-high": (SONNET, "high"),
}
ClientFactory = Callable[[Settings, str, tuple[str, bool], frozenset[str]], LearningClient]

CHUNK: Final = 30
AGREEMENT_YEAR: Final = 2009
AGREEMENT_SAMPLE: Final = 100
AGREEMENT_SEED: Final = 20261014
AGREEMENT_BAR: Final = 0.90
AGREEMENT_FILE: Path = Path("docs/results/memory-agreement-dev.txt")
APPLIES_FILE: Final = "applies.json"
MAX_TOKENS_HAIKU: Final = 2048
MAX_TOKENS_SONNET: Final = 16000
# Controller ruling, final review I2 (2026-10-15): a Sonnet apply call (the agreement's
# reference and the sonnet-high applier) is a short list of lesson ids, so it gets 4,000
# tokens, not 16,000; at 16,000 the projection of one 2009 apply batch (1,201 cases) passed the
# $90 learner line alone. A reply cut off at this limit is a failed reply ("no lesson
# applies"), counted with the failed replies.
MAX_TOKENS_SONNET_APPLY: Final = 4000
DISAGREEING_SHOWN: Final = 10
AGREEING_SHOWN: Final = 5
_NAME: Final = re.compile(r"[a-z0-9][a-z0-9-]*")
_CODE: Final = re.compile(r"\d{6}")
_ID: Final = re.compile(r"L(\d+)")
# A code as a reply may write it: six leading digits, then nothing that continues the number.
# A category may arrive as an eight-digit item or a ten-digit finding code, whose first six digits
# are the category (plan Deviations, 2026-10-16).
_LEADING_OCCURRENCE: Final = re.compile(r"\s*(\d{6})(?!\d)")
_LEADING_CATEGORY: Final = re.compile(r"\s*(\d{6})(?:\d{2}|\d{4})?(?!\d)")

# Pure helpers. -----------------------------------------------------------------------------


def chunks[T](cases: Sequence[T], size: int = CHUNK) -> list[list[T]]:
    """``cases`` in order, in lists of ``size``; the last may be shorter."""
    return [list(cases[i : i + size]) for i in range(0, len(cases), size)]


def next_lesson_id(existing: Iterable[str]) -> str:
    """The id after the highest ``L<number>`` in ``existing``; ``L001`` for none."""
    numbers = [int(m.group(1)) for i in existing if (m := _ID.fullmatch(i))]
    return f"L{max(numbers, default=0) + 1:03d}"


def parse_applier(text: str) -> Applier:
    """The applier named by the agreement file's ``chosen applier:`` line.

    Raises:
        ValueError: the text has no such line, or names an unknown applier.
    """
    for line in reversed(text.splitlines()):
        if line.startswith("chosen applier:"):
            name = line.partition(":")[2].strip()
            if name in APPLIERS:
                return name
            raise ValueError(f"unknown applier {name!r}")
    raise ValueError("no 'chosen applier:' line (no applier chosen)")


def _id_text(lesson_id: str) -> str:
    """A model-supplied id as printable text: only if it has the shape of an id."""
    return lesson_id if _ID.fullmatch(lesson_id) else "an id of the wrong shape"


def _leading(codes: Sequence[str], pattern: re.Pattern[str]) -> tuple[list[str], int]:
    out: list[str] = []
    changed = 0
    for code in codes:
        match = pattern.match(code)
        read = match.group(1) if match else code
        changed += read != code
        out.append(read)
    return out, changed


def reshape[D: prompts.LessonDraft](draft: D) -> tuple[D, int]:
    """The draft with each code read from its leading digits, and how many codes that changed.

    The learner reads each case's codes with their labels, and finding codes at ten digits; a kept
    lesson is shown back with labels too. In the first 2009 propose run, replies copied those
    forms: a code with its label in ``first_occurrence``, a ten-digit finding code for a category
    (plan Deviations, 2026-10-16). An occurrence code is its six leading digits; a category is the
    six leading digits of a six-, eight- or ten-digit code. Anything else is left as written, and
    the table check drops the draft.
    """
    occurrence, changed_o = _leading(draft.first_occurrence, _LEADING_OCCURRENCE)
    categories, changed_c = _leading(draft.finding_categories, _LEADING_CATEGORY)
    update = {"first_occurrence": occurrence, "finding_categories": categories}
    return draft.model_copy(update=update), changed_o + changed_c


def _problems(draft: prompts.LessonDraft, tables: CodeTables) -> str | None:
    """Why a draft cannot become a lesson, or None."""
    for code in draft.first_occurrence:
        if not (_CODE.fullmatch(code) and code[:3] in tables.phases and code[3:] in tables.events):
            return "a first occurrence code is not a phase and event in the tables"
    for category in draft.finding_categories:
        if category not in tables.categories:
            return "a finding category is not in the tables"
    return None


def _lesson_from(
    draft: prompts.LessonDraft,
    lesson_id: str,
    tables: CodeTables,
    *,
    written_in: int,
    history: tuple[str, ...] = (),
) -> tuple[Lesson | None, str | None]:
    """A lesson from a draft, or why not: codes, validation, then the identifier rule (0201).

    Codes are first read from their leading digits (``reshape``).
    """
    draft, _ = reshape(draft)
    if (why := _problems(draft, tables)) is not None:
        return None, why
    try:
        lesson = Lesson(
            lesson_id=lesson_id,
            kind=draft.kind,
            statement=draft.statement,
            scope=draft.scope,
            predicts=Prediction(
                first_occurrence=tuple(draft.first_occurrence),
                finding_categories=tuple(draft.finding_categories),
            ),
            written_in=written_in,
            history=history,
        )
    except ValidationError as exc:
        return None, f"invalid lesson: {exc.errors()[0]['msg']}"
    found = checks.identifier_findings(Memory(name="one", periods=(), lessons=(lesson,)))
    if found:
        # fixed words: the finding quotes the text that failed, and that text must not be printed
        return None, "identifier check: a digit or an unlisted capitalised word"
    return lesson, None


def _replace(lessons: tuple[Lesson, ...], new: Lesson) -> tuple[Lesson, ...]:
    return tuple(new if lesson.lesson_id == new.lesson_id else lesson for lesson in lessons)


def _edited(
    old: Lesson, draft: prompts.LessonDraft, year: int, tables: CodeTables, verb: str
) -> tuple[Lesson | None, str | None]:
    return _lesson_from(
        draft,
        old.lesson_id,
        tables,
        written_in=old.written_in,
        history=(*old.history, f"{verb} in {year}"),
    )


def merge_proposal(
    memory: Memory,
    reply: prompts.ProposeReply,
    year: int,
    tables: CodeTables,
    next_id: Callable[[], str],
) -> tuple[Memory, list[str]]:
    """Apply a propose reply to a memory: edits, retirements, then new lessons.

    A draft is dropped, with a message, when a code is not in the tables, the lesson does not
    validate, or its text fails the identifier check; at most ``MAX_NEW_PER_CALL`` new lessons
    are kept. An edit drops the lesson's counted support (it is stale until recounted).

    Returns:
        The merged memory and one message per draft or instruction dropped.
    """
    lessons = memory.lessons
    dropped: list[str] = []
    known = {lesson.lesson_id: lesson for lesson in lessons}
    for edit in reply.edits:
        if edit.lesson_id not in known:
            dropped.append(f"edit of {_id_text(edit.lesson_id)}: no such lesson")
            continue
        new, why = _edited(known[edit.lesson_id], edit, year, tables, "edited")
        if new is None:
            dropped.append(f"edit of {_id_text(edit.lesson_id)} dropped: {why}")
            continue
        lessons = _replace(lessons, new)
    for lesson_id in reply.retire:
        if lesson_id not in known:
            dropped.append(f"retire {_id_text(lesson_id)}: no such lesson")
        else:
            lessons = tuple(lesson for lesson in lessons if lesson.lesson_id != lesson_id)
    added: list[Lesson] = []
    for position, draft in enumerate(reply.new):
        if len(added) >= prompts.MAX_NEW_PER_CALL:
            dropped.append(f"new lesson {position + 1} dropped: over {prompts.MAX_NEW_PER_CALL}")
            continue
        new, why = _lesson_from(draft, next_id(), tables, written_in=year)
        if new is None:
            dropped.append(f"new lesson {position + 1} dropped: {why}")
        else:
            added.append(new)
    return memory.model_copy(update={"lessons": (*lessons, *added)}), dropped


def merge_revision(
    memory: Memory, lesson_id: str, reply: prompts.ReviseReply, year: int, tables: CodeTables
) -> tuple[Memory, list[str]]:
    """Apply a revise reply to one lesson: retire it, or replace it with the edited one.

    A bad edit leaves the old lesson in place, with a message.
    """
    old = next((lesson for lesson in memory.lessons if lesson.lesson_id == lesson_id), None)
    if old is None:
        return memory, [f"revision of {_id_text(lesson_id)}: no such lesson"]
    if reply.action == "retire":
        kept = tuple(lesson for lesson in memory.lessons if lesson.lesson_id != lesson_id)
        return memory.model_copy(update={"lessons": kept}), []
    new, why = _edited(old, reply, year, tables, "revised")
    if new is None:
        return memory, [f"revision of {lesson_id} dropped: {why}"]
    return memory.model_copy(update={"lessons": _replace(memory.lessons, new)}), []


# Shared setup and cost projection. -----------------------------------------------------------


def projected_usd(calls: Sequence[Call], *, batch: bool) -> float:
    """The calls' cost at their estimated input and full ``max_tokens`` of output (0207)."""
    total = 0.0
    for call in calls:
        price = sources.claude_price(call.model, batch=batch)
        tokens = estimated_tokens(call.system + call.user)
        total += (
            tokens * price.input_usd_per_mtok + call.max_tokens * price.output_usd_per_mtok
        ) / 1e6
    return total


def _check_budget(settings: Settings, calls: Sequence[Call], *, batch: bool, label: str) -> None:
    """Refuse a phase that would pass the month's learner line; print its projection."""
    projection = projected_usd(calls, batch=batch)
    print(f"{label}: {len(calls)} calls, projected at most ${projection:.4f}")
    budget.check_learning_budget(
        settings.runs_dir,
        projection,
        settings.learning_monthly_budget_usd,
        now=datetime.now(UTC),
    )


def _default_factory(
    settings: Settings, run_id: str, commit: tuple[str, bool], forbidden: frozenset[str]
) -> LearningClient:
    return LearningClient(
        claude.sdk_from_key(settings.require_anthropic_key()),
        settings.runs_dir,
        run_id,
        commit=commit,
        forbidden=forbidden,
    )


@dataclass(frozen=True)
class Run:
    """What every subcommand shares: settings, tables, the client, the run and what is forbidden."""

    settings: Settings
    tables: CodeTables
    client: LearningClient
    run_id: str
    forbidden: frozenset[str]
    commit: str

    @property
    def folder(self) -> Path:
        """The run folder."""
        return self.settings.runs_dir / self.run_id


def _draft_path(settings: Settings, run_id: str) -> Path:
    return settings.runs_dir / run_id / "draft.json"


def _load_draft(settings: Settings, run_id: str) -> Memory:
    path = _draft_path(settings, run_id)
    if not path.exists():
        raise ConfigurationError(f"{path} is missing: run propose first")
    return Memory.model_validate_json(path.read_text())


def call_for_apply(
    role: str, model: str, effort: Effort, memory: Memory, case: LearningCase
) -> Call:
    """One case's apply request; ``scripts.memory_recount`` rebuilds its key (decision 0209)."""
    return Call(
        role=role,
        model=model,
        effort=effort,
        system=prompts.SYSTEM_APPLY + render_for_apply(memory),
        user=prompts.apply_user(case.cause),
        schema=strict_schema(prompts.ApplyReply),
        max_tokens=MAX_TOKENS_HAIKU if model == HAIKU else MAX_TOKENS_SONNET_APPLY,
        case_ids=(case.case_id,),
    )


def run_apply(
    run: Run,
    memory: Memory,
    cases: Sequence[LearningCase],
    applier: Applier,
    *,
    role: str,
) -> tuple[dict[str, frozenset[str]], int]:
    """Which lessons the applier says cover each case, in one batch, and how many replies failed.

    Unknown lesson ids are dropped; a failed or unparsable reply counts as an empty set.
    """
    if not memory.lessons or not cases:
        return {}, 0
    model, effort = APPLIERS[applier]
    calls = [call_for_apply(role, model, effort, memory, c) for c in cases]
    _check_budget(run.settings, calls, batch=True, label=f"apply ({applier})")
    replies = run.client.send_batch(calls)
    known = {lesson.lesson_id for lesson in memory.lessons}
    found: dict[str, frozenset[str]] = {}
    failed = 0
    for case, call in zip(cases, calls, strict=True):
        reply = replies[call.key()]
        ids: frozenset[str] = frozenset()
        if reply.ok and reply.text is not None:
            try:
                ids = frozenset(prompts.ApplyReply.model_validate_json(reply.text).applies) & known
            except ValidationError:
                failed += 1
        else:
            failed += 1
        found[case.case_id] = ids
    return found, failed


def _processed(settings: Settings) -> Path:
    return settings.data_dir / "processed"


# The subcommands. ----------------------------------------------------------------------------


def propose(args: argparse.Namespace, run: Run) -> int:
    """Write and edit lessons from one period's cases, thirty at a time.

    Resume: replies that succeeded are recorded and reused; failed replies are not cached. A
    resume after a failed chunk sends that chunk again, and because the memory text then
    changes, later chunks are sent again too (within the projected cost, which prices every
    chunk). The draft is written after every chunk.
    """
    settings, tables, client, run_id = run.settings, run.tables, run.client, run.run_id
    year = int(args.period)
    if args.from_ == "empty":
        start = Memory(name=args.to, periods=())
    else:
        start = snapshots.load_checked(args.from_, snapshots.SNAPSHOT_DIR)
    if year in start.periods:
        raise ConfigurationError(f"{year} is already one of the periods of {args.from_}")
    draft = Memory(
        name=args.to,
        periods=(*start.periods, year),
        lessons=start.lessons,
        pushed_out=start.pushed_out,
    )
    cases = pool.learning_part(_processed(settings), years={year}, excluded=run.forbidden)
    batches = chunks(cases)
    folder = run.folder

    def make_call(batch: list[LearningCase]) -> Call:
        view = draft.model_copy(update={"pushed_out": ()})
        return Call(
            role="propose",
            model=SONNET,
            effort="high",
            system=prompts.SYSTEM_PROPOSE,
            user=prompts.propose_user(render_memory(view, tables), batch, tables),
            schema=strict_schema(prompts.ProposeReply),
            max_tokens=MAX_TOKENS_SONNET,
            case_ids=tuple(c.case_id for c in batch),
        )

    draft_file = _draft_path(settings, run_id)
    print(f"{_recorded_calls(folder)} calls already recorded in this run")
    # The memory grows with each chunk, so the projection prices every chunk at today's memory.
    _check_budget(settings, [make_call(b) for b in batches], batch=False, label="propose")
    used = {lesson.lesson_id for lesson in (*draft.lessons, *draft.pushed_out)}

    def next_id() -> str:
        new_id = next_lesson_id(used)
        used.add(new_id)
        return new_id

    failed = dropped_total = reshaped_total = 0
    for batch in batches:
        reply = client.send(make_call(batch))
        if not reply.ok or reply.text is None:
            failed += 1
            print(f"chunk failed: {_reason(reply.error)}")
        else:
            try:
                parsed = prompts.ProposeReply.model_validate_json(reply.text)
            except ValidationError:
                failed += 1
                print("chunk failed: reply did not parse")
            else:
                reshaped_total += sum(reshape(d)[1] for d in (*parsed.new, *parsed.edits))
                draft, dropped = merge_proposal(draft, parsed, year, tables, next_id)
                dropped_total += len(dropped)
                for message in dropped:
                    print(message)
        draft_file.write_text(draft.model_dump_json(indent=1) + "\n")
    if not batches:
        draft_file.write_text(draft.model_dump_json(indent=1) + "\n")
    print(
        f"run {run_id}: {len(batches)} chunks, {failed} failed, {len(draft.lessons)} lessons, "
        f"{dropped_total} drafts dropped, {reshaped_total} codes read from their leading digits"
    )
    print(f"next: make mem-agreement RUN={run_id} (2009 only), or the next period's propose")
    return 0


def _reason(error: str | None) -> str:
    """A failed reply's cause as its exception or stop name only, never any quoted text."""
    return (error or "no text").split(":")[0]


def _recorded_calls(folder: Path) -> int:
    path = folder / claude.CALLS_FILE
    return len(path.read_text().splitlines()) if path.exists() else 0


def _rate(both: int, either: int) -> float:
    return both / either if either else 0.0


def agreement(args: argparse.Namespace, run: Run) -> int:
    """Haiku against Sonnet on 100 cases of 2009; the applier is the cheapest that reaches 90%."""
    settings, run_id = run.settings, run.run_id
    draft = _load_draft(settings, run_id)
    if draft.periods != (AGREEMENT_YEAR,):
        raise ConfigurationError(f"agreement runs on the 2009 draft only, not {draft.periods}")
    pool_cases = pool.learning_part(
        _processed(settings), years={AGREEMENT_YEAR}, excluded=run.forbidden
    )
    sample = random.Random(AGREEMENT_SEED).sample(  # noqa: S311 -- a fixed, recorded sample
        pool_cases, min(AGREEMENT_SAMPLE, len(pool_cases))
    )
    rows: list[str] = []
    reference, ref_failed = run_apply(run, draft, sample, "sonnet-high", role="agreement")
    chosen: Applier = "sonnet-high"
    nothing_covered = False
    for name in ("haiku-low", "haiku-medium"):
        marked, failed = run_apply(run, draft, sample, name, role="agreement")
        both, either = curate.agreement(marked, reference)
        rate = _rate(both, either)
        rows.append(
            f"{name}: failed replies {failed}; pairs both marked {both}; "
            f"pairs either marked {either}; agreement {rate * 100:.1f}%"
        )
        if either == 0 and name == "haiku-low":
            nothing_covered = True
            break
        if rate >= AGREEMENT_BAR:
            chosen = name
            break
    header = [
        f"run: {run_id}",
        f"commit: {run.commit}",
        f"lessons in the draft: {len(draft.lessons)}",
        f"sample: {len(sample)} cases of {AGREEMENT_YEAR}, seed {AGREEMENT_SEED}",
        f"reference sonnet-high: failed replies {ref_failed}",
        *rows,
        f"bar: {AGREEMENT_BAR * 100:.0f}% agreement",
    ]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if nothing_covered:
        lines = [*header, "no lesson covered any case: the pilot cannot proceed"]
        out.write_text("\n".join(lines) + "\n")
        print("\n".join(lines))
        return 1
    out.write_text("\n".join([*header, f"chosen applier: {chosen}"]) + "\n")
    print("\n".join([*header, f"chosen applier: {chosen}"]))
    return 0


def _retire(lessons: tuple[Lesson, ...], gone: set[str]) -> tuple[Lesson, ...]:
    return tuple(lesson for lesson in lessons if lesson.lesson_id not in gone)


def drop_failing(
    memory: Memory, withheld: Sequence[str], causes: Sequence[str]
) -> tuple[Memory, list[str]]:
    """Drop every lesson, kept or pushed out, that the copying or withheld-text check refuses.

    ``make mem-check`` runs the same checks (decision 0201) and would refuse the snapshot; a
    saved snapshot is never rewritten, so ``finish`` removes such lessons first (final review
    I1). Messages name the lesson id and the check, never the text.

    Returns:
        The memory without those lessons, and one message per lesson dropped.
    """
    failed = checks.development_failures(memory, withheld, causes)
    if not failed:
        return memory, []
    messages = [
        f"{_id_text(lid)} dropped: {' and '.join(f'{name} check' for name in names)}"
        for lid, names in failed.items()
    ]
    gone = set(failed)
    kept = memory.model_copy(
        update={
            "lessons": _retire(memory.lessons, gone),
            "pushed_out": _retire(memory.pushed_out, gone),
        }
    )
    return kept, messages


def _revise(  # noqa: PLR0913 -- the run, the memory, and the counts its revisions are shown
    run: Run,
    memory: Memory,
    support: dict[str, Support],
    *,
    cases: Sequence[LearningCase],
    applies: dict[str, frozenset[str]],
    year: int,
) -> tuple[Memory, int, int]:
    """Send every lesson that disagrees more than it agrees back to the learner, one at a time.

    Returns:
        The memory after the revisions, and how many lessons were edited and retired.
    """
    revisable = [
        lesson for lesson in memory.lessons if curate.needs_revision(support[lesson.lesson_id])
    ]
    revised = retired = 0
    if not revisable:
        return memory, revised, retired
    calls = {
        lesson.lesson_id: _revise_call(lesson, support, cases, applies, run.tables)
        for lesson in revisable
    }
    _check_budget(run.settings, list(calls.values()), batch=False, label="revise")
    for lesson in revisable:
        reply = run.client.send(calls[lesson.lesson_id])
        if not reply.ok or reply.text is None:
            print(f"revision of {lesson.lesson_id} failed: {_reason(reply.error)}")
            continue
        try:
            parsed = prompts.ReviseReply.model_validate_json(reply.text)
        except ValidationError:
            print(f"revision of {lesson.lesson_id} failed: reply did not parse")
            continue
        before = memory
        memory, messages = merge_revision(memory, lesson.lesson_id, parsed, year, run.tables)
        for message in messages:
            print(message)
        if memory is not before:
            revised += parsed.action == "edit"
            retired += parsed.action == "retire"
    return memory, revised, retired


def finish(args: argparse.Namespace, run: Run) -> int:
    """Drop lessons the checks refuse, apply, count, revise, retire, cap, save unchecked.

    The copying and withheld-text checks (decision 0201) run before support is first counted
    and again after a revision changed any lesson, so neither a lesson carried from the starting
    snapshot nor a revised one reaches the snapshot when ``make mem-check`` would refuse it.
    """
    settings, tables, run_id = run.settings, run.tables, run.run_id
    if (
        not _NAME.fullmatch(args.to)
        or snapshots.snapshot_path(args.to, snapshots.SNAPSHOT_DIR).exists()
    ):
        raise ConfigurationError(f"snapshot name {args.to!r} is invalid or already taken")
    if not gitinfo.is_committed(AGREEMENT_FILE):
        raise ConfigurationError(f"{AGREEMENT_FILE} is not committed: commit it before finish")
    try:
        applier = parse_applier(AGREEMENT_FILE.read_text())
    except ValueError as exc:
        raise ConfigurationError(f"{AGREEMENT_FILE}: {exc}") from exc
    draft = _load_draft(settings, run_id)
    year = max(draft.periods)
    cases = pool.learning_part(
        _processed(settings), years=set(draft.periods), excluded=run.forbidden
    )
    memory = draft.model_copy(
        update={"lessons": (*draft.lessons, *draft.pushed_out), "pushed_out": ()}
    )
    withheld, causes = checks.development_texts(_processed(settings) / "cases.parquet")
    memory, dropped = drop_failing(memory, withheld, causes)

    applies, failed = run_apply(run, memory, cases, applier, role="apply")
    support = curate.count_support(memory.lessons, cases, applies)
    memory, revised, retired_by_revision = _revise(
        run, memory, support, cases=cases, applies=applies, year=year
    )
    if revised or retired_by_revision:
        memory, dropped_again = drop_failing(memory, withheld, causes)
        dropped += dropped_again
        applies, failed = run_apply(run, memory, cases, applier, role="apply")
        support = curate.count_support(memory.lessons, cases, applies)
    gone = {
        lesson.lesson_id for lesson in memory.lessons if curate.unused(support[lesson.lesson_id])
    }
    memory = memory.model_copy(update={"lessons": _retire(memory.lessons, gone)})
    kept, pushed = curate.apply_cap(
        curate.with_support(memory.lessons, support), tables, draft.cap_tokens
    )
    saved = Memory(
        name=args.to,
        periods=draft.periods,
        cap_tokens=draft.cap_tokens,
        lessons=kept,
        pushed_out=pushed,
    )
    path = snapshots.save(saved, snapshots.SNAPSHOT_DIR)
    for message in dropped:
        print(message)
    counts = {
        "dropped_by_checks": len(dropped),
        "applied_cases": len(cases),
        "failed_applies": failed,
        "revised": revised,
        "retired": len(gone) + retired_by_revision,
        "kept": len(kept),
        "pushed_out": len(pushed),
        "cap_tokens": draft.cap_tokens,
    }
    (settings.runs_dir / run_id / "finish.json").write_text(json.dumps(counts, indent=1) + "\n")
    # Decision 0209: the final apply's answers, so support can be recounted without a call.
    (settings.runs_dir / run_id / APPLIES_FILE).write_text(
        json.dumps({case_id: sorted(ids) for case_id, ids in applies.items()}) + "\n"
    )
    print(", ".join(f"{k.replace('_', ' ')} {v}" for k, v in counts.items()))
    print(f"saved {path.name} (unchecked); next: make mem-check SNAPSHOT={args.to}, then commit")
    print("the snapshot and its stamp")
    return 0


def _revise_call(
    lesson: Lesson,
    support: dict[str, Support],
    cases: Sequence[LearningCase],
    applies: dict[str, frozenset[str]],
    tables: CodeTables,
) -> Call:
    covered = [c for c in cases if lesson.lesson_id in applies.get(c.case_id, frozenset())]
    bad = [c for c in covered if not curate.agrees(lesson, c)]
    good = [c for c in covered if curate.agrees(lesson, c)]
    shown = lesson.model_copy(update={"support": support[lesson.lesson_id]})
    return Call(
        role="revise",
        model=SONNET,
        effort="high",
        system=prompts.SYSTEM_REVISE,
        user=prompts.revise_user(
            render_lesson(shown, tables), bad[:DISAGREEING_SHOWN], good[:AGREEING_SHOWN], tables
        ),
        schema=strict_schema(prompts.ReviseReply),
        max_tokens=MAX_TOKENS_SONNET,
        case_ids=tuple(c.case_id for c in (*bad[:DISAGREEING_SHOWN], *good[:AGREEING_SHOWN])),
    )


def _require_clean(dirty: bool) -> None:
    if dirty:
        raise ConfigurationError("the tree has uncommitted changes: commit first")


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    client_factory: ClientFactory = _default_factory,
) -> int:
    """Run one subcommand.

    Returns:
        0 on success, 1 on a refusal (dirty tree, budget, missing file) or a failed result.
    """
    parser = argparse.ArgumentParser(prog="memory_learn")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("propose")
    p.add_argument("--period", type=int, required=True)
    p.add_argument("--from", dest="from_", required=True, help="'empty' or a snapshot name")
    p.add_argument("--to", required=True, help="name of the snapshot this draft is for")
    p.add_argument("--resume", help="reuse a run folder")
    a = sub.add_parser("agreement")
    a.add_argument("--resume", required=True)
    a.add_argument("--out", default=str(AGREEMENT_FILE))
    f = sub.add_parser("finish")
    f.add_argument("--resume", required=True)
    f.add_argument("--to", required=True)
    args = parser.parse_args(argv)
    settings = settings or Settings()
    try:
        commit, dirty = gitinfo.commit_state()
        _require_clean(dirty)
        tables = load_tables()
        forbidden = pool.excluded_ids()
        if args.command == "propose" and not args.resume:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            run_id = f"{stamp}-{commit}-memory-{args.period}"
        else:
            run_id = args.resume
        client = client_factory(settings, run_id, (commit, dirty), forbidden)
        if client.skipped_lines:
            print(f"{client.skipped_lines} unreadable record lines skipped in run {run_id}")
        run = Run(settings, tables, client, run_id, forbidden, commit)
        commands = {"propose": propose, "agreement": agreement, "finish": finish}
        return commands[args.command](args, run)
    except (ConfigurationError, BudgetError) as exc:
        print(f"refused: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
