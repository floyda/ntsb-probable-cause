# 0143 — The fingerprint should cover what the agent receives, and is rebuilt in S3.3

From the S3.2 design session (2026-10-03): Andy's view, option 2. To be amended by this record's
own build in S3.3: [0133](0133-unreadable-dockets-are-listed-and-the-text-is-fingerprinted.md)'s
`+p` is replaced then, and a dated note on 0133 says so. Detail:
[the S3.2 specification](../specs/2026-10-03-s3-2-claims-design.md) §4.2 and §16 (record 3).

## Context

- 0133 made the prompt version fingerprint **the source** of every module that composes
  model-facing text. Any edit to those files, a comment or a refactor included, changes the
  label though the model sees the same words. 0133 accepted those false changes as the safe
  side.
- S3.2 is frozen on that label ([0142](0142-frozen-means-an-unchanged-prompt-version.md)). The
  cost is visible there: any tidy of a fingerprinted file, a comment included, would move the
  label though the model's input stayed the same.
- Andy's view, in his words (spelling corrected, as 0121 does): "the fingerprint should have
  probably been anything the agent sees … source file changes and updates to Pydantic really
  shouldn't be causing a change in fingerprint".
- S3.3 is where the loop's text is next likely to change. S4 is where the label becomes public
  and predictions lock against it.

## Decision

1. **The principle:** the fingerprint covers what the agent receives, not the source that builds
   it.
2. **The method, built in S3.3:** render every fixed text the loop can send from a fixed set of
   made-up inputs, and hash the output. The texts are the system text, the tool definitions,
   each step's instruction, the menus, the tool-result wording, the refusal lines and a later
   trigger's opening.
3. **The risk and its defence.** The one risk is a text built on a path the made-up inputs never
   reach. The defence is a mutation test: change each text-building string in turn, and check
   that the hash moves or a test fails.
4. **It is built in S3.3, before S4 locks any prediction.** S3.2 touches none of the
   fingerprinted files, so nothing in S3.2 needs it.
5. **Continuity is shown then.** The new fingerprint is computed on `fd6053f`'s code and on
   S3.3's code, and the two must match.
6. **Until then,** a `pydantic` update changes the current label only when it changes the tool
   definitions as sent, which is when it changes what the model sees. Such an update waits
   until S3.2 closes (0142 item 3).
7. **0133 is amended when this is built**, not now. This record states the principle; 0133
   stays as it is until the new fingerprint exists.

## Why

1. **A label should move when the model's input moves.** Otherwise it reports edits, not
   behaviour, and a reader cannot tell a real change from a tidy.
2. **S4 is the deadline.** Once predictions are locked against a label, a false change would
   break the link between a prediction and the agent that made it, or tempt someone to ignore a
   changed label.
3. **S3.3 is the natural place.** It is where text is next likely to change, and the structured
   effect field of [0148](0148-results-one-and-four-made-measurable.md) arrives with it.

## What this rules out

- **Building it in S3.2.** The strongest case: Andy's view is right today, and the old
  fingerprint blocks harmless tidy-ups in S3.2. Rejected: it takes about a day, and nothing in
  S3.2 needs it. S3.2 edits none of the ten files, so the old fingerprint costs it nothing.
- **Keeping the source fingerprint for good.** It cannot miss a text. Rejected as the final
  state: its false changes are the cost, which 0133 accepted as the safe side.

## Status

Accepted, 2026-10-03 (Andy, S3.2 design session; specification approved 2026-10-03).

## Glossary

- **Fingerprint (`+p`)**: a short code computed from what builds, or is, the text the model sees.
- **Made-up inputs**: a fixed, invented set of case data, used only to render the texts.
- **Mutation test**: a test that changes the code on purpose and checks that something fails,
  to prove the check can fail (0016).
- **Prompt version**: the label each run records for what elicited its answers.
