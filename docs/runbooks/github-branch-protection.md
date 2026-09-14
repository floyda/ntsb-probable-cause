# Runbook — branch protection and merge settings on `main`

*Applies to `floyda/ntsb-probable-cause`. Decision behind it: S0 specification §11 and
decision 0011 (a check that is not enforced is no check), and decision 0018 (squash merges).*

**What this does.** It makes the three CI jobs — `lint`, `test`, `audit` — required before
anything merges into `main`, and requires changes to arrive by pull request. Without it, CI
reports failures but nothing stops a merge.

**Who runs it.** Andy. It is a repository setting and needs admin rights on the repository.

## Apply

```bash
gh api --method PUT repos/floyda/ntsb-probable-cause/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": {"strict": true, "contexts": ["lint", "test", "audit"]},
  "enforce_admins": false,
  "required_pull_request_reviews": {"required_approving_review_count": 0},
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

`required_approving_review_count: 0` requires a pull request without requiring a second
reviewer, because there is one maintainer. `enforce_admins: false` leaves Andy able to
recover from a broken check; turn it on once the checks have been stable for a stage.

## Verify

```bash
gh api repos/floyda/ntsb-probable-cause/branches/main/protection \
  --jq '{checks: .required_status_checks.contexts, pr: (.required_pull_request_reviews != null)}'
```

Expected: `{"checks": ["lint", "test", "audit"], "pr": true}`.

## Merge settings (decision 0018)

Pull requests are squash-merged only. Each stage lands on `main` as one commit whose title is
the pull-request title (GitHub appends ` (#N)`) and whose body lists the branch's commit
messages. A release tag then points at exactly one commit per stage.

```bash
gh api --method PATCH repos/floyda/ntsb-probable-cause \
  -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false \
  -f squash_merge_commit_title=PR_TITLE -f squash_merge_commit_message=COMMIT_MESSAGES
```

Verify:

```bash
gh api repos/floyda/ntsb-probable-cause \
  --jq '{allow_squash_merge, allow_merge_commit, allow_rebase_merge, squash_merge_commit_title, squash_merge_commit_message}'
```

Expected values: `allow_squash_merge` true, `allow_merge_commit` false, `allow_rebase_merge`
false, `squash_merge_commit_title` `PR_TITLE`, `squash_merge_commit_message` `COMMIT_MESSAGES`.

In the merge dialog, do not retype the title: it is the pull-request title by setting.

## Glossary

**Branch protection.** Repository rules that must be satisfied before a branch can change.

**Required status check.** A CI job that must succeed on a pull request before it can merge.

**Squash merge.** Combining all of a pull request's commits into one new commit on the target
branch. The original commits stay visible on the pull request.
