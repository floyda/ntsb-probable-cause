"""``ntsb-eval``: baseline, run, report, judge, threshold (spec §6.5). Thin argparse wiring."""

import argparse
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.model.batch import BatchClient
from ntsb_probable_cause.model.client import ModelClient
from ntsb_probable_cause.model.openrouter import OpenRouterClient
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring import ledger, report, samples
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.judge import agreement_table, judge_case, pick_disagreements
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.scoring.runner import BatchRunner, Runner, RunSpec
from ntsb_probable_cause.settings import Settings

ClientFactory = Callable[[Settings], tuple[ModelClient, BatchRunner | None]]


def _default_client_factory(settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
    """The real OpenRouter client and its batch wrapper (spec §7.2)."""
    http = OpenRouterClient(
        settings.require_openrouter_key(), base_url=settings.openrouter_base_url
    )
    return http, BatchClient(http)


def month_spent(runs_dir: Path, *, now: datetime) -> float:
    """Cost of every run started in ``now``'s month, aborted runs included (controller res. 4)."""
    if not runs_dir.exists():
        return 0.0
    total = 0.0
    for run_file in sorted(runs_dir.glob("*/run.jsonl")):
        for record in read_jsonl(run_file, RunRecord):
            if record.started.year == now.year and record.started.month == now.month:
                total += record.cost_usd
    return total


def resolve_latest(runs_dir: Path, arm: str, sample: str) -> str:
    """The newest run id for one arm and sample, by the run id's leading timestamp."""
    suffix = f"-{sample}-{arm}"
    candidates = sorted(p.name for p in runs_dir.glob(f"*{suffix}") if p.is_dir())
    if not candidates:
        raise SystemExit(f"no run found for arm={arm!r} sample={sample!r} under {runs_dir}")
    return candidates[-1]


def _maybe_write(out: str | None, text: str) -> None:
    if out is not None:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if text.endswith("\n") else text + "\n")


def _add_common(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--out", help="also write the printed text to this file")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ntsb-eval")
    commands = parser.add_subparsers(dest="command", required=True)

    baseline_p = commands.add_parser("baseline", help="reproduce and report the S1 baseline")
    baseline_p.add_argument("--sample", choices=samples.SAMPLES, default=None)
    _add_common(baseline_p)

    run_p = commands.add_parser("run", help="run one evaluation arm over a sample")
    run_p.add_argument("--arm", choices=("A", "ceiling"), required=True)
    run_p.add_argument("--sample", choices=samples.SAMPLES, required=True)
    run_p.add_argument("--exclude", action="append", default=[], metavar="ROLE")
    run_p.add_argument("--include", action="append", default=[], choices=("case_number",))
    run_p.add_argument("--model", default=RunSpec.model)
    run_p.add_argument(
        "--price-variant", choices=("batch", "standard"), default=RunSpec.price_variant
    )
    run_p.add_argument("--cap-usd", type=float, default=RunSpec.cap_usd)
    run_p.add_argument("--budget-usd", type=float, default=RunSpec.budget_usd)
    run_p.add_argument("--expected-cost-per-case-usd", type=float, default=None)
    run_p.add_argument("--sync", action="store_true")
    run_p.add_argument("--limit", type=int, default=None, help="only the first N sample cases")
    _add_common(run_p)

    report_p = commands.add_parser("report", help="summarise one run, optionally against another")
    report_p.add_argument("run_id", nargs="?")
    report_p.add_argument("--latest", nargs=2, metavar=("ARM", "SAMPLE"))
    report_p.add_argument("--against")
    report_p.add_argument("--against-latest", nargs=2, metavar=("ARM", "SAMPLE"))
    _add_common(report_p)

    judge_p = commands.add_parser("judge", help="grade one run's prose against the withheld text")
    judge_p.add_argument("run_id")
    judge_p.add_argument(
        "--validated", action="store_true", help="allow judging a run on a non-dev-400 sample"
    )
    _add_common(judge_p)

    threshold_p = commands.add_parser("threshold", help="print the stopping-threshold curve")
    threshold_p.add_argument("run_id")
    _add_common(threshold_p)

    return parser


def _resolve_run_id(runs_dir: Path, run_id: str | None, latest: Sequence[str] | None) -> str:
    if latest:
        return resolve_latest(runs_dir, latest[0], latest[1])
    if run_id:
        return run_id
    raise SystemExit("a run id or --latest ARM SAMPLE is required")


def _cmd_baseline(args: argparse.Namespace, settings: Settings) -> None:
    ids = samples.sample_ids(args.sample) if args.sample else None
    text = report.baseline_report(settings.data_dir / "processed", ids, load_tables())
    print(text)
    _maybe_write(args.out, text)


def _cmd_run(args: argparse.Namespace, settings: Settings, client_factory: ClientFactory) -> None:
    processed = settings.data_dir / "processed"
    ids = samples.sample_ids(args.sample)
    if args.limit is not None:
        ids = ids[: args.limit]
    raws = samples.load_cases(processed, ids)
    seen = samples.seen_pairs(processed)
    commit = ledger.commit_state()
    spent = month_spent(settings.runs_dir, now=datetime.now(UTC))
    client, batch = client_factory(settings)
    spec = RunSpec(
        sample=args.sample,
        arm=args.arm,
        exclusions=frozenset(EvidenceRole(e) for e in args.exclude),
        include_case_number="case_number" in args.include,
        model=args.model,
        price_variant=args.price_variant,
        cap_usd=args.cap_usd,
        budget_usd=args.budget_usd,
        sync=args.sync,
        expected_cost_per_case_usd=args.expected_cost_per_case_usd
        if args.expected_cost_per_case_usd is not None
        else settings.expected_cost_per_case_usd,
    )
    runner = Runner(
        client,
        batch=batch,
        tables=load_tables(),
        seen_pairs=seen,
        runs_dir=settings.runs_dir,
        ledger_path=Path("docs/results/heldout-ledger.md"),
        month_spent_usd=spent,
        commit=commit,
    )
    record = runner.run(spec, raws)
    text = f"run {record.run_id}: {record.cases} cases, ${record.cost_usd:.4f}\n"
    print(text, end="")
    _maybe_write(args.out, text)


def _cmd_report(args: argparse.Namespace, settings: Settings) -> None:
    run_id = _resolve_run_id(settings.runs_dir, args.run_id, args.latest)
    folder = settings.runs_dir / run_id
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    (run_record,) = read_jsonl(folder / "run.jsonl", RunRecord)
    text = report.summarise(cases)
    if run_record.sample == "heldout-400":
        headline = report.fmt(report.weighted_headline(cases))
        text += f"\n\nweighted headline (fatal-share top-1): {headline}"
    if args.against or args.against_latest:
        other_id = args.against or resolve_latest(settings.runs_dir, *args.against_latest)
        other_cases = read_jsonl(settings.runs_dir / other_id / "cases.jsonl", CaseResult)
        text += f"\n\nagainst {other_id}:\n{report.compare(cases, other_cases)}"
    print(text)
    _maybe_write(args.out, text)


def _cmd_threshold(args: argparse.Namespace, settings: Settings) -> None:
    folder = settings.runs_dir / args.run_id
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    curve = report.threshold_curve(cases)
    lines = [f"{t:.2f}\t{v:+.3f}" for t, v in curve]
    lines.append(f"\nchosen threshold: {report.choose_threshold(cases):.2f}")
    text = "\n".join(lines)
    print(text)
    _maybe_write(args.out, text)


def _cmd_judge(args: argparse.Namespace, settings: Settings, client_factory: ClientFactory) -> None:
    folder = settings.runs_dir / args.run_id
    (run_record,) = read_jsonl(folder / "run.jsonl", RunRecord)
    if run_record.sample != "dev-400" and not args.validated:
        raise SystemExit(
            f"judge: refusing on sample {run_record.sample!r} without --validated (spec §8)"
        )
    cases = [c for c in read_jsonl(folder / "cases.jsonl", CaseResult) if c.scores and c.steps]
    processed = settings.data_dir / "processed"
    raws = dict(
        zip(
            [c.case_id for c in cases],
            samples.load_cases(processed, [c.case_id for c in cases]),
            strict=True,
        )
    )
    exclude = frozenset(EvidenceRole(e) for e in run_record.exclusions)
    tables = load_tables()
    client, _ = client_factory(settings)
    rows: list[dict[str, object]] = []
    labels = []
    scores = []
    ids: list[str] = []
    for case in cases:
        if case.scores is None:  # filtered by the comprehension above; narrows for mypy
            continue
        _, synthesis, verdict = split_record(raws[case.case_id], exclude=exclude)
        hypothesis = case.steps[-1].hypothesis
        label, _reply = judge_case(client, hypothesis, synthesis, verdict, tables)
        rows.append({"case_id": case.case_id, **label.model_dump()})
        labels.append(label)
        scores.append(case.scores)
        ids.append(case.case_id)
    (folder / "judge.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    disagreements = pick_disagreements(ids, labels, scores)
    text = (
        f"agreement table: {agreement_table(labels, scores)}\n"
        f"disagreements sampled: {disagreements}"
    )
    print(text)
    _maybe_write(args.out, text)


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: ClientFactory = _default_client_factory,
) -> int:
    """Parse arguments and run one eval command."""
    args = _build_parser().parse_args(argv)
    settings = Settings()
    if args.command == "baseline":
        _cmd_baseline(args, settings)
    elif args.command == "run":
        _cmd_run(args, settings, client_factory)
    elif args.command == "report":
        _cmd_report(args, settings)
    elif args.command == "judge":
        _cmd_judge(args, settings, client_factory)
    elif args.command == "threshold":
        _cmd_threshold(args, settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
