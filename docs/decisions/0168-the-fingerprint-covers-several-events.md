# 0168 — The fingerprint covers several events; version 1 is re-pinned

From the S4 design session with Andy, 2026-10-10. Amends
[0161](0161-the-rendered-text-fingerprint-and-the-version-1-check.md) (what `+t` is shown to
cover). Detail: the S4 specification, §3.1.

## Context

1. **`+t` fingerprints the text the loop sends over invented inputs** (`agent/rendered.py`), so a
   live run can refuse anything that is not version 1 (0161).
2. **`fields.py` chooses which event of a record the model reads**, by `isDefiningEvent` and
   `sequenceNumber`. The invented record has a single event, so an edit to that choice would
   change what Ellery reads without moving `+t`. S3.3 carried this to S4 (S3.3 As-built, "Known
   issues carried to S4"). `fields.py` is unchanged since `fd6053f` (ad-hoc, `git diff`, empty).
3. **Decision [0143](0143-the-fingerprint-should-cover-what-the-agent-receives.md) moved the
   fingerprint off source hashes**, because a comment edit moved them.

## Decision

1. `agent/rendered.py` gains a second invented record with several events, out of sequence order,
   exactly one of them defining.
2. `VERSION_1` is pinned again to the new `+t`, and continuity is shown on `fd6053f`'s code with
   `make s33-continuity`, before any cloud night.
3. The mutation sweep gains an edit to each selection key, which must move `+t`.
4. 0161 and `docs/results/s33-fingerprint-continuity.txt` get dated notes; the S3.3
   specification's "it cannot miss a text" becomes "it covers the cases its invented inputs
   exercise".

## Why

1. **It keeps 0143's rule**: the fingerprint covers what the agent receives, not the source.
2. **It costs no model call**: the rendered text is computed offline, about half a day's work.
3. **The live board is about to be public.** The label must mean what it says before S4 locks
   results under it.

## What this rules out

- **Pinning `fields.py`'s source hash.** Simple and exact. Rejected: it is the source-hash approach
  0143 left, and a comment edit would refuse every live night.
- **Leaving it to version 2**, as S3.3 proposed. No work now. Rejected: S4 publishes under
  version 1's label, and the gap is cheap to close.

## Status

Accepted, 2026-10-10 (Andy: "ok fine lets go with B").

## Glossary

- **`+t`**: the part of the prompt version that fingerprints the rendered model-facing text.
- **Continuity**: the same `+t` computed on `fd6053f`'s code and on the current tree.
