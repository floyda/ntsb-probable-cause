# 0134 — A read choice tolerates decisions on documents not on offer, and skips them

From Andy, 2026-10-01, after the first paid smoke run of the S3.1 loop (arm C). Detail: the S3.1
plan's Deviations (`docs/plans/2026-09-30-s3-1-agent-loop.md`). This amends
[the S3 specification](../specs/2026-09-30-s3-agent-loop-design.md) §5.2, "Code checks that each
is on offer".

## Context

1. **The rule.** At a read choice the agent calls `choose_documents` with one decision, read or
   skip, for each document on offer. Only listed documents that can be read and were not read
   yet are on offer (spec §4.2). Until now the code refused the whole call when it held a
   decision on any other document.
2. **The smoke run.** Run `20261001T115444-5890033-dev-400-C`: one `dev-400` case, finished,
   $0.0057 in all (its `run.jsonl`). Its `trail.jsonl` shows 13 calls, 2 of them refused:
   - First read choice: the docket listed 11 documents; 4 could be read and were on offer. The
     model decided on all 11. Refused: "not offered [1, 5, 6, 7, 8, 9, 10]", the 7 documents
     that cannot be read.
   - Second look: the model decided again on the 3 documents it had read, and on the 1 on
     offer. Refused: "not offered [2, 3, 4]".
   - Both passed on the retry. The two refused calls cost $0.000621.
3. **The instruction and the check disagreed.** The fixed instructions say "Choose read or skip
   for every document listed above." and "... for every document listed." The listing shows
   every document, readable or not, and the menu names those already read and those that cannot
   be read. The model did what the text asked, and the code refused it.
4. **What a refusal costs.** A refused call is answered, and its step is sent again. On batch,
   each retry is a whole round: the shape probe's batch calls took 89 seconds to 59 minutes (the
   plan's Deviations, Task 4). A second refusal fails the case, and that counts against the
   format gate ([0130](0130-the-loops-noise-floor-and-format-gate.md): at most 8 of 401 cases).

## Decision

1. **A decision on a document not on offer no longer refuses the call.** Such a decision is an
   *extra*, of one of three kinds:
   - `not_readable`: the document is listed, but it cannot be read;
   - `already_read`: the document was read at an earlier choice, or on an earlier trigger;
   - `unknown`: no listed document has that number.

   `parse_call` (`agent/schemas.py`) returns a `DocumentChoice` for `choose_documents`: the
   arguments as the model sent them, the decisions on offered documents, and the extras, each
   document once.
2. **Every offered document must still be decided exactly once.** A missing or repeated decision
   on an offered document still refuses the call. That choice is the agency being measured.
3. **An extra is skipped, and the model is told.** It is never read, whatever the model asked.
   After the read summary, the tool result holds one fixed line for each extra, by listing index
   only, never a title (`agent/texts.py`):
   - "Document [5] cannot be read; skipped."
   - "Document [2] was already read; skipped."
   - "There is no document [14]; skipped."

   Every extra gets its line, whether its decision was read or skip.
4. **The trail.** Each extra counts as one argument error on its call, as an unknown code does in
   a coding tool. The call's `arguments` keep the decisions as the model sent them, and its
   `protocol_error` stays empty. The read record (`ReadRecord.decisions`) holds the offered
   decisions only, so "read", "skipped", a later trigger's summary and what is built from them
   stay about offered documents. The trail row of a read choice also records the documents on
   offer at that step (`AgentCall.offered`), since the read records are not written to disk.
5. **The noise floor** (`scripts/s3_noise_floor.py`) counts read-or-skip agreement on offered
   documents only: it reads a decision only for a document its row names as offered.
6. **The instructions stay as they are.** Deciding on every listed document is now valid. No
   other text the model sees changes. The prompt version's `+p` changes by itself
   ([0133](0133-unreadable-dockets-are-listed-and-the-text-is-fingerprinted.md)).

## Why

1. **A slip is not a choice** (Andy: "Could we tolerate extras or even tolerate and then respond
   saying they are either not available and have been skipped? … hopefully the model should
   default to skip"). A decision on a document that cannot be read, or was read already, changes
   nothing the agent can do. It is not worth a round.
2. **Time and cost.** A refusal costs one more call and, on batch, a round of up to an hour. The
   instruction invites the slip, so it may recur in many of the 401 cases. This is judgement:
   one case gives no rate.
3. **The format gate measures format.** The gate catches a loop that cannot keep to its protocol.
   A case failed for doing what the instruction asked would count against the loop for the wrong
   reason.
4. **What is measured is kept.** A decision on each offered document is still required, exactly
   once. The extras are counted in the trail, so how often the model makes them can be reported.

## What this rules out

- **Fix the wording only, and keep the strict check.** Say "every document on offer" instead of
  "every document listed", and refuse extras as before. The instruction and the check would
  agree, with less code. Rejected by Andy's question: why refuse rather than default to skip? The
  wording lowers the rate of slips but does not stop them, and each one left still costs a round
  and can fail a case.
- **Leave it as it is.** Rejected: every slip costs a whole batch round, and a failed retry fails
  the case and counts against the format gate, although the model did what the text asked.
- **Tolerate the extras without answering them** (the first form of Andy's question). The result
  would be shorter. Rejected: the model would not learn that the document was not read, or why;
  the second form tells it.

## Status

Accepted, 2026-10-01 (Andy, after the S3.1 smoke run).

## Glossary

- **Batch round**: one set of calls sent together at half price. Its replies can take up to an
  hour.
- **Extra**: a decision, in a read choice, on a document that was not on offer.
- **Format gate**: at most 2% of cases (8 of 401) may fail for format or tool reasons on each
  noise-floor run (0130).
- **Offered document**: a listed document that can be read and has not been read yet.
- **Read choice**: the step where the agent decides, for each offered document, whether to read
  it (`choose_documents`).
