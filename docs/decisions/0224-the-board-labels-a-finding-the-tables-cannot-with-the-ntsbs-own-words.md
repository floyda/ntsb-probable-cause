# 0224. The board labels a finding the tables cannot with the NTSB's own words

Amends [0173](0173-the-board-export-format-board-1.md) (how a label in `board/1` is made) and
narrows [0105](0105-codes-missing-from-the-dictionary-join-the-tables.md) item 5 for display only.
The code tables the model chooses from are unchanged.

## Context

A case the NTSB closed on 2026-11-20 carries the finding `0102000027`. Its item, `01020000`
("Aircraft — Aircraft systems — (general) — (general)"), is in the code tables. Its modifier,
`27`, is not: 0105 item 5 left modifiers 27 and 98 and item `01011100` out of the tables. S4's
export labels a code it cannot label from the tables with the bare code
(`live/board.py:_finding_code`), so the case page showed "0102000027" with no words. A site test
expected every finding label to have a detail part. The morning builds of 2026-11-20 and
2026-11-21 failed that test and published nothing, so the board stayed at 19 November. Pull
request #71 corrected the test. This record is about the label itself.

The NTSB's record gives a description beside every finding code (`findingDescription`). For
example, `Aircraft-Aircraft systems-(general)-(general)-Not installed/available - F`. All 44
development-split findings with modifier 27 end "Not installed/available". The export read only
the codes and dropped those words.

The obvious fix, a row for modifier 27 in `scoring/tables/supplement.csv`, does not work. The
tables are shown to the model. `agent/rendered.py` reads them, so a new row would change version
1's `+t` fingerprint, and every live night refuses any label other than `VERSION_1` (0161, 0169).

## Decision

1. **The split carries the NTSB's words.** `fields.finding_descriptions(raw)` reads each
   finding's `findingDescription`, in the order of `finding_codes`. `split_record` puts it in
   `Verdict.finding_descriptions`. The verdict never reaches a model (0013), and the guard and
   the case marks read nothing new. The export reads the words only through the split, as it
   reads the codes.
2. **The tables come first.** `_finding_code` labels a code in this order:
   - item and modifier in the tables: the tables' label, as before;
   - item in the tables, modifier not: the tables' item, then " - ", then the last part of the
     NTSB's description. Example: "Aircraft — Aircraft systems — (general) — (general) - Not
     installed/available";
   - item not in the tables: the NTSB's whole description, without its final " - C" or " - F"
     (cause or factor). It is not split further;
   - no description either: the bare code, as before.
3. **A later score keeps the words too.** `LaterScore` gains `verdict_finding_descriptions`,
   with a default of empty, so rows written before this record still read. For such a row, the
   description of the record saved at coding fills the gap.
4. **The `board/1` format is unchanged.** A label is still one string.
5. **Only labels change.** Rebuilt from the bucket on 2026-11-21 with this code, the export
   differs from that night's export in two places only: one finding of one case, given in two
   lists. No other byte of the 190 case files differs, and no case now shows a bare code.

## Why

1. **The words are the NTSB's own.** They come from the same record and the same split as the
   codes, not from any person's labelling. This is the same source 0105 took its six labels
   from.
2. **Version 1 stays version 1.** The model's tables and prompt are unchanged, the fingerprint
   is unchanged (`s3-v1+ge17fecdc66ec+tdff9dea78f23`), and a live night accepts the new image.
3. **It covers codes the NTSB adds later.** A hand-kept list would need an edit, a review and a
   deploy for each new code. It would also fail the morning build again before anyone noticed.
4. **The whole description is not split** because the NTSB joins its levels with bare hyphens,
   and some names hold one too ("Low-alt flying"). A split could cut a name in two. No modifier
   label in the tables holds a hyphen, so the last part after the final hyphen is safe.

## What this rules out

- **Adding modifier 27 or item `01011100` to the code tables.** That would move version 1's
  fingerprint and stop the live nights. It would also change what the model may choose, which
  is a version 2 question.
- **A hand-kept list of display labels.** See Why item 3.
- **Splitting the NTSB's description into area and item.** See Why item 4.
- **Reading the record outside `split_record`.** The verdict roles are read in one place only
  (rule 1).

## Status

Accepted, 2026-11-21 (Andy: "yes, go ahead", to the design put to him that day).
