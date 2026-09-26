# 0070 — The word list is vendored into the repository

## Context

`scripts/check_fixtures_redacted.py` tests capitalised words in fixture titles against the
committed vocabulary plus the system word list at `/usr/share/dict/words`. macOS has the
list and the CI runner does not, which turned 0 blocking findings into 158 and left CI red
for two days during S2. Decision 0058 installed the list in CI and recorded that vendoring
a copy into the repository would be the better fix, leaving the choice to Andy.

## Decision

A copy of the word list is committed under `tests/fixtures/words.txt` (about 2.5 MB) and the
check reads that copy on every machine. The CI install step from 0058 is removed. The
warning 0058 made unmissable stays, for the case where the vendored file is missing.

## Why

1. **Local and CI run the identical check.** That is the property 0058 wanted and could only
   approximate: the CI install depends on whatever list Ubuntu ships that day.
2. **It is done while CI is already open** for the recorder's image build job, so it costs
   least here.

## What this rules out

- **Keeping the CI install.** Two machines running slightly different checks, which is how
  the last problem hid.
- **Leaving it for later.** Works today; the same risk stays.

## Status

Accepted, 2026-09-22. Amends 0058.
