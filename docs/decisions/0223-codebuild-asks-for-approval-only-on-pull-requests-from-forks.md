# 0223. CodeBuild asks for approval only on pull requests from forks

## Context

Every Dependabot pull request shows a failed "AWS CodeBuild" check. 0220's Context explains it
as the site's publish build, "which ran on every branch until 9 November and has run only for
`main` since". That is not what the check is. Its text, on every Dependabot pull request from #26
(2026-10-04) to #67 (2026-11-15) except #25 and #65, which carry none, is the same:
"Build not triggered: Pull request approval required for starting a build". No Dependabot pull
request was ever built.

- **The policy.** `NtsbSiteStack` sets no pull-request build policy, so the project has AWS's
  default for new projects: approval for every pull request (`ALL_PULL_REQUESTS`), unless its
  author has the admin, maintain or write role. Dependabot has none of them.
- **The refusal is posted as a failure.** CodeBuild refuses the pull request under that policy
  and posts the refusal to it as a failed check. The webhook's filter (a push to `main`, anchored)
  would not have built it anyway. Andy's own pull requests get no CodeBuild check at all.
- **The same on floyda.dev.** Its seven Dependabot pull requests of 2026-11-21 all showed the
  check, and hid a real failure on its `main`. floyda.dev turned the policy off (its pull request
  #19, deployed the same day). Its repository is private.
- **This repository is public.** Anyone can fork it and open a pull request.

The check is not required on `main` (0220 item 3), so it blocks no merge. It is noise that looks
like a failure.

## Decision

1. **Approval is asked only for pull requests from forks.** The project's
   `Triggers.PullRequestBuildPolicy` is `FORK_PULL_REQUESTS`, with AWS's default approver roles
   written out (`GITHUB_ADMIN`, `GITHUB_MAINTAIN`, `GITHUB_WRITE`), in `infra/site_stacks.py`.
   `tests/test_infra_site_stacks.py` checks both.
2. **The filter is unchanged.** Only a push to `main` starts a build from GitHub.
3. **The check after deploying.** `aws codebuild batch-get-projects` shows the policy. The next
   Dependabot pull request should carry no "AWS CodeBuild" check. If it still carries one, this
   record's reading of AWS's documentation is wrong, and a new record says so.
4. **This corrects 0220's Context** on the failing check. 0220's decisions stand: none rested on
   the check.

## Why

1. **A check that always fails teaches the reader to ignore it.** Grouped pull requests with a
   red check are what the weekly report (0220 item 6) reads. On floyda.dev the same noise hid a
   `main` that had stopped publishing for five days.
2. **Forks keep their gate.** The filter is the only thing that keeps a pull request from
   running the publish build with its role (which may write the site's bucket). If the filter is
   ever widened by mistake, a fork's code still waits for Andy. Dependabot's branches are in this
   repository, not a fork. AWS's page says that under `FORK_PULL_REQUESTS`, "only pull requests
   from forked repositories require comment approval". It does not name Dependabot, so item 3 is
   the test.
3. **The roles are written out** so a change to AWS's default does not change who can approve.

## What this rules out

- **Turning the policy off (`DISABLED`)**, as floyda.dev did. Its strongest case: it is simpler,
  and the filter already stops every pull request from building. But in a public repository it
  would leave the filter as the only guard against a stranger's code running with the build's
  role. floyda.dev is private, so only its collaborators can fork it.
- **Making Dependabot an approver.** An approver role is a GitHub role, and Dependabot has no
  role to give.
- **Leaving it.** It costs nothing to run, but every Dependabot pull request keeps a red check
  that means nothing, and 0220's mistaken reading of it stays unanswered.

## Status

Accepted; corrects 0220's Context on the failing check.
