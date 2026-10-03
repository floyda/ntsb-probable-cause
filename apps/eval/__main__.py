"""``ntsb-eval``: baseline, run, report, judge, threshold (spec §6.5). Thin argparse wiring."""

import argparse
import contextlib
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from ntsb_probable_cause import gitinfo, sources
from ntsb_probable_cause.agent import armb
from ntsb_probable_cause.agent import loop as agent_loop
from ntsb_probable_cause.agent import run as agent_run
from ntsb_probable_cause.agent.run import AgentRunner
from ntsb_probable_cause.agent.texts import is_plain as is_plain_agent_prompt
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.documents import CachedDocuments
from ntsb_probable_cause.docket.render import RESOLUTION
from ntsb_probable_cause.docket.transcribe import (
    PAGE_RULE,
    PAGE_RULES,
    TRANSCRIBE,
    TRANSCRIBER,
    PageJob,
    PageRule,
    ReadingLookup,
    Transcription,
    TranscriptionCache,
    TranscriptionKey,
    key_instruction,
    pages_to_read,
)
from ntsb_probable_cause.errors import (
    BatchCancelledError,
    BudgetError,
    ConfigurationError,
    DocketError,
)
from ntsb_probable_cause.fields import EVIDENCE_FIELDS, EvidenceRole
from ntsb_probable_cause.model.batch import BatchClient
from ntsb_probable_cause.model.client import ModelClient
from ntsb_probable_cause.model.openrouter import OpenRouterClient
from ntsb_probable_cause.model.typesafe import TypeSafeClient
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring import checkpass, ledger, prompt, report, samples
from ntsb_probable_cause.scoring.budget import (
    month_spent,
    open_reservations,
    release,
    reserve_within_budget,
)
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import (
    STATS_NAMES,
    load_stats,
    refuse_pool_holding,
)
from ntsb_probable_cause.scoring.judge import (
    JUDGE_MODEL,
    JudgeItem,
    agreement_table,
    judge_run,
    pick_disagreements,
)
from ntsb_probable_cause.scoring.preparation import PreparationStoppedError, run_preparation
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl, write_jsonl
from ntsb_probable_cause.scoring.runner import BatchRunner, CachedDocketReader, Runner, RunSpec
from ntsb_probable_cause.settings import Settings

# ``month_spent`` moved to ``ntsb_probable_cause.scoring.budget`` (0045); tests still import
# it from here, so it is named explicitly to satisfy mypy's strict re-export check.
__all__ = ["main", "month_spent"]

ClientFactory = Callable[[Settings], tuple[ModelClient, BatchRunner | None]]


def _default_client_factory(settings: Settings) -> tuple[ModelClient, BatchRunner | None]:
    """The real OpenRouter client and its batch wrapper (spec §7.2)."""
    http = OpenRouterClient(
        settings.require_openrouter_key(), base_url=settings.openrouter_base_url
    )
    return http, BatchClient(http)


JevFactory = Callable[[Settings], TypeSafeClient]


def _default_jev_factory(settings: Settings) -> TypeSafeClient:
    """The real TypeSafe client, for the ordering check's ``jev`` and ``jev2`` ways (0097, 0103)."""
    return TypeSafeClient(settings.require_typesafe_key(), base_url=settings.typesafe_base_url)


def answering_run_record(folder: Path) -> RunRecord:
    """The answering run's own ``RunRecord`` -- always the first row in ``run.jsonl``.

    A judged run's ``run.jsonl`` holds a second row, the judge pass's own record
    (``_record_judge_cost``, fix round 1), appended only after the answering run's row
    already exists -- so the first row is always the answering run, whether or not the
    folder has since been judged.
    """
    records = read_jsonl(folder / "run.jsonl", RunRecord)
    return records[0]


def _recorded_spec(folder: Path) -> dict[str, object]:
    """A run folder's ``spec.json``, or ``{}`` where it has none or it cannot be read."""
    path = folder / "spec.json"
    try:
        recorded = json.loads(path.read_text()) if path.is_file() else {}
    except json.JSONDecodeError:
        return {}
    return recorded if isinstance(recorded, dict) else {}


def _ablated(folder: Path) -> bool:
    """Whether an arm C run dropped tools (``--without``, spec §7.2): an ablation, not the arm.

    Recorded in ``spec.json`` only (``RunRecord`` has no field for it), so it is read there.
    """
    return bool(_recorded_spec(folder).get("without"))


def _plain_prompt(record: RunRecord) -> bool:
    """Whether a run's prompt is its arm's plain one.

    Arms A, B and the ceiling: no guidance (a guided run, S2.7, is not the plain arm). Arm C
    always reads S3's guidance (spec §20), so its plain prompt is that guidance and no tuning
    round (``+r``). The text fingerprint (``+p``, Andy 2026-10-01) is not compared, as arms A
    and B's prompt versions are not: a run made before a kept round changed the agent's text is
    still the plain arm of its day (``texts.is_plain``).
    """
    if record.arm != "C":
        return not record.guidance
    return record.guidance == agent_run.GUIDANCE and is_plain_agent_prompt(
        record.prompt_version, agent_run.GUIDANCE
    )


def _derived(record: RunRecord) -> bool:
    """Whether a run is a post-pass over another (the ordering check, or arm B's tool pass).

    Read from the prompt version, which each post-pass extends: ``+check-<way>``
    (``checkpass.check_run``) or ``+tools-<stats>`` (``agent/armb.py``).
    """
    return "+check-" in record.prompt_version or "+tools-" in record.prompt_version


def resolve_latest(
    runs_dir: Path, arm: str, sample: str, *, model: str | None = None, version: str = "v1"
) -> str:
    """The newest *completed, unmodified* run id for one arm and sample.

    A run on another evidence version is skipped too (0076): "latest B" means the latest B
    on v1 unless asked.

    An aborted run (``finished is None``) is skipped (fix round 1, item 9): ``make bars``
    resolving ``--latest`` to a partial run would silently report and publish it as if it
    were whole.

    **An ablation, a probe or a different model is skipped too.** The run id encodes only
    time, commit, sample and arm -- never ``exclusions``, ``includes``, ``model`` or
    ``price_variant`` -- so the registration ablation and the plain ceiling produce ids of
    exactly the same shape and the glob cannot tell them apart. On the real held-out runs
    of 2026-09-17 the ablation was submitted five seconds after the ceiling and sorted
    last, so ``--latest ceiling heldout-400`` returned the ablation: ``make bars`` would
    have written the ablation's numbers into ``docs/results/s1-bars.txt`` as the headline
    bar. The bars published that day were generated from explicit run ids and are not
    affected. The fix reads each candidate's own record rather than trusting its name,
    which is also why the model filter is available: the cross-model comparison runs share
    the ``dev-400-ceiling`` shape with the default-model ceiling.

    Arm C (S3.1 Task 10) is resolved the same way: a tool ablation (``--without``), a tuning
    round, or other guidance is skipped (``_ablated``, ``_plain_prompt``).

    **A renamed folder or a derived run is skipped by its record** (S3.1 Task 12, fix round 1).
    The glob ``*-<sample>-<arm>`` leaves out an id that goes on past the arm (a derived
    ``-check-<way>`` or ``-tools`` run, or a folder renamed with a suffix, such as decision
    0084's ``-confirm2000`` and ``-size16000``). The record is checked as well, so that the
    name's shape is not the only rule: a folder whose record names another run id has been
    copied or renamed, and a record whose prompt version carries ``+check-`` (S2.7, plan W2) or
    ``+tools-`` (the tool post-pass, ``<source>+tools-s3``) is a derived run, not a new
    answering run.
    """
    candidates: list[tuple[str, str]] = []
    for folder in sorted(runs_dir.glob(f"*-{sample}-{arm}")):
        if not folder.is_dir() or not (folder / "run.jsonl").exists():
            continue
        record = answering_run_record(folder)
        if record.run_id != folder.name or _derived(record):
            continue
        if record.finished is None:
            continue
        if record.sample != sample or record.arm != arm:
            continue
        if record.exclusions or record.includes or _ablated(folder):
            continue
        if not _plain_prompt(record):  # a guided run (S2.7), or arm C off its own setup
            continue
        if model is not None and record.model != model:
            continue
        if record.evidence_version != version:
            continue
        candidates.append((folder.name, record.model))
    if not candidates:
        wanted = f"arm={arm!r} sample={sample!r}"
        if model is not None:
            wanted += f" model={model!r}"
        raise SystemExit(
            f"no completed run found for {wanted} under {runs_dir} "
            f"(runs with exclusions or includes are never resolved by --latest: name them)"
        )
    models = {m for _, m in candidates}
    if model is None and len(models) > 1:
        # The cross-model comparison runs share `dev-400-ceiling` with the default-model
        # ceiling, so "the latest" is genuinely ambiguous. Refusing beats picking: the
        # wrong pick here silently publishes another model's numbers as ours.
        raise SystemExit(
            f"{len(candidates)} completed runs match arm={arm!r} sample={sample!r} across "
            f"{len(models)} models ({', '.join(sorted(models))}). Name the run id, or pass "
            f"the model, rather than letting --latest choose between them."
        )
    return candidates[-1][0]


def _maybe_write(out: str | None, text: str) -> None:
    if out is not None:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if text.endswith("\n") else text + "\n")


def _positive_usd(text: str) -> float:
    """A dollar amount above zero (S2.6 final review, I1): zero would reserve nothing."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if not value > 0:
        raise argparse.ArgumentTypeError(f"must be above zero, not {text}")
    return value


def _add_common(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--out", help="also write the printed text to this file")


def _add_transcribe(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """The ``transcribe`` subcommand: S2.6's flags and S2.7 track 2's ``--model``/``--page-rule``.

    Kept apart from ``_build_parser`` so that neither grows past ruff's statement limit once
    both S2.7 tracks' flags are in (the merge of the parent into track 1).
    """
    transcribe_p = commands.add_parser(
        "transcribe", help="read a sample's image pages once, into the cache (S2.6, 0081)"
    )
    transcribe_p.add_argument("--sample", choices=samples.SAMPLES, required=True)
    transcribe_p.add_argument(
        "--expected-cost-per-page-usd",
        type=_positive_usd,
        required=True,
        help="above zero: sets the job's reservation, and the job stops once it is spent",
    )
    transcribe_p.add_argument("--workers", type=int, default=8)
    transcribe_p.add_argument("--retry-failed", action="store_true")
    transcribe_p.add_argument("--dry-run", action="store_true", help="count and price only")
    transcribe_p.add_argument(
        "--model",
        default=TRANSCRIBER,
        help="the transcriber (S2.7 spec §8 step 1); needs a price and a reasoning level in "
        "sources.py",
    )
    transcribe_p.add_argument(
        "--page-rule",
        choices=PAGE_RULES,
        default=PAGE_RULE,
        help="which pages are sent (decision 0100 item 4); the rule in force by default",
    )


def _round_number(text: str) -> int:
    """A tuning round's number: a whole number from 1 (S3.1 Task 13)."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"a round is numbered from 1, not {text}")
    return value


def _add_arm_c(run_p: argparse.ArgumentParser) -> None:
    """The ``run`` flags that only arm C takes: a tool ablation and a tuning round.

    Kept apart from ``_build_parser`` for ruff's statement limit, as ``_add_transcribe`` is.
    """
    run_p.add_argument(
        "--without",
        action="append",
        default=[],
        choices=("suggest_codes", "coding"),
        help="arm C only: a tool ablation (spec §7.2); repeatable",
    )
    run_p.add_argument(
        "--round",
        type=_round_number,
        default=None,
        metavar="N",
        help="arm C only: a registered tuning round; docs/rounds/s3-round-N.md must be "
        "committed first (spec §10.3)",
    )


def _round_registration(number: int) -> Path:
    """The registration an S3 tuning round needs committed before its run (spec §10.3)."""
    return Path("docs/rounds") / f"s3-round-{number}.md"


def _refuse_unregistered_round(args: argparse.Namespace) -> None:
    """``--round`` is arm C's, and its registration must be committed (decision 0130 item 4).

    Checked before any case is read, any client is built or anything is reserved.
    """
    if args.round is None:
        return
    if args.arm != "C":
        raise ConfigurationError(
            f"--round names a tuning round of the agent loop (spec §10.3); arm {args.arm} has none"
        )
    registration = _round_registration(args.round)
    if not gitinfo.is_committed(registration):
        raise ConfigurationError(
            f"round {args.round}: its registration {registration} is not committed; a round is "
            "registered before it runs (spec §10.3, decision 0130 item 4)"
        )


def _add_tools(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """The ``tools`` subcommand: arm B's fixed tool post-pass (S3.1 Task 12, spec §7.1).

    Kept apart from ``_build_parser`` for ruff's statement limit, as ``_add_transcribe`` is.
    """
    tools_p = commands.add_parser(
        "tools",
        help="arm B's fixed coding-tool post-pass over a finished arm B run (spec §7.1); then "
        "check <run id>-tools --way luna --stats s3",
    )
    tools_p.add_argument("run_id")
    tools_p.add_argument(
        "--sync",
        action="store_true",
        help="standard-price calls one at a time, not batch rounds (smoke tests)",
    )
    tools_p.add_argument(
        "--budget-usd", type=float, default=None, help="default: NTSB_MONTHLY_BUDGET_USD"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ntsb-eval")
    commands = parser.add_subparsers(dest="command", required=True)

    baseline_p = commands.add_parser("baseline", help="reproduce and report the S1 baseline")
    baseline_p.add_argument("--sample", choices=samples.SAMPLES, default=None)
    _add_common(baseline_p)

    run_p = commands.add_parser("run", help="run one evaluation arm over a sample")
    run_p.add_argument(
        "--arm", choices=("A", "B", "ceiling", "C"), required=True, help="C is the agent loop"
    )
    run_p.add_argument("--sample", choices=samples.SAMPLES, required=True)
    run_p.add_argument("--evidence-version", choices=("v1", "v2", "v3"), default="v1")
    run_p.add_argument(
        "--transcriber",
        default=TRANSCRIBER,
        help="v2 only: the transcriber whose readings the run reads (S2.7 spec §7.5)",
    )
    run_p.add_argument(
        "--page-rule",
        choices=PAGE_RULES,
        default=PAGE_RULE,
        help="v2 only: the page rule the readings were chosen by (S2.7 spec §7.5)",
    )
    run_p.add_argument("--exclude", action="append", default=[], type=EvidenceRole, metavar="ROLE")
    run_p.add_argument("--include", action="append", default=[], choices=("case_number",))
    run_p.add_argument("--model", default=RunSpec.model)
    run_p.add_argument(
        "--price-variant", choices=("batch", "standard"), default=RunSpec.price_variant
    )
    run_p.add_argument("--max-output-tokens", type=int, default=RunSpec.max_output_tokens)
    run_p.add_argument(
        "--cap-usd",
        type=float,
        default=None,
        help=f"the per-case cap; default {RunSpec.cap_usd}, or {agent_run.CAP_USD} for arm C",
    )
    _add_arm_c(run_p)
    run_p.add_argument(
        "--budget-usd", type=float, default=None, help="default: NTSB_MONTHLY_BUDGET_USD"
    )
    run_p.add_argument("--expected-cost-per-case-usd", type=float, default=None)
    run_p.add_argument(
        "--guidance",
        action="append",
        default=[],
        metavar="NAME",
        help="a guidance file r<N>-<slug>, in stacking order (decision 0098)",
    )
    run_p.add_argument("--sync", action="store_true")
    run_p.add_argument("--limit", type=int, default=None, help="only the first N sample cases")
    run_p.add_argument(
        "--resume",
        default=None,
        metavar="RUN_ID",
        help="continue a run that died, reusing the batches it already paid for "
        "(batch runs only: a --sync run records no batches to resume from)",
    )
    _add_common(run_p)

    report_p = commands.add_parser("report", help="summarise one run, optionally against another")
    report_p.add_argument("run_id", nargs="?")
    report_p.add_argument("--latest", nargs=2, metavar=("ARM", "SAMPLE"))
    report_p.add_argument("--against")
    report_p.add_argument("--against-latest", nargs=2, metavar=("ARM", "SAMPLE"))
    report_p.add_argument(
        "--versions-compared",
        action="store_true",
        help="compare runs on different evidence versions, under a labelled heading (0076)",
    )
    _add_common(report_p)

    judge_p = commands.add_parser("judge", help="grade one run's prose against the withheld text")
    judge_p.add_argument("run_id")
    judge_p.add_argument(
        "--validated", action="store_true", help="allow judging a run on a non-dev-400 sample"
    )
    judge_p.add_argument(
        "--budget-usd", type=float, default=None, help="default: NTSB_MONTHLY_BUDGET_USD"
    )
    _add_common(judge_p)

    threshold_p = commands.add_parser("threshold", help="print the stopping-threshold curve")
    threshold_p.add_argument("run_id")
    _add_common(threshold_p)

    release_p = commands.add_parser("release", help="clear a dead run's budget reservation")
    release_p.add_argument("run_id")

    check_p = commands.add_parser(
        "check", help="the ordering check, as a post-pass over a finished run"
    )
    check_p.add_argument("run_id")
    check_p.add_argument("--way", choices=checkpass.CHECK_WAYS, required=True)
    check_p.add_argument(
        "--stats",
        choices=STATS_NAMES,
        default="s27",
        help="which statistics file the check reads: S2.7's (default) or S3's (decision 0129); "
        "a tool post-pass's run (<run id>-tools) and an arm C run (decision 0137) are checked "
        "with s3 only",
    )
    check_p.add_argument(
        "--budget-usd", type=float, default=None, help="default: NTSB_MONTHLY_BUDGET_USD"
    )

    _add_transcribe(commands)
    _add_tools(commands)

    return parser


def _resolve_run_id(runs_dir: Path, run_id: str | None, latest: Sequence[str] | None) -> str:
    if latest:
        return resolve_latest(runs_dir, latest[0], latest[1])
    if run_id:
        return run_id
    raise SystemExit("a run id or --latest ARM SAMPLE is required")


def _cmd_baseline(args: argparse.Namespace, settings: Settings) -> None:
    if args.sample:
        samples.refuse_sealed(args.sample, is_committed=gitinfo.is_committed)
    ids = samples.sample_ids(args.sample) if args.sample else None
    text = report.baseline_report(settings.data_dir / "processed", ids, load_tables())
    print(text)
    _maybe_write(args.out, text)


def _readings_for_run(args: argparse.Namespace, settings: Settings) -> ReadingLookup | None:
    """v2's readings for an arm B run, refused unless the sample is fully transcribed.

    A v2 run must read v2 evidence, not v1 with some pages missing: ``ntsb-eval transcribe``
    writes the done file only once every page it chose has a reading (spec §8.3).
    """
    if args.arm != "B" or args.evidence_version == "v1":
        return None
    # S2.7 Task 16 (spec §7.5): the marker checked is the one for this run's own transcriber
    # and page rule, so a v2 run never reads pages chosen or read differently from its label.
    readings = ReadingLookup(
        TranscriptionCache(settings.transcription_dir),
        model=args.transcriber,
        page_rule=args.page_rule,
    )
    if not readings.is_done(args.sample):
        raise ConfigurationError(
            f"{args.sample} is not fully transcribed with transcriber {args.transcriber} and "
            f"page rule {args.page_rule}: run ntsb-eval transcribe --sample {args.sample} "
            f"--model {args.transcriber} --page-rule {args.page_rule} first"
        )
    return readings


def _run_guidance(args: argparse.Namespace) -> tuple[str, ...]:
    """The run's guidance, refused unless every file's round registration is committed.

    Arm C reads S3's guidance when none is named (spec §20); ``AgentRunner`` refuses any other
    guidance outside a registered tuning round.
    """
    guidance = tuple(args.guidance) or (agent_run.GUIDANCE if args.arm == "C" else ())
    for name in guidance:
        registration = prompt.registration_path(name)
        if not gitinfo.is_committed(registration):
            raise ConfigurationError(
                f"guidance {name}: its registration {registration} is not committed; a round "
                "is registered before it runs (decision 0098 item 3)"
            )
    prompt.guidance_text(guidance)  # a missing file is refused before any money moves
    return guidance


def _run_spec(args: argparse.Namespace, settings: Settings, guidance: tuple[str, ...]) -> RunSpec:
    """The ``RunSpec`` the flags name; ``--cap-usd`` defaults by arm (arm C: spec §8.2)."""
    default_cap = agent_run.CAP_USD if args.arm == "C" else RunSpec.cap_usd
    return RunSpec(
        sample=args.sample,
        arm=args.arm,
        evidence_version=args.evidence_version,
        exclusions=frozenset(args.exclude),
        include_case_number="case_number" in args.include,
        model=args.model,
        price_variant=args.price_variant,
        max_output_tokens=args.max_output_tokens,
        cap_usd=args.cap_usd if args.cap_usd is not None else default_cap,
        budget_usd=args.budget_usd if args.budget_usd is not None else settings.monthly_budget_usd,
        sync=args.sync,
        expected_cost_per_case_usd=args.expected_cost_per_case_usd
        if args.expected_cost_per_case_usd is not None
        else settings.expected_cost_per_case_usd,
        guidance=guidance,
        # S2.7 Task 16: a v2 run names its reading; a v1 run names none (runner refuses both
        # the other way round).
        transcriber=args.transcriber if args.evidence_version == "v2" else None,
        page_rule=args.page_rule if args.evidence_version == "v2" else None,
    )


def _cmd_run(args: argparse.Namespace, settings: Settings, client_factory: ClientFactory) -> None:
    samples.refuse_sealed(args.sample, is_committed=gitinfo.is_committed)
    if args.without and args.arm != "C":
        raise ConfigurationError(
            f"--without drops the agent loop's tools (spec §7.2); arm {args.arm} has none"
        )
    _refuse_unregistered_round(args)
    if args.arm == "C":
        # The loop's tools count in S3's statistics, whose pool must not hold this sample's own
        # verdicts (decision 0129).
        refuse_pool_holding(agent_run.STATS, args.sample)
    guidance = _run_guidance(args)
    readings = _readings_for_run(args, settings)
    processed = settings.data_dir / "processed"
    ids = samples.sample_ids(args.sample)
    if args.limit is not None:
        ids = ids[: args.limit]
    raws = samples.load_cases(processed, ids)
    seen = samples.seen_pairs(processed)
    commit = ledger.commit_state()
    spent = month_spent(settings.runs_dir, now=datetime.now(UTC))
    client, batch = client_factory(settings)
    spec = _run_spec(args, settings, guidance)
    docket_cm = (
        DocketClient(settings.docket_dir, seconds_per_request=settings.docket_seconds_per_request)
        if args.arm in {"B", "C"}
        else contextlib.nullcontext()
    )
    with docket_cm as docket_client:
        # Arm C reads v1 evidence only: ``_readings_for_run`` gives it no readings.
        docket = (
            CachedDocketReader(docket_client, readings=readings)
            if docket_client is not None
            else None
        )
        runner: Runner | AgentRunner
        if args.arm == "C":
            runner = AgentRunner(
                client,
                batch=batch,
                tables=load_tables(),
                stats=load_stats(agent_run.STATS),
                seen_pairs=seen,
                runs_dir=settings.runs_dir,
                month_spent_usd=spent,
                commit=commit,
                docket=docket,
                # The one setting arm C and arm B's post-pass read (the shape probe decides it).
                pass_reasoning=agent_loop.PASS_REASONING,
                without=frozenset(args.without),
                ledger_path=settings.heldout_ledger_path,
                round_number=args.round,  # recorded in spec.json and the prompt version
            )
        else:
            runner = Runner(
                client,
                batch=batch,
                tables=load_tables(),
                seen_pairs=seen,
                runs_dir=settings.runs_dir,
                ledger_path=settings.heldout_ledger_path,
                month_spent_usd=spent,
                commit=commit,
                docket=docket,
            )
        # The operator re-supplies the original flags; the equality check inside `run` against
        # the folder's own `spec.json` is what proves they supplied the right ones (0032 point 4).
        record = runner.run(spec, raws, resume=args.resume)
    text = f"run {record.run_id}: {record.cases} cases, ${record.cost_usd:.4f}\n"
    print(text, end="")
    _maybe_write(args.out, text)


def _floor_for_report(settings: Settings, sample: str) -> tuple[dict[str, float] | None, str]:
    """The honest baseline's floor, labelled, or a one-line reason it is not shown.

    Omitted entirely for ``dev-400``: the floor is fit on development and scored on the
    held-out split, so showing it beside a development table would compare a run against a
    population it was not run on. A read-only command must not traceback just because
    ``cases.parquet`` (or the split it needs) is missing -- that failure is reported as a
    one-line note instead (fix round 2, items 4-5).
    """
    if sample == "dev-400":
        return None, ""
    try:
        return report.honest_baseline_floor(settings.data_dir / "processed"), ""
    except Exception as error:
        return None, f"\n(baseline floor unavailable: {error})"


def _ablation_line(folder: Path) -> str:
    """``without=<tools>`` for an arm C tool ablation (read from ``spec.json``), else nothing."""
    without = _recorded_spec(folder).get("without")
    if not without or not isinstance(without, list):
        return ""
    return f"without={','.join(str(name) for name in without)}\n"


def _cached_share(folder: Path) -> str:
    """The provider's cached share of the prompt tokens, from ``trail.jsonl`` when there is one.

    Counts only (spec §10.2's noise-floor report reads the same); a call that reported no
    cached tokens counts as none cached.
    """
    path = folder / agent_run.TRAIL_FILE
    if not path.is_file():
        return ""
    calls = read_jsonl(path, AgentCall)
    cached = sum(c.cached_tokens or 0 for c in calls)
    prompt_tokens = sum(c.prompt_tokens for c in calls)
    return f"\ncached share of prompt tokens: {cached}/{prompt_tokens}"


def _cmd_report(args: argparse.Namespace, settings: Settings) -> None:
    run_id = _resolve_run_id(settings.runs_dir, args.run_id, args.latest)
    folder = settings.runs_dir / run_id
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    run_record = answering_run_record(folder)
    floor, floor_note = _floor_for_report(settings, run_record.sample)
    text = report.provenance(run_record) + _ablation_line(folder)
    text += "\n" + report.summarise(cases, floor=floor) + floor_note
    text += "\n\n" + report.failure_summary(cases)
    if any(r.marks for r in cases):
        text += (
            "\n\nunmarked cases only (S2.6 spec §4.4):\n"
            + report.summarise(report.unmarked(cases), floor=floor)
            + "\n\n"
            + report.marks_summary(cases)
        )
    if any(r.narrative_share is not None for r in cases):
        text += "\n" + report.share_bands(cases)
    if run_record.arm == "B":
        text += "\n\n" + report.cap_summary(cases)
    if run_record.arm == "C":
        # Arm C leaves a document unread by choice (or by stopping first), not at a cap: the
        # same count, worded for what it is.
        text += "\n\n" + report.cap_summary(cases, heading="unread", what="left documents unread")
        text += _cached_share(folder)
    if run_record.evidence_version != "v1":
        text += "\n" + report.preparation_summary(cases)
    if run_record.sample == "heldout-400":
        cell = report.weighted_headline(cases)
        text += f"\n\nweighted headline (fatal-share top-1): {report.fmt_n(cell)}"
    if args.against or args.against_latest:
        other_id = args.against or resolve_latest(settings.runs_dir, *args.against_latest)
        other_cases = read_jsonl(settings.runs_dir / other_id / "cases.jsonl", CaseResult)
        other_record = answering_run_record(settings.runs_dir / other_id)
        report.refuse_cross_version(
            run_record, other_record, versions_compared=args.versions_compared
        )
        heading = report.comparison_heading(run_record, other_record)
        text += f"\n\n{heading}\n{report.compare_by_fatal(cases, other_cases)}"
        if run_record.arm == "C" and "+check-" in run_record.prompt_version:
            # Decision 0137's reading rule: the ordering check's diagnostic over arm C prints
            # its first codes changed, with their fixes and breaks, beside the paired top-1.
            text += "\n" + report.first_code_changes(cases, other_cases)
        if run_record.evidence_version != other_record.evidence_version:
            # Spec §9.1: the comparison also "for the cases that hold image pages" -- those
            # this run paid to transcribe pages for.
            transcribed_ids = {r.case_id for r in cases if r.preparation_cost_usd > 0}
            text += (
                f"\n\non the {len(transcribed_ids)} cases with transcribed pages:\n"
                + report.compare_by_fatal(
                    [r for r in cases if r.case_id in transcribed_ids],
                    [r for r in other_cases if r.case_id in transcribed_ids],
                )
            )
        marked_ids = {r.case_id for r in [*cases, *other_cases] if r.marks}
        if marked_ids:
            text += (
                f"\n\non cases unmarked in both runs ({len(marked_ids)} marked cases left out):\n"
                + report.compare_by_fatal(
                    [r for r in cases if r.case_id not in marked_ids],
                    [r for r in other_cases if r.case_id not in marked_ids],
                )
            )
    reservations = open_reservations(settings.runs_dir)
    if reservations:
        text += "\n\nopen budget reservations: " + ", ".join(
            f"{k} ${v:.2f}" for k, v in sorted(reservations.items())
        )
    print(text)
    _maybe_write(args.out, text)


def _cmd_threshold(args: argparse.Namespace, settings: Settings) -> None:
    folder = settings.runs_dir / args.run_id
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    # The same provenance header `report` writes. Without it the committed curve names
    # neither the run nor the sample it came from, so a reader cannot tell a development
    # curve from a held-out one, and rule 3's "every reported number comes from a script"
    # has nothing to point at (the close-out review found exactly this gap).
    curve = report.threshold_curve(cases)
    lines = [report.provenance(answering_run_record(folder)), ""]
    lines.append("threshold\tmean score\tcases answered")
    lines += [f"{t:.2f}\t{v:+.3f}\t{report.answered_at(cases, t)}" for t, v in curve]
    chosen = report.choose_threshold(cases)
    lines.append(f"\nchosen threshold: {chosen:.2f}")
    if report.threshold_is_trivial(cases, chosen):
        # Without this the reader takes 0.95 for a confident operating point. It is the
        # opposite: nothing clears it, so the "best" policy is to answer nothing at all.
        lines += [
            "",
            "NOT A USABLE THRESHOLD. No case is answered at this confidence, so the policy",
            "answers nothing and scores exactly what always abstaining scores. The curve's",
            "maximum is the trivial policy, not an operating point.",
            "",
            "This is structural rather than a quirk of one run: the mean score is",
            "P(answer) x (2 x accuracy - 1), so while accuracy is below 50% every answer",
            "costs more than it earns and answering nothing wins at every threshold. A",
            "usable threshold can only come from a run that is right more often than not.",
        ]
    text = "\n".join(lines)
    print(text)
    _maybe_write(args.out, text)


MAX_FAILED_SHARE = 0.02
"""The finished-transcription marker's retry threshold (Task 14 review, findings M1/M2).

The S2.6 plan's Task 15 Step 2 already said the retry rule out loud: failed pages over 2% of
the total means run once more with ``--retry-failed`` before going on. Task 14 itself never
enforced it -- on 2026-09-26 a run hit the OpenRouter account's budget limit, 5,191 of 12,458
pages (42%) failed with $0 403 errors, and the marker was still written, so a v2 run could
have started on readings that were 42% missing. This constant is that rule, enforced rather
than just written down.
"""


def _failure_reason(error: str | None) -> str:
    """An error's prefix up to its second colon (e.g. "model: ModelError"), never page text.

    Every failure in ``transcribe.py`` is recorded as ``"{prefix}: {detail}"``, where
    ``detail`` itself usually starts with ``"{type(error).__name__}: ..."`` (a model failure)
    or a message that itself contains a colon (a schema failure, e.g.
    ``"schema: reply is not JSON: ..."``). Cutting after the second colon keeps exactly the
    prefix and its immediate cause, never the page-specific detail after it.
    """
    minimum_parts = 2
    if error is None:
        return "unknown"
    parts = error.split(":", 2)
    if len(parts) < minimum_parts:
        return parts[0].strip()
    return f"{parts[0].strip()}: {parts[1].strip()}"


def _top_failure_reasons(readings: Sequence[Transcription | None], limit: int = 3) -> list[str]:
    """The most common failure reasons among failed readings, most common first."""
    reasons = [_failure_reason(r.error) for r in readings if r is not None and r.status == "failed"]
    counts = Counter(reasons)
    return [reason for reason, _count in counts.most_common(limit)]


def _page_jobs(
    raws: Sequence[Mapping[str, object]],
    docs: CachedDocuments,
    *,
    model: str = TRANSCRIBER,
    page_rule: PageRule = PAGE_RULE,
) -> tuple[list[PageJob], int]:
    """One job per page v2 reads, over every PDF in every case's docket.

    Decision W2: v2 reads the photo-only documents too, so none is skipped here. A file that
    is not a PDF is not a failure and is not counted. A case whose docket cannot be listed, a
    document that cannot be fetched, and a document that cannot be parsed for its pages *are*
    counted rather than silently dropped (Task 14 review, finding M2); the second return value
    is that count. ``model`` and ``page_rule`` are S2.7 track 2 Task 3's re-test flags (spec
    §8 step 1; decision 0100 item 5).
    """
    jobs: list[PageJob] = []
    skipped = 0
    for raw in raws:
        mkey = raw.get("mKey")
        if not isinstance(mkey, int):
            continue
        try:
            entries = docs.listing(mkey).entries
        except DocketError:
            skipped += 1
            continue
        for entry in entries:
            if not entry.is_pdf():
                continue
            try:
                data = docs.document(mkey, entry.index)
                chosen = pages_to_read(data, page_rule=page_rule)
            except DocketError:
                skipped += 1
                continue
            sha = hashlib.sha256(data).hexdigest()
            for page, mixed in chosen:
                # Fix round 3, R4: the job's key carries the instruction its own ``mixed``
                # status implies (0085, amended by Task 13's I3), the key v2 looks up.
                key = TranscriptionKey(
                    document_sha256=sha,
                    page=page,
                    model=model,
                    instruction=key_instruction(TRANSCRIBE, mixed=mixed),
                    dpi=RESOLUTION,
                )
                jobs.append(PageJob(key, docs.loader(mkey, entry.index), mixed))
    return jobs, skipped


def _maybe_mark_done(  # noqa: PLR0913 -- model and page_rule (S2.7 T3) name the pair covered.
    cache: TranscriptionCache,
    sample: str,
    jobs: Sequence[PageJob],
    skipped: int,
    *,
    model: str = TRANSCRIBER,
    page_rule: PageRule = PAGE_RULE,
) -> int:
    """Write the finished-transcription marker only within the retry threshold (M1).

    Every chosen page must have a reading (transcribed or failed) before anything is decided.
    Once that holds, the marker is written only when failed readings are at most
    ``MAX_FAILED_SHARE`` of the pages chosen; otherwise nothing is written, the failure count,
    share and the three most common failure reasons are printed (never page text), the
    operator is told to re-run with ``--retry-failed``, and the exit code is non-zero so this
    cannot pass unnoticed in a script. ``model`` and ``page_rule`` (S2.7 track 2 Task 3) name
    the pair the marker covers, so each model/rule pair gets its own marker (spec §8 step 1).
    """
    readings = [cache.get(j.key) for j in jobs]
    if not all(r is not None for r in readings):
        return 0
    total = len(jobs)
    failed = sum(1 for r in readings if r is not None and r.status == "failed")
    share = failed / total if total else 0.0
    if total and share > MAX_FAILED_SHARE:
        reasons = _top_failure_reasons(readings)
        print(
            f"{sample}: {failed} of {total} pages failed ({share:.1%}), above the "
            f"{MAX_FAILED_SHARE:.0%} retry threshold; marker NOT written. Most common "
            f"failure reasons: {', '.join(reasons)}. Run the same command again with "
            "--retry-failed."
        )
        return 1
    ReadingLookup(cache, model=model, page_rule=page_rule).mark_done(
        sample,
        {
            "pages": total,
            "failed": failed,
            "failed_share": share,
            "skipped_documents": skipped,
            "model": model,
            "page_rule": page_rule,
            "dpi": RESOLUTION,
        },
    )
    print(f"{sample}: every page has a reading; v2 runs may start")
    return 0


def _cmd_transcribe(args: argparse.Namespace, settings: Settings) -> int:
    """Every page v2 needs, for one sample: counted, priced, then read once (0081).

    Counts only are printed: pages are read by program and no person sees them. The done
    file is written only when every chosen page has a reading (transcribed or failed) and
    failures are within ``MAX_FAILED_SHARE`` (M1), which is what ``run --evidence-version v2``
    checks for.

    A held-out sample is refused before anything is fetched or paid for (S2.6 final review,
    I3): decision 0090 defers every held-out step, and this command writes no held-out ledger
    row. A later stage lifts the refusal deliberately, with the ledger row and the dirty-tree
    check every other held-out entry point has.

    A job that spends its reservation stops (``PreparationStoppedError``, final review I1): what it
    read is reported, no marker is written, and the exit code is non-zero.
    """
    samples.refuse_sealed(args.sample, is_committed=gitinfo.is_committed)
    if args.sample.startswith("heldout"):
        raise ConfigurationError(
            f"transcribing {args.sample} is refused: decision 0090 defers every held-out run, "
            "and this command writes no held-out ledger row. A later stage lifts this "
            "deliberately."
        )
    # S2.7 track 2, Task 3: a model the price table or the reasoning table does not know would
    # fail inside the job (transcribe.settings_for); refuse it before anything is fetched.
    try:
        sources.price_of(args.model)
    except KeyError:
        raise ConfigurationError(
            f"no price on file for {args.model}; add it to sources.py"
        ) from None
    if args.model not in sources.LOWEST_REASONING:
        raise ConfigurationError(
            f"no reasoning level on file for {args.model}; add it to sources.LOWEST_REASONING"
        )
    raws = samples.load_cases(settings.data_dir / "processed", samples.sample_ids(args.sample))
    cache = TranscriptionCache(settings.transcription_dir)
    with DocketClient(
        settings.docket_dir, seconds_per_request=settings.docket_seconds_per_request
    ) as client:
        jobs, skipped = _page_jobs(
            raws, CachedDocuments(client), model=args.model, page_rule=args.page_rule
        )
        pending = [
            j
            for j in jobs
            if (hit := cache.get(j.key)) is None or (args.retry_failed and hit.status == "failed")
        ]
        projected = len(pending) * args.expected_cost_per_page_usd
        print(
            f"{args.sample}: {len(jobs)} pages to read with {args.model} at {RESOLUTION} dpi, "
            f"rule {args.page_rule}, {len(pending)} not yet read; projected ${projected:.2f}; "
            f"{skipped} document(s) could not be listed, fetched or parsed"
        )
        if args.dry_run:
            return 0
        # Nothing to pay for: no job, no reservation and no API key needed.
        stopped: PreparationStoppedError | None = None
        try:
            done = (
                run_preparation(
                    kind="transcription",
                    jobs=jobs,
                    instruction=TRANSCRIBE,
                    settings=settings,
                    commit=ledger.commit_state(),
                    expected_cost_per_page_usd=args.expected_cost_per_page_usd,
                    workers=args.workers,
                    retry_failed=args.retry_failed,
                )
                if pending
                else []
            )
        except PreparationStoppedError as error:
            stopped = error
            done = list(error.read)
    readings = [cache.get(j.key) for j in jobs]
    failed = sum(1 for r in readings if r is not None and r.status == "failed")
    print(
        f"read {len(done)} pages now (${sum(r.cost_usd for r in done):.2f}); "
        f"{failed} of {len(jobs)} failed in all"
    )
    if stopped is not None:
        print(f"transcribe: {stopped} The marker is NOT written.", file=sys.stderr)
        return 1
    return _maybe_mark_done(
        cache, args.sample, jobs, skipped, model=args.model, page_rule=args.page_rule
    )


def _cmd_release(args: argparse.Namespace, settings: Settings) -> int:
    if release(settings.runs_dir, args.run_id):
        print(f"released {args.run_id}")
        return 0
    print(f"release: no open reservation for {args.run_id}", file=sys.stderr)
    return 1


_GROUP_FIELD = next(f for f in EVIDENCE_FIELDS if f.role is EvidenceRole.PHASE_OF_FLIGHT)


def _cmd_check(
    args: argparse.Namespace,
    settings: Settings,
    client_factory: ClientFactory,
    jev_factory: JevFactory,
) -> None:
    folder = settings.runs_dir / args.run_id
    record = answering_run_record(folder)
    samples.refuse_sealed(record.sample, is_committed=gitinfo.is_committed)
    if (
        not record.sample.startswith("dev")
        or "heldout" in args.run_id
        or record.arm not in checkpass.CHECKED_ARMS
    ):
        raise ConfigurationError(
            f"check: the ordering check runs on development arm B runs, and on development arm "
            f"C runs as a diagnostic, only; {args.run_id} is {record.sample}, arm {record.arm} "
            "(decisions 0096, 0097, 0137)"
        )
    # Decision 0137: the diagnostic reads the arm, whose `occurrence_usage` tool is the premise
    # it tests. A tool ablation (`--without`, recorded in `spec.json` only) dropped that tool or
    # the suggestion tool, so it is refused here, before anything is read or reserved.
    if record.arm == "C" and _ablated(folder):
        raise ConfigurationError(
            f"check: {args.run_id} is an arm C tool ablation "
            f"({_ablation_line(folder).strip()}): the ordering check's diagnostic reads the "
            "arm itself (decision 0137 item 1)"
        )
    # Before anything is read, reserved or written: the counts must not hold the answers they
    # check (decision 0129). S2.7's pool still holds `dev-seal-s3-400`; the default `--stats s27`
    # stays, so every existing check is unchanged, and this refuses it for that sample.
    refuse_pool_holding(args.stats, record.sample)
    # Before any case is read (fix round 1, Important 2): an ablation run withheld a field --
    # possibly phase_of_flight -- from the model, and reading it back from the raw record
    # below to rebuild `groups` would hand the check evidence the source run never had.
    # `resolve_latest` treats the same shape of run (exclusions or includes set) as unfit to
    # stand for its arm; the check refuses it outright rather than silently reading around it.
    if record.exclusions or record.includes:
        raise ConfigurationError(
            f"check: {args.run_id} is an ablation (exclusions={record.exclusions}, "
            f"includes={record.includes}): rebuilding its phase-of-flight group would read "
            "back a field the source run withheld from the model"
        )
    way: checkpass.Way = args.way
    # Every refusal `check_run` would make, run once here, before anything is reserved or
    # written (fix round 2, Important): the old code called `checkpass.check_run` only after
    # reserving the budget, so a refusal inside it (a repeat check of an already-finished
    # derived run, an unfinished source, a source that was itself a derived check run) left an
    # open reservation, and for the "itself a derived check run" case an empty derived folder
    # too, since `reserve_within_budget` creates it as a side effect. `preflight` is read-only:
    # nothing here can leave anything behind.
    # A tool post-pass's check must count in the file its tools did (decision 0129 item 4):
    # `preflight` refuses any other `--stats` there, and the derived prompt version names the
    # file whenever it is not S2.7's (`checkpass.suffix`).
    pre = checkpass.preflight(folder, way, settings.runs_dir, stats=args.stats)
    cases = pre.cases
    processed = settings.data_dir / "processed"
    ids = [c.case_id for c in cases]
    groups = {
        case_id: (value if isinstance(value := _GROUP_FIELD.extract(raw), str) else None)
        for case_id, raw in zip(ids, samples.load_cases(processed, ids), strict=True)
    }
    stats, tables = load_stats(args.stats), load_tables()
    # Computed before any reservation too (fix round 2): a failure in either call must not
    # leave a reservation with nothing left to settle it.
    seen_pairs = samples.seen_pairs(processed)
    commit = ledger.commit_state()
    run_id = pre.run_id
    if way == "rule":
        checker = checkpass.rule_checker(stats)
        derived = checkpass.check_run(
            folder,
            way,
            checker,
            runs_dir=settings.runs_dir,
            groups=groups,
            seen_pairs=seen_pairs,
            commit=commit,
            now=lambda: datetime.now(UTC),
            stats=args.stats,
        )
    else:
        # Reserved, not just checked, before any client is built (fix round 1, Important 1):
        # a ~400-call synchronous pass would otherwise be invisible to a concurrent paid job
        # for the whole run, since nothing recorded its projected spend until this pass's own
        # `finally`. `reserve_within_budget` raises before touching the filesystem if the
        # projection would bust the budget, so an over-budget call never reaches
        # `client_factory`/`jev_factory` below.
        budget = args.budget_usd if args.budget_usd is not None else settings.monthly_budget_usd
        projected = len(cases) * checkpass.EXPECTED_COST_PER_CASE_USD[way]
        reserve_within_budget(settings.runs_dir, run_id, projected, budget, now=datetime.now(UTC))
        # From here to the end of `check_run`'s own pass, nothing may raise without releasing
        # what was just reserved (fix round 2, Important): `check_run` settles it once the
        # pass's real spend is on disk, but a factory that raises (a missing key) or a refusal
        # `preflight` already cleared yet `check_run` re-finds (a genuine race) never reaches
        # that `finally`, and would otherwise hold the reservation open until someone ran
        # `ntsb-eval release` by hand.
        try:
            if way == "luna":
                checker = checkpass.luna_checker(client_factory(settings)[0], stats, tables)
            elif way == "jev2":
                # The registered second Jev check (decision 0103): the same path as `jev`.
                checker = checkpass.jev2_checker(jev_factory(settings), stats, tables)
            else:
                checker = checkpass.jev_checker(jev_factory(settings), stats, tables)
            derived = checkpass.check_run(
                folder,
                way,
                checker,
                runs_dir=settings.runs_dir,
                groups=groups,
                seen_pairs=seen_pairs,
                commit=commit,
                now=lambda: datetime.now(UTC),
                stats=args.stats,
            )
        except BaseException:
            release(settings.runs_dir, run_id)
            raise
    print(f"check {derived.run_id}: {derived.cases} cases, ${derived.cost_usd:.4f}")


def _cmd_tools(args: argparse.Namespace, settings: Settings, client_factory: ClientFactory) -> None:
    """Arm B's fixed tool post-pass over a finished arm B run (S3.1 Task 12, spec §7.1).

    Every refusal (``armb.preflight``, then the sealed sample) comes before any case is read or
    any client is built. The budget is reserved and settled inside ``armb.tools_run``.
    """
    folder = settings.runs_dir / args.run_id
    pre = armb.preflight(folder, settings.runs_dir)
    samples.refuse_sealed(pre.record.sample, is_committed=gitinfo.is_committed)
    processed = settings.data_dir / "processed"
    ids = [case.case_id for case in pre.cases if armb.in_post_pass(case)]
    raws = dict(zip(ids, samples.load_cases(processed, ids), strict=True))
    seen = samples.seen_pairs(processed)
    commit = ledger.commit_state()
    budget = args.budget_usd if args.budget_usd is not None else settings.monthly_budget_usd
    client, batch = client_factory(settings)
    with DocketClient(
        settings.docket_dir, seconds_per_request=settings.docket_seconds_per_request
    ) as docket_client:
        derived = armb.tools_run(
            folder,
            raws,
            client=client,
            batch=batch,
            docket=CachedDocketReader(docket_client),
            tables=load_tables(),
            stats=load_stats(agent_run.STATS),
            stats_name=agent_run.STATS,
            seen_pairs=seen,
            runs_dir=settings.runs_dir,
            budget_usd=budget,
            commit=commit,
            sync=args.sync,
        )
    print(f"tools {derived.run_id}: {derived.cases} cases, ${derived.cost_usd:.4f}")


def _judge_items(
    cases: Sequence[CaseResult],
    raws: Mapping[str, Mapping[str, object]],
    exclude: frozenset[EvidenceRole],
) -> list[JudgeItem]:
    """One judge item per scored, stepped case: id, hypothesis, synthesis, verdict, scores."""
    items: list[JudgeItem] = []
    for case in cases:
        if case.scores is None or not case.steps:
            continue
        _, synthesis, verdict = split_record(raws[case.case_id], exclude=exclude)
        hypothesis = case.steps[-1].hypothesis
        items.append((case.case_id, hypothesis, synthesis, verdict, case.scores))
    return items


def _record_judge_cost(  # noqa: PLR0913, PLR0917 -- one field per RunRecord fact it carries.
    settings: Settings,
    folder: Path,
    run_record: RunRecord,
    commit: tuple[str, bool],
    cost: float,
    cases: int,
) -> RunRecord:
    """Append a second ``RunRecord`` for the judge pass, and a held-out ledger row if due.

    Spec §5.4/§13 item 8: the held-out ledger lists every run that touched a held-out
    sample, and a judge pass on one reads withheld verdicts and spends money just as an
    answering run does (fix round 2, item 3).
    """
    now = datetime.now(UTC)
    judge_record = RunRecord(
        run_id=f"{run_record.run_id}-judge",
        sample=run_record.sample,
        arm=run_record.arm,
        # The judged run's own version (S2.6 final review, I4): the held-out ledger this row
        # may be appended to is append-only, so a defaulted "v1" could never be corrected.
        evidence_version=run_record.evidence_version,
        exclusions=run_record.exclusions,
        includes=run_record.includes,
        prompt_version=run_record.prompt_version,
        guidance=run_record.guidance,
        guidance_sha256=run_record.guidance_sha256,
        model=JUDGE_MODEL,
        # The judge calls chat-completions directly, so it pays the standard price; recording
        # "batch" here would understate this pass's real spend by half.
        price_variant="standard",
        cap_usd=0.01,
        budget_usd=run_record.budget_usd,
        commit_sha=commit[0],
        dirty=commit[1],
        started=now,
        finished=now,
        cases=cases,
        cost_usd=cost,
    )
    write_jsonl(folder / "run.jsonl", [judge_record])
    if run_record.sample.startswith("heldout"):
        ledger.append_row(settings.heldout_ledger_path, judge_record, str(folder / "judge.jsonl"))
    return judge_record


def _cmd_judge(args: argparse.Namespace, settings: Settings, client_factory: ClientFactory) -> None:
    folder = settings.runs_dir / args.run_id
    run_record = answering_run_record(folder)
    if run_record.sample != "dev-400" and not args.validated:
        raise SystemExit(
            f"judge: refusing on sample {run_record.sample!r} without --validated (spec §8)"
        )
    commit = ledger.commit_state()
    # A held-out judge pass reads withheld verdicts and spends money exactly as a held-out
    # `run` does, so it is refused from a dirty tree by the same rule (fix round 2, item 3).
    ledger.refuse_if_heldout_and_dirty(run_record.sample, commit[1])
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    scorable_ids = [c.case_id for c in cases if c.scores is not None and c.steps]
    processed = settings.data_dir / "processed"
    raws = dict(zip(scorable_ids, samples.load_cases(processed, scorable_ids), strict=True))
    exclude = frozenset(EvidenceRole(e) for e in run_record.exclusions)
    tables = load_tables()
    client, _ = client_factory(settings)
    items = _judge_items(cases, raws, exclude)

    judge_path = folder / "judge.jsonl"
    partial_path = folder / "judge.jsonl.partial"
    judge_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path.unlink(missing_ok=True)
    paid: list[float] = []

    def on_row(row: Mapping[str, object]) -> None:
        # Rows go to a partial file; the previous pass's file is replaced only once this
        # pass completes (spec §3.5), so a pass that dies mid-way destroys nothing paid for.
        with partial_path.open("a") as handle:
            handle.write(json.dumps(row) + "\n")
        paid.append(cast(float, row["cost_usd"]))

    budget_usd = args.budget_usd if args.budget_usd is not None else settings.monthly_budget_usd
    spent = month_spent(settings.runs_dir, now=datetime.now(UTC))
    try:
        result = judge_run(
            client,
            tables,
            items,
            runs_dir=settings.runs_dir,
            price_variant="standard",
            budget_usd=budget_usd,
            month_spent_usd=spent,
            on_row=on_row,
        )
    except BaseException:
        # Whatever was paid for before the failure is still recorded, so the next run's
        # budget check is not blind to it (fix round 1, Important 1; mirrors the runner's
        # own partial-write-then-reraise, spec §6.4).
        if paid:
            _record_judge_cost(settings, folder, run_record, commit, sum(paid), len(paid))
        raise
    if paid:
        partial_path.replace(judge_path)
    judge_record = _record_judge_cost(
        settings, folder, run_record, commit, result.cost_usd, len(paid)
    )
    disagreements = pick_disagreements(
        list(result.case_ids), list(result.labels), list(result.scores)
    )
    # The sampled ids go to the run folder, which is outside git, and never into the text
    # `--out` writes. `--out` normally targets `docs/results/`, which is committed, and on a
    # held-out run these are held-out case numbers: a committed held-out id is a route for
    # held-out cases to reach development work. Held-out ids are not printed to the terminal
    # either. On a development run they are, because that list IS the hand-check sheet.
    ids_file = folder / "judge-disagreements.txt"
    ids_file.write_text("\n".join(disagreements) + "\n")
    text = (
        f"agreement table: {agreement_table(result.labels, result.scores)}\n"
        f"disagreements sampled: {len(disagreements)} "
        f"(case ids written to {ids_file.name} in the run folder, never to --out)\n"
        f"judge cost: ${result.cost_usd:.4f} over {len(result.case_ids)} cases "
        f"(recorded as run {judge_record.run_id!r} for month_spent)"
    )
    print(text)
    if run_record.sample.startswith("heldout"):
        print(f"held-out sample: the {len(disagreements)} sampled case ids are not printed.")
    else:
        print(f"disagreement case ids: {disagreements}")
    _maybe_write(args.out, text)


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: ClientFactory = _default_client_factory,
    jev_factory: JevFactory = _default_jev_factory,
) -> int:
    """Parse arguments and run one eval command.

    ``BudgetError``/``ConfigurationError`` are refusals Andy is expected to hit by hand
    (an over-budget run, a held-out run from a dirty tree); printing one line to stderr and
    exiting 1 is the right shape for that, not a traceback (fix round 1, item 10).
    """
    args = _build_parser().parse_args(argv)
    settings = Settings()
    try:
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
        elif args.command == "release":
            return _cmd_release(args, settings)
        elif args.command == "check":
            _cmd_check(args, settings, client_factory, jev_factory)
        elif args.command == "transcribe":
            return _cmd_transcribe(args, settings)
        elif args.command == "tools":
            _cmd_tools(args, settings, client_factory)
    except (BudgetError, ConfigurationError, BatchCancelledError) as error:
        # A cancelled batch (arm C's batch rounds) stops the run with its records written; the
        # message names the run id to pass to --resume (S3.1 Task 10).
        print(f"{args.command}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
