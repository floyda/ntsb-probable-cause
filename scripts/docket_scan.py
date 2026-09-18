"""Fetch every dev-400 docket once and report its shape: counts and quantiles only (spec §8.1).

Usage:
    uv run python -m scripts.docket_scan [--limit N] [--out docs/results/s2-shape-dev.txt]

One fetch serves the shape numbers, the threshold, the filter measurement and the fixture pool
(decision 0039 item 4). Listing pages and documents are cached under NTSB_DOCKET_DIR, never
committed. No case number and no text is printed.

Two corrections to the original brief, both from decision 0046 (the owner/operator name
replacement, added after this script's design):

1. ``owner_names`` reuses ``attach.py``'s own ``owner_operator_values`` -- the exact selection
   rule the redaction step applies (minimum length 3, a bare digit string excluded) -- instead
   of re-deriving a 4-character floor with a "zip"-in-key-name exclusion. Reusing the real
   selection means this measurement and the redaction behaviour cannot drift apart.
2. ``ShapeState`` tracks the amateur-built and the owner/operator replacement counts
   separately (``AttachResult.replacements`` is now the sum of both mechanisms), and both are
   reported under their own label -- the old single "amateur-built replacements" label would
   now be published over a number that is no longer only amateur-built hits.

Fix round 1 (spec-compliance review) added three more corrections to this file, all about
whether a reader can trust the numbers rather than about decision 0046:

3. The report states its own denominator -- cases attempted, listing fetch failures and
   mKey-missing skips, per stratum and overall -- so a reader can tell a complete run from a
   partial one instead of every quantile silently being over an unstated population.
4. A "Definitions and limits" section spells out four places where a figure's exact meaning
   is not obvious from its label: what the detail figures are counted over, "containing" vs.
   "replaced", how tokens per docket are summed, and what "scanned pages" counts.
5. `quantiles` now matches its own "nearest-rank" docstring: `math.ceil`, not `round`, which
   at a half-integer rank was silently returning one rank low.

Task 14 review found the "Definitions and limits" section's "scanned pages" sentence itself
wrong (item 4 above added the section but misdescribed this one entry):

6. "Scanned pages" was documented as counting every page of a scan-classified document. The
   code at `accumulate`'s `state.scan_pages` line sums ``r.pages - r.readable_pages`` over every
   document with a known ``kind`` (born-digital, partial or scan), so it also adds the
   individually-unreadable pages inside a partial-classified document, not only whole
   scan-classified ones. The sentence is corrected to describe that.

Final whole-branch review (before merge, item 3) found the "name" labels themselves too narrow
for what the code counts, not the counting:

7. ``owner_names``/``redact_known_names`` (via ``attach.owner_operator_values``) reach every
   ``REDACTED_FIELDS`` value -- addresses, zip codes, a certificate number, not only the five
   name-bearing fields ``scripts/name_coverage.py`` measures. Publishing that broader count
   under a "name" label overstates what was measured; decision 0046 keeps the broad scope
   (an address is personal data too, and it carries no collision risk) but the label was
   wrong. "documents containing ... name" and "... name replacements" are now "... detail" and
   "... detail replacements" throughout this script's printed report.
"""

import argparse
import math
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ntsb_probable_cause.docket.attach import (
    amateur_built_replace,
    owner_operator_values,
    redact_known_names,
)
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.manifest import Docket, read_docket
from ntsb_probable_cause.errors import DocketError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.settings import Settings

STRATA = ("fatal", "non-fatal")
TOKEN_LINE = 10_000
_CHAR_BINS = ((0, 0), (1, 49), (50, 99), (100, 299), (300, 599), (600, 10**9))


def quantiles(
    values: Sequence[float], qs: Sequence[float] = (0.5, 0.75, 0.9, 1.0)
) -> dict[float, float]:
    """Nearest-rank quantiles; empty input gives an empty dict.

    Fix round 1, finding 4: nearest-rank means ``math.ceil(q * n)`` (1-based rank), not
    ``round(q * n)`` -- ``round`` is half-to-even, so at a half-integer rank with an even
    floor it silently returns one rank low (n=5 at p90: rank 4, not 5; n=150 at p75: rank
    112, not 113). It happened to be exact at n=400, so `s2-shape-dev.txt`'s overall row was
    right and only the fatal/non-fatal strata rows were off by one rank.
    """
    if not values:
        return {}
    ordered = sorted(values)
    return {q: ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))] for q in qs}


def owner_names(raw: Mapping[str, object]) -> list[str]:
    """Owner and operator name strings the record holds.

    Correction 1 (decision 0046): these are exactly the strings ``redact_known_names`` looks
    for -- ``attach.py``'s own ``owner_operator_values``, not a separately re-derived rule.
    That helper already applies the minimum length (3 characters) and excludes a value that is
    nothing but digits, whatever field it came from (a bare postcode is indistinguishable from
    a serial number or a weight; a hyphenated ZIP+4 is distinctive and stays in scope).
    """
    return list(owner_operator_values(raw))


def _stratum(fatal: bool) -> str:
    """The stratum key a case's ``highestInjuryLevel`` sorts into."""
    return "fatal" if fatal else "non-fatal"


@dataclass
class ShapeState:
    """Everything the scan accumulates. Counts and per-docket numbers, never text or ids."""

    # Fix round 1, finding 1: without these, `docs/results/s2-shape-dev.txt` cannot say
    # whether it covers 400 dockets or 385 -- every quantile in it would be over a silently
    # different population. Populated once per case, in `main`'s loop, before it is known
    # whether the case's docket could be read at all; `dockets` below (already existed) is the
    # count of cases that *did* succeed, so `cases_attempted - listing_failed - missing_mkey`
    # should equal `dockets` for the same stratum.
    cases_attempted: Counter[str] = field(default_factory=Counter)
    listing_failed: Counter[str] = field(default_factory=Counter)
    missing_mkey: Counter[str] = field(default_factory=Counter)
    dockets: Counter[str] = field(default_factory=Counter)
    docs_per_docket: defaultdict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    pages_per_docket: defaultdict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    tokens_per_docket: defaultdict[str, list[int]] = field(
        default_factory=lambda: defaultdict(list)
    )
    tokens_per_doc: defaultdict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    scan_pages: Counter[str] = field(default_factory=Counter)
    scan_only: Counter[str] = field(default_factory=Counter)
    form_6120: Counter[str] = field(default_factory=Counter)
    form_6120_text: Counter[str] = field(default_factory=Counter)
    with_submission: Counter[str] = field(default_factory=Counter)
    documents: Counter[str] = field(default_factory=Counter)
    non_pdf: Counter[str] = field(default_factory=Counter)
    categories: Counter[str] = field(default_factory=Counter)
    statuses: Counter[str] = field(default_factory=Counter)
    char_bins: Counter[str] = field(default_factory=Counter)
    name_hits: Counter[str] = field(default_factory=Counter)
    name_cases: Counter[str] = field(default_factory=Counter)
    # Correction 2 (decision 0046): the two replacement mechanisms are counted separately --
    # AttachResult.replacements is their sum, but publishing that sum under the old
    # "amateur-built replacements" label would misdescribe what the number now counts.
    amateur_built_replacements: Counter[str] = field(default_factory=Counter)
    owner_operator_replacements: Counter[str] = field(default_factory=Counter)
    fetch_failed: Counter[str] = field(default_factory=Counter)


def _bin(chars: int) -> str:
    for low, high in _CHAR_BINS:
        if low <= chars <= high:
            return f"{low}-{high}" if high < 10**9 else f"{low}+"
    return "?"


def record_attempt(state: ShapeState, *, fatal: bool) -> None:
    """One case the scan tried to read, before it is known whether the docket was readable."""
    state.cases_attempted[_stratum(fatal)] += 1


def record_missing_mkey(state: ShapeState, *, fatal: bool) -> None:
    """A case skipped because the record holds no usable ``mKey``."""
    state.missing_mkey[_stratum(fatal)] += 1


def record_listing_failed(state: ShapeState, *, fatal: bool) -> None:
    """A case whose docket listing could not be fetched after every retry."""
    state.listing_failed[_stratum(fatal)] += 1


def accumulate(
    state: ShapeState, docket: Docket, *, fatal: bool, raw: Mapping[str, object]
) -> None:
    """Add one docket's numbers to the state."""
    stratum = _stratum(fatal)
    state.dockets[stratum] += 1
    readable = [r for r in docket.documents if r.status == "read"]
    non_photo = [r for r in docket.documents if not r.entry.is_photo_only()]
    state.docs_per_docket[stratum].append(len(docket.documents))
    state.pages_per_docket[stratum].append(sum(r.entry.pages for r in non_photo))
    state.tokens_per_docket[stratum].append(sum(r.estimated_tokens for r in readable))
    state.tokens_per_doc[stratum].extend(r.estimated_tokens for r in readable)
    pdfs = [r for r in docket.documents if r.kind is not None]
    state.scan_pages[stratum] += sum(r.pages - r.readable_pages for r in pdfs)
    state.scan_only[stratum] += bool(pdfs) and all(r.kind == "scan" for r in pdfs)
    state.with_submission[stratum] += any(
        r.category == "party_submission" for r in docket.documents
    )
    names = owner_names(raw)
    case_hit = False
    for record in docket.documents:
        state.documents[stratum] += 1
        state.categories[f"{stratum}/{record.category}"] += 1
        state.statuses[f"{stratum}/{record.status}"] += 1
        state.non_pdf[stratum] += not record.entry.is_pdf()
        if record.category == "pilot_form_6120" and record.kind is not None:
            state.form_6120[stratum] += 1
            state.form_6120_text[stratum] += record.kind != "scan"
        if record.status == "fetch failed":
            state.fetch_failed[stratum] += 1
        text = docket.texts.get(record.entry.index)
        if text is None:
            continue
        for chars in _chars_by_page(text):
            state.char_bins[_bin(chars)] += 1
        lowered = text.lower()
        if any(name.lower() in lowered for name in names):
            state.name_hits[f"{stratum}/{record.category}"] += 1
            case_hit = True
        # Correction 2: chained exactly as attach_docket applies them in production (decision
        # 0046), so a name that only becomes matchable after the amateur-built pass (or vice
        # versa) is measured the same way it is redacted -- and each mechanism's count is kept
        # under its own key, never summed into one figure.
        replaced_text, amateur_count = amateur_built_replace(text, raw)
        state.amateur_built_replacements[f"{stratum}/{record.category}"] += amateur_count
        _, owner_count = redact_known_names(replaced_text, raw)
        state.owner_operator_replacements[f"{stratum}/{record.category}"] += owner_count
    state.name_cases[stratum] += case_hit


def _chars_by_page(text: str) -> list[int]:
    """Characters per page from the page-marked text (the marker lines excluded)."""
    counts: list[int] = []
    for block in text.split("[page ")[1:]:
        body = block.split("]\n", 1)[1] if "]\n" in block else ""
        counts.append(len(body.strip()))
    return counts


def _fmt_count(value: float) -> str:
    """A count as a thousands-separated integer, never ``:g``'s scientific notation.

    Also from the final review's smaller findings: at or above 1,000,000, ``:g`` renders a
    figure like ``1234567`` as ``1.23457e+06`` -- exactly what makes a reader distrust a
    published results file. Every value here is a count (documents, pages, tokens), so an
    integer with no decimal place is always the right rendering.
    """
    return f"{value:,.0f}"


def _fmt_q(values: Sequence[float]) -> str:
    q = quantiles(values)
    return (
        "n=0"
        if not q
        else f"n={len(values)} median={_fmt_count(q[0.5])} p75={_fmt_count(q[0.75])} "
        f"p90={_fmt_count(q[0.9])} max={_fmt_count(q[1.0])}"
    )


def report(state: ShapeState) -> str:
    """The results text, by stratum and overall."""
    lines = ["# S2 development docket shape (scripts/docket_scan.py) — counts and quantiles only"]
    # Fix round 1, finding 2: stated once, up front, rather than repeated as a caveat on every
    # affected line below -- this file is meant to sit beside the spike's own numbers, so
    # where a definition differs from the spike's it has to say so, not let a reader assume
    # the two match.
    lines.append("\n## Definitions and limits")
    lines.append(
        "Owner/operator detail figures (addresses, zip codes, a certificate number, and "
        "names -- decision 0046's full REDACTED_FIELDS scope, not name-bearing fields "
        "alone) are counted only over documents whose text was extracted; a scanned "
        "document is never searched, so the count is a floor for that reason as well as "
        "because a detail the record does not hold is not counted."
    )
    lines.append(
        '"Containing" is a case-insensitive substring test; the replacement counts use '
        "word-boundary anchored matching (decision 0046), so the two are not the same "
        "measurement and a document can register on one without the other."
    )
    lines.append(
        "Tokens per docket sums each document's own characters-divided-by-four floor; the "
        "spike's own figures floored once over a docket's total characters instead, so the "
        "two totals are not directly comparable for a docket with more than one document."
    )
    lines.append(
        '"Scanned pages" sums pages minus readable pages over every document with a known kind '
        "(born-digital, partial or scan), so it counts every page of a scan-classified document "
        "and also the individually-unreadable pages inside a partial-classified one, not only "
        "whole scan-classified documents."
    )
    groups = {s: [s] for s in STRATA} | {"overall": list(STRATA)}
    for name, strata in groups.items():
        docs = [v for s in strata for v in state.docs_per_docket[s]]
        pages = [v for s in strata for v in state.pages_per_docket[s]]
        tokens = [v for s in strata for v in state.tokens_per_docket[s]]
        per_doc = [v for s in strata for v in state.tokens_per_doc[s]]
        n = sum(state.dockets[s] for s in strata)
        lines.append(f"\n## {name}: {n} dockets")
        # Fix round 1, finding 1: the denominator this whole group's numbers are over -- a
        # complete run has `cases attempted == dockets read + listing fetch failed +
        # skipped for missing mKey` for every stratum.
        lines.append(
            f"cases attempted: {sum(state.cases_attempted[s] for s in strata)}; "
            f"listing fetch failed: {sum(state.listing_failed[s] for s in strata)}; "
            f"skipped for missing mKey: {sum(state.missing_mkey[s] for s in strata)}"
        )
        lines.append(f"documents per docket: {_fmt_q(docs)}")
        lines.append(f"non-photo pages per docket: {_fmt_q(pages)}")
        lines.append(f"estimated readable tokens per docket: {_fmt_q(tokens)}")
        lines.append(f"estimated tokens per readable document: {_fmt_q(per_doc)}")
        under = sum(1 for t in tokens if t < TOKEN_LINE)
        lines.append(f"dockets under {TOKEN_LINE} tokens: {under} of {len(tokens)}")
        lines.append(
            f"scanned pages: {sum(state.scan_pages[s] for s in strata)}; "
            f"scan-only dockets: {sum(state.scan_only[s] for s in strata)}"
        )
        lines.append(
            "pilot forms with a text layer: "
            f"{sum(state.form_6120_text[s] for s in strata)} of "
            f"{sum(state.form_6120[s] for s in strata)}"
        )
        lines.append(
            f"dockets with a party submission: {sum(state.with_submission[s] for s in strata)}"
        )
        lines.append(
            f"non-PDF documents: {sum(state.non_pdf[s] for s in strata)} of "
            f"{sum(state.documents[s] for s in strata)}"
        )
        lines.append(f"fetch failures: {sum(state.fetch_failed[s] for s in strata)}")
        lines.append(
            "category mix: "
            + ", ".join(
                f"{k.split('/', 1)[1]} {v}"
                for k, v in sorted(state.categories.items())
                if k.split("/")[0] in strata
            )
        )
        lines.append(
            "documents containing an owner or operator detail from the record, by category: "
            + ", ".join(
                f"{k.split('/', 1)[1]} {v}"
                for k, v in sorted(state.name_hits.items())
                if k.split("/")[0] in strata
            )
        )
        lines.append(
            f"cases with such a document: {sum(state.name_cases[s] for s in strata)} "
            "(a floor: a detail the record does not hold is not counted)"
        )
        lines.append(
            "amateur-built replacements, by category: "
            + ", ".join(
                f"{k.split('/', 1)[1]} {v}"
                for k, v in sorted(state.amateur_built_replacements.items())
                if k.split("/")[0] in strata
            )
        )
        lines.append(
            "owner or operator detail replacements, by category: "
            + ", ".join(
                f"{k.split('/', 1)[1]} {v}"
                for k, v in sorted(state.owner_operator_replacements.items())
                if k.split("/")[0] in strata
            )
        )
    lines.append(
        "\n## characters per page, all readable documents (spec §5.2 thresholds at 50 and 300)"
    )
    lines += [
        f"{b}: {state.char_bins[b]}" for b in ("0-0", "1-49", "50-99", "100-299", "300-599", "600+")
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    """Fetch (cached) every dev-400 docket, accumulate, print and optionally write the report."""
    parser = argparse.ArgumentParser(prog="docket_scan")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    settings = Settings()
    processed = settings.data_dir / "processed"
    ids = samples.sample_ids("dev-400")
    if args.limit is not None:
        ids = ids[: args.limit]
    raws = samples.load_cases(processed, ids)
    state = ShapeState()
    with DocketClient(
        settings.docket_dir, seconds_per_request=settings.docket_seconds_per_request
    ) as client:
        for position, raw in enumerate(raws, start=1):
            fatal = raw.get("highestInjuryLevel") == "Fatal"
            record_attempt(state, fatal=fatal)
            mkey = raw.get("mKey")
            if not isinstance(mkey, int):
                record_missing_mkey(state, fatal=fatal)
                continue
            try:
                docket = read_docket(client, mkey)
            except DocketError as error:
                record_listing_failed(state, fatal=fatal)
                print(
                    f"{position}/{len(raws)}: listing failed ({type(error).__name__})",
                    file=sys.stderr,
                )
                continue
            accumulate(state, docket, fatal=fatal, raw=raw)
            print(f"{position}/{len(raws)}: {len(docket.documents)} documents", file=sys.stderr)
    text = report(state)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
