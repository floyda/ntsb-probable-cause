# 0018 — Squash merges, and tag-only releases at stage close

## Context

Andy asked for an automated changelog as part of a well-kept Python repository. This project
does not publish a package and will rarely release. What it needs from a version is a fixed,
named point in time: "the agent as it was when stage N closed", which a reader can check out
and re-run.

Every automated changelog tool builds its entries from commit messages. With one pull request
per stage, the entry is one line per stage whatever the tool. The detailed record of what a
stage delivered already exists in its specification's As-built section (0017).

A second constraint: `main` accepts changes only through pull requests, and Claude Code never
pushes to it. Tools that write a changelog file and a version commit onto `main` after a merge
(commitizen's `cz bump`) cannot run there; tools that do it through a bot pull request
(release-please) need a third-party Action and a token that can open pull requests.

## Decision

1. **Pull requests are squash-merged, and only squash-merged.** Merge commits and rebase merges
   are disabled. The squash commit's title is always the pull-request title
   (`squash_merge_commit_title = PR_TITLE`); its body is the branch's commit messages
   (`squash_merge_commit_message = COMMIT_MESSAGES`). Each stage lands on `main` as one commit.
   The settings are applied by Andy from `docs/runbooks/github-branch-protection.md`.
2. **Each closed stage is released as a tag with generated notes.** The stage's close-out
   (the `close-stage` skill) sets `version` in `pyproject.toml` to the release version: `0.1.0`
   for S0, then the minor version increases by one for each stage closed after it. After the
   pull request merges, Andy runs
   `gh release create v<version> --target main --generate-notes --title "<stage>: <name>"`,
   which creates the tag and a GitHub release listing the pull requests merged since the
   previous tag.
3. **There is no `CHANGELOG.md` and no commit-message convention.** The GitHub Releases page is
   the changelog; each release links to its stage pull request, which links to the As-built
   record. Pull-request titles follow the existing form `S0: foundation`.
4. **Results are pinned to a commit, not only to a version.** Evaluation runs and live
   prediction rows record the commit SHA of the code that produced them and whether the working
   tree had uncommitted changes. Tags mark stages; the SHA marks every run between them. Built
   with the evaluation harness (S1) and the predictions store (S4), not in S0.

## Why

1. **A release here is a pin, not a publication.** A tag on a single squash commit names exactly
   one tested state of the whole stage. Generated notes are enough to say what that state
   contains, because the As-built record carries the detail.
2. **Nothing writes to `main` outside a pull request.** The version is set inside the stage's
   own pull request, where CI and review see it; the tag is created on the merged commit. No bot,
   no extra token, no second pull request per stage.
3. **Less tooling to keep correct.** No commit-message hook, no title check, no changelog
   template. Each would guard a file that would hold one line per stage.
4. **The SHA is what makes a result reproducible.** Most runs will happen between tags. A version
   alone could not say which code produced a given prediction; the commit can, which is the
   property the single-repository design (roadmap §2) depends on.

## What this rules out

- **commitizen (Conventional Commits, `cz bump` writes the version, changelog and tag).** The
  standard Python choice and one tool for all three. Rejected because the bump commits to `main`
  after the squash merge exists, which the pull-request-only rule forbids, and enforcing the
  message format buys a one-line-per-stage file.
- **release-please (a bot opens a release pull request after each merge).** Fully automated and
  pull-request-based. Rejected because it adds a third-party Action, a write token and a second
  pull request per stage for the same one-line entries.
- **git-cliff or towncrier writing `CHANGELOG.md`.** More flexible or better-written entries.
  Rejected because the file duplicates the As-built record, and towncrier's hand-written
  fragments are not automated.
- **Merge commits or rebase merges.** Keep every branch commit on `main`. Rejected because a tag
  would then point into a sequence that includes review-fix commits never meant to stand alone,
  and the branch history is still kept in the squash commit body and on the pull request.
- **Tags without a version in `pyproject.toml`.** One fewer step at close-out. Rejected because
  `ntsb_probable_cause.__version__` would disagree with the tag it was released under.

## Status

Accepted, 2026-09-13.
