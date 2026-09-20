"""Where the withheld narratives reappear inside docket documents, and at what sentence length.

``MIN_SENTENCE_CHARS = 20`` was measured in S0 over the record's own fields, before any docket
text existed (``docs/results/s0-corpus-scan.txt``). Attaching docket documents puts a large new
body of text under the same tripwire, and it fires: the investigators' factual narrative is
written *from* the docket, so sentences recur in both. Decision 0019 already met this shape
once, in the weather field, and exempted it after establishing the direction of the copying.

This script measures the scale and the threshold, so the choice is made from evidence rather
than from a guess. For every case it attaches *every readable document* -- not the subset that
fits the cost cap -- because the S3 loop may read any document, so a threshold has to hold for
the whole docket, not for one arm's selection.

No matched text is ever printed, saved or returned: only lengths and counts. ``Leak.fragment``
holds withheld text and is never rendered here.

Run: ``uv run python -m scripts.docket_leak_scan`` (``--out PATH`` to save the text).
"""

import argparse
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ntsb_probable_cause.docket.attach import attach_docket
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.errors import DocketError, LeakageError
from ntsb_probable_cause.fields import EvidenceRole, VerdictRole
from ntsb_probable_cause.records.guard import find_leaks
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring.runner import CachedDocketReader
from ntsb_probable_cause.scoring.samples import load_cases, sample_ids
from ntsb_probable_cause.settings import Settings

CANDIDATES = (20, 30, 40, 60, 80, 100, 120, 150, 200, 250, 300, 400)
NO_SENTENCES = 10**9
EXEMPT_SOURCE = "factual_narrative"

# The "before" column must keep measuring the guard AS IT STOOD BEFORE decision 0050, so it is
# pinned to a frozen copy of the pre-0050 exemption set rather than left to inherit
# guard.SENTENCE_CHECK_EXEMPTIONS. Inheriting it was a real defect: once 0050 added the
# docket_documents pair, the live default suppressed the very matches this column exists to
# count, and the before column collapsed onto the after column (12 of 40 became 1 of 40).
# scripts/doctype_scan.py freezes its pre-fix matcher for the same reason.
BEFORE_0050_EXEMPTIONS = frozenset({(EvidenceRole.WEATHER_METAR.value, "factual_narrative")})
MKEY = "mKey"
DOCKET_ROLES = frozenset({EvidenceRole.DOCKET_DOCUMENTS.value, EvidenceRole.DOCKET_LISTING.value})


def _offline() -> httpx.BaseTransport:
    """A transport refusing every request, so a cache miss is loud and costs no fetch."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline: this measurement reads the cache only")

    return httpx.MockTransport(refuse)


@dataclass
class Sweep:
    """What tripped the guard, accumulated over the sample."""

    cases: int = 0
    skipped: int = 0
    code_cases: int = 0
    cases_hit: Counter[int] = field(default_factory=Counter)
    hits: Counter[int] = field(default_factory=Counter)
    by_source: Counter[str] = field(default_factory=Counter)
    # Andy's ruling 2026-09-20: a factual-narrative sentence shared with a docket document is
    # not a leak. These count what would STILL trip once that exemption is applied -- the
    # number the ruling actually turns on, rather than the gross count above it.
    cases_after: Counter[int] = field(default_factory=Counter)
    hits_after: Counter[int] = field(default_factory=Counter)
    cases_by_source: Counter[str] = field(default_factory=Counter)
    by_role: Counter[str] = field(default_factory=Counter)
    lengths: list[int] = field(default_factory=list)


def sweep(records: Sequence[Mapping[str, object]], reader: CachedDocketReader) -> Sweep:
    """Attach every readable document in each case and test each candidate threshold."""
    result = Sweep()
    for raw in records:
        mkey = raw.get(MKEY)
        if not isinstance(mkey, int):
            result.skipped += 1
            continue
        try:
            docket = reader.read(mkey)
        except DocketError:
            result.skipped += 1
            continue
        readable = [r.entry.index for r in docket.documents if r.status == "read"]
        context = attach_docket(raw, docket, documents=readable).context
        try:
            evidence, synthesis, verdict = split_record(
                context, exclude=frozenset(), min_sentence_chars=NO_SENTENCES
            )
        except LeakageError:
            # Codes are compared whatever the sentence threshold, so a code hit lands here.
            result.code_cases += 1
            result.skipped += 1
            continue
        result.cases += 1
        withheld = {**synthesis.texts(), VerdictRole.PROBABLE_CAUSE: verdict.probable_cause}
        role_values = {role.value: value for role, value in evidence.role_values().items()}
        for candidate in CANDIDATES:
            leaks = [
                leak
                for leak in find_leaks(
                    role_values,
                    withheld,
                    (),
                    min_sentence_chars=candidate,
                    exemptions=BEFORE_0050_EXEMPTIONS,
                )
                if leak.evidence_role in DOCKET_ROLES
            ]
            after = [leak for leak in leaks if leak.source != EXEMPT_SOURCE]
            if after:
                result.cases_after[candidate] += 1
                result.hits_after[candidate] += len(after)
            if not leaks:
                continue
            result.cases_hit[candidate] += 1
            result.hits[candidate] += len(leaks)
            if candidate == CANDIDATES[0]:
                result.cases_by_source.update({str(s) for s in (leak.source for leak in leaks)})
                result.by_source.update(str(leak.source) for leak in leaks)
                result.by_role.update(leak.evidence_role for leak in leaks)
                result.lengths.extend(len(leak.fragment) for leak in leaks)
    return result


def report(result: Sweep, sample: str) -> str:
    """The measurement, as docs/results/s2-docket-leak.txt holds it."""
    cases = result.cases
    lines = [
        "withheld narrative text inside docket documents",
        f"sample {sample}, {cases} cases scanned"
        f" (skipped: {result.skipped}; of those, tripped on a code: {result.code_cases})",
        "every readable document attached, not only the ones the cost cap admits",
        "no matched text is printed anywhere in this file",
        "",
        "  minimum sentence length, and what still trips the guard.",
        "  'after' applies the ruling: factual-narrative sentences in docket_documents are",
        "  no longer compared; every other source and role is compared exactly as now.",
        "    chars   cases hit         hits      cases after     hits after",
        *(
            f"    {c:5d}   {result.cases_hit[c]:3d} of {cases}"
            f" ({100 * result.cases_hit[c] / cases if cases else 0:5.1f}%)"
            f"   {result.hits[c]:5d}"
            f"      {result.cases_after[c]:3d} of {cases}"
            f" ({100 * result.cases_after[c] / cases if cases else 0:5.1f}%)"
            f"   {result.hits_after[c]:5d}"
            for c in CANDIDATES
        ),
        "",
        f"  at the current threshold ({CANDIDATES[0]} chars):",
        "    by withheld source: "
        + (", ".join(f"{k} {v}" for k, v in result.by_source.most_common()) or "none"),
        "    cases carrying at least one match, by source: "
        + (", ".join(f"{k} {v}" for k, v in result.cases_by_source.most_common()) or "none"),
        "    by evidence role:   "
        + (", ".join(f"{k} {v}" for k, v in result.by_role.most_common()) or "none"),
    ]
    if result.lengths:
        ordered = sorted(result.lengths)
        p90 = ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))]
        lines.append(
            f"    matched fragment length: n={len(ordered)} min={ordered[0]}"
            f" median={statistics.median(ordered):.0f} p90={p90} max={ordered[-1]} characters"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Sweep the sentence threshold over the sample and print the result."""
    parser = argparse.ArgumentParser(prog="docket_leak_scan")
    parser.add_argument("--sample", default="dev-400")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    settings = Settings()
    reader = CachedDocketReader(DocketClient(settings.data_dir / "docket", transport=_offline()))
    records = load_cases(settings.data_dir / "processed", sample_ids(args.sample))
    if args.limit:
        records = records[: args.limit]
    text = report(sweep(records, reader), args.sample)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
