# 0044 — The amateur-built replacement applies to document text, in the attach step, counted as a floor

Extends 0020 from record fields to docket text. Written with the S2 specification (§6.4).

## Context

0020 replaces the make and model of an amateur-built aircraft with the label `Amateur-built`
in evidence, because the recorded make is usually the builder's name and the builder is often
the pilot. Docket documents name the builder in prose: maintenance records, examination
reports, the pilot's form. 0037 says no scripted redaction of free text is reliable enough to
trust unread; but here the strings to find are known from the record.

## Decision

1. For an amateur-built aircraft, the attach step (0041) replaces every case-insensitive
   occurrence of the record's make and model strings in listing titles and document text
   with `Amateur-built`, before the split runs.
2. The number of replacements per case goes in the manifest; the count by document type is
   published with the development shape numbers.
3. The count is a floor: a variant spelling, an initial or a bare surname passes through, and
   the results file says so.

## Why

1. **The strings are known**, so the replacement is mechanical and testable, unlike free-text
   name scrubbing.
2. **The header and the text agree.** A header that hides the name above text that shows it
   protects nothing.
3. **It sits in the one slot for changes to document text**, so any later name handling
   joins it rather than adding a second place.

## What this rules out

- **Applying 0020 to the provenance header only.** The model reads the name a line below.
- **Withholding documents from amateur-built cases.** Removes the docket on exactly the cases
  whose mechanical causes are most varied.
- **Claiming the replacement is complete.** It is a floor, stated as one.

## Status

Accepted, 2026-09-18 (Andy).
