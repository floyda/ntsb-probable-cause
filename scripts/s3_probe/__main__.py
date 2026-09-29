"""``python -m scripts.s3_probe select|run|report|trails``: the probe's four commands.

Status
    One-shot learning probe for S3 (2026-09-29). Output is not a result; it sets no bar and
    tunes nothing.

``select`` reads ``dev-400``'s records and each case's docket at evidence version v2 (the
docket cache and the cached transcriptions only -- nothing is fetched: a cache miss is
counted as missing, not retried into a fetch). It makes no model call and spends nothing. It
writes ``<data_dir>/probes/s3-probe/cases.json`` (case ID -> cell) and prints, per cell, the
number of ``dev-400`` cases available and the number chosen.

``run`` reads that file and runs the loop over the selected cases; see
:mod:`scripts.s3_probe.run`.

``report JOB_ID [--out PATH]`` reads a run's job folder and prints (and, with ``--out``, also
writes) the counts-only report meant for commit; see :mod:`scripts.s3_probe.report`.

``trails JOB_ID`` writes one readable Markdown file per case under the job folder, never
committed; see :mod:`scripts.s3_probe.trails_md`.
"""

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

from ntsb_probable_cause.errors import DocketError
from ntsb_probable_cause.scoring.runner import CachedDocketReader
from ntsb_probable_cause.scoring.samples import load_cases, sample_ids
from ntsb_probable_cause.settings import Settings
from scripts.s3_probe.cases import (
    CELLS,
    MKEY_FIELD,
    CaseInfo,
    docket_reader,
    facts,
    has_scan,
    select,
)
from scripts.s3_probe.report import cmd_report
from scripts.s3_probe.run import PROBE_ROOT, cmd_run
from scripts.s3_probe.trails_md import write_trails

OUT_RELATIVE = Path("probes/s3-probe/cases.json")


def _fatal(raw: Mapping[str, object]) -> bool:
    """Whether a record's highest injury is fatal.

    The exact rule ``scoring/runner.py`` uses to set ``CaseResult.fatal``
    (``runner.py:1251`` and ``:1335``): ``raw.get("highestInjuryLevel") == "Fatal"``. There is
    no module-level helper for this in the library to import, so the one-line rule is
    replicated here rather than re-derived.
    """
    return raw.get("highestInjuryLevel") == "Fatal"


def _build_candidates(
    ids: Sequence[str],
    raws: Sequence[Mapping[str, object]],
    reader: CachedDocketReader,
) -> tuple[tuple[CaseInfo, ...], int]:
    """Every case whose docket is cached, as a ``CaseInfo``; and how many were not."""
    candidates: list[CaseInfo] = []
    missing = 0
    for case_id, raw in zip(ids, raws, strict=True):
        mkey = raw.get(MKEY_FIELD)
        if not isinstance(mkey, int):
            missing += 1
            continue
        try:
            docket = reader.read(mkey)
        except DocketError:
            missing += 1
            continue
        candidates.append(
            CaseInfo(case_id=case_id, fatal=_fatal(raw), has_scan=has_scan(facts(docket)))
        )
    return tuple(candidates), missing


def _cell_counts(candidates: Sequence[CaseInfo]) -> Counter[tuple[bool, bool]]:
    return Counter((c.fatal, c.has_scan) for c in candidates)


def _cmd_select(settings: Settings) -> int:
    ids = sample_ids("dev-400")
    raws = load_cases(settings.data_dir / "processed", ids)
    reader = docket_reader(settings)
    candidates, missing = _build_candidates(ids, raws, reader)
    print(f"dev-400 cases: {len(ids)}; dockets missing from the cache: {missing}")
    available = _cell_counts(candidates)
    for fatal, scan in CELLS:
        print(f"  fatal={fatal} has_scan={scan}: {available[(fatal, scan)]} available")

    chosen_ids = select(candidates)
    by_id = {c.case_id: c for c in candidates}
    cells = {
        case_id: {"fatal": by_id[case_id].fatal, "has_scan": by_id[case_id].has_scan}
        for case_id in chosen_ids
    }
    chosen_counts = Counter((c.fatal, c.has_scan) for c in candidates if c.case_id in cells)
    for fatal, scan in CELLS:
        print(f"  fatal={fatal} has_scan={scan}: {chosen_counts[(fatal, scan)]} chosen")

    out_path = settings.data_dir / OUT_RELATIVE
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cells, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point: ``python -m scripts.s3_probe <command>``."""
    parser = argparse.ArgumentParser(prog="s3_probe")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("select", help="draw the probe's balanced 20-case sample")
    run_p = subparsers.add_parser("run", help="run the loop over the selected cases")
    run_p.add_argument("--limit", type=int, default=None, help="only the first N selected cases")
    run_p.add_argument("--workers", type=int, default=4, help="worker threads (one client each)")
    run_p.add_argument(
        "--dry-run", action="store_true", help="schema-valid canned replies; spends nothing"
    )
    report_p = subparsers.add_parser("report", help="counts-only report for one run")
    report_p.add_argument("job_id")
    report_p.add_argument("--out", type=Path, default=None, help="also write the report here")
    trails_p = subparsers.add_parser(
        "trails", help="one readable Markdown trail per case (never committed)"
    )
    trails_p.add_argument("job_id")
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "select":
        return _cmd_select(settings)
    if args.command == "run":
        return cmd_run(settings, limit=args.limit, workers=args.workers, dry_run=args.dry_run)
    if args.command == "report":
        cmd_report(settings.data_dir / PROBE_ROOT / args.job_id, out=args.out)
        return 0
    if args.command == "trails":
        n = write_trails(settings.data_dir / PROBE_ROOT / args.job_id)
        print(
            f"wrote {n} trail file(s) to {settings.data_dir / PROBE_ROOT / args.job_id / 'trails'}"
        )
        return 0
    raise SystemExit(f"unknown command: {args.command}")  # pragma: no cover -- argparse only


if __name__ == "__main__":
    raise SystemExit(main())
