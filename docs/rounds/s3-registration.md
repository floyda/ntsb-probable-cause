# S3.2: the registration (decisions 0141 to 0151)

Committed before any S3.2 run. It fixes the runs, the rules that turn them into a verdict, and
nine predictions, so that none of them can be chosen after a result is seen. Specification:
`docs/specs/2026-10-03-s3-2-claims-design.md` (approved 2026-10-03).

**What committing this file does.** From the commit that adds it, arm C may run on
`heldout-400`, and arm B's tool post-pass and its `luna` ordering check may each run once on a
held-out arm B run (decision 0142; `checkpass.S32_REGISTRATION`). It does **not** open the sealed
sample `dev-seal-s3-400`, which stays sealed for v2 (decision 0141; its unlock is
`docs/rounds/s3-sealed.md`).

## The setups, exactly

- **The loop (arm C)**: frozen at commit `fd6053f`, prompt version
  `s3-v1+ge17fecdc66ec+p947fac1c86a4` (decision 0139). S3.2 changes none of the ten
  fingerprinted files, and `tests/test_s32_frozen.py` asserts the version (decision 0142). It is
  version 1 (v1) of the agent.
- **Arm B**: S2.7's answer with the guidance files `r3-loc-stall` then `r6-aircraft-control`
  (prompt `s1-v6+ge17fecdc66ec`), then the tool post-pass (`+tools-s3+p947fac1c86a4`), then the
  ordering check `luna` with S3's statistics (`+check-luna-s3`) (decision 0127).
- **Arm A**: start facts only, one call, no guidance.
- **Every run**: `openai/gpt-6-luna` at reasoning `medium`, reply budget 8,000 tokens, evidence
  v1, S3's statistics, batch (the ordering check is synchronous at the standard price), and one
  per-case cap of **$0.30** (decision 0144). The cap check found no noise-floor case whose coding
  was cut short at $0.15 (`docs/results/s32-cap-check-dev.txt`), so the cap stands.

`scripts/s32_claims.py` refuses any held-out run whose recorded settings differ from these.

## What runs, once each, in this order

Each through `scripts/paid_run.sh <target>` (a clean checkout reset to `origin/s3-2-claims`),
after `make s3-spend EST=<estimate>` shows S3's total stays at or below $17.11 (decision 0150).
Each held-out target's ledger row is committed and pushed before the next starts. An interrupted
run is continued with `RESUME=<run id>`.

1. `s32-coding-ablation` — the loop without its coding tools, on `dev-400` (about $1.20 billed,
   estimate). Read against the two noise-floor runs.
2. `s32-heldout-a` — arm A on `heldout-400` (about $0.30).
3. `s32-heldout-b-answer` — arm B's answer on `heldout-400` (about $1.10).
4. `s32-heldout-b-tools RUN=<3's id>` — its tool post-pass (about $1.00).
5. `s32-heldout-b-check RUN=<4's id>` — its ordering check (about $0.11).
6. `s32-heldout-c` — the loop on `heldout-400` (about $1.90).
7. `s32-heldout-c-nodocket` — the loop without the docket on `heldout-400` (about $0.50 to $1).

Then, free: `make s32-coding-ablation-report RUN=<1's id>` and `make s32-claims` with the run
ids, which write `docs/results/s32-coding-ablation-dev.txt` and
`docs/results/s32-claims-heldout.txt`. Nothing else reads a held-out run.

## The rules (specification §6 to §10)

- **Cost (decision 0145).** Each arm's cost is what was billed for its held-out run, on the same
  cases, failed cases included. Arm B's is the sum of its three parts. The loop's cost is
  **lower** when more than 10% below arm B's, **greater** when more than 10% above, and
  **equal** otherwise. Computed cost and prompt tokens are printed beside, never deciding.
- **Accuracy (decision 0146).** Occurrence top-1 decides: the paired difference, loop minus arm
  B (its final, checked run), with its 95% interval.
  - **Beats**: the interval lies wholly above zero.
  - **Matches**: the bottom of the interval is above −6 points, and it does not beat.
  - **Worse**: the top of the interval is below zero.
  - **Undecided**: anything else, published as "not shown to match".

  Finding recall@10 (flagged) and top-3 are reported under the same rule and do not decide. The
  bottom of the top-1 interval is printed on its own, so a reader can apply a stricter margin.
- **Failed cases (decision 0146).** A guard refusal removes the case from the comparison for
  both arms. Every other failure counts as wrong in the arm where it happened. The "both
  answered" reading is printed beside. Two runs over different case sets are refused.
- **Warranted (decision 0146).** The loop beats arm B at equal or lower cost, or matches it at
  lower cost. Every other combination is "not warranted".
- **Calibration (decision 0147).** The frozen curve is
  `src/ntsb_probable_cause/scoring/tables/calibration_s3.json`: intercept −1.5762, slope 0.9435,
  fitted on the 785 scored answers of the two noise-floor runs at commit `3f1f992`
  (`docs/results/s32-calibration-dev.txt`). On held-out, the loop's scored answers are put in
  three equal groups by fitted value; the curve is **calibrated** when, in every group, the
  average fitted value lies inside that group's 98.3% Wilson interval for the share right. The
  share right in the high group minus the low group is reported beside, with its interval.
- **Abstain (decision 0147).** The loop abstains when its fitted chance is below 16.4%. It does
  not change the arm comparison.
- **Result 1 (decision 0148)** holds when the loop reads every document on offer on more than
  half of the cases with documents on offer, or first uses the four coding tools in arm B's
  exact order on more than half of the cases counted. Reported by fatal and non-fatal and by
  documents offered.
- **Result 2** holds when the loop does not beat arm B and its billed cost is equal or greater.
- **Result 3** holds when the calibration test fails.
- **Result 4** is published as **not shown**: version 1's stated effects describe what a
  document may show; they do not predict how the hypothesis will move (decision 0148).
- **The reading (decision 0149).** Question 1, "is the loop warranted", is decided by the rule
  above alone; results 1 and 2 say how. Question 2, "can the board's numbers and reasons be
  trusted", is results 3 and 4: if result 3 holds the board shows its confidence with a plain
  warning; while result 4 is not shown the board labels a stated effect "the agent's note". The
  headline is one of the sentences in specification §10. If the verdict rests on cost, the
  report splits the billed saving into reading less and cache discounts.

## The predictions

Each is scored "met" or "not met" by `scripts/s32_claims.py` and published either way.

1. **Top-1** (held-out): the loop matches but does not beat arm B — the interval's bottom is
   above −6 points and the interval is not wholly above zero. (Andy's stated expectation.)
2. **Cost** (held-out): the loop's billed cost is more than 10% below arm B's.
3. **Top-3** (held-out): the loop is below arm B, the interval wholly below zero.
4. **Findings** (held-out, recall@10 flagged): level, the interval including zero.
5. **Without the docket** (held-out): the loop loses at least 10 points of top-1 — the paired
   difference, without minus with, is −10.0 points or lower.
6. **Without coding tools** (`dev-400`): the loop is worse on top-1 than each noise-floor run,
   each interval wholly below zero.
7. **Result 1** (held-out): the loop reads every document on offer on more than half of the
   cases with documents on offer, and uses arm B's exact tool order on fewer than 5% of the
   cases counted.
8. **Calibration** (held-out) passes the three-group test, and the abstain threshold fires on
   fewer than 5% of the loop's scored cases. *See the disclosure on the abstain half below.*
9. **Format** (held-out loop run): at most 8 of the 400 cases fail for format or tool reasons.

Not predicted: the level of top-1.

## Disclosures

Each of these was seen or chosen before the predictions above were written:

- **The learning probe** (pull request #18; 20 `dev-400` cases, twice), disclosed in 0121.
- **The noise-floor runs** and their accuracy (`docs/results/s3-noise-floor-dev.txt`). Read
  under this registration's failure rule, the two runs differ by top-1 −1.5 points [−5.0, +2.0]
  on 399 cases, 2 guard refusals removed and 5 and 8 failures counted wrong
  (`docs/results/s32-noise-dev.txt`).
- **The six comparisons of the loop with arm B on `dev-400`** (`docs/results/s3-armc-*`):
  against S3's full arm B, top-1 −1.0% [−5.3%, +3.3%] and +1.0% [−3.6%, +5.6%], top-3 −11.4%
  [−16.0%, −6.9%] and −12.8% [−17.9%, −8.2%], finding recall@10 +0.4% [−2.0%, +2.9%] and −1.5%
  [−3.9%, +0.6%].
- **The ordering diagnostic** on the loop (`docs/results/s3-check-diagnostic-dev.txt`, 0137) and
  **S3.1 Task 15's probes**.
- **The behaviour counts on `dev-400`** (`docs/results/s32-behaviour-dev.txt`): the loop read
  every document on offer on 225 and 220 of 379 cases (59.4% and 58.0%), and used arm B's exact
  tool order on 1 and 0 of 401. It read everything on 82.2% and 81.1% of non-fatal cases with
  documents on offer, against 37.6% and 36.1% of fatal ones. So result 1 is expected to hold.
  The fixed-order share's denominator is every case counted (401), not the scored cases.
- **Result 4's measure on `dev-400`**: of the stated effects on documents read, 48 of 2,094 and
  50 of 2,072 name an event label (the strict figure). A looser route, a finding category's
  last segment, adds many matches on generic words such as "maintenance", so the combined
  336 and 331 (16.0%) is an upper bound only.
- **Abstain cannot fire on this curve.** The frozen curve's lowest value, at a stated confidence
  of zero, is 17.1%, above the 16.4% cut-off. So no answer can abstain, on `dev-400` (0 of 785)
  or on held-out. The abstain half of prediction 8 is therefore met by construction; it tests
  nothing. It is kept as registered in the specification and reported with this note. The
  finding it stands for: the agent's confidence cannot yet tell thin evidence from good.
- **Rules chosen after seeing `dev-400`**: the billed-cost measure (§6), the 6-point margin
  (§7.2), and the result 1 definitions (§9.1).
- **The guidance files' overlap** with `dev-seal-s3-400` (0129 item 6): their counts come from a
  pool that held its cases. The sample is unused in S3.2.
- **The recorder re-check**, closed at 12 nights by decision 0151
  (`docs/results/s3-recorder-report-2026-10-04.txt`): 46 of 46 timed docket arrivals came in the
  same nightly run as the case's closure, none before or after; about 1% to 2% of open cases hold
  a docket whose arrival time is unknown. Dockets almost always arrive at closure, so S3.2
  measures the full condition only.
