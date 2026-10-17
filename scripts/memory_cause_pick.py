"""The picking call: the learner picks up to five lessons from a case's 20 nearest (decision 0213).

Status
    Live tool for decision 0213's fallback, run only because the steering gate printed
    ``winner: none`` (``docs/rounds/memory-embed-lookup.md`` §4 step 5). Paid from plan credits like
    the apply step (0202, 0207): Sonnet 5.5 at effort high, in batches, role ``test-apply``, spend
    kind ``learning``. It refuses a dirty tree and runs only once the registration is committed. It
    checks the month's learner line (``NTSB_LEARNING_MONTHLY_BUDGET_USD``) with the worst-case
    projection before sending. Its sample is ``dev-steer-400``, or ``dev-seal-400`` once registered
    and only if the picking call won on the steering slice (``memory_embed.steering_winner``).

What it sends
    For each case with a cause sentence and a vector in the embedding run (``--embeds``): the 20
    eligible lessons nearest its cause sentence (``lookup.by_similarity``, every lesson of the
    snapshot, kept or pushed out, support floor 10), shown in id order as the apply step shows
    lessons (``render_for_apply``: ids, statements and scopes, never codes), and the cause sentence
    alone. The client keeps every case of the samples the ``mem`` statistics leave out forbidden,
    and lets ``test-apply`` alone read the chosen sample's (as ``scripts/memory_cause_apply.py``).

What it writes
    ``<runs>/<stamp>-<commit>-memory-cause-pick-<sample>-<model>/``: the client's ``calls.jsonl``
    and ``batches.jsonl``, ``picks.json`` (each sent case's ids, best first: ids not on its
    shortlist dropped, repeats dropped, cut to five) and ``pick.json`` (what made them, and the
    failed replies). It prints counts only and writes no results file: the coverage reading
    (``scripts/memory_coverage.py --picks``) scores the picks, gates them and refuses them past 2%
    failed replies (the registration's §7).

Resume
    ``--resume RUN_ID`` continues a run that died before ``pick.json`` was written: calls with a
    usable reply are not sent again. Once ``pick.json`` exists the run is finished and a resume is
    refused, so failed replies stand.

Usage
    uv run python -m scripts.memory_cause_pick --embeds RUN [--sample S] [--snapshot NAME]
        [--resume RUN_ID]
"""

import argparse
import json
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
from scripts import memory_cause_apply, memory_coding_test, memory_embed, memory_learn

PROG: Final = "memory_cause_pick"
ROLE: Final = memory_cause_apply.ROLE
APPLIER: Final[memory_learn.Applier] = "sonnet-high"
SHORTLIST: Final = 20
PICKS_FILE: Final = "picks.json"
SUMMARY_FILE: Final = "pick.json"
SAMPLES: Final = (memory_coding_test.SAMPLE, memory_coding_test.SEAL_SAMPLE)


class PickSummary(BaseModel):
    """``pick.json``: what the picking run read, and its counts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sample: str
    snapshot: str
    snapshot_sha256: str
    embed_run: str
    embed_model: str
    model: str
    effort: str
    shortlist: int
    cases_sent: int
    failed: int
    commit: str


def allowed_ids(sample: str) -> frozenset[str]:
    """The sample's cases: the ones ``test-apply`` calls may read (0211 item 3, 0213)."""
    return frozenset(samples.sample_ids(sample))


def refuse_finished(folder: Path) -> None:
    """Refuse to resume a finished run, so its failed replies stand and are never retried.

    Raises:
        ConfigurationError: ``pick.json`` exists in ``folder``.
    """
    if (folder / SUMMARY_FILE).exists():
        raise ConfigurationError(f"{folder.name} is finished: its failed replies stand (0213)")


def picked(reply_ids: Sequence[str], shortlist: Sequence[Lesson]) -> list[str]:
    """The reply's ids in its order: off-shortlist ids and repeats dropped, cut to five."""
    allowed = {lesson.lesson_id for lesson in shortlist}
    return [i for i in dict.fromkeys(reply_ids) if i in allowed][: lookup.K]


def shortlists(
    every: Sequence[Lesson], run: memory_embed.EmbedRun, found: Mapping[str, str]
) -> dict[str, tuple[Lesson, ...]]:
    """Each case's 20 nearest eligible lessons, in id order; a case with no vector has none."""
    return {
        case_id: tuple(
            sorted(
                lookup.by_similarity(every, run.lessons, run.cases[case_id], k=SHORTLIST),
                key=lambda lesson: lesson.lesson_id,
            )
        )
        for case_id in found
        if case_id in run.cases
    }


def send(
    settings: Settings,
    client: LearningClient,
    memory: Memory,
    lists: Mapping[str, tuple[Lesson, ...]],
    found: Mapping[str, str],
) -> tuple[dict[str, list[str]], int]:
    """Each sent case's picks, and how many replies failed (a failed reply picks nothing)."""
    model, effort = memory_learn.APPLIERS[APPLIER]
    calls = {
        case_id: memory_learn.pick_call(
            ROLE,
            model,
            effort,
            memory.model_copy(update={"lessons": shortlist, "pushed_out": ()}),
            case_id=case_id,
            cause=found[case_id],
        )
        for case_id, shortlist in lists.items()
    }
    memory_learn.check_budget(settings, list(calls.values()), batch=True, label=f"pick ({APPLIER})")
    replies = client.send_batch(list(calls.values()))
    picks: dict[str, list[str]] = {}
    failed = 0
    for case_id, call in calls.items():
        reply = replies[call.key()]
        ids: list[str] = []
        if reply.ok and reply.text is not None:
            try:
                ids = picked(
                    prompts.ApplyReply.model_validate_json(reply.text).applies, lists[case_id]
                )
            except ValidationError:
                failed += 1
        else:
            failed += 1
        picks[case_id] = ids
    return picks, failed


def refuse_seal_unless_pick_won(sample: str, run: memory_embed.EmbedRun) -> None:
    """On ``dev-seal-400``, run only if the picking call over this run's model won on steering.

    Raises:
        ConfigurationError: the steering winner is not ``pick:<this run's model>``.
    """
    memory_embed.refuse_other_than_winner(run.model, sample, method="pick")


def _run_id(args: argparse.Namespace, commit: str, model: str) -> str:
    """``--resume``'s id, refused unless it names the same sample and model, or a fresh one.

    Raises:
        ConfigurationError: ``--resume`` was made on another sample or embedding model.
    """
    tail = f"-memory-cause-pick-{args.sample}-{memory_embed.slug(model)}"
    if args.resume is not None:
        if not str(args.resume).endswith(tail):
            raise ConfigurationError(
                f"--resume {args.resume} was not made on {args.sample} with {model}: resume it "
                "with the sample and embedding run it was started with"
            )
        return str(args.resume)
    return f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{commit}{tail}"


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    client_factory: memory_learn.ClientFactory = memory_learn.default_factory,
) -> int:
    """Run the picking call on a sample, or resume it. 0 on success, 1 on a refusal."""
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--embeds", required=True, help="the embedding run whose shortlists to use")
    parser.add_argument("--sample", choices=SAMPLES, default=memory_coding_test.SAMPLE)
    parser.add_argument("--snapshot", default=memory_embed.SNAPSHOT)
    parser.add_argument("--resume", metavar="RUN_ID", help="reuse a run folder")
    args = parser.parse_args(argv)
    settings = settings or Settings()
    try:
        commit, dirty = gitinfo.commit_state()
        memory_learn.require_clean(dirty)
        memory_embed.refuse_without_registration()
        memory_coding_test.refuse_sample(args.sample)
        memory = snapshots.load_checked(args.snapshot, snapshots.SNAPSHOT_DIR)
        sha = snapshots.sha256_of(snapshots.snapshot_path(args.snapshot, snapshots.SNAPSHOT_DIR))
        run = memory_embed.read_vectors(
            settings.runs_dir / args.embeds, snapshot=args.snapshot, sha=sha, sample=args.sample
        )
        refuse_seal_unless_pick_won(args.sample, run)
        causes = memory_coding_test.causes(settings.data_dir / "processed", args.sample)
        found = {case_id: cause for case_id, cause in causes.items() if cause}
        lists = shortlists((*memory.lessons, *memory.pushed_out), run, found)
        run_id = _run_id(args, commit, run.model)
        refuse_finished(settings.runs_dir / run_id)
        client = client_factory(settings, run_id, (commit, dirty), pool.excluded_ids())
        client.allow_for_test_apply(allowed_ids(args.sample))
        if client.skipped_lines:
            print(f"{client.skipped_lines} unreadable record lines skipped in run {run_id}")
        picks, failed = send(settings, client, memory, lists, found)
        model, effort = memory_learn.APPLIERS[APPLIER]
        summary = PickSummary(
            sample=args.sample,
            snapshot=args.snapshot,
            snapshot_sha256=sha,
            embed_run=run.run_id,
            embed_model=run.model,
            model=model,
            effort=effort,
            shortlist=SHORTLIST,
            cases_sent=len(lists),
            failed=failed,
            commit=commit,
        )
        folder = settings.runs_dir / run_id
        (folder / PICKS_FILE).write_text(json.dumps(picks, indent=1) + "\n")
        (folder / SUMMARY_FILE).write_text(summary.model_dump_json(indent=1) + "\n")
        sizes = [len(ids) for ids in picks.values()]
        print(
            "\n".join(
                [
                    f"picking run {run_id} (decision 0213)",
                    f"{model} at {effort} over {run.model}'s {SHORTLIST} nearest lessons; "
                    f"sample {args.sample}; snapshot {args.snapshot}",
                    f"cases sent: {len(lists)}; not sent (no cause sentence or no vector): "
                    f"{len(causes) - len(lists)}; failed replies: {failed}",
                    f"lessons picked a case: mean {statistics.mean(sizes) if sizes else 0:.2f}; "
                    f"none {sum(n == 0 for n in sizes)}",
                ]
            )
        )
    except (ConfigurationError, BudgetError) as exc:
        print(f"refused: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
