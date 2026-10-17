"""The apply step on a sample: the lessons each case's cause sentence calls for (0211, 0212).

Status
    Live tool for the cause-lookup test, paid from plan credits like the learner (0202, 0207):
    Sonnet 5.5 at effort high, in batches, the applier the agreement test chose. It refuses a
    dirty tree and runs only once ``docs/rounds/memory-cause-lookup.md`` is committed. It checks
    the month's learner line (``NTSB_LEARNING_MONTHLY_BUDGET_USD``) before sending. Its sample is
    ``dev-steer-400``, or ``dev-400`` for decision 0212's confirmation once
    ``docs/rounds/memory-confirm-dev400.md`` is committed, or ``dev-seal-400`` for decision 0213's
    once ``docs/rounds/memory-embed-lookup.md`` is committed (``memory_coding_test.refuse_sample``).

What it sends
    For each of the sample's cases with a probable-cause sentence, one apply request: the
    learner's apply prompt (``memory_learn.apply_call``) over every lesson of a checked snapshot,
    kept or pushed out, in id order, and the case's cause sentence alone. No code from any answer
    or verdict is sent. The request's role is ``test-apply``; its client keeps every case of the
    samples the ``mem`` statistics leave out forbidden, and lets that role alone read the chosen
    sample's (``LearningClient.allow_for_test_apply``, decision 0211 item 3, 0212). It writes no
    lesson.

What it writes
    ``<runs>/<run id>/``: the client's ``calls.jsonl`` and ``batches.jsonl`` (so a resumed run
    never pays again for a usable reply), ``applies.json`` (each case's lesson ids) and
    ``apply.json`` (the snapshot, its hash, the applier, and counts). Then, counts only,
    ``docs/results/memory-cause-apply-dev.txt`` (``-dev400.txt`` for ``dev-400``,
    ``-devseal.txt`` for ``dev-seal-400``): what the apply step named, and what the cause lookup
    (``lookup.by_fit``) would give each case. No score is read.

Resume
    ``--resume RUN_ID`` continues a run that died before ``apply.json`` was written: calls with a
    usable reply are not sent again. Once ``apply.json`` exists the run is finished and a resume
    is refused, so failed replies are reported as they stand and never retried (the registration's
    §8).

Usage
    uv run python -m scripts.memory_cause_apply --snapshot NAME [--sample S] [--resume RUN_ID]
        [--out PATH]
"""

import argparse
import json
import re
import statistics
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, ValidationError

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.errors import BudgetError, ConfigurationError
from ntsb_probable_cause.memory import lookup, pool, prompts, snapshots
from ntsb_probable_cause.memory.claude import LearningClient
from ntsb_probable_cause.memory.lessons import Lesson, Memory
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.settings import Settings
from scripts import memory_coding_test, memory_learn
from scripts._s3_runs import write_result

PROG: Final = "memory_cause_apply"
REGISTRATION: Final = Path("docs/rounds/memory-cause-lookup.md")
SAMPLE: Final = memory_coding_test.SAMPLE
ROLE: Final = "test-apply"
APPLIER: Final[memory_learn.Applier] = "sonnet-high"
APPLIES_FILE: Final = "applies.json"
SUMMARY_FILE: Final = "apply.json"
DEFAULT_OUT: Final = Path("docs/results/memory-cause-apply-dev.txt")
CONFIRM_OUT: Final = Path("docs/results/memory-cause-apply-dev400.txt")
SEAL_OUT: Final = Path("docs/results/memory-cause-apply-devseal.txt")
SAMPLES: Final = (SAMPLE, memory_coding_test.CONFIRM_SAMPLE, memory_coding_test.SEAL_SAMPLE)
_ID: Final = re.compile(r"L(\d+)")


class ApplySummary(BaseModel):
    """``apply.json``: what the apply run read, and its counts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sample: str
    snapshot: str
    snapshot_sha256: str
    model: str
    effort: str
    lessons_shown: int
    cases_sent: int
    no_cause: int
    failed: int
    commit: str


def refuse_without_registration() -> None:
    """Refuse the apply step until the cause-lookup registration is committed.

    Raises:
        ConfigurationError: ``docs/rounds/memory-cause-lookup.md`` is not committed (0211 item 4).
    """
    if not gitinfo.is_committed(REGISTRATION):
        raise ConfigurationError(
            f"{REGISTRATION} is not committed: the apply step waits for its registration "
            "(decision 0211 item 4)"
        )


def refuse_finished(folder: Path) -> None:
    """Refuse to resume a finished run, so its failed replies stand and are never retried.

    Raises:
        ConfigurationError: ``apply.json`` exists in ``folder`` (the registration's §8).
    """
    if (folder / SUMMARY_FILE).exists():
        raise ConfigurationError(f"{folder.name} is finished: its failed replies stand (0211)")


def allowed_ids(sample: str = SAMPLE) -> frozenset[str]:
    """The sample's cases: the ones ``test-apply`` calls may read (0211 item 3, 0212)."""
    return frozenset(samples.sample_ids(sample))


def _number(lesson: Lesson) -> int:
    found = _ID.fullmatch(lesson.lesson_id)
    return int(found.group(1)) if found else 0


def apply_memory(memory: Memory) -> Memory:
    """The memory the apply step reads: every lesson, kept or pushed out, in id order."""
    every = sorted((*memory.lessons, *memory.pushed_out), key=lambda x: (_number(x), x.lesson_id))
    return memory.model_copy(update={"lessons": tuple(every), "pushed_out": ()})


def send(
    settings: Settings, client: LearningClient, memory: Memory, found: Mapping[str, str]
) -> tuple[dict[str, list[str]], int]:
    """Each case's lesson ids, in sample order, and how many replies failed.

    Unknown ids are dropped; a failed or unparsable reply counts as no lesson.
    """
    model, effort = memory_learn.APPLIERS[APPLIER]
    calls = [
        memory_learn.apply_call(ROLE, model, effort, memory, case_id=case_id, cause=cause)
        for case_id, cause in found.items()
    ]
    memory_learn.check_budget(settings, calls, batch=True, label=f"apply ({APPLIER})")
    replies = client.send_batch(calls)
    known = {lesson.lesson_id for lesson in memory.lessons}
    applied: dict[str, list[str]] = {}
    failed = 0
    for case_id, call in zip(found, calls, strict=True):
        reply = replies[call.key()]
        ids: set[str] = set()
        if reply.ok and reply.text is not None:
            try:
                ids = set(prompts.ApplyReply.model_validate_json(reply.text).applies) & known
            except ValidationError:
                failed += 1
        else:
            failed += 1
        applied[case_id] = sorted(ids)
    return applied, failed


def default_out(sample: str) -> Path:
    """Each sample's own counts file (decisions 0211, 0212, 0213)."""
    return {
        SAMPLE: DEFAULT_OUT,
        memory_coding_test.CONFIRM_SAMPLE: CONFIRM_OUT,
        memory_coding_test.SEAL_SAMPLE: SEAL_OUT,
    }[sample]


def _decision(sample: str) -> str:
    return {
        SAMPLE: "decision 0211",
        memory_coding_test.CONFIRM_SAMPLE: "decisions 0211 and 0212",
        memory_coding_test.SEAL_SAMPLE: "decisions 0211 and 0213",
    }[sample]


def report(memory: Memory, applied: Mapping[str, Sequence[str]], summary: ApplySummary) -> str:
    """The counts-only reading of what the apply step named and what the lookup would give."""
    every = memory.lessons
    named = [len(ids) for ids in applied.values()]
    given = [lookup.by_fit(every, set(ids)) for ids in applied.values()]
    sizes = [len(g) for g in given]
    k = lookup.K
    eligible = sum(x.support is not None and x.support.applies >= lookup.MIN_APPLIES for x in every)
    return "\n".join(
        [
            f"apply step on {summary.sample}'s cause sentences, {summary.snapshot}, "
            f"{summary.model} at {summary.effort} ({_decision(summary.sample)}); counts only",
            "",
            f"lessons shown: {summary.lessons_shown}; the lookup may choose: {eligible} "
            f"(floor {lookup.MIN_APPLIES})",
            f"cases sent: {summary.cases_sent}; without a cause sentence: {summary.no_cause}; "
            f"failed replies: {summary.failed}",
            f"lessons named a case: mean {statistics.mean(named):.2f}, median "
            f"{statistics.median(named):.0f}, none {sum(n == 0 for n in named)}",
            f"cause lookup, K={k}: with {k} lessons {sum(n == k for n in sizes)}; with 1 to "
            f"{k - 1} {sum(0 < n < k for n in sizes)}; with none {sum(n == 0 for n in sizes)}",
            f"distinct lessons the lookup uses: {len({x.lesson_id for g in given for x in g})}",
        ]
    )


def _run_id(args: argparse.Namespace, commit: str) -> str:
    """The run's id: ``--resume``'s, refused unless it names the same sample, or a fresh one.

    Raises:
        ConfigurationError: ``--resume`` names a run made on another sample than ``--sample``,
            which would send that sample's cases into the other run's folder.
    """
    if args.resume is not None:
        named = [s for s in SAMPLES[1:] if f"-memory-cause-apply-{s}-" in args.resume]
        if named != ([] if args.sample == SAMPLE else [args.sample]):
            raise ConfigurationError(
                f"--resume {args.resume} was not made on {args.sample}: resume it with the "
                "sample it was started with"
            )
        return str(args.resume)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    # The steering slice's ids are as decision 0211 made them; another sample is named.
    sample = "" if args.sample == SAMPLE else f"{args.sample}-"
    return f"{stamp}-{commit}-memory-cause-apply-{sample}{args.snapshot}"


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    client_factory: memory_learn.ClientFactory = memory_learn.default_factory,
) -> int:
    """Run the apply step on a sample, or resume it. 0 on success, 1 on a refusal."""
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--snapshot", required=True, help="a checked snapshot's name")
    parser.add_argument("--resume", metavar="RUN_ID", help="reuse a run folder")
    parser.add_argument(
        "--sample",
        choices=SAMPLES,
        default=SAMPLE,
        help="dev-400 for decision 0212's confirmation, dev-seal-400 for 0213's",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    out = args.out or default_out(args.sample)
    settings = settings or Settings()
    try:
        commit, dirty = gitinfo.commit_state()
        memory_learn.require_clean(dirty)
        refuse_without_registration()
        memory_coding_test.refuse_sample(args.sample)
        memory = apply_memory(snapshots.load_checked(args.snapshot, snapshots.SNAPSHOT_DIR))
        sha = snapshots.sha256_of(snapshots.snapshot_path(args.snapshot, snapshots.SNAPSHOT_DIR))
        causes = memory_coding_test.causes(settings.data_dir / "processed", args.sample)
        found = {case_id: cause for case_id, cause in causes.items() if cause is not None}
        run_id = _run_id(args, commit)
        refuse_finished(settings.runs_dir / run_id)
        client = client_factory(settings, run_id, (commit, dirty), pool.excluded_ids())
        client.allow_for_test_apply(allowed_ids(args.sample))
        if client.skipped_lines:
            print(f"{client.skipped_lines} unreadable record lines skipped in run {run_id}")
        applied, failed = send(settings, client, memory, found)
        model, effort = memory_learn.APPLIERS[APPLIER]
        summary = ApplySummary(
            sample=args.sample,
            snapshot=args.snapshot,
            snapshot_sha256=sha,
            model=model,
            effort=effort,
            lessons_shown=len(memory.lessons),
            cases_sent=len(found),
            no_cause=len(causes) - len(found),
            failed=failed,
            commit=commit,
        )
        folder = settings.runs_dir / run_id
        (folder / APPLIES_FILE).write_text(json.dumps(applied, indent=1) + "\n")
        (folder / SUMMARY_FILE).write_text(summary.model_dump_json(indent=1) + "\n")
        text = report(memory, applied, summary)
        print(f"{run_id}\n{text}")
        write_result(PROG, out, text)
    except (ConfigurationError, BudgetError) as exc:
        print(f"refused: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
