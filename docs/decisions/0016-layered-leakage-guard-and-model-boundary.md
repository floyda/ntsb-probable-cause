# 0016 — A layered leakage guard, and a request-side model boundary with a recording fake

## Context

`CLAUDE.md` rule 1: evidence and withheld fields are separated in one function with an
assertion, never by convention. The spike's `assert_no_answer_fields()` checked only that no
answer *role name* was a key in the evidence dictionary. Its own assembler writes only
evidence names, so the check could not fail: it would miss an evidence role pointed at an
answer path, or answer text copied into an evidence value. S0's definition of done
requires a test that fails when withheld content is smuggled in.

A first design also compared analysis sentences of 40 characters or more against the
payload. That length was a guess. Measured on the development split, analysis sentences
appear verbatim in the factual narrative in 7,793 cases (M5): the check would have stopped
more than half the corpus. 0013 then withheld the factual narrative, which removes that
overlap from the payload entirely. Detail: `docs/specs/2026-09-13-s0-foundation-design.md`
§7–8.

## Decision

`records/split.py` holds `split_record(raw, *, exclude) -> (Evidence, Synthesis, Verdict)`,
the only place a record is split. The guard has five layers:

0. **Allow-list** — evidence reads only declared paths.
1. **Keys** — `Evidence` has a fixed schema, no extra attributes.
2. **Paths** — no evidence path lies under a withheld subtree (factual, analysis and
   probable-cause narratives, `events[]`, `findings[]`, `richNarratives`). One named
   exception: `phase_of_flight` reads the defining event.
3. **Provenance** — a boundary test checks every payload value equals the value at its
   declared raw path.
4. **Tripwire** — no synthesis or verdict text, whole or by sentence, and no occurrence or
   finding code as a whole token, may appear in the payload; raises `LeakageError` (fail
   closed). Known boilerplate ("this report was modified on …") is excluded. The minimum
   sentence length is the lowest with zero hits in `scripts/corpus_scan.py` over the whole
   corpus; the scan writes it, with its other counts, to `docs/results/s0-corpus-scan.txt`,
   and the guard reads that value from a constant that cites the file.

The model boundary is request-side only: `Payload` (built only from `Evidence`, without
`case_id` or `docket_url`), a `ModelClient` Protocol, a provisional text-only `ModelReply`,
and a `RecordingFakeClient` that keeps every payload. import-linter forbids `model` from
importing synthesis or verdict. A mutation test proves the boundary test fails when
`split_record()` leaks.

## Why

1. **Each layer catches a route the others miss.** Keys catch a name; paths catch a
   mis-pointed role; provenance catches a value from the wrong place; the tripwire catches
   copied content by any route.
2. **The guard targets mechanical leakage only.** Evidence that makes a cause obvious is a
   property of the NTSB's text; it is measured and reported, not used as a runtime check.
   A runtime check built on a similarity threshold would let a tuning choice define evidence.
3. **The `phase_of_flight` exception is justified and visible.** Open cases carry the coded
   event sequence from day 1, so a live agent has it; the spike's ablation found it worth at
   most 2.5 points. Being a named entry, a second exception cannot be added silently.
4. **Numbers, not guesses, set the tripwire.** The 40-character guess was wrong by a wide
   margin before measurement.
5. **The response side waits for a real response.** Rule 2: usage, cost and tool-call shapes
   come from S1's saved OpenRouter probe. The fake is built now because S1 harness tests, S3's
   cost cap and abstain path, and a key-free continuous integration all depend on it.
6. **Case number and docket URL stay out of the payload.** Both are exact handles to a
   published report a model may have seen in training; the case number also encodes the
   investigation class (93.1% of F-class and 0.0% of C-class development cases are fatal,
   M4). Docket documents print the case number, so this removes a free handle rather than
   solving memorisation, which S1 and S3 measure. The aircraft registration is also a
   handle; it stays in the payload and is ablated in S1.

## What this rules out

- **Port the spike's check as-is, with a test.** Most faithful to "carry over as-is". The test
  would have to plant a forbidden key directly to fail, so it proves almost nothing.
- **Types and a path check, without a runtime tripwire.** Simpler, with no false-positive risk.
  Rejected because a splitter bug that copies text would pass.
- **A sentence-similarity check against analysis text.** Rejected on the measurement above.
- **The full response interface now, from OpenRouter's documentation.** S1 would only add a
  client, but at the risk of reshaping types after the probe.

## Status

Accepted, 2026-09-13.
