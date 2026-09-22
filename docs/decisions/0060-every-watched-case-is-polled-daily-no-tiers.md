# 0060 — Every watched case is polled once a day, with no tiers

## Context

The recorder (S2.5) polls open investigations to record when each piece of evidence first
appears. The measurement it feeds is "days from the event to first appearance", so the unit is
the day. A full pass of about 905 watched cases (ad-hoc count, re-derived in the stage) at the
docket client's enforced one request every two seconds takes about 30 minutes.

A tiered schedule was designed in the session: daily until a case's docket has appeared and
been quiet for N weeks, then weekly, returning to daily on any change. Its saving was
computed: at the smallest Fargate size a daily pass costs about $0.25 a month, so halving the
run time saves about $0.12 a month.

## Decision

Every watched case is polled once a day, at 03:00 UTC. There are no tiers. The run also
writes one summary row per night — cases polled, cases changed, new documents, failures,
minutes — because how many open cases change on a typical night is the number S4 uses to
size the agent's live runs.

## Why

1. **Daily polling gives exactly the precision the measurement uses.** Every arrival is
   known to within a day, for every document, for as long as the case is watched.
2. **The saving from tiering is about twelve cents a month.** Cost gives no reason to tier.
3. **Tiering loses precision on the cases nobody understands.** Whether a docket that has
   gone quiet stays quiet has never been measured; a weekly tier would rest on that guess and
   the lost precision could never be recovered.
4. **No tiers means no tier state, no parameter N, no check script and no rule to defend
   on the methods page.** "Every open case, every day" cannot be argued with.

## What this rules out

- **Tiered polling by observed quiet.** The better of the tiered designs; rejected for the
  reasons above. It is revisited only if the nightly run exceeds an hour, or the NTSB asks for
  a lower request rate. By then the recorder's own data says whether quiet cases stay quiet.
- **Tiered polling by case age.** Worse than the above: it keys on a guess rather than an
  observation.
- **Polling more than once a day.** Half-day precision the measurement never uses, at
  double the requests to a government site.

## Status

Accepted, 2026-09-22.
