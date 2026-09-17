# 0039 — Docket shape is re-measured on closed open-split cases, 40 per stratum, numbers only

Settles the S2 measurement that 0024 permits and the roadmap's deferred-decisions table
assigns to S2: docket shape on dockets from 2020 or later.

## Context

Every docket-size number the design rests on comes from accidents in 2015 to 2019
(`../ntsb-spike/scripts/docket_shape_probe.py`, register A13): a population-weighted median
of 4 documents, 0.89 of dockets under 10,000 estimated tokens, and no scan-only docket among
the 32 whose text was extracted. That era was C-class heavy. The corpus scan
(`docs/results/s0-corpus-scan.txt`) counts C-class cases as 6,126 of 13,560 development
cases and 0 of the 1,840 closed open-split cases (1,729 L, 111 F). Practice may also have
changed: 5 of the 14 dockets the spike probed from 2020 onward were scan-only.

Predictions P1 to P3 (0022), the "four in five fit one call" claim, the cost cap and arm B's
budget all rest on the old numbers. The held-out years stay untouched, so the closed
open-split cases are the only current-era dockets that can be measured, and 0024 allows it
only as numbers: no case numbers, no text, no cached documents, no per-case rows.

## Decision

1. **Sample.** Closed open-split cases (event date 2024 or later, `completionStatus ==
   "Completed"`), stratified fatal and non-fatal, **40 dockets per stratum**, drawn by a
   committed seed and rule. Every non-photo PDF in all 80 dockets is extracted. The seed and
   rule are committed; the drawn case list is not, because it would be a per-case row.
2. **Statistics**, the same as the spike's so the eras sit side by side: documents and
   non-photo pages per docket; estimated readable tokens per docket and per document; the
   share of dockets under 10,000 tokens; scanned pages and the share of scan-only dockets;
   the share of Form 6120s with a text layer; party-submission presence; non-PDF share; and
   the title-category mix. Each is a count or a quantile, by stratum and overall.
3. **Read and discard.** The script streams each listing and document into the parser and
   extractor and keeps only the numbers. It writes nothing under `data/`; the results file is
   its only output, and a test asserts so.
4. **Use of the numbers.** Published on the Methods page beside the development-era figures.
   They set the expectation for the per-case cost cap S3 confirms, and may report, as counts,
   how arm B's development-chosen filter would perform on the current title mix. They never
   choose the filter, the threshold or a prompt (0024).

## Why

1. **The cases the agent is evaluated and shown on come from a different era** than the one
   every size figure describes.
2. **Forty per stratum is cheap and doubles the spike's precision** on the scan-only share,
   the number most likely to change the design. The cost is an hour or two of polite
   fetching and no money.
3. **Numbers cannot leak.** A quantile of page counts carries nothing back into development
   or evaluation work (0024, reason 1).

## What this rules out

- **Measuring on the held-out split.** Tighter numbers from 4,241 cases. Rejected: every look
  at held-out is a tune, and 0024 exists so this never touches those years.
- **Fifteen per stratum**, the first proposal. Rejected by Andy for a tighter interval.
- **Caching the fetched documents for later reuse.** Rejected by 0024, item 2.
- **Reading the fatal numbers as a forecast for cases still open.** The 111 closed fatal
  cases are a small population and a draw of 40 covers over a third of it; the figures
  describe that population, and the results file says so.

## Status

Accepted, 2026-09-17 (Andy: "30 or even 40 is reasonable"; 40 taken).
