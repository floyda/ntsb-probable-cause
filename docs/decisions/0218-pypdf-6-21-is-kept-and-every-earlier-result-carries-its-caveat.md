# 0218 — pypdf 6.21 is kept, and every earlier result carries its caveat

Andy, 2026-11-03, after the measurement below. Amends
[0047](0047-pypdf-extracts-docket-text-no-ocr.md) item 1 (the version floor); changes no
result already recorded.

## Context

1. **pypdf extracts the text of every docket document the agent reads** (decision 0047). Every
   result that read a docket, from S2 to the live nights, read text from **pypdf 6.19.0**: the lock
   held that version from the first docket commit (2026-09-18) to 2026-11-02.
2. **Pull request #41 (2026-11-02) moved pypdf to 6.21.4** to clear the 18 advisories that
   pip-audit reported against 6.19.0, failing CI on `main` and on every open pull request. Each
   advisory is a crafted PDF that makes pypdf loop without end, use a great deal of memory or run
   for a long time; one (CVE-2026-113786) makes it call any installed image decoder. None leaks
   data. The live night parses public PDFs on AWS, and a memory failure is what stopped it from
   2026-10-22 (decision 0217).
3. **#41 recorded no check that the text was unchanged.** This record's measurement is that check,
   made after the merge: `make pypdf-text-check`
   (`scripts/exploratory/pypdf_text_check.py`, `docs/results/pypdf-text-dev.txt`), on `dev-400`'s
   docket cache, offline, with no model call. It reads each case as `CachedDocketReader` does
   (arm B and the loop) under each version, then attaches every readable document and splits the
   case as `scripts/docket_leak_scan.py` does.
4. **What it found**, of 3,790 listed documents in 401 cases:

   | Under 6.21.4 the document's text is | Documents | Cases |
   |---|---|---|
   | identical | 2,045 | 340 |
   | the same characters in the same order, with spaces and line breaks in other places | 561 | 271 |
   | different characters | 2 | 2 |
   | read, where 6.19.0 could not open the file | 3 | 3 |
   | not read by either version (scans, photographs and the like) | 1,179 | 307 |

   - **Examples of the layout change**, from the two versions' texts compared by hand (Claude,
     2026-11-02, development cases; the committed script counts the classes, not the kinds): a
     weather report's continuation line is now joined to the line before it; a form's row of tick
     boxes is split across two lines; a space is inserted or removed inside a word, as in
     `Mod el:`.
   - **The two documents with different characters** are French-language reports by a foreign
     authority. Read by hand (Claude, 2026-11-02, development cases): 6.19.0 wrote the font's
     name for a non-breaking space, `/uni00A0`, into the text (`300/uni00A0km/h`); 6.21.4 writes
     a space (`300 km/h`). It also splits some headings (`A NALYSE`), and one line drawn in a
     font with no character map comes out as symbols.
   - **The classifier:** 4 documents change status, all of them files 6.19.0 could not open.
     Three are now read, one page each. The fourth is a scan, and remains unread. No page crosses
     the 50-character readable line (decision 0053).
   - **The split:** the same 2 cases are refused by the guard under both versions, and the other
     399 pass under both. Case marks and the narrative-coverage share are the same in all 399.
     **The docket text the agent would be sent differs in 270 of the 399.**
5. **The text a run is sent is not covered by Ellery version 1's label.** The `+t` fingerprint
   (decision 0161) covers the model-facing text the loop builds from invented inputs, not the
   library that reads a document. The docket hashes of decisions 0176 and 0185 are hashes of the
   document files, so they do not move.

## Decision

1. **pypdf 6.21.4 is kept.** `pyproject.toml` raises the floor to `pypdf[crypto]>=6.21.4`, so the
   lock cannot fall back to an affected version.
2. **Every result recorded before 2026-11-02 stands as recorded, with this caveat:** where the
   run read docket text, it read pypdf 6.19.0's text. That is every arm B and arm C run, every
   S2 to S3.3 development and held-out reading built on them, and every live night up to the
   first night on an image built after #41. Arm A, the one-shot ceiling and the no-model baseline
   read no docket, and the coding memory's coding test reads only the NTSB's cause sentence, so
   none of them is affected. No result is re-run, and no results file is
   edited.
3. **A comparison across the change says so.** A paired reading between a run on 6.19.0 and a run
   on 6.21.4 or later names this record beside its numbers. A run's commit identifies its
   version through `uv.lock`, so nothing more needs recording on the run.
4. **Ellery stays version 1.** The live board's nights after the next deploy read 6.21.4's text;
   the agent, its prompts and its settings are unchanged.

## Why

1. **The advisories matter here.** The night reads public files from a source this project does
   not control, unattended, on a task with a fixed memory limit. A file that loops or fills
   memory stops the queue behind it, as one large scan did for eleven days (0217).
2. **The change is layout, not content.** In 2,606 of the 2,608 documents read by both versions,
   the text holds the same characters in the same order. What moved is where lines break and
   where spaces fall. Nothing the guard decides, nothing the classifier decides about a document
   both versions read, and no case mark changed.
3. **It is small against the noise already measured (judgement, not measured).** Two identical
   loop runs on `dev-400` change the first occurrence code on 162 of 387 cases
   (`docs/results/s3-noise-floor-dev.txt`). A model reading the same words broken into lines
   differently is expected to vary well inside that. The size of the effect on scores has not
   been measured, and this record does not claim it is zero.
4. **Re-running every result costs more than the caveat is worth.** S2 to S3.2's paid runs, and
   the held-out gates that closed after use (`docs/rounds/s3-2-used.md`), cannot be repeated as
   they were, and `heldout-400` can no longer test a later version (decision 0153).

## What this rules out

- **Pinning pypdf at 6.19.0 and waiving its advisories.** It keeps the evidence exactly as
  measured, but leaves the night open to the failures the advisories describe.
- **Re-running the recorded results on 6.21.4.** See Why 4.
- **Treating a later pypdf upgrade as routine.** A version change in the extractor is a change in
  the evidence. The next one is measured with `make pypdf-text-check` (`PYPDF_OLD` set to the
  version it replaces) before it merges, and recorded.

## Status

Accepted.
