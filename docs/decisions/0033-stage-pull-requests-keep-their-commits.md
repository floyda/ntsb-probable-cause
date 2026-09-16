# 0033 — Stage pull requests are merged, not squashed, so a recorded commit resolves

Amends [0018](0018-squash-merges-and-tag-only-releases.md), which stays in
place.

## Context

Decision 0018 settled two things in the same record. Pull requests are squash-merged, so each
closed stage arrives on `main` as one commit and the release notes generate cleanly. And every
evaluation run and prediction row records the commit SHA that produced it, so a published
number can be traced to the exact code behind it.

Those two halves are in tension, and 0018 did not notice. A squash merge replaces a branch's
commits with a single new commit. The commits the branch actually carried are not in `main`'s
history afterwards. So a run recording `bf435fb` — and S1 has produced runs recording exactly
that — cites a commit that `main` does not contain. It survives only while the branch or the
pull request's refs survive.

The gap is narrower than it first sounds. The results files and the code both reach `main` in
the squash, so a reader can see the numbers and the code that produced them. What dangles is
the precise intermediate commit. But this project's argument is falsifiability in public, and
"the commit we published does not resolve" is a scuff on exactly the property being
demonstrated.

Three merge strategies were available, and only one preserves the recorded SHA:

| strategy | what happens to the recorded SHA |
|---|---|
| squash | not in `main`'s history; reachable only while the branch or PR refs live |
| rebase | **rewritten** — the recorded SHA exists nowhere, and a different SHA holds the same tree |
| merge commit | preserved on `main` permanently |

## Decision

1. **A pull request that closes a stage is merged with a merge commit**, never squashed and
   never rebased. The stage's commits keep their SHAs and reach `main` intact, so every SHA
   recorded by a run or a prediction row resolves for as long as the repository exists.
2. Squash merges remain available and remain the default for incidental pull requests that
   produce no measurements — documentation fixes, tooling, dependency bumps.
3. Rebase merging stays disabled. It is the worst of the three here and the most likely to be
   chosen by mistake, because it looks like the tidy compromise.
4. These are enforced as repository settings, not as a habit: `allow_merge_commit` on,
   `allow_rebase_merge` off, `delete_branch_on_merge` off. A stage merge commit takes the
   pull request's title and body, so the reasoning lands in the history rather than only in
   the web interface.
5. 0018's other provisions stand unchanged: each closed stage is still a tagged release with
   generated notes, there is still no changelog file, and runs and prediction rows still
   record the commit SHA and whether the tree was dirty.

## Why

The deciding argument is that the alternative is a ritual. Provenance could have been
preserved under squash merges by tagging each branch tip before merging, or by never deleting
a stage branch. Both work. Both are things somebody has to remember, every stage, forever, and
the failure is silent and only discovered years later by the one person who tries to check a
published number. This project refuses that trade elsewhere on principle — the leakage guard
is layered rather than "by convention" (0016), and the cost cap is enforced in code rather
than measured (0030). A merge commit is structural: there is nothing to remember.

The cost is that `main`'s history stops being one commit per stage. That is a real loss of
tidiness and it is worth less than the traceability. Release notes generate from a merge
commit as readily as from a squash, and the tag on each closed stage still gives the clean
one-entry-per-stage view that squashing was chosen for.

Recording the reasoning in the merge commit's body follows the same instinct as the decision
records themselves: a reader who disagrees with a choice should be able to find the argument
for it, rather than infer it from the code that survived.

## What this rules out

- **Squash merges for stages**, and with them the one-commit-per-stage `main` history. Anyone
  wanting that view uses the tags.
- **Rebase merging**, permanently and for every kind of pull request. It destroys recorded
  SHAs while appearing to preserve history, which is worse than squashing honestly.
- **Tag-the-branch-tip and never-delete-the-branch** as the provenance mechanism. Both were
  viable and both were rejected as rituals; `delete_branch_on_merge` stays off as a second
  line of defence, not as the guarantee.
- **Changing what a run records.** The SHA was never the problem; its reachability was.
  Existing run records stay valid as written, and the S1 runs that cite branch commits become
  resolvable on `main` once this stage merges.

## Status

Accepted.
