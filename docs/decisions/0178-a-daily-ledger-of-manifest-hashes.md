# 0178 — A daily ledger of manifest hashes

From the S4 design session with Andy, 2026-10-10. Builds the roadmap's "hashed ledger and the
continuous-integration job that commits it". Detail: the S4 specification, §11.

## Context

1. **The roadmap asks for tamper evidence**: hashed rows committed to git (design notes).
2. **The repository is public**, so a job's logs and commits are public.
3. **The live task should never be able to write to the repository.**

## Decision

1. **A daily GitHub Actions job** (`ledger.yml`, 10:00 UTC) signs in through a read-only role
   allowed only to list `runs/` and `nights/` and read their `manifest.json` files, and appends one
   line per new manifest to `ledger.jsonl` on a `ledger` branch: the date, the run or night, its
   counts where the manifest holds them, and the manifest's SHA-256. It prints no file's contents.
2. **The `ledger` branch** allows no force push and no deletion and needs no pull request.
3. **Every store write gets a manifest.** No path read by the role names a case.
4. **The role is created by Andy's `cdk deploy`.** Before the merge, the job also runs on pushes to
   the S4 branch, which the role trusts until the close-out removes it.
5. **`ntsb-live verify-ledger`** checks the bucket against its manifests and the ledger.

## Why

1. **Public, dated, append-only proof** that results were not changed later, without publishing
   them.
2. **Separation**: the task that writes results cannot write the ledger, and the job that writes the
   ledger cannot read results.

## What this rules out

- **The task committing its own hashes.** One job fewer. Rejected: the task would hold write access
  to a public repository.
- **No ledger, relying on bucket versioning.** Less to build. Rejected: versioning is under the
  account owner's control, so it proves nothing to a reader.

Andy chose this with "I guess A"; Claude offered a smaller version if it seemed more than a demo
needs, and none was asked for.

## Status

Accepted, 2026-10-10 (Andy).
