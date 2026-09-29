"""``python -m scripts.s3_probe select``: draws the probe's balanced 20-case sample.

Status
    One-shot learning probe for S3 (2026-09-29). Output is not a result; it sets no bar and
    tunes nothing.

Reads ``dev-400``'s records and each case's docket at evidence version v2 (the docket cache
and the cached transcriptions only -- nothing is fetched: a cache miss is counted as missing,
not retried into a fetch). It makes no model call and spends nothing. It writes
``<data_dir>/probes/s3-probe/cases.json`` (case ID -> cell) and prints, per cell, the number
of ``dev-400`` cases available and the number chosen.
"""

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.transcribe import ReadingLookup, TranscriptionCache
from ntsb_probable_cause.errors import DocketError
from ntsb_probable_cause.scoring.runner import CachedDocketReader
from ntsb_probable_cause.scoring.samples import load_cases, sample_ids
from ntsb_probable_cause.settings import Settings
from scripts.s3_probe.cases import CELLS, CaseInfo, facts, has_scan, select

# Field name in the raw record that carries the docket's internal key (scoring/runner.py,
# scripts/docket_leak_scan.py).
MKEY_FIELD = "mKey"
OUT_RELATIVE = Path("probes/s3-probe/cases.json")


def _offline() -> httpx.BaseTransport:
    """A transport refusing every request, so a docket cache miss is loud and costs no fetch.

    The ``_offline()`` pattern in ``scripts/docket_leak_scan.py``: a case whose docket or
    transcriptions are not already cached fails with ``DocketError`` instead of fetching.
    """

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline: the S3 probe reads the docket cache only")

    return httpx.MockTransport(refuse)


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
    reader = CachedDocketReader(
        DocketClient(settings.docket_dir, transport=_offline()),
        readings=ReadingLookup(TranscriptionCache(settings.transcription_dir)),
    )
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
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "select":
        return _cmd_select(settings)
    raise SystemExit(f"unknown command: {args.command}")  # pragma: no cover -- argparse only


if __name__ == "__main__":
    raise SystemExit(main())
