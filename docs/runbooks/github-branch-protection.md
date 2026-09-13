# Runbook — branch protection on `main`

*Applies to `floyda/ntsb-probable-cause`. Decision behind it: S0 specification §11 and
decision 0011 (a check that is not enforced is no check).*

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

## Glossary

**Branch protection.** Repository rules that must be satisfied before a branch can change.

**Required status check.** A CI job that must succeed on a pull request before it can merge.
