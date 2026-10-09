# 0159 — S3.3's closure runs are scored the same morning, as counts only, and printed alone

From the S3.3 design session with Andy (2026-10-07). Detail:
[the S3.3 specification](../specs/2026-10-07-s3-3-live-shadow-design.md) §10.

## Context

1. **At closure the verdict is in the case record.** The split withholds it from Ellery; the
   scorer may read it, as in evaluation ([0013](0013-evidence-synthesis-verdict.md)).
2. **The S3 outline** said S3.3 measures "mechanics and cost only".
3. **Open-split cases enter a measurement only as numbers**
   ([0024](0024-open-split-enters-measurements-only-as-numbers.md)).
4. **Ellery version 1 is frozen** ([0156](0156-the-board-runs-ellery-version-1.md)).

## Decision

1. **Each closure run is scored the same morning**, by the loop runner's existing scoring, with
   the board's three grades (the first occurrence code right; the NTSB's first code among
   Ellery's three but not first; different), abstains, and failures by reason.
2. **A case whose record holds no verdict yet is left unscored**, and counted.
3. **Counts only**, in one committed results file (`docs/results/s33-live-shadow.txt`), with a 95%
   interval on "first code right". No case number, no case key, no text.
4. **Printed alone.** No held-out figure appears beside it
   ([0021](0021-agency-measured-as-hypothesis-trail.md)).

## Why

1. **It rehearses S4's scoring on real closure records**, where evaluation never looked: an NTSB
   code missing from the code tables, a case closed as N/A, a verdict not yet in the record.
2. **It costs nothing**: no model call.
3. **It cannot tempt tuning**: version 1 is frozen, and a change would be a new version needing a
   registered comparison (0156 item 4).
4. **Andy, 2026-10-07:** "Yer A".

## What this rules out

- **The fixed pipeline (arm B) run beside the loop, unpublished.** The strongest case: a fresh,
  paired check of whether held-out's −9.5 points holds on new cases. Its cost: twice the runs and
  chaining arm B's three passes on live cases. Left to version 2's registered comparison, which
  needs arm B anyway ([0140](0140-the-precedent-tool-after-s4-as-a-measured-v2.md)).
- **No scoring, mechanics and cost only.** The strictest. Rejected: S4 would build its scoring
  untried against real closures.

## Status

Accepted, 2026-10-07 (Andy, S3.3 design session; specification approved 2026-10-07).

## Glossary

- **Interval (95%)**: the range the true rate very likely lies in; about ±10 points at 50 cases.
- **Unscored**: coded, but with no verdict to compare against yet.
