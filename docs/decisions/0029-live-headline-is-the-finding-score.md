# 0029 — The live board's headline is the finding score

## Context

The occurrence code is read from the coded defining event, which open cases often carry
from day 1 (roadmap §13, S0 specification §2.4). On a live case, "the agent predicted the
occurrence code" could therefore mean it read something already public. The finding codes,
the NTSB's "why", appear only at closure. The roadmap left the live headline to S1.

## Decision

1. On the live board, the headline score is the finding score at closure: ten-digit
   precision and recall against the findings the NTSB flagged as in the probable cause
   (0025).
2. Occurrence top-1 is shown beside it, labelled "often public early".
3. Held-out tables show both scores, so the live and held-out numbers are comparable, and
   the two are never mixed in one figure (agency design §7.2).

## Why

1. **A headline should measure what was not public.** The finding codes are the part of the
   verdict that only closure provides.
2. **Comparability.** Showing both on both boards lets a reader see the same two columns
   everywhere.

## What this rules out

- **Occurrence top-1 as the live headline.** Would credit the agent for reading the
  defining event.
- **A composite score.** Would hide which part was public.

## Status

Accepted.
