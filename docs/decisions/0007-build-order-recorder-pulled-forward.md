# 0007 — Build order, with the recorder pulled forward

## Context

The work decomposes into several independent subsystems. Built in dependency order they
would run: foundation, scoring, docket tool, agent loop, live pipeline, deployment. One
constraint cuts across that order.

## Decision

Stages S-0 (spike housekeeping), S0 (foundation), S1 (scoring and harness), S2 (docket
tool), **S2.5 (the recorder)**, S3 (agent loop), S4 (predictions and resolution), S5
(deployment and site). Each stage gets its own specification before it is built.

The recorder — poll open investigations, diff docket listings, stamp first-seen times —
is pulled forward ahead of the agent.

## Why

1. **The recorder has a hard clock on it and nothing else does.** The spike established
   that evidence-arrival timing cannot be reconstructed afterwards: the API deletes
   preliminary text when a case closes, docket listings carry no per-document dates, and
   the server's `Last-Modified` header reflects caching rather than authorship. Every week
   it is not running is a week of timeline that can never be recovered.
2. It depends on the docket client and a table, not on the agent, so it does not have to
   wait for one.
3. **Scoring before the thing being scored.** S1 precedes S3 so the agent is never tuned
   against a moving target, and so the harness proves itself by reproducing a number that
   is already known before it is trusted to judge one that is not.

## What this rules out

- **Strict dependency order.** Simpler to follow and finishes the agent sooner, at the
  cost of months of unrecoverable evidence timeline.
- **Deploying the whole live pipeline early to start collecting.** Gets the same data but
  requires the agent, the predictions store and the hosting stack to exist first —
  which is the delay being avoided.

## Status

Accepted. See `docs/specs/2026-09-12-architecture-and-roadmap.md` §11.
