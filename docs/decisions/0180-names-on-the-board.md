# 0180 — Names on the board

From the S4 design session with Andy, 2026-10-10. Applies
[0049](0049-the-name-line-is-the-public-surface-not-the-repository.md) item 2 to the board. Detail:
the S4 specification, §12.2.

## Context

1. **No personal name may appear in any output this project produces** (0049 item 2, absolute).
2. **Three kinds of text reach the board** and can hold a name: document titles, Ellery's text
   (cause statements, notes and accounts of the evidence), and the NTSB's cause statement. The
   accounts are the longest, and summarise documents that name people.
3. **Two tools exist**: the title rule (`docket/title_vocab.py`, a capitalised word in neither the
   title vocabulary nor the word list), and the owner and operator replacement of
   [0046](0046-known-owner-and-operator-names-are-replaced-in-document-text.md). The word list is
   `tests/fixtures/words.txt`, which the image does not hold.

## Decision

1. **Titles**: words the title rule flags are replaced with `[name]`.
2. **Ellery's text and the NTSB's cause statement**: the words flagged in that case's own titles, and
   the owner and operator strings, are replaced.
3. **The word list ships in the package**, and the title check moves into the library.
4. **A free measurement first**, on `dev-400`'s two arm C noise-floor runs, counts only
   (`docs/results/s4-names-dev.txt`): how many cases' texts hold a word flagged in their own titles,
   and how many hold any flagged word, each kind of text apart. If none holds a flagged word outside
   the rule, the rule stands; if any does, Andy chooses between the full rule on Ellery's text and a
   published limit, and for the accounts also between those and leaving the field empty until a
   stronger rule exists.
5. **The limit is published**, and the count of words replaced is reported as a floor.

## Why

1. **Names are removed out of respect**: the owner is often the pilot who died.
2. **The full rule on free text would replace brand, place and aircraft names** and make cause
   statements hard to read; the measurement shows whether that is needed.

## What this rules out

- **The full title rule on every text, now.** Safest. Deferred to the measurement: it may cost
  readability for nothing.
- **No rule on Ellery's text.** Rejected: Ellery reads documents that name people.

## Status

Accepted, 2026-10-10 (Andy: "A").

## Replaced in part and extended, 2026-10-12 (appended; nothing above is edited)

- Item 2 (Ellery's text and the NTSB's cause statement have the case's own flagged title words and the owner and operator strings replaced) is replaced by [0182](0182-names-on-the-board-after-the-measurement.md) item 1: prose has only the owner and operator strings replaced (and, from [0183](0183-make-and-model-in-prose-registration-replaced.md), the registration).
- Item 1 (titles: flagged words replaced with `[name]`) is extended by [0184](0184-names-in-document-titles.md): the case's exact parts (owner and operator strings, every registration) are replaced first, then the title rule runs, and the limit is published.
- Items 3, 4 and 5 stand; item 5's "count of words replaced as a floor" is now the limit sentence in `live/names.py` (`NAMES_LIMIT`), printed by the S4 report.
