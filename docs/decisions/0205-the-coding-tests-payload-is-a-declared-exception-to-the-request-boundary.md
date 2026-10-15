# 0205 — The coding test's payload is a declared exception to the request boundary

From Andy, 2026-10-15. Detail: `docs/specs/2026-10-08-coding-memory-design.md` §6.

## Context

1. **The request side of the leakage guard sends only evidence.** `model/client.py`'s `Payload`
   is built from evidence or from one page, and nothing else
   ([0016](0016-layered-leakage-guard-and-model-boundary.md)).
2. **The coding test needs a verdict sentence.** [0204](0204-the-coding-test-and-the-pilots-stop-rule.md)
   has GPT-6 Luna code a case from the NTSB's probable-cause sentence. That sentence is verdict
   text, and `Payload` cannot carry it.
3. **The other way in is a workaround.** The sentence could go in the system text, beside a dummy
   payload. The boundary would still pass, and nothing would show that verdict text had gone out.

## Decision

1. **`Payload.for_coding_test(cause: str)`** renders `{"ntsb_probable_cause": cause}` and nothing
   else.
2. **Only `scripts/memory_coding_test.py` calls it.** A test scans every Python file under
   `src/`, `apps/` and `scripts/` for the name, and fails if any other file uses it.
3. **This amends 0016 for this one role.** [0200](0200-a-model-may-read-development-verdicts-to-learn-coding-lessons.md)
   item 2 is its authority: the coding test may read the steering slice's verdicts.
4. **The honest limit.** The caller test is a text search. Code that reached the method by a
   roundabout route, for example by building the name from a string, would pass it. That is the
   same strength as the project's other boundary tests, and review is the backstop.

## Why

1. **A named door is visible and testable.** A reader can search for it, and the test names the
   one file that may use it.
2. **A workaround in system text would pass the boundary silently.** Nothing would record that a
   verdict had been sent.

## What this rules out

- **The sentence in the system text beside a dummy payload.** Rejected: it hides the exception
  (Why 2).
- **Running the coding test on Claude.** It would not need the door. Rejected: 0204 chose the
  product's model, so that the test measures what the product will do.

## Status

Accepted; amends 0016 for the coding test only. Approved by Andy, 2026-10-15.
