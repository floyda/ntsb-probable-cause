# 0066 — The recorder fetches with the docket client's cache off and keeps its own copies

## Context

S2's `DocketClient` caches `listing.html` per case and replays it for ever: the only re-fetch
is a missing file or a hash mismatch. That is right for closed dockets and S2's As-built named
it the precondition for this stage — a recorder using the cache would compare a listing with
itself every night and never see a change. The client already supports `cache_dir=None`:
fetch, use, discard, added for the open-split shape measurement (0040).

## Decision

The recorder constructs the docket client with `cache_dir=None`. Each poll fetches the live
page; the recorder stores what it needs in its own store (0063). The evaluation cache and the
client's caching code are unchanged. The client's only job for the recorder is fetching, with
its rate limit and retries.

## Why

1. **No open-split page enters the evaluation cache**, which 0024 wants.
2. **Nothing changes for the evaluation runs.** No expiry rule, no re-fetching of closed
   dockets already held.
3. **The recorder needs its own copies anyway** (0063), so a refreshed cache would duplicate
   them and, being historyless, would still lose the previous night's page on overwrite.

## What this rules out

- **An expiry time on the client's cache.** Every user of the client would carry a rule only
  the recorder needs, and the evaluation cache would start re-fetching dockets it already has.
- **A `refresh` flag on the client.** Simple, but the refreshed page overwrites the cached one
  and the cache keeps no history.

## Status

Accepted, 2026-09-22.
