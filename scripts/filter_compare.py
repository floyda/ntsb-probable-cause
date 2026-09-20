"""Arm B's category filter against the simpler rule: attach everything that yielded text.

Andy, 2026-09-20: "Part of me feels like we could be placing each file into much cleaner
buckets focused on how much the model will see in prose." The category filter excludes one
title-derived bucket, ``photos``, as a proxy for "this document has nothing to read". Whether
a document has anything to read is measured, not inferred -- ``status == "read"`` already says
so. This script measures what the proxy costs and what dropping it would cost.

Both rules already exist in the code, so neither is reimplemented here:

- ``published``   -- the filter as it stands: every readable document whose category is in
                     ``filter.ARM_B_TYPES`` (that is, every category but ``photos``).
- ``unfiltered``  -- every readable document, whatever its category.

Each case is prepared exactly as a run prepares it -- ``runner.prepare_case``, the same
smallest-first cap loop, the same payload rendering and the same leakage tripwire -- so the
attached set, the cap and the omissions are the run's own, not an approximation of them.

Counts only. No document text, no case number and no model call: nothing is sent anywhere and
no money is spent. Reads the docket cache offline; a cache miss is counted, never fetched.

Run: ``uv run python -m scripts.filter_compare`` (``--out PATH`` to save the text).
"""

import argparse
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.filter import Variant
from ntsb_probable_cause.errors import DocketError, LeakageError
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.runner import CachedDocketReader, RunSpec, prepare_case
from ntsb_probable_cause.scoring.samples import load_cases, sample_ids
from ntsb_probable_cause.settings import Settings

VARIANTS: tuple[Variant, Variant] = ("published", "unfiltered")
MKEY_PATH = "mKey"


def _offline_transport() -> httpx.BaseTransport:
    """A transport that refuses every request, so a cache miss is loud and costs no fetch."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline: this measurement reads the cache only")

    return httpx.MockTransport(refuse)


def _quantiles(values: Sequence[int]) -> str:
    """``n=… median=… p75=… p90=… max=…`` over a list of counts."""
    if not values:
        return "n=0"
    ordered = sorted(values)
    p75 = ordered[min(len(ordered) - 1, int(0.75 * len(ordered)))]
    p90 = ordered[min(len(ordered) - 1, int(0.90 * len(ordered)))]
    return (
        f"n={len(ordered)} median={statistics.median(ordered):,.0f} "
        f"p75={p75:,} p90={p90:,} max={ordered[-1]:,}"
    )


@dataclass
class Totals:
    """What both rules did, accumulated over the sample."""

    attached: dict[Variant, list[int]] = field(default_factory=lambda: {v: [] for v in VARIANTS})
    tokens: dict[Variant, list[int]] = field(default_factory=lambda: {v: [] for v in VARIANTS})
    capped: dict[Variant, int] = field(default_factory=lambda: dict.fromkeys(VARIANTS, 0))
    complete: dict[Variant, int] = field(default_factory=lambda: dict.fromkeys(VARIANTS, 0))
    cases: int = 0
    differing: int = 0
    no_docket: int = 0
    leaked: int = 0
    gained: int = 0
    lost: int = 0


def measure(
    records: Sequence[Mapping[str, object]], reader: CachedDocketReader, sample: str
) -> Totals:
    """Prepare every case under both rules, exactly as a run would."""
    tables = load_tables()
    t = Totals()
    for raw in records:
        mkey = raw.get(MKEY_PATH)
        if not isinstance(mkey, int):
            t.no_docket += 1
            continue
        try:
            docket = reader.read(mkey)
        except DocketError:
            t.no_docket += 1
            continue
        sets: dict[Variant, frozenset[int]] = {}
        try:
            for variant in VARIANTS:
                spec = RunSpec(sample=sample, arm="B", docket_filter=variant)
                prepared = prepare_case(raw, spec, tables, docket)
                sets[variant] = frozenset(prepared.attached)
                t.attached[variant].append(len(prepared.attached))
                t.tokens[variant].append(
                    sum(docket.record(i).estimated_tokens for i in prepared.attached)
                )
                if prepared.not_read:
                    t.capped[variant] += 1
                else:
                    t.complete[variant] += 1
        except LeakageError:
            t.leaked += 1
            continue
        t.cases += 1
        if sets[VARIANTS[0]] != sets[VARIANTS[1]]:
            t.differing += 1
        t.gained += len(sets[VARIANTS[1]] - sets[VARIANTS[0]])
        t.lost += len(sets[VARIANTS[0]] - sets[VARIANTS[1]])
    return t


def report(t: Totals, sample: str) -> str:
    """The comparison, as docs/results/s2-filter-compare.txt holds it."""
    cases = t.cases
    attached, tokens, capped, complete = t.attached, t.tokens, t.capped, t.complete
    spec = RunSpec(sample=sample, arm="B")
    lines = [
        "arm B's category filter against 'attach everything readable'",
        f"sample {sample}, {cases} cases measured"
        f" (no cached docket: {t.no_docket}; leakage tripwire: {t.leaked})",
        f"model {spec.model} ({spec.price_variant}), per-case cap ${spec.cap_usd:.2f}",
        "both rules run through runner.prepare_case -- the run's own cap loop, not a copy",
        "",
        "  documents attached per case",
        *(f"    {v:12s} {_quantiles(attached[v])}" for v in VARIANTS),
        "",
        "  estimated tokens attached per case",
        *(f"    {v:12s} {_quantiles(tokens[v])}" for v in VARIANTS),
        "",
        "  cases whose whole admitted set fitted under the cap",
        *(
            f"    {v:12s} {complete[v]:3d} of {cases}"
            f" ({100 * complete[v] / cases:.0f}%); stopped by the cap: {capped[v]}"
            for v in VARIANTS
        ),
        "",
        f"  cases where the two rules attach a different set   {t.differing:3d} of {cases}"
        f" ({100 * t.differing / cases:.0f}%)",
        f"  documents 'unfiltered' attaches that 'published' does not   {t.gained}",
        f"  documents 'published' attaches that 'unfiltered' does not   {t.lost}"
        "   (the cap displacing a larger document, not the filter)",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Measure both rules over the sample and print the comparison."""
    parser = argparse.ArgumentParser(prog="filter_compare")
    parser.add_argument("--sample", default="dev-400")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    settings = Settings()
    client = DocketClient(settings.data_dir / "docket", transport=_offline_transport())
    records = load_cases(settings.data_dir / "processed", sample_ids(args.sample))
    if args.limit:
        records = records[: args.limit]
    text = report(measure(records, CachedDocketReader(client), args.sample), args.sample)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
