# 0183 — Make and model may appear in prose; the registration is replaced

From the S4 Task 11 review, 2026-10-11, with Andy. Narrows item 3 of
[0173](0173-the-board-export-format-board-1.md) (what the export never holds) and adds to
[0182](0182-names-on-the-board-after-the-measurement.md). Detail: the S4 specification, §10.2.

## Context

1. **0173 item 3 lists "a make or model" among what the export never holds.** The export's fields
   obey it: the board shows an aircraft's category, engine count and engine type, never a make or
   model (`board/1` `Aircraft`).
2. **Ellery's prose quotes the evidence it reads**, and version 1's evidence holds the make, the
   model and the registration. The Task 11 review found the case's own make in the accounts or
   causes of 268 of `dev-400`'s 401 cases, and the registration in 1. These are the reviewer's
   counts, from an uncommitted probe, not a scripted result.
3. **On amateur-built aircraft the make and model usually name the builder**, and the evidence
   already holds the label `Amateur-built` instead
   ([0020](0020-amateur-built-make-and-model-replaced-in-evidence.md)). The review found no
   amateur-built make in the prose.
4. **The registration leads to an owner's name** in the public aircraft register, often the pilot who
   died (S5 specification §12, item 11). The title rule cannot catch it: it looks for capitalised
   words, and an N-number is all capitals.

## Decision

1. **The export's fields hold no make, model or registration** (0173 item 3, unchanged for fields).
2. **Prose may name the make and model.** Prose here means Ellery's text, the coding lookups' free-text
   arguments and the NTSB's cause statement.
3. **The case's own registration is replaced with `[name]`** in prose and in document titles, as
   the owner and operator strings are (0182 item 1).

## Why

1. **Andy (2026-10-11)**: chose "A: allow in prose".
2. **A certified aircraft's make names a manufacturer, not a person**, and the builder's name is
   already removed upstream (0020).
3. **Replacing make and model would cost readability** for no gain in respect: "the [make] [model]
   lost power".
4. **The registration is the one identifier that leads to a person**, so it is replaced wherever it
   appears.

## What this rules out

- **Replacing the case's make and model in prose.** Offered and not chosen.
- **Leaving the registration in prose.** Rejected: it leads to the owner's name.

## Status

Accepted, 2026-10-11 (Andy: "A: allow in prose").
