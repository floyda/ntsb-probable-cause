# 0049 — The line on names is the public surface, not the repository

Taken 2026-09-19 after the title name-check was built and measured. Andy's ruling: *"as long as
these names don't make it into the demo page we are dealing with public data anyway."*

**Supersedes two parts of [0037](0037-docket-fixtures-from-development-dockets-only.md)**,
named here because Andy asked the right question — does this amend older decisions? It does, and a
decision that quietly makes an earlier one's stated reason false is exactly what the append-only
rule exists to prevent:

1. **0037 item 2 says the listing page "holds no personal text".** That is now measured false.
   Document titles carry personal names: real surnames of pilots, instructors and witnesses were
   found in the first hand-check sheet drawn, and 367 of 401 cached listings carry at least one
   word the title check cannot vouch for. The *conclusion* of 0037 item 2 — commit the page as
   received — stands, and this decision reaffirms it. Its *reason* does not, and is replaced by the
   reason in item 1 below: the page is already published by the NTSB, so storing a copy withholds
   nothing.
2. **0037's context says "rule 6 forbids victim names in any output, which a public repository
   is".** This decision narrows that. A repository storing a byte-exact copy of a public NTSB page
   is not this project speaking; the live board, a published results file and a prediction row are.
   `CLAUDE.md` rule 6 is unchanged and absolute — what changes is where "output" is understood to
   begin, and item 2 below draws that line.

Also extends [0020](0020-amateur-built-make-and-model-replaced-in-evidence.md),
[0044](0044-amateur-built-replacement-applies-to-document-text.md) and
[0046](0046-known-owner-and-operator-names-are-replaced-in-document-text.md), and settles where the
check built for 0046 applies. It does not touch
[0015](0015-fixtures-redacted-real-dev-records.md): owner and operator fields are
still stripped from every record fixture.

## Context

A check was added that flags a capitalised word in a document title appearing in neither a
committed vocabulary of NTSB title words nor an ordinary dictionary — measured as a good signal for
a proper noun specific to one case. It works: it found real surnames of pilots, instructors and
witnesses in the first hand-check sheet drawn, before that sheet reached a public repository.

Applied to whole docket listing pages it is far stricter than intended. Measured over all 401
development dockets:

- **34 of 401 listings (8%) carry no flagged word at all.**
- Most carry two to four flagged titles out of a typical seven documents.
- **None of the 9 dockets holding a party submission is clean**, so a fixture criterion that needs
  one can never be satisfied.

Requiring a clean listing would therefore have drawn the fixture pool from the least representative
8% of the corpus and left two of six docket shapes untested — a real cost to the parser's test
coverage, paid to withhold names the NTSB itself already publishes on a public web page.

## Decision

1. **A docket listing page is committed as received, names included.** It is an already-public NTSB
   page; decision 0037's byte-exactness is what makes it a valid fixture, and filtering which pages
   may be committed by their titles costs test coverage without withholding anything.
2. **The line is the public surface this project itself produces.** No personal name may appear in
   the live board, in a published results file, in a prediction row, or in any output this project
   generates. That is where the guard belongs, and it is absolute.
3. **The title check becomes advisory for listing pages and stays blocking elsewhere**: for the
   hand-check sheet and any other artefact this project authors, and for committed document text,
   where 0037's human read remains the gate.
4. **The hand-check sheet stays redacted** (0048 item 4). It is not a public NTSB page but a
   document this project wrote, so item 2 applies to it.
5. **Document text and PDFs are unchanged**: 0037 item 3 governs, and Andy's ruling of the same day stands
   that the documents he reads for the fixture pool come from a non-fatal case.

## Why

1. **It puts the guard where the harm is.** A surname in a fixture inside a source repository is the
   same surname the NTSB publishes on its own website. A surname on a demonstration page about a
   fatal accident is this project putting it there. Only the second is ours to prevent.
2. **The measured cost of the strict rule was too high for what it bought.** 92% of the corpus
   excluded, two docket shapes untestable, to duplicate a public page's own reticence.
3. **It keeps the check honest rather than deleting it.** The check found real surnames within
   minutes of existing. Advisory where the data is already public, blocking where this project is
   the author, is the distinction that keeps it worth reading.
4. **It names the obligation the live board must meet** before that board exists, rather than after.

## What this rules out

- **Filtering which docket listings may be committed by whether their titles carry names.** Measured
  as costly and unhelpful; the page is public either way.
- **Treating "it is public data" as a reason to relax the output side.** Item 2 is not weakened by
  item 1. The project's own surfaces stay clean regardless of where the name came from.
- **Deleting the title check.** It stays, and stays blocking for everything this project authors.

## Status

Accepted, 2026-09-19 (Andy).
