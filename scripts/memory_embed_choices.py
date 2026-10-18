"""The choices of decision 0214's four embedding lookups, and their lesson coverage, described.

Status
    Live reading, free: reads finished apply, embedding and picking run folders and the NTSB's
    verdict codes, and makes no model call. Development only: the steering slice, or
    ``dev-seal-400`` (``memory_coding_test.refuse_sample``); never a live run (decision 0024).
    Refused until ``docs/rounds/memory-embed-coding.md`` is committed, and refused on a dirty tree
    before anything is written. Counts only: no case number, cause or lesson text is printed.

The candidates
    All over one embedding run of ``openai/text-embedding-3-large``, every lesson of the snapshot
    (kept or pushed out), K = 5 and the support floor of 10:

    - ``openai/text-embedding-3-large``: the five nearest by cosine (``lookup.by_similarity``);
    - ``pick:openai/text-embedding-3-large``: the picking call's run over that embedding run;
    - ``fit:openai/text-embedding-3-large``: the five with the highest cosine x fit
      (``lookup.by_similarity_fit``);
    - ``fill:openai/text-embedding-3-large``: today's cause lookup (``lookup.by_fit`` over the
      apply run), and for a case it leaves empty the one nearest lesson
      (``lookup.by_fit_or_nearest``).

What it prints and writes
    Today's cause lookup and each candidate: hit rate, precision, lessons a case, each part apart
    (``coverage.part_coverage``) and, for a candidate, both hit rates minus today's, paired. It
    decides nothing: the coding test does (``scripts/memory_embed_coding_result.py``). On the
    steering slice it writes the four candidates' choices folders; on ``dev-seal-400`` only the
    steering winner's (``--candidate``, checked by ``memory_embed.refuse_other_than_winner``),
    with ``--picks`` if and only if the winner is the picking call. Each choices folder is
    ``memory_coverage``'s, read by ``memory_coding_test tools --choices``. Output:
    ``docs/results/memory-embed-choices-dev.txt`` or ``-devseal.txt``.

Usage
    uv run python -m scripts.memory_embed_choices --applies RUN --embeds RUN [--picks RUN]
        [--sample S] [--candidate NAME] [--snapshot NAME] [--out PATH]
"""

import argparse
import statistics
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import coverage, lookup, snapshots
from ntsb_probable_cause.memory.coverage import Coverage
from ntsb_probable_cause.memory.lessons import Lesson
from ntsb_probable_cause.memory.pool import LearningCase
from ntsb_probable_cause.scoring import metrics
from ntsb_probable_cause.settings import Settings
from scripts import memory_coding_test, memory_coverage, memory_embed
from scripts._s3_runs import write_result

PROG: Final = "memory_embed_choices"
REGISTRATION: Final = Path("docs/rounds/memory-embed-coding.md")
MODEL: Final = "openai/text-embedding-3-large"
METHODS: Final = ("embedding", "pick", "fit", "fill")  # decision 0214 item 2, in its order
STEERING: Final = memory_coding_test.SAMPLE
SEAL: Final = memory_coding_test.SEAL_SAMPLE
OUTS: Final = {
    STEERING: Path("docs/results/memory-embed-choices-dev.txt"),
    SEAL: Path("docs/results/memory-embed-choices-devseal.txt"),
}
CHOICES_FILE: Final = memory_coverage.CHOICES_FILE
CHOICE_SUMMARY_FILE: Final = memory_coverage.CHOICE_SUMMARY_FILE
LAST_LINE: Final = "description only (decision 0214): the coding test decides"

Clock = Callable[[], datetime]
Chosen = dict[str, tuple[Lesson, ...]]


def refuse_without_registration() -> None:
    """Refuse until 0214's registration is committed.

    Raises:
        ConfigurationError: ``docs/rounds/memory-embed-coding.md`` is not committed.
    """
    if not gitinfo.is_committed(REGISTRATION):
        raise ConfigurationError(
            f"{REGISTRATION} is not committed: decision 0214's choices wait for its registration"
        )


def part_lines(
    chosen: Mapping[str, Sequence[Lesson]],
    cases: Mapping[str, LearningCase],
    today: tuple[Coverage, Coverage] | None,
) -> list[str]:
    """Each part's coverage, and each part's case hit minus ``today``'s when given."""
    lines: list[str] = []
    for label, part, against in zip(
        ("first-code part", "finding part"),
        coverage.part_coverage(chosen, cases),
        today or (None, None),
        strict=True,
    ):
        share = (
            f"{part.precision * 100:.1f}% ({part.agreeing} of {part.handed_out})"
            if part.handed_out
            else "none handed out"
        )
        lines.append(f"  {label}: case hit {part.hit_rate * 100:.1f}%, precision {share}")
        if against is not None:
            ids = sorted(against.hits.keys() & part.hits.keys())
            mean, low, high = metrics.paired_difference(
                [part.hits[i] for i in ids], [against.hits[i] for i in ids]
            )
            lines.append(
                f"    {label} case hit minus today's: {mean * 100:+.1f} points "
                f"[{low * 100:+.1f}, {high * 100:+.1f}] n={len(ids)}"
            )
    return lines


def choose(  # noqa: PLR0913 -- the method and every input a method reads
    method: str,
    *,
    every: Sequence[Lesson],
    applied: Mapping[str, frozenset[str]],
    run: memory_embed.EmbedRun,
    picked: Mapping[str, tuple[Lesson, ...]],
    cases: Mapping[str, LearningCase],
) -> Chosen:
    """Each scored case's lessons under ``method`` (decision 0214 item 2)."""
    if method == "pick":
        return {c: picked[c] for c in cases if c in picked}
    if method == "fill":
        return {
            c: lookup.by_fit_or_nearest(
                every, applied.get(c, frozenset()), run.lessons, run.cases.get(c)
            )
            for c in cases
        }
    rank = lookup.by_similarity_fit if method == "fit" else lookup.by_similarity
    return {c: rank(every, run.lessons, run.cases[c]) for c in cases if c in run.cases}


def _methods(args: argparse.Namespace) -> tuple[str, ...]:
    """The methods to write, refused unless the arguments fit the sample.

    Raises:
        ConfigurationError: on the steering slice, ``--candidate`` or no ``--picks``; on
            ``dev-seal-400``, no ``--candidate``, one other than the steering winner, or
            ``--picks`` given exactly when the winner is not the picking call.
    """
    if args.sample == STEERING:
        if args.candidate is not None:
            raise ConfigurationError(
                f"--candidate is for {SEAL}: the steering slice writes all four"
            )
        if args.picks is None:
            raise ConfigurationError("the steering slice needs --picks, the picking call's run")
        return METHODS
    if args.candidate is None:
        raise ConfigurationError(f"on {SEAL}, --candidate names the steering winner")
    method, model = memory_embed.split_candidate(args.candidate)
    memory_embed.refuse_other_than_winner(model, SEAL, method=method)
    if (args.picks is not None) != (method == "pick"):
        raise ConfigurationError(f"on {SEAL}, --picks goes with the picking call only")
    return (method,)


def reading(args: argparse.Namespace, settings: Settings, now: datetime) -> str:
    """The whole text; writes the choices folders.

    Raises:
        ConfigurationError: a refused sample, run or argument (see the module docstring).
    """
    sample: str = args.sample
    refuse_without_registration()
    memory_coding_test.refuse_sample(sample)
    commit, dirty = gitinfo.commit_state()
    memory_embed.require_clean(dirty)
    methods = _methods(args)
    memory = snapshots.load_checked(args.snapshot, snapshots.SNAPSHOT_DIR)
    sha = snapshots.sha256_of(snapshots.snapshot_path(args.snapshot, snapshots.SNAPSHOT_DIR))
    every = (*memory.lessons, *memory.pushed_out)
    applied = memory_coding_test.read_applies(
        settings.runs_dir / args.applies, args.snapshot, sha, sample
    )
    run = memory_embed.read_vectors(
        settings.runs_dir / args.embeds, snapshot=args.snapshot, sha=sha, sample=sample
    )
    if run.model != MODEL:
        raise ConfigurationError(f"decision 0214's candidates are over {MODEL}, not {run.model}")
    picked: dict[str, tuple[Lesson, ...]] = {}
    if args.picks is not None:
        _summary, picked = memory_coverage.read_picks(
            settings.runs_dir / args.picks,
            snapshot=args.snapshot,
            sha=sha,
            sample=sample,
            embeds={run.run_id: run},
            lessons={lesson.lesson_id: lesson for lesson in every},
        )
    cases, left_out = memory_coverage.verdict_cases_for(settings.data_dir / "processed", sample)
    today = {c: lookup.by_fit(every, applied.get(c, frozenset())) for c in cases}
    today_parts = coverage.part_coverage(today, cases)
    today_cov = coverage.coverage(today, cases)
    out = [
        f"embedding lookups for the coding test, {sample}, {args.snapshot}, K={lookup.K}, "
        f"floor {lookup.MIN_APPLIES} (decision 0214); counts only",
        "",
        f"cases scored: {len(cases)}; left out (no occurrence code): {left_out}",
        "",
        *memory_coverage._block(
            f"today's cause lookup (apply run {args.applies})", today_cov, today
        ),
        *part_lines(today, cases, None),
    ]
    for method in methods:
        chosen = choose(method, every=every, applied=applied, run=run, picked=picked, cases=cases)
        name = memory_embed.candidate_name(method, MODEL)
        source = args.picks if method == "pick" else run.run_id
        cov = coverage.coverage(chosen, cases)
        out += [
            "",
            *memory_coverage._block(f"{name} (from {source})", cov, chosen),
            memory_coverage._paired_line(cov, today_cov),
            *part_lines(chosen, cases, today_parts),
        ]
        choices_run = memory_coverage._write_choices(
            settings.runs_dir,
            chosen,
            sample=sample,
            snapshot=args.snapshot,
            sha=sha,
            candidate=name,
            source_run=source,
            commit=commit,
            now=now,
            extra={"applies_run": args.applies} if method == "fill" else {},
        )
        out.append(f"choices run: {choices_run}")
    lessons_a_case = statistics.mean(len(v) for v in today.values()) if today else 0.0
    out += ["", f"today's lessons a case: {lessons_a_case:.2f}", LAST_LINE]
    return "\n".join(out)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def main(
    argv: Sequence[str] | None = None, *, settings: Settings | None = None, now: Clock = _utc_now
) -> int:
    """Write the choices and their description. 0, or 1 refused."""
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--applies", required=True, help="today's apply run on the sample")
    parser.add_argument("--embeds", required=True, help=f"the sample's {MODEL} embedding run")
    parser.add_argument("--picks", help="the picking call's run over that embedding run")
    parser.add_argument("--sample", default=STEERING, choices=tuple(OUTS))
    parser.add_argument("--candidate", help=f"on {SEAL}: the steering winner")
    parser.add_argument("--snapshot", default=memory_coverage.SNAPSHOT)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    settings = settings or Settings()
    try:
        text = reading(args, settings, now())
        print(text)
        write_result(PROG, args.out or OUTS[args.sample], text)
    except ConfigurationError as exc:
        print(f"refused: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
