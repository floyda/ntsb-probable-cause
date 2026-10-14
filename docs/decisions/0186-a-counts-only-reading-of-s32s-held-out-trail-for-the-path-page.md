# 0186. One counts-only reading of S3.2's held-out loop trail, for the Path page's question 7

## Context

The public site's Path page (S5 specification §7.4) gives question 7, "Does choosing what to
read beat reading everything?", one figure: each case's belief before reading, after reading
and at the answer, against the NTSB's first code. §7.4 calls it "the direct evidence on
agency", and says it "can go either way".

S3.2's held-out diagnosis (decision 0153) already prints two of the moves that figure needs,
from the trail of the loop's held-out run `20261004T140804-e0dc881-heldout-400-C`
(`docs/results/s32-heldout-diagnosis.txt`). Before reading (H0) to the answer: 43 and 94 right
of 394 answered cases, 60 fixed, 9 broken. The last hypothesis before coding to the answer:
20 fixed, 7 broken. It does not print "after reading" as its own checkpoint, or the move from
before reading to after reading. 0153 fixed its six breakdowns before any was read, and its
script "prints those six and no others", so a further reading needs its own record, written
before it runs.

0153 item 4 already gave up `heldout-400` as a test for any later version of the agent. A
further counts-only reading of the same run costs no further sample. What it can cost is a
reading chosen after looking, which is why its breakdowns are fixed here, before the script
exists.

## Decision

1. **One reading, of one run.** A new exploratory script (decision 0059),
   `scripts/exploratory/s5_belief_path.py`, reads the loop's held-out run named above through
   the diagnosis's own held-out path and refusals. It runs once, from a clean commit that holds
   this record, and writes `docs/results/s5-belief-path-heldout.txt`. It makes no model call.
2. **The cases** are the ones the loop answered, as the diagnosis counts them (394). A case
   with no H0 in its trail is left out and counted.
3. **Three checkpoints per case,** each judged right when its first code is the NTSB's first
   code, scored as the diagnosis scores a hypothesis:
   - **before reading:** H0, the first accepted `h0`;
   - **after reading:** the latest accepted checkpoint of `h0`, `h1` and `h2` (the diagnosis's
     "last hypothesis before coding"). For a case that recorded no belief after a read choice,
     it is H0, and those cases are counted;
   - **the answer:** the case result's recorded top-1.
4. **It prints these and no others:** the right count at each checkpoint, of the cases
   counted; and for before → after reading and for after reading → the answer, how many stayed
   right, were fixed, were broken and stayed wrong. Counts only (decision 0024): no case
   number, and no model or case text.
5. **A check against the record.** The before-reading and answer counts, and the after-reading
   → answer fixes and breaks, must equal the diagnosis's committed figures, or the script stops
   and writes nothing.
6. **It decides nothing and claims nothing** (decision 0059). It is a figure for the public
   site, read with the diagnosis's caution about docket size.

## Why

- **The figure the specification describes needs the after-reading checkpoint.** Without it,
  the page can show only that the agent ended with more right than it began. It cannot show
  whether that came from reading the documents or from the coding step, which is the question
  the figure exists to answer (Andy, 2026-10-14).
- **The cost in samples is already paid.** 0153 item 4 spent `heldout-400` for later
  versions. The S3.2 runs are on held-out cases, and the public figure should come from the
  same cases as the result it illustrates.
- **Fixing the breakdowns first keeps the reading honest.** As with 0153, what is counted is
  stated before anything is read, so the figure cannot be shaped after looking.

## What this rules out

- **Drawing the figure from the diagnosis's committed counts alone.** It needs no new reading
  and no record, and it shows before reading and the answer, with the coding step's share. It
  was the cheaper option, and was not taken: it leaves "after reading" out, which is the
  checkpoint that tests reading (Andy, 2026-10-14).
- **Any other breakdown from this reading** (by docket size, fatal and non-fatal, read-all and
  skipped, confidence), and any reading of another held-out run. Each would need its own record.
- **Using the reading to change the agent.** Version 1 is frozen (0139). This is a figure, not
  a tuning signal.

## Status

Accepted (Andy, 2026-10-14).
