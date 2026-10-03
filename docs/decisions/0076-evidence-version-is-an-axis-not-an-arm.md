# 0076 — Evidence version is an axis, not an arm

Extends [0022](0022-loop-must-beat-call-every-tool-arm.md).

## Context

S2.6 widens what the docket holds once read: transcriptions of words in images, and, in a
probe, the pictures themselves. Andy asked whether that makes a new arm. The arms of 0022 differ
in *how* evidence is gathered — start facts only (A), every tool once (B), the loop (C). A wider
docket changes *what* is gathered, for every arm alike.

## Decision

1. The docket as the agent receives it has a **version**: v1 = text layers (S2); v2 = v1 plus
   transcriptions (S2.6); v3 = v2 plus photographs and diagrams as images, alongside the text
   (S2.6, probe only). Any arm can run on any version.
2. Every run records its version beside its commit, model and arm. A run from before S2.6 reads
   as v1.
3. `ntsb-eval report` refuses to compare runs on different versions, except through an explicit
   flag that prints the comparison under an "evidence-version comparison" heading.
4. The held-out ledger records the version. The S2 bar stays as written, read as "B, v1".

## Why

1. **Equal evidence by structure, not care.** A "B with images" arm would let a later reader
   compare C-with-images against plain B. A recorded version and a refusing report make that
   comparison impossible by accident.
2. **Two claims stay apart.** *Wider reading helps* is B on one version against B on another;
   *choosing helps* is C against B on one version.
3. **Nothing is overwritten.** Every earlier number stays citable under its version.

## What this rules out

- **A new arm per widening.** Rejected for reason 1; it also multiplies arms without adding a
  new way of gathering.
- **Silently replacing arm B's definition.** Rejected: the S2 bar would change meaning after it
  was published.

## Status

Accepted, 2026-09-23 (Andy: "Yes ok another axis or version of Arm B").
