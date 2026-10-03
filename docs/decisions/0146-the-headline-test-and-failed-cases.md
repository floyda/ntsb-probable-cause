# 0146 — The headline test: top-1 decides, a 6 point margin, and how failed cases count

From the S3.2 design session (2026-10-03): the margin, and failed cases, option A. Fills in
[0121](0121-agency-moves-to-reading-and-coding.md) item 5's test and applies
[0136](0136-s3-rounds-count-failed-cases-as-wrong.md)'s reason. Detail:
[the S3.2 specification](../specs/2026-10-03-s3-2-claims-design.md) §7.

## Context

The loop and arm B answer the same held-out cases. 0121 item 5 says the loop is warranted if it
beats arm B at equal cost, or matches it at lower cost. It does not say what "beats" and "matches"
mean. Without a margin, "the interval includes zero" would count as a match, and a small or
noisy test would always match.

On `dev-400`, seen before this rule was written: against arm B, noise-floor run b's top-1
difference is +1.0% [-3.6%, +5.6%] and run a's is -1.0% [-5.3%, +3.3%]
(`docs/results/s3-armc-b-vs-s3-armb-full-dev.txt`, `s3-armc-a-vs-s3-armb-full-dev.txt`).

Failed cases: S2.4's held-out arm B had 40 guard refusals among its 64 failures
(`docs/results/s24-bars.txt`). A guard refusal comes from our leakage guard, which blocks a
document holding words from the NTSB's own conclusions.

## Decision

1. **Occurrence top-1 decides.** It has been the headline since S1. **Finding recall@10
   (flagged)** is reported under the same rule as its own result and does not decide.
   **Top-3** is reported beside and does not decide: its gap is mostly the ordering check, which
   only arm B runs. On `dev-400` that check added +8.3% [+5.5%, +11.3%] to arm B's top-3
   (`docs/results/s3-armb-full-dev.txt`) and +9.1% [+6.1%, +12.2%] to the loop's in the
   diagnostic (`docs/results/s3-check-diagnostic-dev.txt`).
2. **The four outcomes**, from the paired mean (loop minus arm B) and its 95% interval:
   - **Beats:** the interval lies wholly above zero.
   - **Matches:** the bottom of the interval is above **-6 points**, and it does not beat.
   - **Worse:** the top of the interval is below zero.
   - **Undecided:** anything else, published as "not shown to match".
3. **The margin of 6 points** is chosen after seeing `dev-400`, while Andy expected the arms to
   be equal. Andy (spelling corrected): "I genuinely think it is equal, but perhaps wins on
   cost." That expectation is registered as prediction 1. Every report prints the bottom of the
   interval, so a reader can apply a stricter margin.
4. **Failed cases.**
   - **A guard refusal removes the case from the comparison for both arms.**
   - **Every other failure counts as wrong, in the arm where it happened**: format or tool
     (`failed: <step>`), the round limit (`failed: rounds`) and the cap. For findings, a failed
     case scores zero when the NTSB flagged findings.
   - **This differs from 0136 on guard refusals only.** 0136 counts every failure wrong in a
     tuning round, the two guard refusals in each noise-floor run included. A tuning round
     compares one loop with another that meets the same refusals. This comparison is between two
     arms, so a refusal is removed for both.
   - **It applies to every paired reading in S3.2,** the ablations included.
   - **Printed beside:** the "both answered" reading, on the cases both arms scored, as earlier
     stages reported.
   - **The noise floor is read under the same rule.** A committed script reads the noise-floor
     pair over all 401 cases, guard refusals removed and other failures wrong, so the noise and
     the claim are measured alike. It is the reading of the pair under 0136's rule that S3.1 did not commit
     (0139 Context 1).
5. **The model's own abstain flag** is scored as the reports already score it (counted wrong for
   top-1), in both arms. The abstain threshold of [0147](0147-calibration-and-abstain.md) does
   not change the comparison.

## Why

1. **A margin is needed for "matches" to mean anything.** With about 390 paired cases the
   interval is about ±4.3 points wide (the `dev-400` comparisons). If the loop were exactly as
   good as arm B, the bottom of the interval would land above -5 only about 63% of the time,
   above -6 about 78%, and above -7 about 89% (estimates, normal arithmetic on that width). At
   5 points a truly equal loop would be marked "not shown to match" about one time in three.
2. **What the margin costs is stated.** On a score of about 27%, 6 points lets the loop get about
   one in five fewer cases right and still "match". The choice was made after seeing `dev-400`,
   and the disclosure is in the registration (spec §13).
3. **Chance sorts identical runs near the margin.** Under this rule both `dev-400` readings
   above match. Under a 5-point margin, run a would not.
4. **A guard refusal is not the agent's failure.** The loop is offered the same documents arm B
   reads, so it can meet only a refusal arm B also meets, and it can avoid one by skipping the
   document. Counting that against arm B would hand the loop points for dodging the guard,
   which no live case needs: open cases have no analysis to leak.
5. **Other failures are the arm's own.** A format failure, a round limit and a cap are what the
   agent did (0136's reason).
6. **Expected effect of the removal:** with about 360 cases left of 400, the interval widens a
   little, to about ±4.5 points (estimate).

## What this rules out

- **A margin of 3 or 5 points.** The strongest case for 5: it is a stricter bar, and the loop
  is easier to doubt. Rejected: a truly equal loop would be marked "not shown to match" about
  one time in three at 5 points, and more often at 3.
- **No margin.** Rejected in Context: a noisy test would always match.
- **Leaving every failure out.** It is what S2.4's report did. Rejected: it would reward an
  arm for failing on its hardest cases.
- **Counting guard refusals as wrong.** Rejected in Why 4.

## Status

Accepted, 2026-10-03 (Andy, S3.2 design session; specification approved 2026-10-03).

## Glossary

- **Beats, matches, worse, undecided**: the four outcomes of item 2.
- **Guard refusal**: the leakage guard blocks a document that holds words from the NTSB's own
  conclusions; the case fails with a `leak:` reason.
- **Interval (95%)**: the span the true difference very likely lies in, given the number of cases.
- **Margin**: how much worse the loop may be and still "match" arm B.
- **Paired difference**: both arms scored on the same cases; the mean gap with its interval.
- **Warranted**: the loop beats arm B at equal or lower cost, or matches it at lower cost
  (spec §7.4).
