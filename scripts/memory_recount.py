"""Recount a learner run's lessons by the corrected rule, from its saved answers (decision 0209).

Status
    Live tool, free, local: sends no call. Needs the learner run's folder under ``NTSB_RUNS_DIR``
    and ``data/processed/cases.parquet``. Development only: the run's learning-part cases.

What it reads
    The run's ``draft.json`` and saved replies (``calls.jsonl``), the snapshot its ``finish`` step
    saved, and the agreement file that named the applier. A run finished after decision 0209 keeps
    its final apply's answers in ``applies.json``, which is read directly. An earlier run's answers
    are rebuilt: the final apply's memory text is the draft's lessons in their order, with the
    snapshot's revised texts and without the lessons the checks dropped. A lesson retired as unused
    after that apply is in the text but not in the snapshot, so each lesson the snapshot lacks is
    tried in turn. A rebuild is accepted only when every case's request key is among the saved
    apply replies, so the answers counted are the ones the applier gave; otherwise it refuses.

What it writes
    A new snapshot, unchecked, with the snapshot's lesson texts, support counted by the corrected
    rule (``curate.count_support``), lessons no case falls under retired, and the cap applied
    (``curate.apply_cap``). Run ``make mem-check SNAPSHOT=<name>`` next, then commit the snapshot
    and its stamp. Prints counts only.

Usage
    uv run python -m scripts.memory_recount --run RUN_ID --from SNAPSHOT --to NAME
"""

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from pydantic import ValidationError

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import claude, curate, pool, prompts, snapshots
from ntsb_probable_cause.memory.lessons import Memory
from ntsb_probable_cause.memory.pool import LearningCase
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.settings import Settings
from scripts import memory_learn as ml

CallKey = Callable[[Memory, LearningCase], str]


def saved_applies(folder: Path) -> dict[str, str]:
    """Every answered apply reply in the run, by request key."""
    replies, _ = claude.read_replies(folder / claude.CALLS_FILE)
    return {r.key: r.text for r in replies if r.role == "apply" and r.ok and r.text is not None}


def final_apply_memory(draft: Memory, final: Memory, extra: str | None) -> Memory:
    """The memory the final apply read, if ``extra`` is the one lesson retired after it."""
    texts = {lesson.lesson_id: lesson for lesson in (*final.lessons, *final.pushed_out)}
    lessons = tuple(
        texts.get(lesson.lesson_id, lesson)
        for lesson in (*draft.lessons, *draft.pushed_out)
        if lesson.lesson_id in texts or lesson.lesson_id == extra
    )
    return draft.model_copy(update={"lessons": lessons, "pushed_out": ()})


def rebuild_applies(
    draft: Memory,
    final: Memory,
    cases: Sequence[LearningCase],
    call_key: CallKey,
    saved: Mapping[str, str],
) -> tuple[dict[str, frozenset[str]], str | None]:
    """The final apply's answers, and the retired lesson the rebuild needed (None if none).

    Raises:
        ConfigurationError: no candidate memory text gives every case a saved reply.
    """
    kept = {lesson.lesson_id for lesson in (*final.lessons, *final.pushed_out)}
    missing = [
        lesson.lesson_id
        for lesson in (*draft.lessons, *draft.pushed_out)
        if lesson.lesson_id not in kept
    ]
    for extra in (None, *missing):
        memory = final_apply_memory(draft, final, extra)
        keys = {case.case_id: call_key(memory, case) for case in cases}
        if not all(key in saved for key in keys.values()):
            continue
        known = {lesson.lesson_id for lesson in memory.lessons}
        found: dict[str, frozenset[str]] = {}
        for case_id, key in keys.items():
            try:
                ids = prompts.ApplyReply.model_validate_json(saved[key]).applies
            except ValidationError:
                ids = []  # as run_apply: an unparsable reply counts as an empty set
            found[case_id] = frozenset(ids) & known
        return found, extra
    raise ConfigurationError(
        "no rebuilt memory text matches the saved apply replies for every case: "
        "the answers cannot be recovered without a call"
    )


def recount(
    final: Memory, name: str, cases: Sequence[LearningCase], applies: Mapping[str, frozenset[str]]
) -> Memory:
    """The snapshot's lessons with corrected support, unused ones retired, the cap applied."""
    lessons = (*final.lessons, *final.pushed_out)
    support = curate.count_support(lessons, cases, applies)
    used = [lesson for lesson in lessons if not curate.unused(support[lesson.lesson_id])]
    kept, pushed = curate.apply_cap(
        curate.with_support(used, support), load_tables(), final.cap_tokens
    )
    return Memory(
        name=name,
        periods=final.periods,
        cap_tokens=final.cap_tokens,
        lessons=kept,
        pushed_out=pushed,
    )


def refuse_other_cases(folder: Path, n_cases: int) -> None:
    """Refuse a recount over a different number of cases than the run's finish step applied to.

    Raises:
        ConfigurationError: ``finish.json`` is missing, or its ``applied_cases`` is not
            ``n_cases`` (the processed file or the exclusions changed since the run).
    """
    try:
        applied = json.loads((folder / "finish.json").read_text())["applied_cases"]
    except OSError, ValueError, KeyError:
        raise ConfigurationError(f"{folder.name}: no finished finish step to recount") from None
    if applied != n_cases:
        raise ConfigurationError(
            f"the finish step applied to {applied} cases; the recount would count {n_cases}"
        )


def _answers(
    folder: Path, draft: Memory, final: Memory, cases: Sequence[LearningCase]
) -> tuple[dict[str, frozenset[str]], str]:
    """The final apply's answers, read or rebuilt, and how they were obtained."""
    stored = folder / ml.APPLIES_FILE
    if stored.exists():
        raw = json.loads(stored.read_text())
        applies = {case_id: frozenset(ids) for case_id, ids in raw.items()}
        known = {lesson.lesson_id for lesson in (*final.lessons, *final.pushed_out)}
        if applies.keys() != {case.case_id for case in cases}:
            raise ConfigurationError(f"{stored.name} covers other cases than the run's periods")
        if not set().union(*applies.values()) <= known:
            raise ConfigurationError(f"{stored.name} names lessons the snapshot does not hold")
        return applies, f"read from {stored.name}"
    model, effort = ml.APPLIERS[ml.parse_applier(ml.AGREEMENT_FILE.read_text())]

    def call_key(memory: Memory, case: LearningCase) -> str:
        return ml.call_for_apply("apply", model, effort, memory, case).key()

    applies, extra = rebuild_applies(draft, final, cases, call_key, saved_applies(folder))
    return applies, (
        "rebuilt from saved replies, every key matched; "
        f"retired lesson in the text: {extra or 'none'}"
    )


def _recount_run(args: argparse.Namespace, settings: Settings) -> tuple[Memory, int, str]:
    """The recounted snapshot, the number of cases and how the answers were obtained.

    Raises:
        ConfigurationError: the new name is taken, or the answers cannot be recovered.
    """
    if snapshots.snapshot_path(args.to, snapshots.SNAPSHOT_DIR).exists():
        raise ConfigurationError(f"snapshot {args.to} already exists")
    folder = settings.runs_dir / args.run
    draft = Memory.model_validate_json((folder / "draft.json").read_text())
    final = snapshots.load(args.source, snapshots.SNAPSHOT_DIR)
    cases = pool.learning_part(
        settings.data_dir / "processed", years=set(draft.periods), excluded=pool.excluded_ids()
    )
    refuse_other_cases(folder, len(cases))
    applies, how = _answers(folder, draft, final, cases)
    return recount(final, args.to, cases, applies), len(cases), how


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    """Recount, save the new snapshot unchecked, and print counts. 0 on success, 1 on a refusal."""
    parser = argparse.ArgumentParser(prog="memory_recount", description=__doc__)
    parser.add_argument("--run", required=True, help="the learner run whose finish saved --from")
    parser.add_argument("--from", dest="source", required=True, help="the snapshot to recount")
    parser.add_argument("--to", required=True, help="the new snapshot's name")
    args = parser.parse_args(argv)
    try:
        memory, n_cases, how = _recount_run(args, settings or Settings())
    except (ConfigurationError, OSError, ValueError) as error:
        print(f"memory_recount: {error}")
        return 1
    path = snapshots.save(memory, snapshots.SNAPSHOT_DIR)
    print(f"{n_cases} cases; answers {how}")
    print(
        f"kept {len(memory.lessons)}, pushed out {len(memory.pushed_out)}, cap {memory.cap_tokens}"
    )
    print(f"saved {path.name} (unchecked); next: make mem-check SNAPSHOT={args.to}, then commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
