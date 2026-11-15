# 0184 — Names in document titles: exact parts and the title rule, the limit published

From the S4 final review, 2026-10-12, with Andy. Extends
[0182](0182-names-on-the-board-after-the-measurement.md) item 2 and
[0183](0183-make-and-model-in-prose-registration-replaced.md) item 3. Detail: the S4 specification,
§12.2.

## Context

1. **The board shows each docket document's title**, and titles are where witness names most often
   appear (for example, a statement titled with the witness's name).
2. **The title rule** replaces a capitalised word that is in neither the title vocabulary nor the
   word list (0180 item 1). The final review found that it keeps a name made only of ordinary
   words. A test export built from invented records kept "Witness statement - John Smith"
   unchanged, because "John" and "Smith" are both in the word list.
3. **The exact parts were applied to titles only in part.** Titles had the registration replaced but
   not the owner and operator strings, and only the first aircraft's registration was used.
4. Three choices were put to Andy:
   - A: titles kept, with the exact parts, the title rule and a published limit;
   - B: the document's kind shown instead of its title;
   - C: a strict title vocabulary, measured first.

## Decision

1. **Titles have the case's exact parts replaced first**: the owner and operator strings and every
   aircraft's registration, matched without regard to case, as in prose.
2. **Then the title rule runs**, as before.
3. **The limit is published**: a name the rules cannot recognise is not replaced. In prose, that is
   any name other than the owner, operator and registration. In titles, it is also a name made only
   of ordinary words, such as a common surname or given name. A registration shorter than three
   characters is not replaced, because it would also match tokens such as "N1".

## Why

1. **Andy (2026-10-12)**: "I thought we have already tried B, I assume A matches what we have done
   elsewhere so would be my preference, don't want C".
2. **A matches prose** (0182): exact parts plus a stated limit, with no guessing beyond the title
   rule that already existed.
3. **The exact parts cost nothing in readability**, and the owner is often the pilot who died.

## What this rules out

- **The document's kind instead of its title (B).** It would remove the risk. Not chosen.
- **A strict title vocabulary (C).** Not chosen.

## Status

Accepted, 2026-10-12 (Andy: A).
