# 0172 — The store is run folders in a private bucket, with a nightly export

From the S4 design session with Andy, 2026-10-10. Replaces the SQLite predictions tables that the
roadmap's S4 entry and the S3 specification (§11) gave S4. Detail: the S4 specification, §9.

## Context

1. **The roadmap planned predictions tables** in SQLite: case, evidence fingerprint, timestamp,
   answer, cost, commit.
2. **S3.3's run folders already hold all of that** (decision
   [0160](0160-the-live-package-its-run-folders-and-the-open-split-fence.md)), and were built to
   move to S3 as a plain copy: self-contained, versioned, secret-free, with a manifest.
3. **The site is a pure function of the store**
   ([0003](0003-static-site-as-pure-function-of-store.md)), and S5 needs one place to read.

## Decision

1. **The store is the run folders in a private, versioned bucket** in `NtsbLiveStack`, copied up
   after each case so a night can resume. A finished folder is never written again.
2. **Later scores, retry counts and night records are new files**: `scores/<date>.jsonl` and
   `nights/<date>/`. No path names a case except the export's per-case files.
3. **The task role can put but never delete.** Old versions of export files are kept 30 days; old
   versions of other files are kept.
4. **Each night rebuilds one export from scratch** (decision 0173), the only part S5 reads.
5. **No SQLite predictions tables are built.**

## Why

1. **It is the smallest store S5 needs.** The files exist and are tested; a database would copy
   them into a second form to keep in step.
2. **Append-only by permission, not by convention**: without delete, and with versioning, a bad
   write is recoverable.
3. **The export keeps the site simple**: S5 reads one shaped format, not run internals.
4. **Under a cent a month** (external, AWS price list for eu-west-2, read 2026-10-10; estimate,
   about 100 KB a case).

## What this rules out

- **SQLite predictions tables.** Queryable, as the roadmap planned. Rejected: a second copy of the
  run folders, a migration to keep, and nothing S5 needs that the export lacks.
- **Committing results to git.** Public and versioned. Rejected: raw records and trails are not for
  git, and decision 0024 keeps open-split cases out of measurements.
- **Letting S5 read run folders directly.** No export to build. Rejected: the site would depend on
  run internals, and every format change would break it.

## Status

Accepted, 2026-10-10 (Andy: "yes A plus export").
