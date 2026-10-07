# Runbook — Live shadow mornings

*For S3.3. Specification: `docs/specs/2026-10-07-s3-3-live-shadow-design.md` (sections 4, 8
and 9). Decisions: 0157 to 0164.*

**What this is.** Once a day, after the recorder's night run, you start one command. It takes
the cases the NTSB has just closed, reads their documents, lets the agent (Ellery, version 1)
write a verdict for each, and records the result. The NTSB's own verdict for each case is
scored later. The command writes only to your computer. It never changes the recorder's store.

Words in **bold** the first time they appear are in the glossary at the end.

---

## 1. Before the first morning

1. Do not push code to the branch while a morning is unfinished. See section 5.
2. Check that the disk has at least 5 GB free. A 10-case morning adds about 175 MB while it
   runs. The command deletes most of it when the run is finished (section 7).
3. Plug the laptop into mains power and **keep the lid open** for the whole morning. The
   command runs `caffeinate`, which stops the laptop sleeping when idle, but a closed lid
   still puts it to sleep.

## 2. When to run

- **Not before about 03:45 UTC** (04:45 UK time in summer; 03:45 in winter). The recorder's
  night run usually finishes at about 03:45 UTC. If you start earlier, the command refuses
  (section 6, "recorder has not finished").
- **Before 09:00 UTC.** After 09:00 the command prints a warning, because the batch service is
  slower after about 12:00 UTC.
- The first paid morning uses `LIMIT=1`. It codes one case only. You look at the summary, then
  later mornings run without a limit.

## 3. The commands

Run these in your own terminal, from the main project folder.

1. Log in to AWS. This lets the command read the recorder's store from S3.

   ```
   aws login --profile ntsb
   ```

2. (Optional, free.) Check everything without any model call:

   ```
   make s33-dry-run
   ```

   It opens the store, builds the queue, fetches one case and its docket, and prints what a
   morning would do. It writes no run folder.

3. Run the morning. The first one:

   ```
   NTSB_PAID_BRANCH=s3-3-live-shadow scripts/paid_run.sh s33-morning LIMIT=1
   ```

   Every later one:

   ```
   NTSB_PAID_BRANCH=s3-3-live-shadow scripts/paid_run.sh s33-morning
   ```

   `paid_run.sh` makes a clean copy of the branch, sets the model key from the password store,
   and runs `make s33-morning`. That target first checks two spending lines (S3's $50 and
   S3.3's own line), and only then starts `ntsb-live run`. A morning takes about 1 to 2 hours.
   Leave the terminal open.

Only one morning can run at a time. The command locks `live.lock` in the runs folder.

## 4. What the summary means

The command prints counts only. It names no case.

| Line | Meaning |
|---|---|
| `run` | The run folder's name (date, commit, `live`, arm `C`). |
| `coded` | Cases the agent gave a verdict for. Each has a closure record. |
| `not coded, <reason>` | Cases that were closed but not coded, with the reason (for example `format`, `cap`, `no docket`, a guard refusal). The record is written. The case is not tried again. |
| `returned to the queue` | Cases that failed before the agent saw them (a fetch failed). They are tried again tomorrow. |
| `still queued` | Closed cases waiting for a later morning. A morning takes at most 10 cases. |
| `cost` | The computed cost, and the amount the batch service billed (it may arrive later). |
| `minutes` | How long the morning took. |
| `bytes freed` | Space deleted at the end (section 7). |
| `warning` | Something to read. For example, "started after 09:00 UTC". |

The monthly live cap is $5. If the next morning would pass it, the command refuses.

## 5. An interrupted morning

If the command stops (power cut, network loss, `Ctrl-C`, a crash), the run folder stays on
disk with its batches. **Run the same command again.** The command finds the unfinished run,
reuses the batches already paid for, and finishes it. It uses the same cases as the first start.

**Finish (or resume) an interrupted morning before any code is pushed to the branch.**
`paid_run.sh` resets its copy to the branch tip, and a resume on a different commit is
refused. If code is pushed while a run is unfinished, that run is stranded. To avoid it,
check before you push anything: a folder under `data/runs` whose `run.jsonl` has no
`finished` time is an unfinished run. Run the morning command again first.

## 6. When the command refuses

A refusal is one line on the screen and the command stops with code 1. Nothing is spent
unless the line says so.

| What you see | What it means | What to do |
|---|---|---|
| `the agent's prompt version is ..., not the frozen v1`, or `Ellery's text differs from version 1` (**fingerprint** mismatch) | The text the agent would send is not the text measured on held-out. A code or package change moved it. | Stop. Do not run again. Tell Claude. The cause is a change on the branch or in `uv.lock`. |
| `the recorder has not finished a run on <date>` | The store is not tonight's yet. | Wait. Try again after the recorder finishes (usually 03:45 UTC, at the latest about 05:31 UTC). If it is later than 06:00 UTC, check the recorder (`docs/runbooks/recorder-bridge.md`). |
| `the day's limit of 10 cases is reached` (printed as a warning; exit code 0) | Ten cases were already coded today. | Nothing. Run again tomorrow. |
| `... past the $5.00 monthly cap` | This month's live spend plus this morning's projection passes $5. The cases stay queued. | Do not run. Wait for next month, or ask Andy to change the cap by a decision. |
| `refused: ... would pass the line (decision 163)` | The S3.3 stop: S3.3 has spent its $10. (The S3 line, $50, is checked first, with decision 0128.) | Do not run. Report the numbers to Andy. |
| `AWS refused the request ... run aws login --profile ntsb` | The AWS login has expired. | Run `aws login --profile ntsb`, then run the same command again. |
| `another morning is running` | A second morning holds the lock. | Wait for it. If you are sure none is running (the laptop restarted), run again: a lock does not survive a restart. |
| `the unfinished live run ... has no inputs.jsonl` or `... no backfill held anywhere` | The folder of an interrupted run is damaged. | Do not delete it. Tell Claude. |
| `refusing: ... has uncommitted changes` or `holds ... commit(s) not on origin` (from `paid_run.sh`) | The paid-runs copy has unpushed or uncommitted work. | Follow the message. Commit and push from that folder. Never discard. |

## 7. Disk space and cleanup

- When a run is finished, the command deletes that run's documents from the live cache and
  deletes the store working copy. It prints the space freed.
- A run that stopped part-way keeps its documents until it finishes, so a resume needs no
  second fetch.
- Run folders are kept. They are about 1 MB each. Do not delete them: they hold the closure
  records, the manifest and the spend that the monthly cap counts.
- To see space: `du -sh data/live-docket data/runs`. If the live docket folder is large (more
  than 2 GB) and no morning is unfinished, tell Claude before deleting anything.
- The large development cache (`data/docket`, about 28 GB) is not touched by a morning.

## 8. After a morning

- Read the summary. Tell Claude the counts (coded, not coded, queued, cost, minutes).
- Do not open the run folder's case files in an editor or share them. They hold text from open
  cases. Only counts leave the computer (`make s33-report`, a later step).
- Do not run `ntsb-eval` on a live run. It refuses (decision 0024).

---

## Glossary

- **AWS.** Amazon's cloud service. The recorder keeps its store (a database file) there.
- **`aws login --profile ntsb`.** A command that signs you in to the AWS account for this
  project. The sign-in lasts a few hours. It is how the command is allowed to read the store.
- **S3.** The AWS part that keeps files. The store is one file in S3. The morning command
  downloads a copy and never uploads.
- **Store.** The recorder's database of cases, documents and nightly runs.
- **Recorder.** The program that runs each night, watches the NTSB's cases and notes what changed.
- **Closed case.** A case where the NTSB has published its final report.
- **Coded.** The agent gave a verdict for the case (what happened and why).
- **Queue.** The closed cases waiting to be coded, oldest first.
- **Batch.** A way of sending many model requests at a lower price. The answer comes back later,
  usually within an hour or two.
- **Run folder.** A folder under `data/runs` holding one morning's records.
- **Closure record.** The record for one case: what the agent was given, what it said, and when.
  It holds no document text.
- **Manifest.** A list of the run folder's files with their checksums, so a changed file is seen.
- **Fingerprint (`+t`).** A short code of all the text the agent sends. It must equal version 1's.
  If it differs, the agent is not the one that was measured.
- **Cap.** A spending limit. Here: $0.30 for one case, $5 for one month of live runs, and the
  S3.3 line.
- **Lock.** A small file that stops two mornings from running together.
- **UTC.** The world time standard. UK summer time is UTC plus 1 hour.
