"""Lesson coverage, the gate, and the choices file for the embedding lookup (decision 0213).

Status
    Live reading, free: reads finished apply and embedding run folders and the NTSB's verdict
    codes, and makes no model call. Development only: the steering slice, or ``dev-seal-400`` once
    ``docs/rounds/memory-embed-lookup.md`` is committed (``memory_coding_test.refuse_sample``);
    never a live run (decision 0024). Counts only: no case number, cause or lesson text is printed.

What it reads
    Today's cause lookup: an apply run (``scripts/memory_cause_apply.py``), each case's five by
    ``lookup.by_fit``. Each embedding run (``scripts/memory_embed.py embed``): each case's five by
    ``lookup.by_similarity``. Both over every lesson of the snapshot, kept or pushed out. The
    sample's verdict codes, through ``fields``, for scoring only (``memory.coverage``).

With ``--picks``, the picking call's run (``scripts/memory_cause_pick.py``, decision 0213's
fallback) is read as one more candidate, ``pick:<model>``, scored and gated the same way, and
refused past 2% failed replies. If it wins, its choices are written with method ``pick``.

What it prints and writes
    Per lookup: hit rate, precision, lessons handed out, cases with none, and, for each embedding
    run, its hit rate minus today's with the paired 95% interval. On the steering slice, the gate
    (``gate_rule``, the registered text) over all three candidates' runs, and the last line
    ``winner: <model>`` or ``winner: none``; the winner's choices are written. On ``dev-seal-400``
    no gate: one run, of the steering winner (``memory_embed.steering_winner``, read from the
    committed steering reading), named by ``--model``; its choices are written, and the last line
    says the reading is a description only. A dirty tree is refused before anything is written,
    and ``choice.json`` records the clean tree the coding test requires. Output:
    ``docs/results/memory-coverage-dev.txt`` or ``-devseal.txt``. The choices folder,
    ``<runs>/<stamp>-<commit>-memory-choices-<sample>-<model>/``, holds ``choices.json`` (each
    case's lesson ids, in order) and ``choice.json`` (what made them); the coding test's
    ``tools --choices`` reads it.

Usage
    uv run python -m scripts.memory_coverage --applies RUN --embeds RUN [RUN ...]
        [--picks RUN] [--sample S] [--model M] [--snapshot NAME] [--out PATH]
"""

import argparse
import json
import statistics
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import coverage, lookup, snapshots
from ntsb_probable_cause.memory.coverage import Coverage
from ntsb_probable_cause.memory.lessons import Lesson
from ntsb_probable_cause.memory.pool import LearningCase
from ntsb_probable_cause.scoring import metrics, samples
from ntsb_probable_cause.settings import Settings
from scripts import memory_cause_pick, memory_coding_test, memory_embed
from scripts._s3_runs import write_result

PROG: Final = "memory_coverage"
SNAPSHOT: Final = "pilot-2010-recount"
STEERING: Final = memory_coding_test.SAMPLE
SEAL: Final = memory_coding_test.SEAL_SAMPLE
OUTS: Final = {
    STEERING: Path("docs/results/memory-coverage-dev.txt"),
    SEAL: Path("docs/results/memory-coverage-devseal.txt"),
}
CHOICES_FILE: Final = "choices.json"
CHOICE_SUMMARY_FILE: Final = "choice.json"
NONE: Final = "none"

Clock = Callable[[], datetime]
Chosen = dict[str, tuple[Lesson, ...]]


def gate_rule(
    today: Coverage, candidates: Mapping[str, Coverage], prices: Mapping[str, float]
) -> tuple[str | None, list[str]]:
    """Decision 0213, as registered in docs/rounds/memory-embed-lookup.md.

    A candidate passes only if its hit rate minus today's cause lookup's, paired on the same
    cases, is positive with its whole 95% interval above zero, and its precision is no lower
    than today's. Of those that pass, the highest hit rate goes forward; an exact tie goes to the
    lower list price. None passing gives none.
    """
    passed: list[tuple[float, float, str]] = []
    lines: list[str] = []
    for model, cov in candidates.items():
        ids = sorted(today.hits.keys() & cov.hits.keys())
        mean, low, high = metrics.paired_difference(
            [cov.hits[i] for i in ids], [today.hits[i] for i in ids]
        )
        reasons = []
        if not low > 0:
            reasons.append("hit-rate interval not above zero")
        if cov.precision < today.precision:
            reasons.append("precision lower than today's")
        head = (
            f"{model}: hit rate {mean * 100:+.1f} points [{low * 100:+.1f}, {high * 100:+.1f}], "
            f"precision {cov.precision * 100:.1f}% against {today.precision * 100:.1f}%"
        )
        lines.append(f"{head}: {'not passed: ' + '; '.join(reasons) if reasons else 'passed'}")
        if not reasons:
            passed.append((-cov.hit_rate, prices[model], model))
    return (min(passed)[2] if passed else None), lines


def verdict_cases_for(processed: Path, sample: str) -> tuple[dict[str, LearningCase], int]:
    """The sample's cases to score and how many were left out (``coverage.verdict_cases``).

    Raises:
        ConfigurationError: a case of the sample is not in the processed file.
    """
    ids = samples.sample_ids(sample)
    try:
        raws = samples.load_cases(processed, ids)
    except ValueError:
        raise ConfigurationError(
            f"some of the {len(ids)} cases are not in {processed / 'cases.parquet'}"
        ) from None
    return coverage.verdict_cases(ids, raws)


def read_picks(  # noqa: PLR0913 -- the run and every fact it must match
    folder: Path,
    *,
    snapshot: str,
    sha: str,
    sample: str,
    embeds: Mapping[str, memory_embed.EmbedRun],
    lessons: Mapping[str, Lesson],
) -> tuple[memory_cause_pick.PickSummary, Chosen]:
    """A picking run's summary and each case's picked lessons, best first.

    Raises:
        ConfigurationError: no readable picking run; one on another sample, snapshot, snapshot
            file or embedding model; one whose embedding run is not among ``embeds``; more than
            2% failed replies (the registration's §7); an id that is not a lesson of the
            snapshot, or more than K ids for a case.
    """
    try:
        summary = memory_cause_pick.PickSummary.model_validate_json(
            (folder / memory_cause_pick.SUMMARY_FILE).read_text()
        )
        raw = json.loads((folder / memory_cause_pick.PICKS_FILE).read_text())
        picks = {str(case_id): [str(i) for i in ids] for case_id, ids in raw.items()}
    except (OSError, ValueError, ValidationError, AttributeError, TypeError) as error:
        raise ConfigurationError(
            f"{folder.name}: not a finished picking run ({type(error).__name__})"
        ) from None
    if summary.embed_run not in embeds:
        raise ConfigurationError(
            f"{folder.name}: its embedding run is not one of the --embeds runs"
        )
    wanted = {
        "sample": sample,
        "snapshot": snapshot,
        "snapshot_sha256": sha,
        "embed_model": embeds[summary.embed_run].model,
    }
    differing = [key for key, value in wanted.items() if getattr(summary, key) != value]
    if differing:
        raise ConfigurationError(f"{folder.name} differs in {', '.join(differing)}")
    if summary.failed * 100 > summary.cases_sent * 2:
        raise ConfigurationError(
            f"{folder.name}: {summary.failed} of {summary.cases_sent} replies failed, more than "
            "2%: its picks are not used (decision 0213)"
        )
    for ids in picks.values():
        if len(ids) > lookup.K or not set(ids) <= set(lessons):
            raise ConfigurationError(
                f"{folder.name}: a case has more than {lookup.K} ids, or an id the snapshot lacks"
            )
    return summary, {case_id: tuple(lessons[i] for i in ids) for case_id, ids in picks.items()}


def _block(label: str, cov: Coverage, chosen: Chosen) -> list[str]:
    sizes = [len(chosen.get(case_id, ())) for case_id in cov.hits]
    mean = statistics.mean(sizes) if sizes else 0.0
    return [
        label,
        f"  hit rate: {cov.hit_rate * 100:.1f}% n={len(cov.hits)}",
        f"  precision: {cov.precision * 100:.1f}% ({cov.agreeing} of {cov.handed_out} lessons)",
        f"  lessons a case: mean {mean:.2f}; with none {sum(n == 0 for n in sizes)}",
    ]


def _paired_line(cov: Coverage, today: Coverage) -> str:
    ids = sorted(today.hits.keys() & cov.hits.keys())
    mean, low, high = metrics.paired_difference(
        [cov.hits[i] for i in ids], [today.hits[i] for i in ids]
    )
    return (
        f"  hit rate minus today's: {mean * 100:+.1f} points "
        f"[{low * 100:+.1f}, {high * 100:+.1f}] n={len(ids)}"
    )


def _write_choices(  # noqa: PLR0913 -- the choices and every fact that made them
    runs_dir: Path,
    chosen: Chosen,
    *,
    sample: str,
    snapshot: str,
    sha: str,
    candidate: str,
    source_run: str,
    commit: str,
    now: datetime,
) -> str:
    slug = memory_embed.slug(candidate)
    run_id = f"{now:%Y%m%dT%H%M%SZ}-{commit}-memory-choices-{sample}-{slug}"
    folder = runs_dir / run_id
    folder.mkdir(parents=True)
    ids = {case_id: [lesson.lesson_id for lesson in lessons] for case_id, lessons in chosen.items()}
    (folder / CHOICES_FILE).write_text(json.dumps(ids, indent=1) + "\n")
    summary = {
        "sample": sample,
        "snapshot": snapshot,
        "snapshot_sha256": sha,
        "k": lookup.K,
        "min_applies": lookup.MIN_APPLIES,
        "method": "pick" if candidate.startswith(memory_embed.PICK_PREFIX) else "embedding",
        "model": candidate.removeprefix(memory_embed.PICK_PREFIX),
        "source_run": source_run,
        "commit": commit,
        "dirty": False,
    }
    (folder / CHOICE_SUMMARY_FILE).write_text(json.dumps(summary, indent=1) + "\n")
    return run_id


def _refuse_seal_arguments(args: argparse.Namespace) -> None:
    """On ``dev-seal-400``: one embedding run, of the steering winner, and its method.

    Raises:
        ConfigurationError: no ``--model``; not exactly one ``--embeds`` run; or a model or
            method (``--picks`` or not) other than the steering winner's.
    """
    if args.model is None:
        raise ConfigurationError(f"on {SEAL}, --model names the method the steering slice chose")
    if len(args.embeds) != 1:
        raise ConfigurationError(f"on {SEAL}, name one embedding run: the steering winner's")
    method = "pick" if args.picks is not None else "embedding"
    memory_embed.refuse_other_than_winner(args.model, SEAL, method=method)


def _embedding_runs(
    args: argparse.Namespace, settings: Settings, sha: str
) -> dict[str, memory_embed.EmbedRun]:
    """The ``--embeds`` runs by model.

    Raises:
        ConfigurationError: a run that does not belong (``read_vectors``); two runs of one model;
            ``--model`` naming none of them; or, on the steering slice, not all three candidates.
    """
    runs = [
        memory_embed.read_vectors(
            settings.runs_dir / name, snapshot=args.snapshot, sha=sha, sample=args.sample
        )
        for name in args.embeds
    ]
    by_model = {run.model: run for run in runs}
    if len(by_model) != len(runs):
        raise ConfigurationError("two embedding runs of one model: name one run per model")
    if args.model is not None and args.model not in by_model:
        raise ConfigurationError(f"--model {args.model} names no embedding run given")
    if args.sample == STEERING and set(by_model) != set(memory_embed.CANDIDATES):
        raise ConfigurationError(
            "the gate reads all three candidates' embedding runs (decision 0213): "
            f"{len(by_model)} given"
        )
    return by_model


def reading(args: argparse.Namespace, settings: Settings, now: datetime) -> str:
    """The whole text; writes the choices folder of the winner (steering) or of ``--model``.

    Raises:
        ConfigurationError: a refused sample, run or argument (see the module docstring).
    """
    sample: str = args.sample
    if sample not in OUTS:
        raise ConfigurationError(f"lesson coverage reads {STEERING} or {SEAL}, not {sample}")
    memory_coding_test.refuse_sample(sample)
    # Before anything is written: a choices folder from uncommitted code would feed a paid run.
    commit, dirty = gitinfo.commit_state()
    memory_embed.require_clean(dirty)
    if sample == SEAL:
        _refuse_seal_arguments(args)
    memory = snapshots.load_checked(args.snapshot, snapshots.SNAPSHOT_DIR)
    sha = snapshots.sha256_of(snapshots.snapshot_path(args.snapshot, snapshots.SNAPSHOT_DIR))
    every = (*memory.lessons, *memory.pushed_out)
    applied = memory_coding_test.read_applies(
        settings.runs_dir / args.applies, args.snapshot, sha, sample
    )
    by_model = _embedding_runs(args, settings, sha)
    pick: memory_cause_pick.PickSummary | None = None
    if args.picks is not None:
        pick, picked = read_picks(
            settings.runs_dir / args.picks,
            snapshot=args.snapshot,
            sha=sha,
            sample=sample,
            embeds={run.run_id: run for run in by_model.values()},
            lessons={lesson.lesson_id: lesson for lesson in every},
        )
    cases, left_out = verdict_cases_for(settings.data_dir / "processed", sample)

    today_chosen: Chosen = {
        case_id: lookup.by_fit(every, applied.get(case_id, frozenset())) for case_id in cases
    }
    chosen: dict[str, Chosen] = {
        model: {
            case_id: lookup.by_similarity(every, run.lessons, run.cases[case_id])
            for case_id in cases
            if case_id in run.cases
        }
        for model, run in by_model.items()
    }
    labels = {
        model: f"{model} (embedding run {run.run_id}; {len(run.failed_cases)} failed)"
        for model, run in by_model.items()
    }
    sources = {model: run.run_id for model, run in by_model.items()}
    if pick is not None:
        name = f"{memory_embed.PICK_PREFIX}{pick.embed_model}"
        chosen[name] = {case_id: picked[case_id] for case_id in cases if case_id in picked}
        labels[name] = (
            f"{name}, the picking call over {pick.embed_model}'s {pick.shortlist} nearest "
            f"(picking run {args.picks}; {pick.failed} of {pick.cases_sent} replies failed)"
        )
        sources[name] = str(args.picks)
    today = coverage.coverage(today_chosen, cases)
    scored = {model: coverage.coverage(c, cases) for model, c in chosen.items()}

    out = [
        f"lesson coverage on {sample}, {args.snapshot}, K={lookup.K}, floor {lookup.MIN_APPLIES} "
        "(decision 0213); counts only",
        "",
        f"cases scored: {len(cases)}; left out (no occurrence code): {left_out}",
        "",
        *_block(f"today's cause lookup (apply run {args.applies})", today, today_chosen),
    ]
    for name, cov in scored.items():
        out += [*_block(labels[name], cov, chosen[name]), _paired_line(cov, today)]
    if sample == STEERING:
        prices = memory_embed.load_prices(settings.data_dir)
        # The picking call is priced as the model whose shortlist it read, for a tie only.
        prices |= {name: prices[name.removeprefix(memory_embed.PICK_PREFIX)] for name in scored}
        winner, lines = gate_rule(today, scored, prices)
        out += ["", "gate (decision 0213)", *[f"  {line}" for line in lines]]
        last = f"winner: {winner or NONE}"
    else:
        prefix = memory_embed.PICK_PREFIX if pick is not None else ""
        winner, last = f"{prefix}{args.model}", "description only (decision 0213)"
    if winner is not None:
        choices_run = _write_choices(
            settings.runs_dir,
            chosen[winner],
            sample=sample,
            snapshot=args.snapshot,
            sha=sha,
            candidate=winner,
            source_run=sources[winner],
            commit=commit,
            now=now,
        )
        out.append(f"choices run: {choices_run}")
    out.append(last)
    return "\n".join(out)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def main(
    argv: Sequence[str] | None = None, *, settings: Settings | None = None, now: Clock = _utc_now
) -> int:
    """Read the runs, apply the gate on the steering slice, write the choices. 0, or 1 refused."""
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("--applies", required=True, help="today's apply run on the sample")
    parser.add_argument("--embeds", nargs="+", required=True, help="one embedding run per model")
    parser.add_argument("--sample", default=STEERING, choices=tuple(OUTS))
    parser.add_argument("--model", help=f"on {SEAL}: the model whose choices to write")
    parser.add_argument("--picks", help="the picking call's run, over one of the --embeds runs")
    parser.add_argument("--snapshot", default=SNAPSHOT)
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
