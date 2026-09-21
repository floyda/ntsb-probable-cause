"""How much of the withheld factual narrative a single docket document can reproduce.

Status
    One-shot, complete (S2 close-out). Produced ``docs/results/s2-narrative-coverage.txt`` and
    ``docs/results/s2-narrative-coverage-heldout.txt`` (commit ``cc73ebf``, 2026-09-21):
    held-out maximum 74.6% with nothing at or above 80%, which is why the published 22.3%
    stands; two development cases of 379 above 90%, which is the hole. **Likely to be rerun.**
    The first S2.5 item is replacing the exact whole-text backstop with a coverage threshold,
    and this script is the measurement that would decide where the threshold sits.

Decision 0050 exempts factual-narrative *sentences* from the tripwire inside
``docket_documents``: the narrative is written from the docket, so a shared sentence is the
narrative quoting a document rather than a document holding the answer. The whole-text needle
is NOT exempt, so an exact, complete copy of the narrative still trips the guard.

The gap that leaves, found in the S2 close-out decision audit: a *near*-complete copy -- the
narrative missing one sentence, or with one word altered -- matches no whole-text needle, and
every one of its sentences is exempt. It would pass into evidence unseen.

This script measures whether that gap is theoretical or real, by asking, for every case: what
share of the factual narrative's sentences appear inside the docket documents, and does any
single document carry nearly all of them? A document reproducing most of the narrative is the
shape the gap describes.

No matched text is printed, saved or returned: only counts and shares.

Run: ``uv run python -m scripts.narrative_coverage`` (``--out PATH`` to save the text).
"""

import argparse
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ntsb_probable_cause.docket.attach import prepare_attachment
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.errors import DocketError, LeakageError
from ntsb_probable_cause.fields import EvidenceRole, SynthesisRole
from ntsb_probable_cause.records.guard import find_leaks
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring.runner import CachedDocketReader
from ntsb_probable_cause.scoring.samples import load_cases, sample_ids
from ntsb_probable_cause.settings import Settings
from scripts.docket_scan import quantiles

NO_SENTENCES = 10**9
MKEY = "mKey"
NO_EXEMPTIONS: frozenset[tuple[str, str]] = frozenset()
SOURCE = SynthesisRole.FACTUAL_NARRATIVE.value
DOCUMENTS = EvidenceRole.DOCKET_DOCUMENTS.value
# Shares reported as "how many cases reach at least this much of the narrative".
BANDS = (0.25, 0.50, 0.80, 0.90, 0.99)


def _offline() -> httpx.BaseTransport:
    """A transport refusing every request, so a cache miss is loud and costs no fetch."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline: this measurement reads the cache only")

    return httpx.MockTransport(refuse)


@dataclass
class Coverage:
    """Per-case narrative coverage, accumulated over the sample."""

    cases: int = 0
    skipped: int = 0
    no_narrative: int = 0
    whole_text_hits: int = 0
    shares: list[float] = field(default_factory=list)
    best_document_shares: list[float] = field(default_factory=list)
    band_cases: Counter[float] = field(default_factory=Counter)
    band_documents: Counter[float] = field(default_factory=Counter)


def _sentence_needles(narrative: str) -> set[str]:
    """Every sentence needle the guard would build from the narrative, matched against itself."""
    leaks = find_leaks({"self": narrative}, {SOURCE: narrative}, (), exemptions=NO_EXEMPTIONS)
    return {leak.fragment for leak in leaks if leak.kind == "sentence"}


def _matched(haystack: str, narrative: str) -> set[str]:
    """The narrative's sentence needles that appear in one haystack."""
    leaks = find_leaks({DOCUMENTS: haystack}, {SOURCE: narrative}, (), exemptions=NO_EXEMPTIONS)
    return {leak.fragment for leak in leaks if leak.kind == "sentence"}


def sweep(records: Sequence[Mapping[str, object]], reader: CachedDocketReader) -> Coverage:
    """Measure narrative coverage for every case whose docket is cached."""
    result = Coverage()
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
        if not readable:
            result.skipped += 1
            continue
        attachment = prepare_attachment(raw, docket)
        try:
            _, synthesis, _ = split_record(
                attachment.context_for(readable).context,
                exclude=frozenset(),
                min_sentence_chars=NO_SENTENCES,
            )
        except LeakageError:
            result.skipped += 1
            continue
        narrative = synthesis.texts().get(SOURCE) or ""
        needles = _sentence_needles(narrative)
        if not needles:
            result.no_narrative += 1
            continue
        result.cases += 1
        texts = [attachment.document_texts[i] for i in readable]
        joined = "\n".join(texts)
        if find_leaks(
            {DOCUMENTS: joined}, {SOURCE: narrative}, (), exemptions=NO_EXEMPTIONS
        ) and any(
            leak.kind == "text"
            for leak in find_leaks(
                {DOCUMENTS: joined}, {SOURCE: narrative}, (), exemptions=NO_EXEMPTIONS
            )
        ):
            result.whole_text_hits += 1
        share = len(_matched(joined, narrative)) / len(needles)
        best = max((len(_matched(text, narrative)) / len(needles) for text in texts), default=0.0)
        result.shares.append(share)
        result.best_document_shares.append(best)
        for band in BANDS:
            if share >= band:
                result.band_cases[band] += 1
            if best >= band:
                result.band_documents[band] += 1
    return result


def report(result: Coverage, sample: str) -> str:
    """The measurement, as docs/results/s2-narrative-coverage.txt holds it."""
    lines = [
        "# how much of the withheld factual narrative a docket can reproduce",
        f"sample {sample}; {result.cases} cases measured, "
        f"{result.skipped} skipped (no cached docket, no readable document, or a code hit), "
        f"{result.no_narrative} with no factual narrative to compare",
        "every readable document attached, not only the ones the cost cap admits",
        "no matched text is printed anywhere in this file",
        "",
        "decision 0050 exempts factual-narrative SENTENCES inside docket_documents. The",
        "whole-text needle is not exempt, so an exact complete copy still trips the guard.",
        "This file measures the gap between those two: a near-complete copy.",
        "",
    ]
    if result.cases:
        # scripts.docket_scan.quantiles, not a second convention: nearest rank, and already
        # corrected once for a half-integer off-by-one (see its docstring).
        whole = quantiles(result.shares, (0.5, 0.9, 1.0))
        best = quantiles(result.best_document_shares, (0.5, 0.9, 1.0))
        lines += [
            "share of the narrative's sentences found anywhere in the docket:",
            f"  median {whole[0.5]:.1%}   p90 {whole[0.9]:.1%}   max {whole[1.0]:.1%}",
            "share found inside ONE single document (the shape the gap describes):",
            f"  median {best[0.5]:.1%}   p90 {best[0.9]:.1%}   max {best[1.0]:.1%}",
            "",
            "cases at or above each share:",
        ]
        for band in BANDS:
            lines.append(
                f"  {band:.0%}  whole docket {result.band_cases[band]:>4} of {result.cases}"
                f"   single document {result.band_documents[band]:>4} of {result.cases}"
            )
        lines += [
            "",
            f"cases where the WHOLE narrative matched exactly (the guard catches these): "
            f"{result.whole_text_hits}",
        ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    """Measure narrative coverage over a sample and print the numbers."""
    parser = argparse.ArgumentParser(prog="narrative_coverage")
    parser.add_argument("--sample", default="dev-400")
    parser.add_argument("--out", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    settings = Settings()
    ids = sample_ids(args.sample)
    records = list(load_cases(settings.data_dir / "processed", ids))
    if args.limit:
        records = records[: args.limit]
    with DocketClient(settings.docket_dir, transport=_offline()) as client:
        result = sweep(records, CachedDocketReader(client))
    text = report(result, args.sample)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
