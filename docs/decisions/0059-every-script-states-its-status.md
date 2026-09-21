# 0059 — Every script states its status in its docstring

## Context

By the close of S2 `scripts/` held 19 modules and three exploratory ones. They are not one kind
of thing. Some are live tools with a `make` target. Some produced a single committed file under
`docs/results/` and will never run again, and are kept only because rule 3 publishes no number
without the script behind it. Some measured a mechanism that a later decision then removed — and
are the evidence for removing it.

Nothing on the outside of a file said which kind it was, and two files actively misled. The
opening docstring of `scripts/score_handcheck.py` said it "grades three uses": the arm B
photograph exclusion, the deny-list, and the provenance clause. All three had been deleted, by
decisions 0052, 0056 and 0051, in the same stage that wrote the script. `scripts/doctype_scan.py`
described a loss to a filter that no longer exists. `scripts/corpus_scan.py` put its module
docstring's deny-list claim 530 lines above the note saying the deny-list was retired.
`README.md` told a reader that `make scan-docket` measures "the deny-list threshold". Eight of
the ten scripts S2 added appeared in no index at all.

A reader who trusts a docstring — a future session most of all — would have concluded that this
repository contains a deny-list, a photograph filter and a provenance clause. It contains none of
them.

## Decision

Every module in `scripts/`, including `scripts/exploratory/`, carries a **`Status` block**
directly beneath its summary line, before `Usage`. The block states:

1. **which of three kinds it is** — *live tool* (rerun when its input changes), *one-shot,
   complete* (it produced a committed file and its job is done), or *deprecated* (the mechanism
   it measured no longer exists);
2. **what it produced**, by path, with the commit and date;
3. **what has changed since**, by decision number, whenever a decision removed or narrowed the
   thing the script measures.

`scripts/__init__.py` states the three kinds. `README.md` carries the table of every script, its
kind and its output, and names the one committed result whose script was deleted
(`docs/results/s2-filter-compare.txt`).

**Nothing is deleted.** A deprecated script is the evidence behind the decision that deprecated
it, and this project's argument is that its reasoning can be inspected.

## Why

1. **A stale docstring is worse than no docstring.** It is read as current, and it is read first.
   The failure it produces is an agent building on a mechanism that does not exist.
2. **The cost falls at the worst moment.** A fresh session opening this repository has no memory
   of the stage that wrote these files; the decision records exist but nothing in the script
   points at them.
3. **The three kinds are not guessable from the code.** `score_handcheck.py` and
   `check_fixtures_redacted.py` are both small scripts that read a committed CSV. One is finished
   and describes removed mechanisms; the other runs on every commit.

## What this rules out

- **Deleting one-shot and deprecated scripts to reduce the count.** Rejected: rule 3 requires the
  script behind every published number, and `docs/results/s2-filter-compare.txt` is already a
  committed number whose script was removed — recoverable from history, but no longer beside its
  output. That is the state to avoid repeating, not to spread.
- **A separate manifest file listing script statuses.** Rejected: it is one more thing to drift.
  The status lives in the file it describes; the README table is an index, and `check_docs.py`
  does not verify it.
- **Leaving the plan-task citations in place** (`make_docket_fixture.py`, `doctype_scan.py`,
  `build_code_tables.py` cite "Task 16", "Task 5" and a `docs/plans/` path). Decision 0017 deletes
  a plan at merge, so every such citation dangles by construction. The Status blocks now name the
  As-built section that holds the reasoning instead.

## Status

Accepted, 2026-09-21.
