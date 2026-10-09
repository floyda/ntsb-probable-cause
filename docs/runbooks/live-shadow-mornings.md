# Runbook — Live shadow mornings

*For S3.3. Specification: `docs/specs/2026-10-07-s3-3-live-shadow-design.md` (sections 4, 8
and 9). Decisions: 0157 to 0166.*

**What this is.** Once a day, after the recorder's night run, you start one command. It takes
the cases the NTSB has just closed, reads their documents, lets the agent (Ellery, version 1)
write a verdict for each, and records the result. The NTSB's own verdict for each case is
scored later. The command writes only to your computer. It never changes the recorder's store.

Words in **bold** the first time they appear are in the glossary at the end.

---

## 1. Before the first morning

1. Do not push code to the branch while a morning is unfinished. See section 5.
2. Check that the disk has at least 5 GB free. A 10-case morning adds about 175 MB while it
   runs, so a 50-case one (the most in a day, decision 0167) adds about 900 MB. The command
   deletes most of it when the run is finished (section 7).
3. Plug the laptop into mains power and **keep the lid open** for the whole morning. The
   command runs `caffeinate`, which stops the laptop sleeping when idle, but a closed lid
   still puts it to sleep.
4. Check that `pass` is unlocked. Mornings need no AWS login: the `ntsb-live` profile reads a
   key from `pass` (section 9). You need `aws login` only for the one-time setup and to replace
   the key. The `ntsb` profile is a role profile that borrows the `default` login, so plain
   `aws login` refreshes it. `aws login --profile ntsb` does not work.
5. You do not type the store location or the AWS profile. The command does it for you
   (`scripts/live_env.sh`): it sets `AWS_PROFILE` to `ntsb-live` and, if `NTSB_STORE` is not set,
   asks AWS for the recorder's bucket name and uses `s3://<bucket>/recorder.sqlite`. It also
   installs the AWS parts it needs (`--extra aws`: boto3 and awscrt, pinned in `uv.lock`) for that one run. If the
   lookup fails it stops with a message (section 6).
6. `scripts/paid_run.sh` reads the NTSB key (password-store entry `api/ntsb`) and the model key
   (`api/openrouter`) for you. It never prints them.
7. Do the free check first, from the place named in section 3:

   ```
   NTSB_PAID_BRANCH=s3-3-live-shadow scripts/paid_run.sh s33-dry-run
   ```

   It opens the store, builds the queue, fetches one case and its docket, and prints what a
   morning would do. No model is called and no run folder is written. Do not use `make
   s33-dry-run` on its own: only `paid_run.sh` passes the NTSB key. Run it after 03:45 UTC,
   like a real morning. Do the first paid morning only when it ends with a summary and no
   refusal.

## 2. When to run

- **Not before about 03:45 UTC** (04:45 UK time in summer; 03:45 in winter). The recorder's
  night run usually finishes at about 03:45 UTC. If you start earlier, the command refuses
  (section 6, "recorder has not finished").
- **Any time after that.** There is no batch window (decision 0165): a live run uses the
  standard price and answers in seconds. Start whenever you can keep the laptop open for about
  half an hour.
- The first paid morning uses `LIMIT=1`. It codes one case only. You look at the summary, then
  later mornings run without a limit.

## 3. The commands

Run these in your own terminal. **Where to run from:** until S3.3 is merged, the main project
folder is on an old `main` that has no `scripts/paid_run.sh` and no `s33-` targets. Run from this
branch's worktree: `/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/.claude/worktrees/s3-3-live-shadow`.
`paid_run.sh` then runs the target in its own clean checkout of the branch tip. After S3.3 is
merged, run from the main project folder. **Start one paid command at a
time.** Do not start a second `paid_run.sh` while one is running: it resets the shared paid
checkout under the first one before the lock of `ntsb-live` can refuse it.

1. Check that `pass` is unlocked. (No `aws login` is needed.)
2. The first morning:

   ```
   NTSB_PAID_BRANCH=s3-3-live-shadow scripts/paid_run.sh s33-morning LIMIT=1
   ```

   Every later one:

   ```
   NTSB_PAID_BRANCH=s3-3-live-shadow scripts/paid_run.sh s33-morning
   ```

`paid_run.sh` makes a clean copy of the branch and runs `make s33-morning`. That target first
checks two spending lines (S3's $50 and S3.3's own line), and only then starts `ntsb-live run`.
A morning takes about 1.2 to 1.6 minutes a case (9 cases took 14.2 minutes and 10 took 12.4, on
2026-10-08 and 2026-10-09), so a full day of 50 cases (decision 0167) takes about an hour.
Keep the laptop open and leave the terminal open until it ends. The calls go one at a time at the
standard price, so there is no queue to wait in.

Only one morning can run at a time. The command locks `live.lock` in the runs folder.

## 4. What the summary means

The command prints counts only. It names no case.

| Line | Meaning |
|---|---|
| `run` | The run folder's name (date, commit, `live`, arm `C`). |
| `coded` | Cases the agent gave a verdict for. Each has a closure record. |
| `not coded, <reason>` | Cases that were closed but not coded, with the reason: one of `schema` (the reply broke its format), `model` (the model failed), `leak` (the leakage guard stopped it), `cap` or `cap: context` (the case reached its cost cap or the context limit), `failed` (the loop failed at a step), `aborted`, `missing result`, or `other`. The record is written. The case is not tried again. |
| `returned to the queue` | Cases that failed before the agent saw them (a fetch failed). They are tried again tomorrow. |
| `still queued` | Closed cases waiting for a later morning. A UTC day takes at most 50 cases (decision 0167; 10 until 2026-10-09). A case that comes back as `returned to the queue` on three mornings in a row: tell Claude (it would hold the closing rule back). |
| `cost` | The computed cost. A live run is not a batch, so no separate billed amount comes back. |
| `minutes` | How long the morning took. |
| `bytes freed` | Space deleted at the end (section 7). |
| `warning` | Something to read. For example, "completed the records of an earlier run". |

The monthly live cap is $5. If the next morning would pass it, the command refuses. The check
projects $0.04 a case (the standard price, with room for large dockets). That is a ceiling the
caps use, not the expected spend: the standard-price mornings cost about $0.005 to $0.007 a case.
A day that has an unfinished run to resume and then a fresh run can code up to 100 cases (50 a
run since decision 0167; see section 5), so a day's cost can reach about $4.00 projected
(100 x $0.04), and the real cost is far less. The all-purpose $40 monthly guard is checked too
(section 6).

## 5. An interrupted morning

If the command stops (power cut, network loss, `Ctrl-C`, a crash), the run
folder stays on disk. **Run the same command again.** (A message may say `--resume`; `ntsb-live`
has no such option. Just run the same command.) The command finds the unfinished run, reuses
the replies already on disk (they are not paid for again), and sends only the calls not yet answered. It uses the same cases as the first start.

**Finish (or resume) an interrupted morning before any code is pushed to the branch.**
`paid_run.sh` resets its copy to the branch tip, and a resume on a different commit is
refused. If code is pushed while a run is unfinished, that run is stranded. To avoid it,
check before you push anything. A folder under `/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/runs` is an unfinished live run if either:

- it has no `run.jsonl` file at all (a power cut or a kill leaves this), and its `spec.json`
  says `"sample": "live"`; or
- its `run.jsonl` has no `finished` time.

If you find one, run the morning command again first. Use the absolute path of the main
folder's runs (`/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/runs`); a
worktree's own `data/` is empty.

**A morning that only resumes.** If a run was unfinished, the command resumes it and stops. It
does not start today's new cases in the same command. After it ends, run the command **once more**
to code today's cases.

**A stranded run** (code was pushed first, and the resume is refused with `cannot resume ...
commit_sha was ... and is ... now`). Push nothing more. Tell Claude. The recovery, which Claude
does with you: read `commit_sha` in the run's `spec.json`; create a branch named `s3-recover-<date>`
at that commit and push it; run
`NTSB_PAID_BRANCH=s3-recover-<date> scripts/paid_run.sh s33-morning` **once**, to finish that run
on the code that began it; then go back to `NTSB_PAID_BRANCH=s3-3-live-shadow` for every later
morning. Do not delete the run folder.

## 6. When the command refuses

A refusal is one line on the screen and the command stops with code 1. Nothing is spent
unless the line says so. The first column quotes the message the program prints. A test checks
that each quoted text is in the program.

| What you see | What it means | What to do |
|---|---|---|
| `the agent's prompt version is` ... `morning runs version 1 only (decision 0161)` (**fingerprint** mismatch; the full line reads "..., not the frozen s3-v1+ge17fecdc66ec+te7811b387b31: a live morning runs version 1 only") | The text the agent would send is not the text measured on held-out. A code or package change moved it. | Stop. Do not run again. Tell Claude. The cause is a change on the branch or in `uv.lock`. |
| `these settings are not version 1's` | A setting that changes what Ellery receives or how it is asked (the model, the reply budget, the cap, the temperature, the statistics file, the pass-reasoning switch) is not the one version 1 was measured with. The line names which. Nothing was fetched or spent. | Stop. Do not run again. Tell Claude. |
| `the recorder has not finished a run on` | The store is not tonight's yet. | Wait. Try again after the recorder finishes (usually 03:45 UTC, at the latest about 05:31 UTC). If it is later than 06:00 UTC, tell Claude (`docs/runbooks/recorder-bridge.md`). |
| `the day's limit of` | The day's limit (50 cases since decision 0167; 10 before) was already coded today. This is a warning, not a refusal: the exit code is 0 and no run is made. | Nothing. Run again tomorrow. |
| `cannot resume` ... `commit_sha` ... `when the run started, and is` | An unfinished run was begun on one commit, and the tree is on another now (code was pushed first). The run cannot be resumed on different code. Nothing was spent. | Stop. Push nothing. Tell Claude. The recovery is in section 5 ("A stranded run"). |
| `monthly guard of` | The month's spend and open reservations, plus this morning's projection, pass the all-purpose $40 monthly guard (`monthly_budget_usd`). Nothing was fetched and no run was made. | Do not run. Tell Claude. |
| `monthly cap (decision 163)` | This month's live spend plus this morning's projection passes $5. The cases stay queued. | Do not run. Tell Claude. Only a new decision changes the cap. |
| `would pass the line` | A spending line is reached. `paid_run.sh` prints which: S3's $50 (decision 0128) or the S3.3 line (decision 163, $10 of S3.3's own). | Do not run. Tell Claude the numbers printed. |
| `the AWS login has expired` | The AWS sign-in ended. With the `ntsb-live` profile this is unlikely: it means `pass` is locked or the key is no longer valid. | With `ntsb-live`: unlock `pass`, check the key (section 9), then run the same command again. With an `aws login` profile: run `aws login`, then run the same command again. |
| `AWS error (` | Another AWS problem: no credentials, a wrong profile, a missing bucket, no permission, no network. The class name in brackets says which. | Do not just log in again. Tell Claude the line. |
| `profile could not read the stack` | `scripts/live_env.sh` could not ask AWS for the bucket name. Most likely `pass` is locked or the `ntsb-live` profile is missing. AWS's own error follows the line. | Unlock `pass`, check that the profile exists (`aws configure list-profiles`), and try again. If it fails again, tell Claude. |
| AWS's own message after the line above says "Unable to locate credentials" or "AccessDenied" (not our text) | The key in `pass` is missing, wrong or was deleted, or the user lacks the permission. | Replace the key (section 9). If that fails, tell Claude. |
| The AWS command says the profile is "already configured with Assume Role credentials" (this is the AWS command's own message, not ours) | You ran `aws login --profile ntsb`. `ntsb` is a role profile that borrows the `default` login, so it cannot be logged in by itself. | Run `aws login` instead, then run the morning command. (Mornings use `ntsb-live` now, so this should not come up.) |
| `no store at` | The recorder's store is not at the location. | Tell Claude. Do not set `NTSB_STORE` by hand unless Claude says so. |
| `boto3 is not installed` | The AWS parts are missing in this run. | Tell Claude. (The make target installs them for each run; this means it was started another way.) |
| `NTSB_API_KEY is not set` | The NTSB key was not passed. | Start the morning through `scripts/paid_run.sh` as in section 3, not `make` alone. If you did, check that the `pass` entry `api/ntsb` exists, then tell Claude. |
| `OPENROUTER_API_KEY is not set` | The model key was not passed. | Same as the line above, for the entry `api/openrouter`. |
| `live_docket_dir must differ from docket_dir` | The live document folder is set to the development one. This would mix open-case documents with the development cache. | Do not run. Unset `NTSB_LIVE_DOCKET_DIR`, or tell Claude. |
| `no recorded training cut-off for` | The model has no recorded training cut-off date. | Do not run. Tell Claude. |
| `live run folders appeared during the run` | Two live run folders were made during one morning. | Do not delete anything. Tell Claude. |
| `resumed with the records it began with` or `the finished live run` | The folder of an interrupted or finished run lacks the file that holds the cases it began with. | Do not delete it. Tell Claude. |
| `is resumed with no backfill held anywhere` | The folder of an interrupted run lacks its backfill list. | Do not delete it. Tell Claude. |
| `another morning is running` | A second morning holds the lock. | Wait for it. If you are sure none is running (the laptop restarted), run again: a lock does not survive a restart. |
| `has no --resume option` | A run was cancelled (a batch run only; live runs are not batches, so this should not appear). The records so far are written. | Run the same command again. If it appears, tell Claude. |
| `has uncommitted changes` (from `paid_run.sh`) | The paid-runs copy holds unsaved work. | Follow the message. Commit and push from that folder. Never discard. |
| `not on origin/` (from `paid_run.sh`) | The paid-runs copy holds a commit that is not pushed. | Follow the message. Push it. |

## 7. Disk space and cleanup

- When a run is finished, the command deletes that run's documents from the live cache and
  deletes the store working copy. It prints the space freed.
- A run that stopped part-way keeps its documents until it finishes, so a resume needs no
  second fetch.
- Run folders are kept, in `/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/runs`. They are about 1 MB each. Do not delete them: they hold the closure
  records, the manifest and the spend that the monthly cap counts.
- To see space: `du -sh /Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/live-docket /Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/runs`. If the live docket folder is large (more
  than 2 GB) and no morning is unfinished, tell Claude before deleting anything.
- The large development cache (`data/docket`, about 28 GB) is not touched by a morning.

## 8. After a morning

- Read the summary. Tell Claude the counts (coded, not coded, queued, cost, minutes).
- Do not open the run folder's case files in an editor or share them. They hold text from open
  cases. Only counts leave the computer (`make s33-report`, a later step: run it by hand, from this
  branch's worktree until S3.3 is merged, with `NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data` set; never
  through `paid_run.sh`, and not while a morning runs: it takes the same lock).
- Do not run `ntsb-eval` on a live run. It refuses (decision 0024).

---

## 9. The live shadow's AWS key

**What it is.** `ntsb-live-reader` is an **IAM user** in the project's AWS account. It exists
only for the morning command. Its **access key** is in `pass` as `aws/ntsb-live-reader`, and the
`ntsb-live` profile reads it from there (`credential_process`).

**What it can do.** Two things only:

- read one file: `recorder.sqlite`, in the recorder's bucket (`s3:GetObject`);
- look up one stack, `NtsbRecorderStack`, so `scripts/live_env.sh` can find the bucket name
  (`cloudformation:DescribeStacks`).

It cannot write, delete or list anything. It cannot read any other file. The file it reads is
public NTSB case data.

**Mornings.** You do not run `aws login`. `pass` must be unlocked, nothing else.

**Replace the key every few months.** Do this in order. Each `aws` command needs
`--profile ntsb` after `aws login`.

1. `aws login`
2. List the keys: `aws iam list-access-keys --user-name ntsb-live-reader --profile ntsb`.
   Note the old key's `AccessKeyId`.
3. Make a new key and store it in `pass`, so it is never shown on screen. The `--query` part
   writes the three JSON fields the profile reads (`Version`, `AccessKeyId`, `SecretAccessKey`);
   `-f` replaces the old entry. The key is held in a shell variable first and stored only if `aws`
   succeeded, so a failed `aws` (an expired login, or the user already holding two keys) leaves
   the old entry as it was:

   ```
   key="$(aws iam create-access-key --user-name ntsb-live-reader --profile ntsb --query 'AccessKey.{Version: `1`, AccessKeyId: AccessKeyId, SecretAccessKey: SecretAccessKey}' --output json)" && printf '%s\n' "$key" | pass insert -m -f aws/ntsb-live-reader; unset key
   ```
4. Check the new key works: `aws sts get-caller-identity --profile ntsb-live` prints an ARN ending
   `user/ntsb-live-reader` (no secret). Then run a free check:
   `NTSB_PAID_BRANCH=s3-3-live-shadow scripts/paid_run.sh s33-dry-run`.
5. Delete the old key:
   `aws iam delete-access-key --user-name ntsb-live-reader --access-key-id <old id> --profile ntsb`

**Remove it all at S4** (the cloud task then has its own role). Each with `--profile ntsb` after
`aws login`:

1. `aws iam delete-access-key --user-name ntsb-live-reader --access-key-id <id>`
2. `aws iam delete-user-policy --user-name ntsb-live-reader --policy-name live-shadow-read-store`
3. `aws iam delete-user --user-name ntsb-live-reader`
4. `pass rm aws/ntsb-live-reader`, and remove the `ntsb-live` profile from the AWS config.

Decision: `docs/decisions/0166-a-read-only-aws-key-for-the-live-shadow.md`.

---

## Glossary

- **AWS.** Amazon's cloud service. The recorder keeps its store (a database file) there.
- **`aws login`.** A command that signs you in to the AWS account for this
  project. The sign-in lasts a few hours. Mornings no longer need it (section 9); you use it only
  for the one-time setup and to replace the key.
  `ntsb` is a role profile that borrows the `default` login, so this refreshes it;
  `aws login --profile ntsb` fails with "already configured with Assume Role credentials".
- **Profile.** A named set of AWS sign-in settings. Mornings use `ntsb-live`. The profile `ntsb`
  is used only for setup and key replacement.
- **IAM user.** A sign-in identity inside an AWS account, with its own permissions. `ntsb-live-reader`
  is one. It is not a person; it exists so the morning command can read two things.
- **Access key.** A pair of long secret strings (an ID and a secret) that lets a program sign in
  as an IAM user without a password. Unlike `aws login`, it does not end after a few hours. Keep
  it in `pass`; never paste it in a chat or a file.
- **`credential_process`.** A line in an AWS profile that names a command to run to get the key.
  Here it is `pass show aws/ntsb-live-reader`, so the key stays in `pass` and not in an AWS file.
- **S3.** The AWS part that keeps files. The store is one file in S3. The morning command
  downloads a copy and never uploads.
- **Bucket.** A named place in S3 that holds files. The recorder's bucket name is looked up
  for you.
- **Store.** The recorder's database of cases, documents and nightly runs.
- **Recorder.** The program that runs each night, watches the NTSB's cases and notes what changed.
- **Closed case.** A case where the NTSB has published its final report.
- **Coded.** The agent gave a verdict for the case (what happened and why).
- **Queue.** The closed cases waiting to be coded, oldest first.
- **Standard price.** The provider's normal service: one request at a time, answered in seconds,
  at about twice the batch price per token. Live runs use it (decision 0165).
- **Batch.** A way of sending many model requests at a lower price. The answer comes back later.
  Live runs no longer use it.
- **Run folder.** A folder under the main folder's `data/runs` holding one morning's records.
- **Closure record.** The record for one case: what the agent was given, what it said, and when.
  It holds no document text.
- **Manifest.** A list of the run folder's files with their checksums, so a changed file is seen.
- **Fingerprint (`+t`).** A short code of all the text the agent sends. It must equal version 1's.
  If it differs, the agent is not the one that was measured.
- **Cap.** A spending limit. Here: $0.30 for one case, $5 for one month of live runs, and the
  S3.3 line.
- **Lock.** A small file that stops two mornings from running together.
- **UTC.** The world time standard. UK summer time is UTC plus 1 hour.
