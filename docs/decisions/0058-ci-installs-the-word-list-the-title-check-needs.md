# 0058 — Continuous integration installs the word list the title check needs

## Context

`scripts/check_fixtures_redacted.py` refuses to let a committed docket fixture carry a name.
Its title check (decision 0046, replacing the old trigger-word heuristic) asks whether each
capitalised word in a title is an *ordinary* word: it tests membership of the committed
vocabulary `vocab/title_words.txt` — every capitalised word found in five or more distinct
cached dockets — **plus the system word list at `/usr/share/dict/words`, when the machine has
one** (`docket/title_vocab.py:known_title_words`). A word in neither is very likely a proper
noun specific to one case, and on a `.csv` sheet that finding is blocking (0049).

macOS ships `/usr/share/dict/words`. `ubuntu-latest`, which every CI job runs on, does not.

`known_title_words` reports a missing word list to stderr rather than passing over it in
silence, and the code's comment argued that running on the committed vocabulary alone "only
makes it stricter — a common word not yet in the vocabulary is a false positive, never a
missed name". That reasoning is sound about *safety* and wrong about *usability*. Measured on
the committed fixtures at close-out:

| word list | findings | blocking |
|---|---|---|
| `/usr/share/dict/words` present | 8 | 0 |
| absent | 196 | 158 |

So every CI job that ran the check failed on 158 false positives. **Continuous integration had
been red since 2026-09-19**, the commit that added the six docket fixtures and the hand-check
sheet, and stayed red through eight commits — invisible to a developer working on macOS, where
the same command passes. It was found at the S2 close-out, while confirming the stage's tenth
done-means ("continuous integration is green"), which was on its way to being recorded as met.

## Decision

1. The `lint` and `test` jobs install a word list (`wamerican`) before running anything that
   invokes the check, so CI and a developer machine test titles against the same vocabulary.
2. The missing-word-list message says plainly that the blocking findings printed under it are
   mostly false positives, gives the measured figures, and names the package to install. A
   warning nobody acts on for two days is not a warning.

No change to what the check flags, to the committed vocabulary, or to decision 0049's rule
that a `.html` listing is advisory and everything else blocking.

## Why

1. **A guard whose strictness depends on the machine is not a guard.** The same fixtures
   passed on one operating system and produced 158 blocking findings on another. Whichever
   answer is right, they cannot both be.
2. **"Stricter" is only safe if someone can still read the output.** 158 false positives hide
   the one true finding as effectively as no check at all, and in practice the run is simply
   ignored or the check disabled.
3. **The cheapest fix that removes the divergence.** The word list is a build input, not a
   result, and installing it changes no published number.

## What this rules out

- **Treating an absent word list as a safe, stricter mode.** It is a broken mode and now says
  so.
- **Making `.csv` findings advisory to get CI green.** That would weaken the one check standing
  between a real surname and a committed fixture, to work around an environment problem.
- **Lowering `MIN_DOCKETS` so the committed vocabulary alone suffices.** Five dockets is a
  measured threshold; loosening it to paper over a missing dictionary would quietly admit
  proper nouns as ordinary words.

## Deferred, and recommended

**Vendoring a word list into the repository** would make the check fully deterministic on every
machine, with no system dependency and no apt step — the same reasoning decision 0047 used to
reject a system-binary PDF extractor, that the environment should not be part of the result.
It was not taken here because it adds a large committed file with its own licence question, and
because a stage close-out is the wrong moment to choose one. Recorded for Andy as the better
long-term fix.

## Status

Accepted, 2026-09-21 (S2 close-out).

Amended by 0070 (2026-09-22): the word list is vendored into the repository and the CI install step is removed.
