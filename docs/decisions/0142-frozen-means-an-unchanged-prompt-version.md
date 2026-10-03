# 0142 — "Frozen" means an unchanged prompt version, held by a test

From the S3.2 design session (2026-10-03): frozen, option A. Applies
[0139](0139-s31-tuning-closes-without-a-registered-round.md) item 2 and relies on
[0133](0133-unreadable-dockets-are-listed-and-the-text-is-fingerprinted.md)'s fingerprint.
Detail: [the S3.2 specification](../specs/2026-10-03-s3-2-claims-design.md) §4.1, §4.3 and §4.4.

## Context

- 0139 froze the loop at `fd6053f`, prompt version `s3-v1+ge17fecdc66ec+p947fac1c86a4`. S3.2
  compares the coding ablation with the noise-floor runs, and the held-out loop with every
  `dev-400` reading. Those comparisons are like for like only if the model sees exactly the same
  text.
- The `+p` part of the prompt version is a fingerprint of the source of ten files and of the
  tool definitions as sent (`agent/texts.py:TEXT_SOURCES`, `agent_text_sha256`; 0133). Any edit
  to those files, a comment included, changes it.
- The S3 specification's "Known issues carried to S3.2" lists defects. Some sit in fingerprinted
  files and some do not. A held-out run is made once, so a defect that a once-only run cannot
  carry has to be fixed first.
- Held-out arm B needs two of its parts, the tool post-pass and the ordering check, to accept a
  held-out run. Today both refuse every held-out run (`scoring/checkpass.py:_refuse_unless_development`,
  called from `agent/armb.py`'s `preflight`).

## Decision

1. **Frozen means the loop's prompt version is unchanged.** A test asserts that it is
   `s3-v1+ge17fecdc66ec+p947fac1c86a4`, so the rule is held in code and not by this sentence.
2. **S3.2 edits none of the ten fingerprinted files**: `scoring/prompt.py`,
   `scoring/hypothesis.py`, `scoring/codes.py`, and `agent/` `texts.py`, `steps.py`, `tools.py`,
   `schemas.py`, `later.py`, `loop.py`, `armb.py`. Not even a comment.
3. **A dependency update that changes the tool definitions as sent** waits until S3.2 closes
   (for example, a `pydantic` release that writes the schemas differently). The test would fail
   on it.
4. **Fixed before held-out, outside the fingerprint:**

   | fix | why now |
   |---|---|
   | A resumed round that was partly answered (`agent/drive.py`): a call with no reply is sent again and costs its case no attempt | Today it counts as one of the case's two attempts. If the laptop sleeps during the held-out loop run, a dozen cases could fail on resume that would have answered. |
   | A completed round the provider reports as cancelled (`agent/drive.py`): the run continues | Today it stops the run, and one more resume continues it. It is the same code as the fix above. |
   | An unreadable `spec.json` (`apps/eval/__main__.py`): a report refuses it | Today it reads as "no ablation". S3.2 runs two ablations, and a report must not label one the plain loop. |
   | Two tests: `month_spent` with a dead round that reported a cost; the temperature each call sends, pinned | The first protects the spend count (0135); the second protects the setting of 0.0 the claims assume. |

5. **Arm B's tool post-pass and ordering check accept one registered held-out run**, in
   `scoring/checkpass.py` and `apps/eval/__main__.py`. They accept it only after S3.2's
   registration is committed, each appends a held-out ledger row and refuses an uncommitted
   tree (0026), as `ntsb-eval run` does, and each refuses a second pass or check on the same
   run. If this cannot be done without editing `agent/armb.py`, work stops and Andy decides.
6. **Left as they are, each with its reason:**

   | left | reason |
   |---|---|
   | The room held at a read choice does not count the documents about to be read (`loop.py`) | In a fingerprinted file. The cap still holds; the $0.30 cap ([0144](0144-one-per-case-cap-for-every-arm.md)) guards against it. |
   | A case forced to answer at H0 still gets the listing in its refinement (`loop.py`) | In a fingerprinted file. It cannot happen at that cap. |
   | The coding step catches every exception (`loop.py`) | In a fingerprinted file. Broad, but it has worked; changing it changes the label. |
   | Arm B's post-pass: its over-budget refusal comes after the dockets are read; its `+tools-<name>` label is not checked against the statistics; one refusal's wording (`armb.py`) | In a fingerprinted file. Ordering and wording only. |
   | Arm C's `spec.json` also holds arm B's `prompt_version` beside `agent_prompt_version` | Cosmetic. Changing the file's keys would break the key-for-key comparison with the noise-floor runs. |
   | `scripts/reply_budget.py` misreading arm C; the precedent probes' pool by event date; `make s3-miss-kinds` overwriting its results file; `AgentCall.offered=()` before 0134 | S3.2 does not use them. The noise-floor runs postdate 0134. |

   The last known issue, the noise pair never read under
   [0136](0136-s3-rounds-count-failed-cases-as-wrong.md)'s rule, is not a bug. S3.2 reads it
   ([0146](0146-the-headline-test-and-failed-cases.md)).

## Why

1. **One label makes every comparison like for like.** The coding ablation and the held-out loop
   are read beside runs made under the same text.
2. **A test holds the rule.** A sentence in a document can be forgotten. A failing test cannot.
3. **The fixes are the ones a once-only run cannot do without.** Held-out is touched rarely and
   each run is recorded in a ledger. A resume that fails cases wrongly cannot be repeated.
4. **What is left is left because fixing it would change the label.** Each item is ordering,
   wording or a path that does not arise at this cap, and each is written down.

## What this rules out

- **Running held-out from `fd6053f` unchanged.** The strongest case: the label never moves, and
  nothing needs editing. Rejected: the post-pass refuses held-out at that commit, so arm B could
  not be completed, and the resume defect stays in a once-only run.
- **Fixing `loop.py` and `armb.py` under a new label.** It would remove the remaining defects.
  Rejected: the dev-400 readings and the noise floor were made under the old label, so the
  comparisons would no longer be like for like. The loop would need its noise floor again, which
  is tuning, and 0139 closed that.
- **Editing a fingerprinted file for a comment or a tidy.** Rejected: any edit moves the label
  (0133).

## Status

Accepted, 2026-10-03 (Andy, S3.2 design session; specification approved 2026-10-03).

## Glossary

- **Fingerprint (`+p`)**: a short hash of the source of the files that build the text the model
  sees. An unchanged hash means unchanged source.
- **Frozen**: the model sees exactly the same text as in the noise-floor runs.
- **Post-pass**: arm B's coding tools and answer, or its ordering check, run over a finished arm
  B run (0127).
- **Prompt version**: the label each run records for what elicited its answers.
