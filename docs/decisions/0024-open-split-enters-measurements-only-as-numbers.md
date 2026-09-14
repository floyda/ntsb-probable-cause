# 0024 — Open-split cases enter a measurement only as numbers

## Context

Repository rule 5 fixes three splits by event date: development up to 2019, held-out
2020–2023, and open from 2024. Open cases feed the live board only. They are the control for
memorisation: no training set can contain an investigation that is still open, and the board
scores the agent on them when the NTSB publishes.

Two measurements the agency design needs can come only from the open split:

- **Docket shape from 2020 on.** The spike measured dockets from 2015–2019 only
  (`scripts/docket_shape_probe.py`). S0's corpus scan (`docs/results/s0-corpus-scan.txt`)
  shows the class mix changed: C-class cases are 6,126 of 13,560 development cases and 0 of
  the 1,840 closed open-split cases. The held-out years stay untouched, so the closed
  open-split cases are the only ones from the current era that can be measured.
- **Evidence arrival.** The masked condition (0023) needs to know when fields, preliminary
  narratives and docket documents appear on ongoing cases. Only the recorder (S2.5) can see
  that.

S0's corpus scan already reads the open split and writes counts only, with no case numbers and
no text.

## Decision

1. A measurement may include open-split cases, closed or ongoing, only if what it stores is
   numbers: counts, distributions and summary statistics, with no case numbers and no text.
   No raw data from those cases is kept by the measurement: no cached documents, no extracted
   text, no per-case rows.
2. S2's docket-shape measurement may use closed open-split cases under item 1. Documents are
   read and discarded; they never enter the docket client's cache.
3. The recorder's store serves the live board. The masked condition takes from it only
   numbers: how many days after the event each kind of evidence first appears. Preliminary
   narratives and other text the recorder captures never enter an evaluation, a fixture or
   development work.
4. Statistics the live board shows about the agent's own runs (0021) are published, and are
   never used to choose a threshold, a filter or a prompt.
5. Rule 5 in `CLAUDE.md` cites this record.

## Why

1. **Nothing readable remains, so nothing can leak.** A distribution of page counts cannot
   carry a case's evidence or verdict into development or evaluation work. A cached document
   or a per-case row can.
2. **It keeps the live board a clean control.** If open-split text reached development work,
   the board could no longer show how the agent does on cases it was not shaped by.
3. **The design's era problem needs current-era numbers.** Without this, predictions and arm
   B's document filter rest on 2015–2019 dockets alone, while the cases that are evaluated and
   shown on the board come from a different era.
4. **It follows a precedent that already works.** The S0 corpus scan reads every split and
   keeps counts only.

## What this rules out

- **The open split closed to every measurement.** The strictest reading of rule 5. Rejected
  because docket shape and evidence arrival from the current era could then never be measured.
- **Closed open-split cases as extra development data.** More data for the filter and the
  threshold. Rejected by reason 2.
- **Per-case numeric rows** (for example, case number and page count). Easier to audit.
  Rejected because a case number is a handle back to the record and its verdict.
- **Captured preliminary narratives in the masked condition.** They would make the masked
  condition more realistic. Rejected because it is raw live text inside an evaluation. The
  masked condition states that it lacks them.

## Status

Accepted on Andy's squash merge of the pull request that carries the agency design revision,
2026-09-14.
