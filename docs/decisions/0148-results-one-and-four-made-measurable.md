# 0148 — Results 1 and 4 made measurable; result 4 is "not shown" on v1

From the S3.2 design session (2026-10-03): the plain definitions, and result 4, option A. Makes
measurable two of the four results of [0121](0121-agency-moves-to-reading-and-coding.md) item 5.
Detail: [the S3.2 specification](../specs/2026-10-03-s3-2-claims-design.md) §9.1 and §9.4.

## Context

0121 item 5 lists four results that count against the loop. Results 2 and 3 are cost and
calibration ([0145](0145-equal-cost-is-billed-cost-with-a-ten-percent-band.md),
[0147](0147-calibration-and-abstain.md)). Results 1 and 4 need definitions.

**Result 1:** "arm C reads every offered document on most cases, **or** calls the coding tools in
arm B's fixed order on most cases."

**Seen before registration** (ad-hoc, from the noise-floor trails; not citable, and S3.2
re-derives each with a committed script): the loop read every offered document on 225 and 220
of 379 cases (59% and 58%), and used arm B's exact order on 1 and 0 cases of about 395. Counting
only cases with at least two documents gives 166 and 161 of 319 (52% and 50%). Where the loop
chooses is already visible: it left 452 documents unread on 121 fatal cases, against 62 on 33
non-fatal cases (scripted, the `unread` line of
`docs/results/s3-armc-a-vs-s3-armb-full-dev.txt`).

**Result 4:** "the effect the agent states for a document it reads does not agree with the change
observed after reading it more often than chance." An ad-hoc look at 15 stated effects drawn at
random from a `dev-400` trail found none that names a code or a direction of change. Three typical
ones: "The pilot's account may establish what occurred during initial climb..."; "Toxicology may
identify impairment..."; "Weather report may establish wind, visibility, and conditions...". The
loop's instruction asks for an "expected effect" in free text
(`DocumentDecision.expected_effect`), and the model answers with a description.

## Decision

1. **Result 1 holds, by plain definitions:**
   - **Reads every offered document:** across the whole case, both read choices together, every
     document on offer (`AgentCall.offered`) was read. A case with nothing on offer leaves the
     count.
   - **Calls the coding tools in arm B's fixed order:** the order in which the case first uses
     each coding tool is exactly `describe_codes`, `occurrence_usage`, `past_findings`,
     `suggest_codes`.
   - **Most:** more than half of the cases counted.
   - **Reported beside:** the same counts by fatal and non-fatal, and by docket size.
2. **The definition counting only cases with at least two documents is not chosen.** Choosing
   it after seeing the numbers above would be choosing the rule that might dodge the result.
3. **Result 4 is published as "not shown" on v1.** That is not "passed". A committed script
   prints, for the held-out loop run, how many stated effects name an occurrence code or
   category, as the measure behind the statement.
4. **The fix comes with the agent's next text change** (S3.3, with the fingerprint of
   [0143](0143-the-fingerprint-should-cover-what-the-agent-receives.md)): a structured field such
   as *expected change: none / confirms / changes the answer to ...*, which a later stage can
   test against what changed.

## Why

1. **The definitions are the plain reading of 0121's words,** fixed before held-out so that no
   one can adjust them after a result.
2. **Not choosing the two-document definition keeps the rule honest.** The ad-hoc counts show it
   would move the first half of result 1 from 59% to 52%, still above half, so the choice would
   matter little to the outcome. Not choosing it, even so, avoids picking a rule after seeing
   what it does.
3. **The stated effects cannot be tested as written.** They describe what a document may show;
   they do not predict how the hypothesis will move. A test of "agrees more often than chance"
   needs a prediction that can disagree.
4. **"Not shown" is the honest word.** It says the test cannot be run on v1, and does not claim
   the effects are right.
5. **The structured field costs nothing now and makes the test possible later.** It is a text
   change, so it belongs with S3.3, where the loop's text is next likely to change.

## What this rules out

- **A validated judge model labelling each effect,** checked first against 40 of Andy's marks.
  It costs cents and about an hour of marking. Rejected: S2.7's judge failed such a check (32 of
  46, 69.6%, against 75%; `docs/results/s27-round0-dev.txt`, decision 0099), and if it passed,
  almost every effect would come back "no claim", leaving too few to test.
- **The two-document definition of result 1.** Rejected in Decision 2.
- **Testing result 4 as written on v1.** Rejected in Why 3.
- **Calling result 4 passed because it cannot fail.** Rejected in Why 4.

## Status

Accepted, 2026-10-03 (Andy, S3.2 design session; specification approved 2026-10-03).

## Glossary

- **Coding tools**: the four tools that take codes as arguments: `describe_codes`,
  `occurrence_usage`, `past_findings`, `suggest_codes` (0125).
- **Offered document**: a docket document the loop is asked to read or skip.
- **Read choice**: one tool call that gives read or skip, with the expected effect, for every
  offered document (0121).
- **Stated effect**: the agent's one-line reason for reading a document.
- **v1**: the loop as frozen at `fd6053f`.

## Amended in part, 2026-10-07 (appended; nothing above is edited)

- **Item 4's timing is amended by [0164](0164-what-no-longer-arises-in-s33.md).** S3.3 changes no
  text Ellery receives ([0156](0156-the-board-runs-ellery-version-1.md)), so the structured
  expected-change field comes with version 2, not S3.3. Result 4 stays "not shown" on version 1.
