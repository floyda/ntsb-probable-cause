# S4 — Predictions and resolution: design

*Drafted 2026-10-10 from a design session with Andy (2026-10-10), after S3.3 closed (pull request
#29, merge commit `ebb16cb`). Status: Approved (Andy, 2026-10-10). The implementation plan is written from this document
separately, in `docs/plans/`. The specification, the plan and the code are on one branch,
`s4-predictions-and-resolution`, and one pull request.*

**How to read this.** Each section says what is done, then why, with an example where one helps.
Terms in **bold** on first use are in the glossary at the end. Numbers here are of five kinds, and
each is labelled:

- **scripted** numbers cite the committed script and results file that produced them;
- **external** numbers come from a published page or a bill, cited by page and the date read;
- **ad-hoc** numbers were counted during the design session by a throwaway command. They are not
  citable, and S4 re-derives any it relies on with a committed script;
- **estimates** are arithmetic, and are replaced by measured figures in the As-built record;
- **run records** are read from a run folder (not committed).

**Decision records.** This design takes decisions 0168 to 0181, written with this document; §16
lists them. *Added 2026-10-12 (final review):* decisions 0182, 0183 and 0184 were taken while the
stage was built, on the names step; §16 lists them too. Decision 0185 (the resume's money and
docket rules) was taken in the final review; §16 lists it.

---

## 1. What S4 is for

The roadmap gave S4 three parts: a predictions store, a resolution watcher that scores a standing
prediction when its case closes, and a hashed ledger committed by continuous integration. Its done
means: "a case closing causes its standing prediction to be scored without anyone intervening."

Two things changed what S4 has to build.

1. **The live run is at closure** (decision
   [0154](../decisions/0154-the-live-run-is-at-closure.md)). Open cases almost never have a docket
   before they close: of the 46 dockets the recorder timed, all 46 appeared on the night of
   closure (scripted, `docs/results/s5-recorder-report-2026-10-06.txt`). So there is no standing
   prediction made long before the verdict. The agent codes a case on the night it closes, from the
   docket as published then, with the verdict withheld by the split and guard. The "resolution" is
   then mostly the same night's scoring. A case coded before the NTSB's codes appear is scored
   later (§6.4).
2. **S5 needs a data source, and Andy wants S5 sooner.** The public site is a pure function of the
   store (decision [0003](../decisions/0003-static-site-as-pure-function-of-store.md)). S5's Draft
   (`docs/specs/2026-10-04-s5-public-site-design.md`, §4 to §6 and §13) lists what the board, the
   opened case and the trail view read. Andy's priority (2026-10-10): "reaching the public demo page
   (S5) sooner. Prefer the smallest S4 that gives S5 what it needs."

So S4 is the S3.3 live shadow moved off Andy's Mac and made unattended. It runs as a scheduled
cloud task, with its own key and limit, its own private store, alerts, and a public ledger. It also
writes an export in a fixed format, `board/1`, that S5 builds against. That format and an invented
sample are delivered early (§14), so S5 can start while S4 waits for its cloud nights.

## 2. Where S4 starts

S3.3 delivered (S3.3 specification, As-built): the `live` package, `ntsb-live run` and `report`, a
queue of closed cases from 23 September 2026 (decision
[0155](../decisions/0155-the-board-is-backfilled-from-the-recorders-first-night.md)), the seen rule
(decision [0157](../decisions/0157-s33-codes-closures-through-a-queue.md)), the rendered-text
fingerprint and the version 1 check (decision
[0161](../decisions/0161-the-rendered-text-fingerprint-and-the-version-1-check.md)), sync runs at
the standard price that can resume (decision
[0165](../decisions/0165-live-runs-at-the-standard-price.md)), self-contained run folders with a
manifest, and the open-split fence in code (decision
[0160](../decisions/0160-the-live-package-its-run-folders-and-the-open-split-fence.md)). Four runs
on the Mac coded 60 cases (scripted, `docs/results/s33-live-shadow.txt`).

**S3.3 carried eight items to S4.** Each is answered here:

1. `fields.py`'s event-selection keys are not covered by `+t` → §3.1, decision 0168.
2. `VERSION_1_SETTINGS["model"]` compares the model id with itself → §3.2, decision 0169.
3. A resume near the $40 guard can be refused inside the runner → §8, decision 0170: the live path
   no longer counts against the $40 guard.
4. Two messages have no runbook row → §7.3, decision 0175.
5. The docket a case was coded from is not frozen → §9.3, decision 0176.
6. A case that fails before it is seen returns without limit → §7.1, decision 0175.
7. The IAM user `ntsb-live-reader` is removed → §4.4, decision 0171.
8. 2 fresh closures stay queued → §6.2, decision 0179: the cloud backfill covers them.

## 3. Version 1, made exact

### 3.1 The fingerprint covers several events

`fields.py` chooses which event of a record the model reads, by `isDefiningEvent` and
`sequenceNumber` (`fields.py` lines 80 to 83, 155 to 173, 235 to 236). The invented record that
`agent/rendered.py` drives has a single event, so the choice never shows in `+t`. An edit to that
choice could change what Ellery reads without moving the label. The file is unchanged since
`fd6053f` (ad-hoc, `git diff fd6053f -- src/ntsb_probable_cause/fields.py`, empty).

**What is done** (decision 0168):

- `agent/rendered.py` gains a second invented record with several events, out of sequence order,
  with exactly one defining event. Its rendered text then depends on the selection keys.
- `VERSION_1` (`agent/version.py`) is pinned again to the new `+t`. Continuity is shown the way
  S3.3 showed it: `make s33-continuity` computes the new `+t` on `fd6053f`'s code and on the tree,
  and they must match. It writes `docs/results/s33-fingerprint-continuity.txt` again, with a dated
  line.
- The mutation sweep (`make s33-mutation-sweep`) gains an edit to each selection key, which must
  move `+t`.
- 0161 and the continuity file get dated notes. The S3.3 specification's §7.2 phrase "it cannot
  miss a text" becomes "it covers the cases its invented inputs exercise".

**Why not pin `fields.py`'s source hash.** Decision
[0143](../decisions/0143-the-fingerprint-should-cover-what-the-agent-receives.md) moved the
fingerprint away from source hashes, because a comment edit moved them. Widening the invented
inputs keeps the rule that the fingerprint covers what the agent receives. It costs no model call.

### 3.2 The model is pinned by name, and the replying model is recorded

`VERSION_1_SETTINGS["model"]` is `LUNA_6.model_id`, the same constant `current_settings()` reads,
so the check compares the constant with itself. **What is done** (decision 0169):

- The setting becomes the literal `"openai/gpt-6-luna"`.
- Every reply's `model` and `provider` fields, which OpenRouter returns on each completion (for
  example `tests/fixtures/openrouter/s3/standard-armb.json`: `"model": "openai/gpt-6-luna"`,
  `"provider": "OpenAI"`), are recorded on the call's trail row (`agent/trail.py`'s `AgentCall`,
  two new optional fields).
- The S4 report counts calls whose replying model differs from the one asked for, and calls by
  provider. A difference is reported, not refused: the request is still version 1's, and OpenRouter
  decides the routing.

## 4. Where it runs

### 4.1 A second scheduled Fargate task

**What is done** (decision 0171): a new CDK stack, `NtsbLiveStack` (`infra/live_stack.py`), beside
the recorder's `NtsbRecorderStack`, which is left unchanged. It holds:

- **its own small network**: a VPC with two public subnets and no NAT gateway, and a security group
  with no inbound rule, the same shape as the recorder's. A VPC, its subnets and a security group
  have no charge (external, AWS VPC pricing page, read 2026-10-10). Having its own keeps the two
  stacks independent, so the recorder's template does not change;
- **its own image repository**, `ntsb-live`, with immutable tags and a rule keeping the 5 newest
  images. It is separate because the recorder's repository keeps only its 5 newest images, so live
  images pushed there could expire the recorder's `:latest`;
- **the task**: Fargate, x86, 0.5 vCPU and 1 GB, the image pinned by digest, started by EventBridge
  Scheduler at 06:00 UTC, with a 3-hour time limit around the command (the recorder has 90
  minutes);
- **the task role**: read the recorder's `recorder.sqlite` (by bucket name, passed as CDK context);
  read, list and put in the live bucket, and **never delete**; publish to the alert topic; put the
  one metric;
- **the execution role**: pull the image, write logs, and read two Parameter Store values: the
  recorder's NTSB key (`/ntsb/api-key`) and the live OpenRouter key (`/ntsb/live/openrouter-key`,
  a SecureString that Andy writes; the standard tier is free, external, AWS Systems Manager pricing
  page, read 2026-10-10);
- **the live bucket**, the alert topic, the alarm, and the ledger's role (§9, §7.2, §11).

The schedule is deployed **disabled**. Enabling it is the go-ahead for the first cloud night
(§4.3).

*Why a scheduled Fargate task:* the recorder already runs this way, so the network, logging and
key handling are known. A night of 30 cases takes about 45 minutes (estimate, from S3.3's
standard-price mornings of 12 to 14 minutes for 9 to 10 cases, ad-hoc), past Lambda's 15-minute
limit. GitHub Actions was ruled out because a public repository's job logs are public.

**Cost** (external, AWS price list for eu-west-2, read 2026-10-10; estimates): Fargate x86 is
$0.04656 a vCPU-hour and $0.00511 a GB-hour, and a public IPv4 address is $0.005 an hour, so this
task costs about $0.034 an hour. A normal night of about 3 fresh cases runs about 10 minutes:
about $0.15 a month. The backfill's three nights cost about $0.07, once. The image repository costs
about a cent a month, judged from the recorder's (external, AWS Cost Explorer, read 2026-10-06).

### 4.2 The image

The live image is built from the same `Dockerfile` as the recorder's, which already installs
`ntsb-live`. A script, `scripts/build_live_image.sh`:

1. refuses a tree with uncommitted changes;
2. builds for `linux/amd64` with `NTSB_COMMIT_SHA` set to the commit;
3. tags the image `live-<commit>` (never `latest`), pushes it to `ntsb-live`, and prints the
   digest that `NtsbLiveStack` pins (CDK context `live_image_digest`).

**The task enforces what `paid_run.sh` enforces on the Mac:** dependencies installed from
`uv.lock` with `--locked` (in the `Dockerfile`), a recorded commit, a clean tree (the build
script), the version 1 label and settings, and the caps (§8). A run's `dirty` flag is `false` by
construction.

**During S4 the image is built from S4 branch commits.** The stage pull request is a merge commit,
so those commits stay reachable from `main` (decision
[0033](../decisions/0033-stage-pull-requests-keep-their-commits.md)). After the merge, the task
moves to an image built from `main`.

### 4.3 Who does what

- **Andy runs** every command that creates or deletes an IAM entity: `cdk deploy` of
  `NtsbLiveStack` (it creates two roles) and the removal of the Mac's key (§4.4). Andy also writes
  the live OpenRouter key into Parameter Store, from `pass`, never printed, and confirms the alert
  email subscription.
- **Claude asks Andy before the first cloud night**, with its cost and duration (about 30 cases,
  about $0.15 and about 45 minutes, estimates), after confirming the key is in Parameter Store and
  the subscription is confirmed. The night starts when the schedule is enabled.
- After that, nights run on the schedule within the caps (§8), and each one's counts and cost
  arrive by email only when something needs attention (§7.2).

### 4.4 The Mac is retired

**What is done** (decision 0171):

- After the first good cloud night, Andy removes the IAM user `ntsb-live-reader`, its access key and
  its inline policy `live-shadow-read-store`, the `pass` entry `aws/ntsb-live-reader`, and the
  `ntsb-live` profile. The runbook lists the steps.
- `ntsb-live run` without `--dry-run` refuses outside the image (when `NTSB_COMMIT_SHA` is unset),
  so paid calls go only to the cloud result store. The local seams stay as test and dry-run
  versions.
- `scripts/live_env.sh` defaults to the `ntsb` profile. `make s33-morning` is removed;
  `make s33-dry-run` and `make s33-report` stay.
  *Note, 2026-10-11 (Task 14):* `make s33-dry-run` was removed in Task 14. With the live stack
  present it would read the live key's limit with the development key and refuse, and without the
  stack it only repeats `make s4-dry-run`'s local fallback. `make s4-dry-run` replaces it.
  `make s33-report` stays and runs S3.3's script directly, because `ntsb-live report` is now the
  S4 report.
- S3.3's rehearsal folders stay on the Mac and are never uploaded (§6.2).

## 5. One night

1. **06:00 UTC: the scheduler starts the task.** The task writes `nights/<date>/started`, with a
   write that fails if the file exists (an S3 conditional write). A second task on the same day
   stops before doing anything. This replaces the Mac's `live.lock` and needs no delete permission.
2. **Checks before any spend:** the image's commit, the version 1 label and settings, the store
   opens and is sound, and the recorder's night has finished (`store.run_finished_on`). The
   recorder starts at 03:00 UTC and its last retry ends by about 05:31 UTC (`infra/recorder_stack.py`:
   two retries, a 3,600-second event age, a 90-minute limit). A failed check stops the night with
   an alert. Nothing is spent, and every queued case waits for the next night.
3. **Resume.** An unfinished run in the bucket is copied down and completed from `replies.jsonl`
   before anything new starts (decision 0165).
4. **Money.** The task reads the live key's `usage_monthly` and sets tonight's number of cases
   (§8). If the key endpoint cannot be reached, the night refuses.
5. **Later scores.** Each case coded without the NTSB's codes has its record fetched again; when
   the codes are there, the score is written (§6.4).
6. **The queue.** Closures on or after 23 September 2026 that are not yet settled, oldest closure
   first (ties by case key), up to tonight's number (§6).
7. **Fetch and code.** Each case's record and docket are fetched, and the loop runs at the standard
   price through the sync driver. The run folder is copied to the bucket after each case.
8. **Close the run.** The closure records, with the hashes of §9.3, and the run's manifest are
   written. Then `nights/<date>/night.json` and the night's manifest, with the night's finished
   mark, are written, and the one metric is published.
9. **Rebuild the export** from every run folder and score file (§10).

*Example (invented):* on 14 October the recorder finishes at 03:22. At 06:00 the task finds 4
closures from that night, $0.71 used this month, so up to 27 cases are allowed. It codes the 4,
writes a later score for a case coded on 9 October, and rebuilds the export by 06:14.

## 6. Which cases are coded, and when they are scored

### 6.1 Every watched closure, once, at closure

The queue, the seen rule and the order are S3.3's (decision 0157): every watched case closed on or
after 23 September 2026, coded once. A case seen is never tried again. **The daily limit of 50
(decision [0167](../decisions/0167-the-live-shadows-daily-limit-is-raised-to-50.md)) goes**, and
the night's size comes from money (§8). `live.queue.DAILY_LIMIT` is removed.

### 6.2 The launch

**What is done** (decision 0179):

- **The launch is S4's first cloud night.** The backfill list, every closure from 23 September 2026
  to that night, is fixed then and written to the run folder with its count and SHA-256; the
  ledger holds the manifest's hash. The 60 cases S3.3 coded on the Mac are coded again in the
  cloud. The Mac's runs were a rehearsal, and their folders are never uploaded.
- At about 30 cases a night (§8), a backfill of about 70 (estimate: S3.3's 60, its 2 queued cases,
  and closures since) drains in about three nights.
- **No early runs.** Open cases are not coded before closure: the recorder found no docket that
  arrived before its case closed (§1). The export carries the count of open cases holding a docket,
  for S5's Open cases page.

### 6.3 Scored at coding

When a case is coded, it is scored at once against the verdict in the same record, which the scorer
reads and Ellery never sees (decision [0013](../decisions/0013-evidence-synthesis-verdict.md)). The
grades are the board's (§10.3), computed by the harness's scoring code.

### 6.4 Scored later, when the codes arrive later

A closed record can lack the NTSB's codes. **What is done** (decision 0174):

- Such a case is coded and marked "coded, awaiting the NTSB's codes".
- Each night its record is fetched again from the NTSB API. The recorder's store holds no verdict,
  so it cannot answer this.
- When the codes are there, the night appends one line to `scores/<date>.jsonl`: the case, both
  code lists, the NTSB's cause statement, the grades, the SHA-256 of the record the verdict came
  from, and the date.
- After 7 nights without codes, an alert is sent, and the nightly re-check goes on.
- **Verdict revisions are not followed.** A score, once written, stands.

## 7. Failures, retries and alerts

### 7.1 Fetch failures

A case whose record or docket fetch fails is not seen, so it returns. S3.3 let it return without
limit. **What is done** (decision 0175):

- A failed fetch **counts** against a case only on a night when other cases fetched.
- An **outage night**, when every fetch failed, counts against no case and sends one alert.
- After 3 counted failures, an alert is sent. After 7, the case is settled as "not coded:
  unreachable", and that result is final.
- The counts are kept in `nights/<date>/night.json`.

### 7.2 Alerts

**What is done** (decision 0177): the task publishes one email per condition to an SNS topic. Each
email names the kind and the counts, never a case number. The kinds:

- before any spend: `recorder-not-finished`, `store-unsound`, `version-refused`, `key-unreachable`;
- during the night: `fetch-failed`, `outage`, `unreachable-3`, `unreachable-final`,
  `awaiting-codes-7`, `money-held-back`;
- from outside the task: a CloudWatch alarm on the one custom metric (one data point per finished
  night) fires when no night has finished for 30 hours. It treats missing data as breaching, so a
  task that crashes or never starts is caught. The plan confirms the alarm's period rule against
  AWS's documentation.

**Cost: none expected.** SNS's first 1,000 email notifications a month are free; CloudWatch's free
tier covers 10 custom metrics and 10 alarm metrics, and the recorder's stack uses none (external,
the AWS SNS and CloudWatch pricing pages, read 2026-10-10). If the first bill shows a CloudWatch
charge, the alarm and metric are removed, and the task sends one summary email each night instead.

### 7.3 The runbook

Every alert kind, and every message `ntsb-live run` can print, has a row in the S4 runbook
(`docs/runbooks/live-cloud-nights.md`): what it means and what Andy does, usually nothing, because
the next night retries. The two messages S3.3 left without a row get rows and failure kinds:
`fetch-failed` for a fetch or docket error (`apps/live/__main__.py`, which now also names the
runbook row instead of "Tell Claude if it happens again"), and `store-unsound` for the store
check (`store/db.py`).

### 7.4 What a failed night costs

Nothing is lost. Work done stays in the bucket; a half-finished case resumes at the price of its
unsent calls; a case is never coded twice, because the seen rule reads the bucket.

## 8. Money

**What is done** (decision 0170):

- **A separate OpenRouter key for live runs**, used only by the cloud task. Andy manages its limit
  on OpenRouter: **$10 a month**, reset monthly. The development key keeps the $40 monthly guard,
  counted from `data/runs` as now.
- **The cloud's spend counter** reads `usage_monthly` from `GET /api/v1/key` with the live key
  (external, OpenRouter's API reference for that endpoint, read 2026-10-10: it returns `limit`,
  `limit_remaining`, `limit_reset` and `usage_monthly`). If the endpoint cannot be reached, or the
  key has no limit, the night refuses.
- **The night's size by the full-cap rule:** cases = floor((cap − `usage_monthly`) ÷ $0.30), where
  the cap is $9, or the key's limit less $1 if that is lower. Every case may run to its $0.30 cap,
  so no night can pass the key's limit. The $1 margin covers the gap between a reply and its
  appearance in `usage_monthly`.
- **$0.30 a case stays**: it is a version 1 setting (decision
  [0144](../decisions/0144-one-per-case-cap-for-every-arm.md)).
- The $0.04 projection, the $5 month of decision
  [0163](../decisions/0163-the-live-shadows-caps.md) and the daily limit go on the cloud path. The
  live path no longer counts against the $40 guard, since the container's `data/runs` is empty, so
  carried item 3 no longer arises.
- **An alert when money holds a night back** (`money-held-back`).

*Why the full-cap rule does not starve the end of the month:* the allowance shrinks by what cases
really cost, about $0.005 each billed (estimate, from S3.2's held-out loop run, $2.0610 for 400
cases, scripted, `docs/results/s32-claims-heldout.txt`), not by $0.30. A month of 100 closures
uses about $0.51, so the allowance stays near 28 cases a night all month.

**S4's development spend** has its own line of $10 on the development key, counted by commit on
`s4-` branches (`stage_spend --stage s4`). No paid development run is expected: the names
measurement and the continuity check are free, and the saved fixtures already carry `model` and
`provider`. The S4 report states the first cloud nights' live spend apart.

## 9. The store

### 9.1 Run folders in a private bucket

**What is done** (decision 0172): the store is the S3.3 run folders, in a private, versioned bucket
in `NtsbLiveStack`. There are no SQLite predictions tables. This replaces the predictions tables
the roadmap and the S3 specification (§11) gave S4. The run folders already hold every field those
tables were to hold (case, timestamp, answer, cost, commit), and the site reads them through the
export (§10).

The bucket holds four kinds of file:

- **`runs/<run id>/`**: one run folder per night, S3.3's files (the spec, the run record, the case
  results, the trail, the replies, the raw records in `inputs.jsonl`, the closure records), with
  `manifest.json`; on the launch night, `backfill.json`. A folder is copied up after each case;
  once its run is finished, nothing in it is written again.
- **`scores/<date>.jsonl`**: the later scores written that night (§6.4).
- **`nights/<date>/`**: `started`, `night.json` (the counts, retry counts, alerts sent and money
  held back) and `manifest.json` (the night's files, with their sizes and SHA-256s, and the
  night's counts).
- **`export/board-1/`**: rebuilt from scratch each night (§10).

**No path holds a case number**, except the export's per-case files, whose cases are on the public
board. The ledger's role reads only manifests (§11), so it never needs a file that names a case.

Old versions of export files are kept 30 days; other files' old versions are kept. The task role
cannot delete, so a bad write is recoverable from the previous version. Nothing in the bucket is
committed to git.

**Cost:** under a cent a month (external, AWS price list for eu-west-2, read 2026-10-10: S3
Standard $0.024 a GB-month, $0.0053 per 1,000 writes; estimate, about 100 KB a case, from the Mac's
S3.3 run folders, ad-hoc, `du`).

### 9.2 Closure record version 2

The closure record becomes `live-closure/2`: version 1's fields, plus the hashes of §9.3, plus the
replying models and providers. Only version 2 is written to the bucket.

### 9.3 The docket, frozen by its hashes

S3.3 deleted a case's documents after its run, and the closure record kept only titles and
statuses, so the docket a case was coded from could not be shown later. **What is done** (decision
0176): the closure record adds the SHA-256 of each fetched file and, for each model call, the
SHA-256 of the request's messages, in call order. No document or text is kept. This is an audit
trail: anyone holding the NTSB's file can show it is the one coded from, and the request hashes show
what was sent without publishing it.

*Added 2026-10-12 (final review, wave A):* two further files exist so a night killed part-way can
be resumed exactly.

- **`dockets.json`** (`live-dockets/1`), in the run folder. It is written before the run's first
  request, and the first push carries it. For each case it holds the case number, the case key, the
  SHA-256 of the raw listing page, the SHA-256 of the parsed listing (`entries_sha256`: each
  entry's index, title and link, sorted by index; no title is stored), each document's SHA-256 by
  listing index, and the indices of the first read choice. The closure records take their hashes
  from this file, so they carry what the run first saw. A resume fetches the dockets again and
  compares the case, the key, the parsed-listing hash, the document hashes and the first offering.
  The raw page's hash is not compared, because a page can carry bytes that change from one fetch to
  the next. Any difference refuses the night with the alert `docket-changed`, before any call. The
  preferred design, dropping the one changed case and resuming the rest, could not be built:
  the harness refuses to resume a run whose case list differs. So the whole run waits behind a
  changed docket until a person decides (runbook, "Tell Claude").
- **`nights/<date>/state.json`**, a copy of the shared `nights/state.json` taken at the night's
  end. The night's manifest lists the copy, never the shared file, because the shared file is
  rewritten the next night and would fail the ledger's check of a finished night.

A resume that cannot proceed for a reason of its own (a missing `dockets.json`, an unreadable
reply row) is refused as `resume-failed`, also with a runbook row. A docket that fails to fetch on
resume stays the `fetch-failed` stop and counts against no case.

## 10. The export, `board/1`

### 10.1 Two kinds of file

**What is done** (decision 0173). The export is JSON, and every file carries `"format": "board/1"`.

**`index.json`**, the board and the site-wide counts:

- **the build stamp**: when the export was built, the commit that built it, the model, and the
  model's published training cut-off with its source (`sources.TRAINING_CUTOFFS`, already in the
  closure record; S5 §13);
- **the counts**: open cases watched; open cases holding a docket; closures per night; cases coded,
  not coded (by kind), and awaiting the NTSB's codes;
- **one row per closed case, newest closure first**: the case number, the date closed, the days
  from the accident to closure (S5's "Took"), the aircraft as category and engines (for example
  "Aeroplane, 1 piston"), the agent's and the NTSB's first occurrence codes, each as code and label,
  and the grade.

**`cases/<case number>.json`**, one opened case and its trail:

- **the facts**: state, kind of flight, injury level, and documents read as "3 of 7";
- **the withheld line**: when the case was coded (UTC), the commit, the prompt version, and the
  model and provider that replied;
- **the agent's answer**: its ordered occurrence codes, its findings, its cause statement, its
  confidence and the abstain flag, each code with its label;
- **the NTSB's verdict**: its ordered occurrence codes, its findings and its cause statement;
- **the comparison**: a mark on each occurrence code (same place, other place, not in the other
  list); the findings split into both, NTSB only and agent only; and the finding scores against the
  findings the NTSB flagged as in the cause (decision
  [0029](../decisions/0029-live-headline-is-the-finding-score.md) makes that the live headline, so
  S5 has it to show);
- **the trail**: each belief's first code, cause statement, confidence, whether it changed from
  the belief before, and Ellery's account of the evidence at that point (`evidence_narrative`, the
  text that takes the place of the investigator's factual narrative; Andy, 2026-10-10: "in case it
  is wanted in S5"; whether S5 shows it is S5's choice); each read choice's documents, each with its position, its title, read,
  skipped or scan only, and the agent's note; the coding lookups (tool and arguments); and each
  step's cost, with the case total;
- **for a case not coded**: its failure kind and one fixed plain sentence for that kind, chosen in
  code, never the failure text itself.

Titles, the agent's text and the NTSB's cause statement pass through the names step first (§12.2).

*Added 2026-10-11 (Task 11b, at the S5 session's request; decision 0173 item 4, so still
`board/1`):* five optional fields, all `null` when unknown. `mkey` (the NTSB's internal case key,
for the docket link) on each row and each case file. `BuildStamp.launched_on` (the date the
launch's backfill list was fixed, decision 0179) and `BoardRow.backfilled` (true, false, or null
when there is no backfill); the list itself is never exported. `DocumentChoice.pages` (the
docket manifest's page count, carried by closure record version 2's `DocumentLine`) and
`DocumentChoice.not_offered_reason` (`not_pdf`, `photo_only` or `fetch_failed`, only on a
`not_offered` document). `not_offered` means a document the reader could not offer as text,
other than a scan; it never means a withheld document. The schema lists these fields as required because every file we write carries them; a reader should still treat a missing key as null.

*Added 2026-10-12 (final review, wave A), `not_offered_reason`'s full set:* the field takes five
values, still all inside `board/1`. The three above stand. `already_read` means the document was
read at an earlier choice, so it was not offered again. `over_size_limit` means a readable
document that was not on offer and not read before; in the loop as built a readable document is
left out only by being read earlier (a call over the prompt-size ceiling stops the case instead,
decision 0152), so S5 should treat `over_size_limit` as rare. The committed sample shows both new
values.

*Added 2026-10-12 (final review, wave A, at the S5 session's request):* two changes to the
bucket, neither a change to a `board/1` file.

- **The finished mark.** After a night's export is uploaded, the last upload is
  `export/board-1/_finished.json`, `{"format": "board-finished/1", "built_at", "commit"}`, taken
  from the index's build stamp. It is written after every case file and `index.json` has uploaded,
  and only if all of them succeeded, so a reader that sees the mark newer than its last copy knows
  the export is whole. A failed upload leaves the earlier mark in place.
- **Bucket events.** The live bucket sends its events to EventBridge (`event_bridge_enabled`), so
  S5 can rebuild the site when the mark changes. This adds CDK's bucket-notification helper (a
  Lambda function and its role, with `s3:PutBucketNotification` on this bucket only), which Andy
  sees at `cdk deploy`.

### 10.2 What the export never holds

The registration; the explanation written for a non-expert; any document text; the evidence fingerprint; an aircraft's make and model;
personal names; and anything about an open case beyond the counts. A test reads every string in an
export built from invented runs against this list, using the boundary test's method.

*Amended 2026-10-11 (decision 0183):* "make and model" applies to the export's fields. Prose
(Ellery's text, the coding lookups' free-text arguments, the NTSB's cause statement) may name them.
The case's own registration is replaced with `[name]` in prose and titles.

*Added 2026-10-12 (final review, decision 0184):* the registration replaced is every aircraft's
registration, not only the first, matched whole and without regard to case. A registration shorter
than 3 characters is left out, because it would also match tokens such as "N1". The same exact
parts apply to titles (§12.2).

### 10.3 The grades

A case's grade is one of six: **same first code** (top-1), **same codes in another order** (in the
agent's three but not first: top-3 less top-1), **different**, **abstained**, **not coded**, and
**awaiting the NTSB's codes**. The grades and the marks come from the harness's scoring code, so the
board's grades are the measures the Methods page reports. S5 writes the one sentence on where the
two codings differ.

### 10.4 What S5 builds against

- The format is a set of typed models in `live/export.py`. A JSON Schema file generated from them
  is committed (`docs/schemas/board-1.schema.json`), and a test fails if the two drift apart. Any
  language can check a file against it.
- **An invented sample** is committed under `tests/fixtures/board/`: a case for each of the six
  grades, a scan-only document, a docket read in two read choices, and an amateur-built aircraft.
  It must pass the schema.
- **The version rule:** adding an optional field keeps `board/1`; removing, renaming or changing the
  meaning of a field makes `board/2`.
- `ntsb-live export --from <folder> --out <folder>` builds an export from a local copy of the
  bucket, for S5's development.

## 11. The ledger

**What is done** (decision 0178):

- **A daily job**, `.github/workflows/ledger.yml`, at 10:00 UTC. It signs in through a read-only
  role (GitHub's OpenID Connect, as the recorder's deploy role does), allowed to list the bucket's
  `runs/` and `nights/` prefixes and to read only `runs/*/manifest.json` and
  `nights/*/manifest.json`. For each new manifest it appends one line to `ledger.jsonl` on the
  `ledger` branch: the date, the run id or night, the night's counts where the manifest holds them,
  and the manifest's SHA-256. It prints no file's contents.
- **The `ledger` branch** allows no force push and no deletion, and needs no pull request. Setting
  that protection is a GitHub change; Claude asks Andy first.
- **The live task never has write access to the repository.** The role is created by Andy's
  `cdk deploy`.
- **Before the merge**, a scheduled workflow runs only from `main`, so the job also runs on each push
  to the S4 branch, and the role trusts `main` and that branch. The close-out commit removes the
  branch's trust; Andy deploys that change after the merge.
- **`ntsb-live verify-ledger`** hashes the bucket's manifests again, checks each folder against its
  manifest, and compares both with the ledger.

*Why:* the roadmap's tamper evidence (design notes: commit hashed rows to git). A reader of the
public ledger sees only lines added, each at a known date; Andy can show the bucket still matches.

## 12. The open-split fence, and names

### 12.1 The fence

Decision [0024](../decisions/0024-open-split-enters-measurements-only-as-numbers.md) stands as S3.3
built it (§8.3 there). Live cases enter a measurement only as counts: the S4 report is counts only,
and a test checks it holds no case number. The export is not a measurement; it is the board, and it
lives in the private bucket and is never committed. The invented sample holds invented cases only.
Alert emails name kinds and counts only.

### 12.2 Names on the board

Decision [0049](../decisions/0049-the-name-line-is-the-public-surface-not-the-repository.md) item 2: no personal name
in any output this project produces, absolutely. Titles, Ellery's text and the NTSB's cause
statement reach the board, and any of them can hold a name.

**What is done** (decision 0180):

- **Titles:** every capitalised word that is neither in the committed title vocabulary nor in the
  word list is replaced with `[name]` (`docket/title_vocab.py`'s rule, applied through
  `live/names.board_title`, which takes the case's names as well).
- **Ellery's text (cause statements, notes and accounts of the evidence) and the NTSB's cause
  statement:** the words that
  rule replaced in that case's own titles, and the owner and operator strings of decision
  [0046](../decisions/0046-known-owner-and-operator-names-are-replaced-in-document-text.md)
  (`docket/attach.py`'s `redact_known_names`), are replaced.
- **The word list ships in the package.** Today it is `tests/fixtures/words.txt`, which the image
  does not hold, and the slim image has no system dictionary. It moves to package data beside
  `vocab/title_words.txt`, and the title check moves from `scripts/check_fixtures_redacted.py` into
  the library.
- **A free measurement first**, on `dev-400`'s two arm C noise-floor runs
  (`20261001T201506-fd6053f-dev-400-C` and `20261001T201648-fd6053f-dev-400-C`) and their records:
  in how many cases do Ellery's cause statements, notes and accounts of the evidence, and the
  NTSB's cause statement, hold a word flagged in that case's own titles, and in how many do they
  hold any flagged word at all? Each kind of text is counted apart. Counts only, `docs/results/s4-names-dev.txt`, from `scripts/s4_names_probe.py`. Fixed before it
  runs: if no case holds a flagged word outside the rule, the rule stands. If any does, Andy chooses
  between applying the full title rule to Ellery's text too, which also replaces brand and place
  names, and keeping the rule and publishing its limit. For the accounts of the evidence, which are
  long and summarise documents that name people, a third choice is open: the field stays in
  `board/1` but is left empty until a stronger rule exists.
- *Amended 2026-10-11 (decision 0182):* the measurement found flagged words outside the rule in
  seven kinds of text, and Andy chose exact parts only. Prose (Ellery's text, the coding lookups'
  free-text arguments, the NTSB's cause statement) has only owner and operator strings replaced;
  titles keep the title rule. The second bullet above is replaced.
- *Amended 2026-10-12 (decision 0183):* prose has every aircraft's registration replaced as well as
  the owner and operator strings, matched whole and without regard to case; a registration shorter
  than 3 characters is left out.
- *Added 2026-10-12 (final review, decision 0184):* titles have the case's exact parts replaced
  first (owner and operator strings and every registration, any case), and then the title rule
  runs. A name the rules cannot recognise is not replaced; in titles that includes a name made only
  of ordinary words, such as a common surname or given name. `names.NAMES_LIMIT` holds the sentence
  the S4 report prints, in place of the count "as a floor".
- **The limit is published either way:** the rule replaces what it can recognise, the Methods page
  says so, and the S4 report gives the count of words replaced as a floor.

## 13. Tests and continuous integration

- **No AWS in the tests.** The cloud seams take narrow protocols, as `store/sync.py`'s `S3Like`
  does, and are tested against in-memory fakes (corrected 2026-10-10, while writing the plan: this
  line first named `tests/s3_probe_fixtures.py`, which holds S3.1 probe trails, not an S3 fake); and `NtsbLiveStack` by CDK template assertions, as
  `tests/test_infra_stack.py` does for the recorder. The template tests check that the task role
  cannot delete, that the ledger role reads only manifests, and that the schedule is disabled
  unless the context enables it. The recorder's template tests stay unchanged and pass.
- **One night, end to end, offline:** every seam faked, the NTSB fetch replaying saved records and
  the model replaying scripted replies. Separate tests cover resume, an outage night, the money
  hold-back, a later score, each alert kind, the same-day marker, and the refusal of a paid run
  outside the image.
- **The fingerprint:** the reach test and the mutation test cover the selection keys; continuity on
  `fd6053f` is re-shown.
- **The export:** the invented sample passes the schema; the export from the offline night passes
  it; the never-holds test (§10.2); the committed JSON Schema matches the models.
- **The names step:** the moved title check keeps its tests; new tests cover replacement in cause
  statements and notes.
- **The ledger:** the workflow's file is checked as `tests/test_ci_workflow.py` checks CI's (its
  permissions, its triggers, no step that prints a file); `verify-ledger` is tested on invented
  folders.
- **`make s4-dry-run`:** one cloud night's checks against the real store and bucket, with no model
  call. Free.

## 14. Order of work

1. **The fingerprint and the model pin** (§3): the second invented record, the re-pin and
   continuity, the literal model name, and replying model and provider on trail rows. Before any
   cloud night.
2. **`board/1`** (§10): the models, the JSON Schema, the invented sample. **S5 can start here**,
   on its own branch, with nothing from AWS.
3. **Names** (§12.2): the measurement, Andy's reading, then the names step in the library.
4. **The queue and the night** (§5 to §8): the money rule, retries, later scores, closure record
   version 2, the same-day marker, alerts.
5. **The cloud seams and the export builder** (§9, §10).
6. **`NtsbLiveStack`, the image script and the runbook** (§4, §7.3).
7. **The ledger** (§11).
8. **Andy's deploy and the first cloud night**, after asking Andy (§4.3).
9. **The backfill, a fresh closure, the test alert and alarm, the Mac key's removal, the report and
   the close-out** (§15).

## 15. When S4 closes

**What is done** (decision 0181). S4 closes when all seven hold:

1. `VERSION_1` is re-pinned with continuity shown, before any cloud night;
2. the scheduled task has run the backfill until it drained, with no one intervening;
3. at least one fresh closure has been coded and scored by the scheduled task on the night after it
   closed (06:00 UTC the next day);
4. the ledger job has committed those runs' manifest hashes;
5. a test alert email has been received, and the missed-night alarm has been shown to fire by a
   deliberate state test;
6. an export built from the real store passes the `board/1` schema, and the counts-only S4 results
   file (`docs/results/s4-live.txt`, from `ntsb-live report`) is committed from its script;
7. the Mac's key is removed.

**Time limit:** if no fresh closure arrives within 14 days after the backfill drains, S4 closes on
the rest and says so.

This meets the roadmap's done means in the form 0154 left it: a case closing causes it to be coded
and scored without anyone intervening.

## 16. Decisions S4 takes

- [0168](../decisions/0168-the-fingerprint-covers-several-events.md): the fingerprint covers
  several events; version 1 is re-pinned.
- [0169](../decisions/0169-the-model-is-pinned-by-name-and-the-replying-model-recorded.md): the
  model is pinned by name, and the replying model and provider are recorded.
- [0170](../decisions/0170-live-runs-have-their-own-key-and-the-full-cap-rule.md): live runs have
  their own key and limit; a night's size by the full-cap rule.
- [0171](../decisions/0171-live-nights-run-as-a-scheduled-fargate-task.md): live nights run as a
  scheduled Fargate task, from a pinned image; the Mac is retired.
- [0172](../decisions/0172-the-store-is-run-folders-in-a-private-bucket.md): the store is run
  folders in a private bucket, with a nightly export.
- [0173](../decisions/0173-the-board-export-format-board-1.md): the board export format, `board/1`.
- [0174](../decisions/0174-scored-at-coding-or-when-the-codes-arrive.md): scored at coding, or when
  the codes arrive.
- [0175](../decisions/0175-fetch-failures-are-counted-and-every-message-has-a-runbook-row.md):
  fetch failures are counted, and every message has a runbook row.
- [0176](../decisions/0176-the-docket-is-frozen-by-its-hashes.md): the docket is frozen by its
  hashes.
- [0177](../decisions/0177-alerts-by-email-and-one-free-alarm.md): alerts by email, and one free
  alarm.
- [0178](../decisions/0178-a-daily-ledger-of-manifest-hashes.md): a daily ledger of manifest hashes.
- [0179](../decisions/0179-the-launch-is-the-first-cloud-night.md): the launch is the first cloud
  night; no early runs.
- [0180](../decisions/0180-names-on-the-board.md): names on the board.
- [0181](../decisions/0181-s4s-closing-rule.md): S4's closing rule.
- [0182](../decisions/0182-names-on-the-board-after-the-measurement.md): names on the board, after
  the measurement: exact parts only. *Added 2026-10-12.*
- [0183](../decisions/0183-make-and-model-in-prose-registration-replaced.md): make and model may
  appear in prose; the registration is replaced. *Added 2026-10-12.*
- [0184](../decisions/0184-names-in-document-titles.md): names in document titles: exact parts and
  the title rule, the limit published. *Added 2026-10-12.*
- [0185](../decisions/0185-a-resumed-night-pays-what-is-left-and-codes-the-same-docket.md): a
  resumed night pays only what is left, and codes the docket it began with. *Added 2026-10-12.*

## 17. Done means (S4)

A case closing causes it to be coded and scored without anyone intervening, its results stored in
the private bucket, hashed in the public ledger and exported in `board/1` for the site, under
version 1, with spend bounded in code and on OpenRouter, and every failure reaching Andy by email.

## 18. Not in S4

- **The site** (S5). S4 delivers the export and its format, not pages.
- **Early runs** on open cases (§6.2).
- **Version 2** of the agent, the precedent tool, and the structured expected-change field
  (decisions [0140](../decisions/0140-the-precedent-tool-after-s4-as-a-measured-v2.md),
  [0164](../decisions/0164-what-no-longer-arises-in-s33.md)).
- **Arm B on live cases** (decision
  [0159](../decisions/0159-closure-runs-are-scored-as-counts-only.md)).
- **Following verdict revisions** (§6.4).
- **A database.** Run folders and an export only (§9.1).

## 19. Risks

- **OpenRouter changes the key endpoint's fields.** The night refuses and alerts
  (`key-unreachable`); nothing is spent.
- **The provider behind `openai/gpt-6-luna` changes.** The replying model and provider are recorded
  and counted (§3.2).
- **The NTSB API is down for days.** Outage nights count against no case (§7.1); the queue waits.
- **No fresh closure for weeks.** The 14-day limit (§15).
- **CloudWatch bills the alarm.** The fallback is a nightly summary email (§7.2).
- **A name the rule cannot recognise reaches the board.** The measurement comes first, and the
  limit is published (§12.2).
- **Building an x86 image on an ARM Mac is slow**, under emulation. It is done once per image.
- **The ledger job runs in public.** Its role reads only manifests, which name no case, and it
  prints nothing it reads (§11).

## 20. What changes in the roadmap at merge

- S4's entry gains a dated note: the live run is at closure; the store is run folders and an
  export; the predictions tables are not built (0172).
- S5's entry loses "scheduled Fargate task", which S4 built, and keeps the site's hosting.
- `CLAUDE.md`'s "SQLite predictions store" and "Scheduler and resolution watcher" lines are updated
  to say what S4 built.

---

## Glossary

- **Alarm**: a CloudWatch rule that sends an alert when a metric does not arrive as expected.
- **Backfill**: the closures from 23 September 2026 to the first cloud night, coded oldest first
  from that night.
- **`board/1`**: the export's format and version, which S5 reads.
- **Conditional write**: an S3 write that succeeds only if the file does not exist yet, so two
  writers cannot both make it.
- **Execution role**: the permissions Fargate uses to start the task: pulling the image, writing
  logs, reading the keys.
- **Export**: files rebuilt each night from the store, shaped for the site, holding only what the
  site may show.
- **Fresh closure**: a case that closes after the backfill list is fixed.
- **Full-cap rule**: a night takes only as many cases as could each run to the $0.30 cap within the
  money left this month.
- **Grade**: the board's one-word result for a case (§10.3).
- **JSON Schema**: a standard file that describes a JSON format, so any language can check a file
  against it.
- **Ledger**: an append-only public list of hashes, which shows that results were not changed later
  without showing the results.
- **Manifest**: a list of a folder's files, each with its size and SHA-256, so a copy can be
  checked.
- **Seam**: a point where the code reaches outside itself, with a local version and a cloud version
  behind one interface.
- **Settled**: coded, not coded with a final reason, or unreachable. A settled case leaves the queue.
- **Task role**: the permissions the running program has.
- **Template assertion**: a test that builds a CDK stack into its CloudFormation template and checks
  the resources and permissions, with no deploy.
- **Version 1**: Ellery's loop as frozen at `fd6053f`, with its label and settings.
