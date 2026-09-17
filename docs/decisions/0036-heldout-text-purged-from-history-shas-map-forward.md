# 0036 — Withheld held-out text is purged from git history; the runs' recorded SHAs map forward

Applies 0013 and 0016 to the repository's history rather than only its working tree, and
qualifies 0018's "every evaluation run records the commit SHA that produced it" for the
commits this purge rewrote.

## Context

S1's final whole-branch review found that `tests/fixtures/eval/decidability_full.csv` and
`tests/fixtures/eval/leakage_full.csv` were committed in full. Between them they held, for
cases verified to be **held-out by event date, all 70 of them**:

- the NTSB's probable cause and finding codes for 40 cases — **verdict** (0013);
- the investigator's factual account, verbatim, for 30 cases — **synthesis** (0013).

The 40 are `heldout-40` itself: the like-for-like sample a bar was measured on the same
morning the review ran. The answer sheet to our own exam was in the repository.

They were guarded by one sentence in a README promising the columns "never enter a payload".
Decision 0016 exists to forbid exactly that: the boundary is held in code, never by
convention. The redaction check that should have caught them globbed `*.json` and never
looked at a CSV. Nothing ever read the files — `conftest.py` loads `*_ids.csv` only, and the
comment claiming the full sheets were "read by name where they are needed" described an
intention that was never implemented.

Deleting them from the working tree, which commit `45b3723` did, does not remove them: stage
pull requests keep their commits (0033), so both files would merge onto `main` and stay
retrievable with `git show` by anyone who clones the repository.

## Decision

1. Both files are purged from this branch's history with `git filter-branch --index-filter`,
   not merely deleted. Nothing else in any commit is altered: only those two paths are
   removed from each tree.
2. `scripts/check_fixtures_redacted.py` reads fixture **CSV headers** as well as fixture
   JSON, and fails on any column carrying synthesis or verdict, matched case- and
   separator-insensitively. `scripts/copy_eval_ids.py` no longer produces the full sheets.
   The evaluation fixtures hold case ids and event dates, nothing else.
3. The purge rewrote every commit after `2e647c0`, so the short SHAs recorded by evaluation
   runs before 2026-09-17 no longer resolve. **The mapping below is the provenance record**
   for those runs, and is authoritative where a recorded `commit_sha` does not resolve.

   | recorded by the run | after the purge | runs |
   |---|---|---|
   | `f93ba36` | `1b88518` | 2 |
   | `d76ccd0` | `900b320` | 1 |
   | `a85b439` | `583fc04` | 1 |
   | `54868fd` | `84a2aa0` | 2 |
   | `cf8fd2e` | `2bab070` | 1 |
   | `e248977` | `486afac` | 1 |
   | `179520f` | `c1a77e2` | 1 |
   | `bf435fb` | `9a2b56f` | 6 |
   | `a6d0e31` | `65743fb` | 0, see below |
   | `efe4951` | `727e987` | 2 |
   | `c366a04` | `f8b720f` | 2 |
   | `c717ab5` | `f037b67` | 4 |
   | `cc4b763` | `d2e2e32` | 1 |

   The 53 commits were paired by position, subject and author date, all three matching, which
   is exact because `filter-branch` preserves each. `c717ab5` is the one that matters most:
   it produced the four held-out runs, and so the bars. `a6d0e31` carries no completed run —
   it is the commit of the Gemini batch that sat unstarted for eleven hours and was
   abandoned — and is listed only so the table covers every SHA a run folder names.
4. The absolute local paths in the same history are **not** purged. They were fixed forward
   in `4791aa3` and reveal only a username the commit author line already carries.

## Why

The two hazards are not comparable. A filesystem path is untidy. Held-out probable-cause
text for the sample a bar was measured on is contamination material: the whole argument S1
exists to support is that the agent's score is earned on cases nothing has seen, and a
future contributor, tool or agent that reads history rather than the working tree could
break that without anyone noticing. A guarantee that depends on nobody running `git show` is
not a guarantee.

Rewriting history has a real cost and it is paid knowingly: the recorded SHAs stop resolving,
which weakens 0018's provenance from "check out this commit" to "check out the commit this
table names". That is weaker, but it is still checkable by anyone, and it is a far smaller
loss than leaving the withheld text where it can be recovered. Re-running the bars on a clean
history was the alternative that would have preserved both; it was rejected because it spends
money to buy back a provenance link that a documented mapping already provides.

The safe alternative to a rewrite — leave the files and rely on the new check to stop more
arriving — was rejected for the same reason the review raised the finding at all: it leaves
the rule standing on convention, this time the convention that nobody will look.

## What this rules out

- **Committing any fixture that carries synthesis or verdict.** The check fails the commit;
  it is no longer a matter of remembering.
- **Treating a recorded `commit_sha` from before 2026-09-17 as directly resolvable.** Read it
  through the table above.
- **Purging the absolute paths as well.** Decided against; they are fixed forward.
- **Rewriting history again to tidy anything cosmetic.** This purge is justified by withheld
  data reaching the repository. Nothing less than that justifies breaking recorded SHAs.

## Status

Accepted.
