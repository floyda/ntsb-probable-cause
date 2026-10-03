# 0133 — Arm C sees the listing of an unreadable docket; its prompt version fingerprints the text

From Andy, 2026-10-01, at the S3.1 final review. Detail: the S3.1 plan's Deviations
(`docs/plans/2026-09-30-s3-1-agent-loop.md`) and
[the S3 specification](../specs/2026-09-30-s3-agent-loop-design.md) §4.2, §9 and §10.3.

## Context

1. **A docket with nothing readable.**
   - The loop (arm C) offers only the documents whose text extraction found text (spec §4.2).
   - When a docket listed documents but none could be read (scans, fetches that failed, files
     that are not PDFs), the loop dropped the docket. It sent no listing, and it told the
     model "No docket documents are available for this case."
   - That sentence was false: the docket exists and lists documents.
   - Arm B's payload always holds the listing with its titles, whatever it attaches
     (`scoring/runner.py`, `prepare_case`). On such a case arm C was shown less than arm B,
     against [0074](0074-words-in-images-are-read-in-the-build.md) (arm B and the loop read equal
  evidence).
   - At most 22 of the 401 `dev-400` cases are of this kind.
     `docs/results/s2-narrative-coverage.txt` skipped 22 cases for "no cached docket, no
     readable document, or a code hit", and a docket with no readable document is among those.
2. **A prompt version built from labels.**
   - The S3.1 plan recorded arm C's prompt version as `s3-v1+g<guidance fingerprint>`, with
     `+r<N>` for a tuning round.
   - A kept round that changes the protocol, a tool's wording or a tool description stays in
     the code. Later plain runs would then carry the same version as the noise-floor runs made
     on the old text, so two different prompts would share one label.

## Decision

1. **Arm C sees the listing of a docket whose documents cannot be read.**
   - The loop keeps the docket whenever its listing holds at least one document.
   - H0's tool result is the listing (through `split_record` and the guard, as for any
     docket), then the menu's not-readable lines, then "None of the documents listed can be
     read.", and then the move to coding.
   - "No docket documents are available for this case." stays for a case with no docket, or
     with a docket that lists nothing.
   - The refinement shows the listing as well, as arm B's payload does.
   - The docket state is "none" only when nothing is listed. The state describes arrival, not
     readability (spec §9). This holds in arm C and in arm B's tool post-pass.
2. **The prompt version fingerprints the text.**
   - Arm C's prompt version is `s3-v1+g<12>+p<12>`, plus `+r<N>` for a tuning round.
   - `+p` is the first twelve hexadecimal characters of `texts.agent_text_sha256()`. That is a
     SHA-256 over the source files of every module that holds or composes the text the agent
     sends (`texts.TEXT_SOURCES`): `scoring/prompt.py`, `scoring/hypothesis.py`,
     `scoring/codes.py`, and `agent/` `texts.py`, `steps.py`, `tools.py`, `schemas.py`,
     `later.py`, `loop.py` and `armb.py`. The files are read as package files. The tool
     definitions and the refinement schema are hashed too, as they are sent.
   - Any edit to those files changes the version, a comment included.
   - The retry line "Your previous reply was rejected: " is now one constant,
     `prompt.REJECTED`. Every caller uses it, and the bytes sent are unchanged.
   - Arm B's tool post-pass carries the same fingerprint in its label:
     `<source>+tools-s3+p<12>`.
   - Not covered:
     - the code tables and the statistics, which are data that the commit SHA and `spec.json`
       name;
     - the guidance, which has its own fingerprint, `+g`;
     - the evidence, its rendering and the transport, which are the same for every arm and
       are named by the commit SHA and the evidence version.
   - `resolve_latest` still takes a run with S3's guidance and no `+r` as plain arm C, whatever
     its `+p`.

## Why

1. **Equal evidence (0074).** The arms are compared on what they choose to do, not on what
   they are shown. Arm B shows the listing, so arm C must show it too.
2. **The sentence was false.** "No docket documents are available" told the model something
   untrue about the case.
3. **The version follows the text automatically, so no run can be mislabelled** (Andy). A
   version bumped by hand depends on someone remembering to bump it; a fingerprint does not.
4. **A false change costs less than a false match.** Hashing whole files changes the version
   on edits that leave the text as it was, such as a comment. That only separates runs that
   were in fact alike, and they still share a commit to show it. A version that stays the same
   over a change of text would merge two different prompts. The noise-floor rule
   ([0130](0130-the-loops-noise-floor-and-format-gate.md)) would then compare unlike runs as if
   they were alike.

## What this rules out

- **Keep the flow and fix the wording only.** The loop would say that the docket lists
  documents and none can be read, but would not send the listing. This is less to change, and
  the sentence becomes true. Rejected: arm C would still see less than arm B (no titles), so the
  two arms would not read equal evidence.
- **Bump the version by hand.** Each round that changes text would bump a number in the code.
  This is simple and easy to read. Rejected: it depends on memory. One missed bump mislabels
  every run after it, and nothing would catch it.
- **Fingerprint the fixed strings only.** This hashes the constants and their rendered
  templates, not the files; it was the first form of this decision, on 2026-10-01. It gives
  fewer false changes. Rejected: it missed text written in other modules (the tools' result
  wording, the prompt's headings, the retry line), so a round could change the text without
  changing the version.

## Status

Accepted, 2026-10-01 (Andy, S3.1 final review).

## Glossary

- **Docket listing**: the docket's table of documents, with each document's title, page count
  and type. It is evidence, and goes through the split and the guard.
- **Fingerprint**: a short hash of some text. If the text changes, the fingerprint changes.
- **H0**: the agent's hypothesis before it reads any document.
- **Prompt version**: the label each run records for what elicited its answers.
- **Tuning round**: a registered change to the loop's text or limits, kept or dropped by its
  result against the noise floor (0130).

**To be amended by [0143](0143-the-fingerprint-should-cover-what-the-agent-receives.md) in S3.3
(appended 2026-10-03; nothing above is edited).** The `+p` fingerprint of source is to be replaced
by a hash of the rendered text the agent receives. This record stands until then.
