# 0106 — S2.7's Round 6 is kept by override of the do-no-harm rule

Overrides the outcome [0098](0098-guidance-rounds-stop-rule-and-prediction.md) item 4 gives
S2.7's Round 6, once. The rule itself is unchanged for every other round.

## Context

Round 6 was S2.7's first finding round (`docs/rounds/s27-round-6.md`): guidance on the NTSB's
habit of flagging "Aircraft control / Pilot", with the flight parameter not held, when the
defining event is a loss of control or a stall. It was registered before its run and read by
`scripts/round_result.py` against the reference, Round 3's checked run:

- finding recall@10 +11.4% [+8.2%, +14.6%] on 397 cases, against a noise floor of 1.7 points;
- occurrence top-1 -6.3% [-10.5%, -2.5%] on 399 cases.

Top-1's interval lies wholly below zero, so the do-no-harm rule drops the round.

Round 4's result note (`docs/rounds/s27-round-4.md`, committed the day before Round 6 ran)
had already recorded that Round 3 is a high run: its checked top-1, 31.3%, is the highest of the
runs so far, and runs move far more than the one identical pair behind the noise floor shows.
Against the other runs, all read on Luna-checked folders (ad-hoc counts, 2026-09-29, in Round
6's note):

| Round 6 against | top-1 | finding recall@10 |
|---|---|---|
| Round 4 (Round 3's guidance plus fuel) | -2.3% [-6.3%, +1.8%] | +12.3% [+9.1%, +15.4%] |
| Round 5 (Round 3's guidance plus sub-phases) | -2.8% [-7.0%, +1.3%] | +12.7% [+9.8%, +15.8%] |
| the repeat (no guidance) | -1.5% [-5.8%, +2.5%] | +10.5% [+7.2%, +13.7%] |

Round 6's own top-1, 25.1%, is the lowest of the six checked runs (26.6% to 31.3% for the
others).

## Decision

1. Round 6 is **kept**. Its guidance, `r6-aircraft-control`, stacks after `r3-loc-stall`, and
   Round 6's checked run is the reference for any later round.
2. Round 6's registration keeps the rule's outcome ("dropped") as written; an override section
   appended below it names this record.
3. S2.7's report, its sealed-run registration (`docs/rounds/s27-sealed.md`) and its As-built
   record state that Round 6 was kept by override, with the top-1 numbers against the
   reference and against the other runs, and that a small top-1 cost (one to three points)
   cannot be ruled out.
4. The judge runs on Round 6 as on any kept round (0098 item 4), when Andy approves its cost.
5. Findings are pursued further after S2.7: the fixed coding lookup Andy is designing for S2.8
   takes findings as its main target.

## Why

1. **Andy's choice**: "I think option B, its clearly something to pursue at a later stage".
2. **The finding gain holds against every run.** It is the largest effect S2.7 has measured,
   and it takes arm B's finding recall on `dev-400` near the no-model baseline's held-out figure
   (22.6% against 23.2%), where every earlier run was under half of it.
3. **The harm is against one run known in advance to be high.** Against three other runs, two
   with the same kept guidance, top-1's difference includes zero. The note that flagged Round 3
   was written before Round 6's result existed.
4. **Dropping it would publish a finding result we already know is beatable by a wide margin**,
   on a technicality about which run was the reference.

## What this rules out

- **Following the rule (drop the round).** Clean, but it discards a gain that holds against
  every comparison because of the one reference known to be high.
- **Re-running Round 3's stack as a fresh reference first.** Fairer in form, about $1.30 and a
  few hours, and still a reference chosen after the result was seen.
- **Changing the do-no-harm rule itself.** It stays as it is for every other round; this record
  overrides one outcome, openly, like [0087](0087-the-transcriber-is-qwen-provisionally.md).

## Status

Accepted, 2026-09-29 (Andy: "I think option B, its clearly something to pursue at a later
stage").

## Source of the numbers (final review, I2)

The table above and Round 6's note were "ad-hoc counts" when this record was written. They are
now reproduced from committed code, free and local: `make s27-round-comparisons`
(`scripts/round_comparisons.py`) reads the seven checked run folders named above and writes
`docs/results/s27-round-comparisons-dev.txt`. No figure in that file differs from this record's
table or from Round 6's note.
