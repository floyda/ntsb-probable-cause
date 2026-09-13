---
name: close-stage
description: Use when a build stage of ntsb-probable-cause is finished and its pull request is ready — appends the As-built record to the stage specification, marks the specification Implemented and the roadmap stage done, deletes the implementation plan, and runs the documentation check (decision 0017).
---

# Close a build stage

Decision 0017: a specification keeps its approved body unchanged and gains an **As built**
record when its stage finishes; the implementation plan is deleted. This skill does that work.
The documentation check (`scripts/check_docs.py`) fails CI if it is skipped.

The As-built section is a document Andy signs off: simplified technical English, clinical
tone, no personal names, and every number taken from a committed script or results file.

## 1. Find the stage

- List `docs/plans/*.md`. Each has a `**Spec:** <path>` line. Confirm with the user which
  stage is closing.
- Read the specification in full, especially its **Done means** section, and the plan in full,
  especially its **Deviations** section.

## 2. Stop conditions — check before writing anything

- Any unticked `- [ ]` step in the plan. List them and stop.
- `make check` fails, or CI on the pull request is not green
  (`gh pr checks`). Report and stop.
- A Done-means condition has no evidence (below). Report which one and stop. Never write a
  condition as met without evidence.

## 3. Gather evidence

```bash
gh pr view --json number,url
git log --oneline origin/main..HEAD
git diff --name-status --diff-filter=A origin/main...HEAD -- docs/decisions/ docs/results/
git log -1 --format=%H -- docs/plans/<plan-file>
```

The last command gives the commit for the plan permalink:
`https://github.com/floyda/ntsb-probable-cause/blob/<sha>/docs/plans/<plan-file>`.

For each Done-means condition, find its evidence: a test node id (`tests/test_x.py::test_y`),
a script with its committed output under `docs/results/`, or a CI run URL.

## 4. Write the As-built section

Append to the end of the specification, before its glossary if it has one at the end, using
exactly these headings:

```markdown
## As built

*Closed YYYY-MM-DD in pull request #N.*

### Delivered

What exists now, by component, in a few bullets. Name modules and commands.

### Done means, with evidence

One bullet per condition in the Done-means section, in the same order:
condition — met — evidence (test node id, script and results file, or CI run).

### Departures from this specification

Every entry from the plan's Deviations section, rewritten plainly: what differs, why, and the
decision record if one was written. "None." if there were none.

### Decisions taken during the stage

Decision records added in this pull request, one line each with a link. "None." if none.

### Implementation record

- Pull request: #N (URL)
- Plan, at its last commit: permalink
- Commits: first..last short hashes
```

## 5. Update statuses and delete the plan

- In the specification's first lines, change `Status: Approved (...)` to
  `Status: Implemented (YYYY-MM-DD, pull request #N)`. Change nothing else in the body.
- In `docs/specs/2026-09-12-architecture-and-roadmap.md`, add ` — done` to the stage's heading
  and one line under it: `As built: see the stage specification's As-built section.`
  with a relative link to the specification.
- `git rm docs/plans/<plan-file>`

## 6. Check, show, commit

```bash
uv run python -m scripts.check_docs
make check
```

Both must pass. Show the user the As-built section and the status changes, and wait for
approval. Then:

```bash
git add -A docs
git commit -m "Close out <stage>: As-built record, plan removed (decision 0017)"
git push
```
