# 0220. Dependency updates merge themselves when CI passes

## Context

On 2026-11-15 twelve Dependabot PRs from 8 November were open and none had been merged.

- **The failing check.** Each showed a failed "AWS CodeBuild" check. That is the site's publish
  build, which ran on every branch until 9 November and has run only for `main` since.
- **No PR for Astro.** Astro had a security fix but no PR. Dependabot opens at most 5 PRs per
  ecosystem, and the site already had exactly 5 (#50 to #54). Dependabot alerts and security
  updates are off for this repository, so the advisory (GHSA-r3h5-4585-7x3w) did not open a PR
  either. Only CI's `pnpm audit` step noticed it, by failing every pull request.
- **The required checks.** `main` required `lint`, `test` and `audit` (Python), with branches up
  to date. `site` was not required, so a PR could be merged with the site's build, tests and
  audit failing.
- **The waits.** Only the site's npm updates had a 7-day wait (`cooldown`). PR #34, which adds
  one for uv, had been open since 11 October.

Merging a PR to `main` reaches three things:

- **The site** is rebuilt from `main` each morning, and published only if its own checks pass
  (S5 specification §18).
- **The recorder's image** (`ntsb-recorder:latest`) is rebuilt by CI's `image-push` job on
  every push to `main`, and the nightly task runs `:latest`.
- **The live nights** are not reached: they run an image pinned by digest, which changes only
  when Andy deploys one (0171).

Andy was shown three choices:

- GitHub merges the updates itself, with no agent;
- a scheduled Claude task reviews and merges them;
- GitHub merges them and a weekly Claude report reads what is left.

He chose the third.

## Decision

1. **Grouped updates.** Each ecosystem (uv, GitHub Actions, Docker, the site's npm) gets one
   grouped PR a week for its minor and patch updates (`.github/dependabot.yml`). A major
   update comes as its own PR. **pypdf and pypdfium2 always come alone**, because a new version
   can change the docket text the agent reads (0218).
2. **A 7-day wait in every ecosystem.** This matches pnpm's minimum release age (S5
   specification §17.2). uv's came from #34, merged on 2026-11-15.
3. **`site` is a required check on `main`** (set on 2026-11-15), beside `lint`, `test` and
   `audit`. Branches must still be up to date with `main`. So once one grouped PR merges, the
   others fall behind and wait. GitHub does not update them, and Dependabot rebases a PR only
   when it conflicts. The weekly report lists them, and an "Update branch" click lets each one
   finish. Dropping the up-to-date rule would let them merge without that click, but the
   combination would then go untested before it reached `main`. It stays.
4. **A workflow turns on auto-merge.** `.github/workflows/dependabot-auto-merge.yml` turns on
   GitHub's auto-merge (squash) for a PR that Dependabot wrote, whose highest change is minor or
   patch, and that updates neither pypdf nor pypdfium2. GitHub merges the PR only when every
   required check passes. The workflow never checks out or runs the PR's code.
5. **Majors and pypdf wait for Andy.** A major update, a pypdf or pypdfium2 update, and any PR
   whose checks fail are left open for Andy.
6. **A weekly Claude report reads what is left**, on Andy's Mac. It lists:
   - open dependency PRs that are major, pypdf, failing, or behind `main`;
   - advisories that `pnpm audit` or `pip-audit` reports on `main` with no PR;
   - any ecosystem at its PR limit.

   It never merges, approves, comments, pushes or changes a setting.
7. **Alerts stay with Andy.** Dependabot alerts and security updates are a repository security
   setting, and are left to Andy. CI's two audit steps remain the check that fails on an
   advisory.
8. **What an automatic merge reaches.** A merge by auto-merge that this workflow turned on
   (with `GITHUB_TOKEN`) starts no `push` workflow. So `image-push` does not run, and the
   recorder keeps its image until the next merge Andy makes. The site is rebuilt the next
   morning, as for any merge. The live nights are unchanged.

## Why

1. **CI is already the gate for these PRs.** Dependabot PRs were merged by hand once CI passed.
   With `site` required, the same checks decide, every week, without waiting for someone to
   have time.
2. **The 7-day wait covers the risk the supply-chain rules target** (S5 specification §17.2): a
   poisoned release is usually found and pulled within days. Auto-merge without the wait would
   skip that protection in three of the four ecosystems.
3. **No model decides what merges** (judgement). A reviewing agent would read release notes
   written by strangers just before merging. Text in them could try to steer it, so its rule
   would have had to be mechanical anyway. The report can use judgement because it changes
   nothing.
4. **Grouping cuts the work and the limit problem.** About four PRs a week instead of a dozen,
   so an ecosystem no longer fills its five slots and hides a later update, as it hid Astro's.
5. **pypdf is measurement, not maintenance.** 0218 showed that one pypdf update changed the
   layout of 561 documents' text on `dev-400`. Such an update needs a decision record, not an
   automatic merge.

## What this rules out

- **A scheduled Claude task that merges.** Its strongest case: it could read changelogs, spot a
  breaking change CI does not test, and notice an update with no PR. It would cost tokens every
  week, and add a model's judgement over text from strangers to the merge path. The report
  keeps the judgement and drops the merging.
- **Auto-merging major updates too.** That would mean less waiting, but majors are where APIs
  break in ways the tests may not reach (for example the CDK, or Astro's output).
- **Renovate in place of Dependabot.** It has better grouping, a built-in auto-merge and its own
  release-age rule. But it is another third-party app with write access to the repository, and
  Dependabot with one small workflow does what is needed.
- **No automation, merging by hand.** That keeps full control, but the last two months show the
  cost: PRs that wait weeks, and an advisory that only failing CI revealed.

## Status

Accepted.
