# S5 before launch — the site publish mode: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (Andy's choice for S5: Claude runs the tasks in the session, one fresh review at the end). Steps use checkbox (`- [ ]`) syntax. Tick a step in the same commit as its code (decision 0017). Log every departure in **Deviations**. Tasks marked **Controller** need Andy.

**Goal:** The morning build can publish the site, not only the holding line. It does so only
when Andy's own `cdk deploy` turns the switch (spec §20: "Launch is Andy's decision"). Until
then nothing changes at `ellery.demo.floyda.dev`.

**Architecture:**
- **The switch is CDK context, `site_mode`.** It is `holding` unless Andy's deploy passes
  `-c site_mode=site`. The stack writes it into the build's `SITE_MODE` variable. A push to the
  repository cannot change it, because the variable lives on the CodeBuild project, which only a
  deploy changes. `site` is refused without `live_bucket_name`, since the site is built from S4's
  export. Any other value stops `cdk synth`.
- **The build has Node 24 and pnpm in every mode.** The buildspec's install phase names
  `nodejs: 24` (CodeBuild's runtime list, read 2026-11-01: `standard:7.0` offers 22, 24 and 26)
  and installs the exact pnpm that `site/package.json`'s `packageManager` names.
- **`publish.sh` in `site` mode** (spec §18.1 step 3, §19.1):
  1. copies `export/board-1/` from S4's bucket into a fresh folder;
  2. checks the finished mark: `_finished.json` is `board-finished/1` and its `built_at` equals
     `index.json`'s `stamp.built_at` (§22, S4's answer), else it stops;
  3. installs the site's packages from the lockfile (`pnpm install --frozen-lockfile`, under the
     supply-chain settings of §17.2);
  4. builds the site from that export (`BOARD_EXPORT_DIR`); the build already checks the schema,
     the counts and the claims, and stops on any fault;
  5. runs the checks over the built pages (`tests/dist.test.ts`);
  6. publishes `site/dist` in the order holding mode already uses.
  Any failure stops the script before anything is copied, so yesterday's site stays and CodeBuild's
  failure rule emails Andy.
- **The finished-mark check is `site/scripts/check-finished.ts`**, run by Node 24 directly, with
  Vitest tests.
- **The page checks that name sample cases skip on a real export.** Ten Vitest tests look up
  particular cases of S4's invented sample: five in `tests/dist.test.ts`, five in
  `src/lib/route.test.ts`. On the export of 20 October every other test passes (2,451 of 2,461).
  The morning build runs `tests/dist.test.ts` only, so its five skip there.

**Tech Stack:** bash, AWS CDK (Python), Astro 7, Vitest.

**Spec:** docs/specs/2026-10-04-s5-public-site-design.md

The design is §18.1 (each morning), §19 (failures and checks), §20 (launch) and §22 (S4's
finished mark).

## Choices made here (each can change at Andy's review)

1. **The morning build runs the checks over the built pages, not the browser checks.** Measured
   on 2026-11-01 against the export of 20 October on Andy's Mac: the browser checks (axe in light,
   dark and phone, 645 tests) took 1.8 minutes on about 4.7 cores; 637 passed, 2 failed on a test
   written for the sample's size, 6 skipped. On CodeBuild's smallest machine (2 cores) that is
   perhaps 5 to 7 minutes, plus downloading a browser each morning. A month of mornings would pass
   CodeBuild's 100 free minutes (§18.3). (The packages are fetched from the npm registry on every
   build either way, from the lockfile; a browser would add a second download, from Playwright's
   own servers.) The browser checks test the site's code, which changes only through a pull request,
   where CI runs them. What changes each morning is the data, and the page checks cover what data
   can break: the respect scan (§11), links, every case page belonging to a board row, and the
   preview tags. Spec §19.2 already lists the browser checks under "on every pull request".
2. **Pages are cached as before.** The site's files go up in holding mode's order and with its
   cache rules: hashed assets for a year, other files for five minutes, pages checked every time.
3. **No new decision record.** The switch was planned in step 1 (`publish.sh`'s header, the
   runbook's opening), and choice 1 follows spec §19.2's split. If Andy prefers the browser
   checks each morning, that is a decision record.

## Tasks

### Task 1: the finished-mark check

- [x] `site/scripts/check-finished.ts`: `checkFinished(dir)` throws when `_finished.json` is
  missing, unreadable, not `board-finished/1`, or its `built_at` differs from `index.json`'s;
  run as a script it prints the reason and exits 1.
- [x] Vitest tests in `site/tests/check-finished.test.ts`.

### Task 2: page checks that run on any export

- [x] `lib/export.ts` gains `onSample()`; the dist describe that names sample cases skips off the
  sample. `route.test.ts` is a unit test and is not run by the morning build.

### Task 3: `publish.sh` site mode

- [x] The steps above; `LIVE_BUCKET` required.
- [x] `tests/test_site_publish.py`: the site mode's order with fake `aws` and `pnpm`; a stale or
  missing mark publishes nothing; a failing build or check publishes nothing; a missing
  `LIVE_BUCKET` publishes nothing.

### Task 4: the stack's switch

- [x] `site_mode` context in `infra/app.py`; `NtsbSiteStack` takes `site_mode`, sets `SITE_MODE`
  and `LIVE_BUCKET`, refuses `site` without a live bucket, and adds the install phase.
- [x] Stack tests: holding by default; site only when asked and with a bucket; unknown value
  refused; Node 24 and the pinned pnpm in the install phase.

### Task 5: the runbook

- [x] `docs/runbooks/site-deploy.md`: a launch stage (deploy with `-c site_mode=site`, start a
  build, the checks), going back to the holding line, and the warning that a later deploy without
  `-c site_mode=site` returns the address to the holding line.

### Task 6: checks and review

- [x] `make check`, the site's checks, a dry run of site mode against the 20 October export with
  a fake `aws` that only records the upload.
- [x] A fresh review; its points fixed or logged here.

## Deviations

- **Task 1 (2026-11-01):** the check runs as TypeScript under Node 24's built-in type stripping
  (on by default since Node 22.18 and 23.6). This Mac has Node 26, so Node 24 itself is first
  exercised by CodeBuild's first site build. In `tests/test_site_publish.py` a fake `node`
  stands in, because CI's Python job has no Node 24; the check's own tests are in Vitest.
- **Task 3 (2026-11-01):** the script also removes `site/dist` before building, so a folder left
  from an earlier build can never be published (tested).
- **Task 5 (2026-11-01):** the runbook's build time is 2 to 3 minutes, not the plan's guess: on
  the Mac the dry run took 5.5 seconds in all (build 0.7 seconds for 182 pages, page checks 2.0
  seconds), so CodeBuild's start and the package install dominate.
- **Task 6 (2026-11-01):** the plan's **Spec:** line held the section numbers too, which
  `scripts/check_docs.py` read as part of the path; they moved to their own line.
- **Task 6, checks (2026-11-01):** `make check` 4,852 passed, 1 skipped; the site's lint, format,
  `astro check`, types, Vitest 582 passed, browser checks 168 passed and 6 skipped, on the
  sample. Dry run with real Node and pnpm and a recording `aws` against the 20 October export:
  exit 0, page checks 2,246 passed and 5 skipped, the upload in holding mode's order. The same
  with the finished mark set a night earlier: exit 1 after the copy, nothing installed, built
  or published.
- **Fresh review (Opus, 2026-11-01): no path found that publishes a half-built or unchecked
  site.** Fixed:
  - *The check could pass by checking nothing.* `check-finished.ts` runs only when Node sees it
    as the script it started, and a symlinked path makes the two differ: it then exits 0 having
    done nothing (reproduced by the reviewer). `publish.sh` now requires the line "the export is
    whole" (tested).
  - *An older build could publish last.* Two builds can overlap (a push and the night's mark),
    and the slower one would finish last. Just before publishing, the script fetches the mark
    again; if it has changed, a newer night has landed, and the script exits 0 without
    publishing, leaving that to the newer night's build (tested). This also stops a build whose
    copy caught S4 mid-upload, once S4's new mark has landed. *Ruled out:* CodeBuild's project
    limit of one build at a time. Its API reference says a build over the limit is "throttled
    and not run" without saying whether it waits; if it is dropped, a night's board would be
    lost with no email.
  - *The page checks pass if nothing was built*, since every block skips without
    `dist/index.html`. The script now requires that page (tested).
  - *Wording.* The runbook's glossary said a push "cannot change" the mode; a push can change
    what each mode does. It now says so, and warns that `cdk deploy --all` without
    `site_mode=site` takes the site down. One stack test was renamed to what it shows; the
    check's tests gained a broken-mark case and remove their folders.
- **Left as they are, with reasons:**
  - *A copy caught mid-upload, when S4's upload then fails.* S4 writes the cases, then
    `index.json`, then the mark. If a build copies during that window and S4's upload then
    fails, the mark never changes, and the build can publish last night's index with some of
    tonight's case files. Each file still passes the schema; the board would be inconsistent
    until the next whole night. It needs a build started by a push in the minutes of S4's upload,
    and a failed upload, which S4 already alerts on. Closing it needs a stamp in every case
    file, an S4 change.
  - *`npm install --global pnpm` and a pnpm already on the image.* The image's Dockerfile
    (`aws/aws-codebuild-docker-images`, `ubuntu/standard/7.0`, `master`, read 2026-11-01) installs
    no pnpm and runs no `corepack enable`, so there is nothing to clash with.
  - *Keeping `site_mode` in the committed `cdk.json` after launch,* so a deploy without it cannot
    take the site down. A pull request still could not deploy. Left to Andy: it would put the
    switch in the repository, which the step-1 design kept out of it.
