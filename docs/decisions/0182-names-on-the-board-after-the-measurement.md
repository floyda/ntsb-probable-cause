# 0182 — Names on the board, after the measurement: exact parts only

From S4 Task 4, 2026-10-11, with Andy. Replaces item 2 of
[0180](0180-names-on-the-board.md) (the case's own flagged title words replaced in Ellery's text and
the NTSB's cause statement). 0180's items 1, 3 and 5 stand. Detail: the S4 specification, §12.2.

## Context

1. **0180 item 4 fixed a rule before the measurement ran**: if no case's text holds a flagged word
   outside the rule, the rule stands; otherwise Andy chooses.
2. **The measurement** (`docs/results/s4-names-dev.txt`, `scripts/s4_names_probe.py`, the two
   `dev-400` arm C noise-floor runs, 401 cases) found flagged words outside the rule in seven kinds
   of text. These are the cases holding at least one:

   | Text | Cases |
   |---|---|
   | Ellery's accounts of the evidence | 246 |
   | read-choice reasons | 182 |
   | cause statements | 150 |
   | the NTSB's cause statement | 70 |
   | coding-lookup expected effects | 55 |
   | document notes | 50 |
   | coding-lookup reasons | 34 |

   So by the fixed rule, Andy chose.
3. **A flagged word is not a name.** The probe uses the rule's own detector: a capitalised word not
   in the word list. A private reading of the flagged words, not committed and not a scripted count,
   found them to be almost all ordinary words the list holds only in another form ("Witnesses",
   "Contributing", "Prioritize"), aircraft makers, places and medicines. Only a handful could be
   surnames.
4. **The task review found a seventh kind of text** that reaches the board: the free-text `reason`
   and `expected_effect` arguments of the coding lookups (`board/1` `Lookup.arguments`).

## Decision

1. **No word-guessing on prose.** Ellery's text (cause statements, accounts of the evidence, document
   notes, read-choice reasons, the coding lookups' free-text arguments) and the NTSB's cause
   statement have only the case's owner and operator strings replaced with `[name]`, by
   `docket/attach.py`'s rule ([0046](0046-known-owner-and-operator-names-are-replaced-in-document-text.md)).
2. **Titles keep the title rule** (0180 item 1): a capitalised word in neither the title vocabulary
   nor the word list becomes `[name]`.
3. **The limit is published** (0180 item 5): a name that appears only in a document's text, and not
   in a title or the owner and operator fields, is not removed. The Methods page says so, and the S4
   report counts the replaced words as a floor.

## Why

1. **Andy (2026-10-11)**: "I'm tempted to just not attempt this I don't think like it will add much,
   more likely to make the text unreadable". Asked whether this meant no names step at all or the
   exact parts only, he chose "Exact parts only".
2. **The exact parts cost no readability.** Owner and operator strings matched one case in each kind
   of text on `dev-400`, and the owner is often the pilot who died. Titles are short labels, where
   witness names most often appear.
3. **Guessing on prose would mostly replace ordinary words, makers and places**, by the measurement
   and the reading in context 3. Even 0180's narrower guess replaces a maker named in a title, such
   as "Robinson", wherever the prose names it.

## What this rules out

- **The full title rule on prose.** Safest against names. Rejected: most cause sentences open with
  "Contributing", which it would replace, along with makers and places.
- **0180 item 2's per-case title words in prose.** Rejected for the same reason, on a smaller scale.
- **Leaving the accounts of the evidence empty.** Rejected: S5 would have none to show.
- **No names step at all.** Offered and not chosen. It would set aside 0049 item 2 for the board.

## Status

Accepted, 2026-10-11 (Andy: "Exact parts only").

## Extended, 2026-10-12 (appended; nothing above is edited)

- Item 2 (titles keep the title rule) is extended by [0184](0184-names-in-document-titles.md): titles first have the case's exact parts replaced (owner and operator strings and every registration, any case), then the title rule runs. Item 1 (prose has only the exact parts replaced) gained the registration in [0183](0183-make-and-model-in-prose-registration-replaced.md).

## Note, 2026-10-12 (appended; nothing above is edited): two slips in the record, corrected

Source for both: `docs/results/s4-names-dev.txt` (from `scripts/s4_names_probe.py`).

- Why item 2 says the owner and operator strings "matched one case in each kind of text". The results file shows count (2) is 1 in five kinds (`cause`, `account`, `note`, `lookup_effect`, `ntsb_cause`) and 0 in the other three (`reason`, `lookup_reason`, `lookup_arg`). The reasoning stands, because the strings are rare in prose, but "each kind" was wrong.
- Context item 4 says the review "found a seventh kind of text" (the coding lookups' free-text arguments). The results file has eight kinds, and the lookups are three of them (`lookup_reason`, `lookup_effect`, `lookup_arg`). The table in context item 2 lists the seven kinds whose count (3) is above zero, and it already holds two lookup rows (expected effects 55, reasons 34). So the lookups were counted, not a later addition; the review's finding was that `Lookup.arguments` reaches the board and needs the names step, and `lookup_arg` is 0 in count (3).
