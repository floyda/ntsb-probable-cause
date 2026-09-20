# 0051 — The document header drops the provenance clause and states readability instead

Supersedes [0038](0038-docket-documents-are-evidence-by-case-level-authorship.md) item 2, which
introduced the clause. Narrows [0048](0048-arm-b-ranks-by-each-documents-measured-size.md)
item 4, which fixed the clause's five-word vocabulary and set the hand-check that measured it.

## Context

Every docket document attached as evidence carries a header this project writes:

> **Examination or site report**, **11 pages**, *written by the investigation.*

The first part is a label, inferred from the document's title. The second is a fact from the
listing. The third — the **provenance clause** — is an inference about *whose account the
document is*, in one of five phrasings: written by the investigation, submitted by a party,
produced by someone independent, recorded at the time, or not stated.

0038 item 2 added it so the agent could weigh a party's self-serving submission differently from
an independent report, as a human investigator does. The clause was never measured against
anything until now.

**The hand-check measured it** (`tests/fixtures/docket/title_handcheck.filled.csv`,
`docs/results/s2-handcheck.txt`, `scripts/score_handcheck.py`). Andy marked 60 stratified titles
with whose account each document carries, using the same five-word vocabulary the clause uses:

- **The clause agreed on 32 of 55 rows — 58%.** Under every more generous reading of the
  category-to-word mapping, agreement lands between 58% and 72%.
- **Five categories agreed perfectly** (5/5): party submissions, weather, medical and toxicology,
  conversation records, manuals and references.
- **Two agreed zero times out of five**: photographs, and specialist factual reports.
- **The word `recorded` failed outright.** It was used 7 times in 60, and never once in the two
  categories built around it. Its single appearance in `atc_radar_data` was the row the marking
  instructions had supplied as the worked example.

**A caveat on that measurement, stated because it bears on how much weight it carries.** The
mapping from category to expected word was derived from the committed label table, which predates
the marks, but the deriving was done after seeing them. It is reconstructible by anyone from
`attach.py`, and the sensitivity analysis above is the honest range. It is not pre-registered.

## Decision

1. **The provenance clause is removed.** `_LABELS` in `docket/attach.py` maps a category to a
   label only. The five-word vocabulary and its prose phrasings go with it.
2. **The header states what was readable instead** — measured per document, not inferred:
   - every page readable: `Examination or site report, 11 pages.`
   - partly readable: `Examination or site report, 11 pages, of which 4 held readable text.`
3. **The label and the page count stay.** The hand-check graded three things and the label was
   not one of them. No measurement supports removing it, so it is not removed here.
4. The hand-check's `author` column, and the vocabulary 0048 item 4 fixed, are now historical.
   The sheet stays committed: it is the evidence for this record.
5. **A divergence found while writing this record, and recorded rather than quietly kept.**
   0038 item 2 specified the header as "title, the document type from the listing, page count,
   and the author's role where the listing gives it". The implementation has never carried the
   title or the document type: it carries a *category label* inferred from the title. Nothing
   recorded that substitution at the time. It is ratified here, on the grounds in Why item 1 --
   the agent is given the whole listing, so every title and document type is already in front of
   it, and repeating them per document would be duplication. The label is what the listing does
   not supply.

## Why

1. **Redundant where it is right, wrong where it is needed.** The agent is already given the
   whole docket listing, every title included (`listing.render_listing`). Where a title is
   explicit — `Party Submission - Lycoming Engines` — the clause repeats what the model can read
   for itself, and agreement is perfect. Where the title is not explicit, the clause is a guess,
   and the guess is unreliable.
2. **It is the only place a misclassification puts words in front of the model.** Every other use
   of the category reorders or drops a document. Telling the agent that a party's submission was
   "written by the investigation" is worse than telling it nothing, because this project wrote it
   and it reads as authoritative.
3. **What replaces it is measured, not inferred.** `readable_pages` against `pages` is computed
   from the extraction. It tells the agent how much of the document it is actually seeing, which
   is information it cannot get from the listing, and it is the per-document number a later OCR
   or vision arm would be compared against.
4. **A wrong provenance label is a confound in the arm B measurement.** If arm B underperforms, a
   clause that is wrong on a quarter to two-fifths of documents is an alternative explanation
   nobody can rule out afterwards.

## What this rules out

- **Keeping the clause only for the five categories that scored 5/5.** Rejected: five rows per
  category is far too few. 5/5 on five rows is consistent with being right only about half the
  time, so choosing which categories keep a clause on that basis is fitting the design to noise.
- **Re-mapping which categories claim `recorded`** to match where Andy used it (logbooks and
  maintenance excerpts). Rejected for the same reason, and it would be fitting the vocabulary to
  60 marks rather than to any principle.
- **Raising the sample and re-measuring the clause.** Not rejected on the merits, but not done:
  it costs Andy another marking session to defend a component whose best case is "redundant where
  it works". If the agent is later shown to need provenance, this can be revisited with a bigger
  sheet.
- **Removing the category label too.** Rejected: ungraded. The hand-check measured the photograph
  exclusion, the deny-list and the clause. The label was not among them, and removing it would be
  a change with no measurement behind it — the thing this record exists to object to.

## Open, deliberately

Whether the agent *needs* provenance at all is untested. It can be tested: run arm B on
`dev-400` with and without the clause and compare. That doubles task 17's cost, from about $3
to about $6. Andy has the choice; this record does not pre-empt it. If it is run, the result
supersedes this decision either way.

## Status

Accepted, 2026-09-20 (Andy: "I think we should drop provenance").
