# S3.3 — Live shadow: design

*Drafted 2026-10-07 from a design session with Andy (2026-10-06 to 2026-10-07), after S3.2 closed
(pull request #27, release v0.9.0, merge commit `832a121`) and the S5 site design merged (pull
request #28, commit `0e467bd`, decisions 0154 to 0156). Status: Approved (2026-10-07, Andy: "Spec approved!"). This is the specification
for sub-stage S3.3 of [the S3 specification](2026-09-30-s3-agent-loop-design.md) (§3, §11), which
holds the design S3 shares. The implementation plan is written from this document separately, in
`docs/plans/`.*

**How to read this.** Each section says what is done, then why, with an example where one helps.
Terms in **bold** on first use are in the glossary at the end. Numbers here are of five kinds, and
each is labelled:

- **scripted** numbers cite the committed script and results file that produced them;
- **external** numbers come from a published page or a bill, cited by page and the date read;
- **ad-hoc** numbers were counted during the design session by a throwaway command. They are not
  citable, and S3.3 re-derives any it relies on with a committed script;
- **estimates** are arithmetic, and are replaced by measured figures in the As-built record;
- **run records** are read from a run folder (not committed).

**Decision records.** The records this design needs are written in the plan's first task, not with
this document. They are numbered from 157 on (0154 to 0156 were taken by the S5 site design); §15
lists them.

---

## 1. What S3.3 is for

S3's specification gave S3.3 one job: run the loop on real cases, every night, with nothing
locked or published, and measure the mechanics and the cost (§11). S3.2 then found the loop worse
than the fixed pipeline on held-out cases (`docs/results/s32-claims-heldout.txt`), and the S5 site
design settled three things S3.3 must follow:

- **The live run is at closure** (decision 0154). Dockets arrive on the night the NTSB closes a
  case, which is also the night it publishes its verdict, so the agent codes a case then, from
  the docket as published, with the verdict withheld by the split and guard. No answer is locked
  before the verdict.
- **The board is backfilled** from the recorder's first night, 23 September 2026 (decision 0155):
  every watched case that closed on or after that date is coded, abstains and failures included.
- **The board runs Ellery, version 1**: the loop frozen at `fd6053f` (decision 0156), although
  the fixed pipeline measured better. A later version replaces it only by beating it in a
  registered comparison.

**So S3.3 rehearses, on your machine, exactly what S4 will run in the cloud.** It codes real
closures with Ellery version 1, scores each one the same morning as counts only, records what S4
and the site need, and measures how often it fails, how long it takes and what it costs. Nothing it
produces is published; its runs never become board rows.

**S3.3 changes nothing Ellery receives.** No prompt, tool, step or limit changes. The one new piece
near the loop is the rendered-text fingerprint (decision 0143), which proves this in code (§7).

## 2. Where S3.3 starts

- **The agent:** Ellery, version 1: the loop frozen at `fd6053f`, prompt version
  `s3-v1+ge17fecdc66ec+p947fac1c86a4` (decisions 0139, 0142, 0156); GPT-6 Luna at reasoning
  `medium` (0073), reply budget 8,000 tokens (0084), evidence v1 (0120), S3's statistics (0129),
  the two kept guidance files (0098, 0106).
- **Its held-out score:** occurrence top-1 23.5% [19.2%, 27.5%] against the fixed pipeline's 33.0%
  (scripted, `docs/results/s32-claims-heldout.txt`).
- **What the recorder has seen** (scripted, `docs/results/s5-recorder-report-2026-10-06.txt`, 14
  finished nights, 23 September to 6 October 2026):
  - no docket appeared before its case closed; 46 appeared on the same nightly run as the
    closure; 5 of the 936 cases watched from the first night already held one;
  - 300 documents appeared at those closures, and none strictly after a closure;
  - 704 cases held a preliminary narrative when first seen, and 17 more gained one while still
    open.
- **Closures come in bursts:** 47 cases closed in those 14 nights, all on three dates (23
  September, 1 October and 2 October 2026; ad-hoc, from the S5 session's read-only query of the
  store; §10's script re-derives it).
- **The model's training cut-off:** GPT-6 Luna has a "May 18, 2026 knowledge cutoff" (external,
  <https://developers.openai.com/api/docs/models/gpt-6-luna>, read 2026-10-07). Every case that
  closes from 23 September 2026 closed after it, so its verdict cannot be in the model's training
  data. The accidents themselves happened earlier, so a preliminary report or a news story about
  one could be.
- **Spend:** S3 has spent $11.46 of its $50 line (scripted, `scripts/stage_spend.py --stage s3`,
  2026-10-07), leaving $38.54, all of it S3.3's by decision 0150. October's spend so far is $11.46
  of the $40 monthly guard (ad-hoc, `month_spent`, 2026-10-07).

## 3. Which cases are coded

### 3.1 The queue

**A case enters the queue** when the recorder first records its status leaving Ongoing, to
Completed or N/A, on or after 23 September 2026 (the store's status history; the same rule as
`Store._closure_runs`). **It leaves the queue** once a live run has coded it, or recorded it as
not coded (§6). Nothing else enters or leaves.

**Order:** oldest closure first; cases that closed on the same night by the recorder's case key
(mkey). The order never depends on anything about the case itself.

**At most 10 cases a day** (Andy, 2026-10-07), counted per UTC calendar day across every live run
started that day. Cases over the limit wait for the following mornings, ahead of later closures.

*Why a queue and not a skip:* skipping cases over the limit would leave them uncoded, and choosing
which cases are coded is selection, which decision 0155 rules out. *Why 10:* closures come in
bursts of about 16 a night on average (ad-hoc, §2), so the limit spreads a burst over two or three
mornings; it bounds one day's worst case at 10 × $0.30 = $3 (§9).

*Example:* 40 cases close in one night. The next morning codes the 10 that closed earliest by
case key; the remaining 30 are coded over the next three mornings, before any case that closes
later.

### 3.2 The backfill rehearsal and fresh closures

- **The backfill list** is the queue as it stands on the first live morning: every closure from
  23 September 2026 to that night. It is fixed then and never changed. It is written into the
  first run's folder (local, §8). Because it names open-split cases, it is never committed
  (decision 0024); the committed results file holds its count and the SHA-256 of the sorted list,
  so anyone holding the list can later show it was not changed.
- **A fresh closure** is a case that closes after the backfill list is fixed.
- **The backfill drains through the same queue**, at 10 a day. S4 codes the backfill again at
  launch with its own store, as decision 0155 says; S3.3's runs are a rehearsal and never become
  board rows. This rule is fixed now, so no one can later choose whichever of two draws looks
  better.

### 3.3 What is not run

- **No run on open cases.** Before closure a case holds no docket, and on the recorded facts
  alone the loop does no better than the no-model baseline (decision 0154; 15.0% against 17.7%,
  scripted, `docs/results/s32-claims-heldout.txt`, `docs/results/s1-bars.txt`).
- **No first pass over the roughly 960 watched cases.** The S3 specification's §11 outline
  planned one; decision 0154 item 6 points the shadow at closure runs and the backfill instead.
- **One run per case.** The 5 cases with an early docket are coded at closure like every other
  (0154 item 2). No case is coded twice, so a later trigger (decision 0122, `agent/later.py`) never
  happens on a live case; `later.py` stays built, tested and unused.

## 4. One morning, start to finish

**Andy starts it**, on a morning after the recorder's night:

```bash
aws login
NTSB_PAID_BRANCH=s3-3-live-shadow scripts/paid_run.sh s33-morning
```

*(Corrected 2026-10-08: `ntsb` is an assume-role profile on `default`, so the login is `aws login`.)*

`paid_run.sh` resets the clean paid-runs checkout to the branch tip, installs with `uv sync
--locked` and sets `UV_LOCKED=1` (§7.3), reads the OpenRouter key from `pass` without printing it,
and runs the `make` target, which keeps the Mac awake while it runs (`caffeinate -i`).

1. **Checks, before anything is spent** (all free; any failure stops the morning with nothing spent
   and nothing changed):
   - Ellery's rendered-text fingerprint equals version 1's (§7);
   - the recorder's run for today (UTC) has finished, read from the store's `runs` table;
   - an unfinished live run is resumed first, never left behind a new one (§6);
   - today's count is under 10;
   - the caps allow the run: the shadow's $5 this month, S3.3's $10 stop, the $40 monthly guard
     and S3's $50 line (§9).
2. **Read the store:** download today's `recorder.sqlite` into the live working file and open it
   read-only. It is never uploaded (§8.3).
3. **Build the queue** (§3.1) and take as many cases as today's limit allows. The first morning
   also writes the backfill list (§3.2).
4. **Fetch each of the morning's cases:** its record from the NTSB API, by its event date (the API
   has no single-case fetch; `data/api.py`, `cases_by_date_range`), then its docket listing and
   every PDF in it, as evaluation does (`docket/manifest.py`, `read_docket`). Photo-only entries
   and non-PDFs are not downloaded. Documents go to the live document cache, never the development
   cache (§8.2), at the existing floor of one request every 2 seconds.
5. **Split:** `split_record` with the preliminary narrative left out (§5), with the guard and marks
   as in evaluation (decisions 0016, 0077, 0078). The run notes whether the API still held a
   preliminary narrative.
6. **Code:** Ellery version 1 through the existing `AgentRunner`, unchanged, at the batch price
   (§4.1), with a $0.30 per-case cap (§9) and the prompt-size ceiling (decision 0152), in
   resumable batch rounds.
7. **Score** each case against the verdict in the same record (§10). Per-case scores stay in the
   run folder.
8. **Write** each case's closure record and the run's manifest (§8.1).
9. **Clean up** (§8.4) and **print a summary:** cases coded, not coded with reasons, left in the
   queue, cost (computed and billed), time taken, space freed.

**Timing.** The recorder's night usually finishes at about 03:45 UTC (scripted, the run summaries
of `docs/results/s5-recorder-report-2026-10-06.txt`), and at the latest at about 05:31 UTC (the
scheduler's retry window and the task's 90-minute limit, `infra/recorder_stack.py`). Checks and
fetching take about 3 minutes (estimate: about 7 documents a case, 300 documents over 46 closures,
at 2 seconds each), then 10 to 15 batch rounds take about 1 to 2 hours (estimate). The batch
service's published figures are a median of 7 minutes a batch, with batches sent after 01:00 UTC
finishing fastest and those sent between 12:00 and 19:00 UTC much slower (external,
<https://openrouter.ai/blog/announcements/batch-api/>, read 2026-09-24); S3.2's held-out runs
sent outside that window finished, more slowly (S3.2 As-built). The command warns when it is
started after 09:00 UTC, because rounds may then run past 12:00 UTC.

*Example (estimated):* on the morning of 8 October the queue holds 52 cases and the limit allows
10. The summary reads: "coded 9, not coded 1 (format), queued 42, $0.098 computed / $0.051 billed,
1 h 24 min, 170 MB freed."

### 4.1 The batch price

*(Superseded 2026-10-08 by decision 0165: live runs use the standard price through the sync driver.)*

Live runs use the **batch price** (Andy, 2026-10-07): half the standard price, and the same service
Ellery version 1 was measured on. Nobody watches a closure run as it happens, so speed buys
nothing. The roadmap's §4 says the live path does not use batch; that sentence was written for
answers on open cases, where speed might have mattered. Decision 0158 records the departure for
S3.3. S4 chooses its own service for the cloud.

## 5. The preliminary narrative is left out, and counted

The API is said to delete the preliminary narrative at closure (decision 0023; the roadmap §10).
That rests on S0's scan of closed cases, where it was empty in all 19,641; whether it is already
gone on the night of closure, when a closure run reads the record, has not been checked.
`split_record` treats it as evidence (`fields.py`, `EvidenceRole.PRELIM_NARRATIVE`), and the payload
renders every evidence role that holds a value (`model/client.py`, `Payload.from_evidence`).

**Every live run excludes `prelim_narrative`**, through the split's existing exclusion set. The
model's text is then identical to a record without one, so the fingerprint and the prompt version
are unaffected. **Each run records whether the API still held one**, and the results file counts
those cases.

*Why:* live runs then match evaluation whatever the API does on the night, which answers the S3
specification's §20 open question; and the count turns an unchecked assumption into a number for
S4. *Ruled out:* leaving it to the API (some runs could silently see evidence evaluation never had)
and reading it on purpose (a new input makes a new version; decision 0156 item 4).

## 6. Failures, resumes and the "seen" rule

**A case is seen once its first model call is sent.**

- **Within a case,** the loop's own rules apply unchanged: one retry for a broken call, then a stop
  at the per-case cap or the prompt-size ceiling.
- **A case that fails after it is seen is not tried again.** A format failure, a guard refusal, a
  stop at the cap or the ceiling: the case is recorded "not coded" with its reason and leaves the
  queue. A second try is a second draw, and choosing between draws is selection (0155). The board
  will show such a case as "Not coded" (the S5 Draft, §4).
- **A case that fails before it is seen returns to the queue.** The NTSB API or the docket site is
  down, or the store cannot be read: Ellery never saw the case, so trying again is not a second
  draw.
- **A run interrupted mid-round is resumed, not restarted** (`AgentRunner` with `--resume`; the
  replies and rounds files make a resume exact, S3.2 §4.3). A morning refuses to start a new run
  while an earlier live run is unfinished; it resumes that run first. Cases in an unfinished run
  are neither re-queued nor counted twice against the day's limit.
- **Unusual closures are coded and counted:**
  - no verdict in the record yet: coded, and left unscored (counted);
  - closed as N/A: coded, and scored only if it carries a verdict (counted);
  - no docket, or nothing readable: coded from the record, in docket state "none", as evaluation
    codes such a case (counted).

*Example:* on one morning the docket site fails for 2 of the 10 cases. Those two go back to the
queue untouched. Of the other eight, one document trips the guard: that case is recorded "not
coded: guard" and never tried again. The other seven are coded.

## 7. The rendered-text fingerprint

### 7.1 What it is

Decision 0143 set the principle: **the fingerprint covers what the agent receives, not the source
that builds it.** Today's `+p` hashes the source of ten files (`agent/texts.py:TEXT_SOURCES`,
decision 0133), so a comment edit moves the label though the model sees the same words.

**The new fingerprint, `+t`,** renders every fixed text the loop or arm B's tool post-pass can send,
from a fixed set of made-up inputs, and hashes the output:

- the system text and the seven tool definitions exactly as sent;
- each step's instruction, the read-or-skip menu (for a made-up docket holding readable, scan-only
  and unreadable entries), the move to coding and the answer and refinement texts;
- every tool-result wording, refusal line and retry message;
- a later trigger's opening (`later.py`, `texts.prior_summary`), though unused live.

The guidance files keep their own part, `+g`. The prompt version becomes
`s3-v1+ge17fecdc66ec+t<12>`. The letter `+r` is taken (tuning rounds), so the new part is `+t`.

**It replaces `+p` everywhere `+p` is used** (the loop's prompt version and arm B's post-pass
label), amending decision 0133, as 0143 provided.

### 7.2 Proving it

- **Continuity:** `+t` computed on `fd6053f`'s code equals `+t` on S3.3's code. Decision 0142 kept
  the ten text files unchanged through S3.2, so they must match; if they do not, work stops and Andy
  decides. Version 1's old and new labels stand side by side in `docs/results/s33-fingerprint-continuity.txt` and in code (`agent/version.py`), and decision 0161 cites both.
- **It cannot miss a text:** a mutation test changes each string that builds model text, in turn,
  and checks that `+t` moves or a test fails. A string that is not model text (an exception
  message, a log line) is listed with its reason.
- **The frozen-label test changes form:** `tests/test_s32_frozen.py` pins `+t` and the mapping, not
  the source hash. A dependency update that leaves the rendered text unchanged then passes; one that
  changes it fails, which is when it changes what the model sees (0143 item 6).
- **It is built first**, before any other S3.3 code touches the loop's modules.

### 7.3 A live run refuses on a mismatch, and records its environment

- **Every live run computes `+t` before any call** and refuses unless it equals version 1's,
  printing both values. The board's "Ellery, version 1" then means the exact text measured on
  held-out, checked in code on every run, not promised in a sentence. A change of text is a new
  version, which needs a registered comparison before it reaches the board (0156 item 4).
- **`scripts/paid_run.sh` installs with `uv sync --locked`** (it uses `--frozen` today) and exports
  `UV_LOCKED=1`, so every `uv run` in the `make` targets also refuses to run if `uv.lock` and
  `pyproject.toml` disagree (Andy, 2026-10-07). CI and the container image already use
  `--locked`.
- **Each live run records the SHA-256 of `uv.lock`** beside `+t`: the fingerprint proves the text
  Ellery received; the lockfile's checksum records the package versions that produced it.

*Example:* a `pydantic` release changes how one tool's arguments are written in the definition sent
to the model. The tests fail on the update's pull request. If it reached the paid-runs checkout
anyway, the morning would stop before any call with "Ellery's text differs from version 1",
naming both fingerprints.

## 8. Code, storage and the open-split fence

### 8.1 The `live` package and its three seams

A new package, `src/ntsb_probable_cause/live/`, named for what it becomes in S4, not for S3.3's
setting (Andy, 2026-10-07). One job per module:

- **the queue:** reads the store copy, lists closures (§3.1), applies the daily limit; the same
  code gives S5 its per-night closure count (§10);
- **fetching:** one case's record from the API, and its docket into the live document cache;
- **the morning:** the checks, the run through `AgentRunner`, scoring, records, cleanup;
- **the closure record and the manifest:** the per-run files S4 will load, each with a format
  version;
- **the report:** the counts-only results file (§10).

**The command is `ntsb-live`** (`apps/live/`), with `run` and `report`, kept apart from
`ntsb-eval`. In S4 the cloud task runs the same command.

**Three seams**, each with only its local version built in S3.3, so S4 adds a cloud version beside
it without editing the queue, the fetching, the run or the scoring:

1. **where results are written:** S3.3's **shadow setting** writes local run folders and is never
   published; S4 adds a setting that writes to its store;
2. **where spending is counted:** S3.3 reads the local run folders (`scoring/budget.py`); S4 adds
   the cloud's count;
3. **where the store copy comes from:** `store/sync.py`'s `pull` from `NTSB_STORE`, an `s3://` URL,
   the same in the cloud.

**The store gains one public, read-only method set** (closures since a date, today's run finished),
so `store/` stays the only code that touches SQLite.

### 8.2 Run folders, built to move

Live runs write to `data/runs`, where `paid_run.sh` already sends every paid run, so the $40 guard
counts their spending (`budget.month_spent` reads `*/run.jsonl` and `*/spend.jsonl` there). Each
carries the sample name **`live`**. Nothing in them is committed.

Andy asked that they can later be moved to a private S3 bucket, without designing the bucket now.
Four rules make that a plain copy:

1. **Self-contained:** each run folder holds everything needed to read it, with no absolute paths
   and no reference to a file outside it; the commit and the case ID are the only links out.
   Anything taken from the store, such as the closure night, is copied in.
2. **Versioned:** every file states its format version (`live-closure/1` and so on).
3. **No secrets:** no key, no AWS profile name, nothing from the environment.
4. **A manifest:** `manifest.json` lists every file with its size and SHA-256, so an upload can be
   checked file for file.

**The closure record**, one line per case, holds what S4 and the site need (decision 0154 item 5):

- the case ID, the closure night (from the store), and the days it waited in the queue;
- when it was coded (the first round sent and the last returned, UTC), the commit and the dirty
  flag, the prompt version with `+t`, the price variant, the model and reasoning level, the
  model's training cut-off (from a committed source constant naming the page and the date read),
  and the SHA-256 of `uv.lock`;
- each listed document by its listing position: its title, the docket reader's status for it (one
  of `read`, `unreadable: scan`, `unreadable: not a pdf`, `skipped: photo-only`, `fetch failed`;
  `docket/manifest.py`), and, for a document on offer, whether Ellery read or skipped it. Titles
  only: no document text;
- whether the API still held a preliminary narrative (§5); the outcome (coded, or not coded with
  its reason, a guard refusal included); the case's marks (decisions 0077, 0078); and the case's
  scores (§10).

The trail keeps its existing rule: no document title and no document text. Titles live only in the
closure record, joined to the trail by listing position.

**There is no "withheld as synthesis" document** (corrected 2026-10-07, after approval and before
the plan, when the plan's reading of `docket/` found it). Decision 0154 item 5 and the S5 Draft
(§6, §13) speak of a document "classed as synthesis" shown as withheld. No such class exists:
decision 0056 removed title-based classing, so every readable document is offered. Withheld text is
caught by the guard on the text itself: a probable-cause sentence in a document refuses the whole
case ("not coded: guard"), and an analysis or narrative sentence only marks the case (0077, 0078).
Decision 0160 says so, for S4 and S5.

*Example closure record (invented):* "closed 1 Oct; coded 2 Oct 07:42 UTC, waited 1 day; commit
4f2a9c1; prompt s3-v1+ge17fecdc66ec+t…; batch; model trained to 18 May 2026; documents: 1 Pilot
statement, read, Ellery read it; 2 Weather study, read, Ellery skipped it; 3 Photos, skipped:
photo-only; 4 Engine examination, unreadable: scan; marks: none."

### 8.3 The open-split fence, in code

Decision 0024: an open-split case enters a measurement only as numbers, and nothing from it may
reach development or evaluation. Live cases are open-split cases. Held in code, each with a test:

- **every development and evaluation command refuses a `live` run**: `ntsb-eval report`, `judge`,
  `check`, `tools`, `--latest` resolution, and the shared loader the S3 scripts use
  (`scripts/_s3_runs.py`);
- **live documents go to their own cache** (`data/live-docket/`, a setting beside
  `NTSB_DOCKET_DIR`), never the development cache;
- **nothing in the library or `ntsb-eval` imports `live`** (an import-linter contract);
- **`live` cannot reach the store's upload** (an import-linter contract and a test that a write to
  the store copy fails);
- **only the counts file is committed**, and a test checks it holds no NTSB case number and no case
  key.

### 8.4 Disk space and cleanup

Measured during the design (ad-hoc, `du`, 2026-10-07): the development docket cache holds 1,603
cases in 28 GB, about 17 MB a case; the held-out loop run's folder is 32 MB for 400 cases, about
80 KB a case; the store copy is 62 MiB; the disk had 70 GB free.

- **When a run is finished** (every case coded or not coded, its records and manifest written), the
  morning deletes that run's documents from the live cache and the store working copy, and prints
  the space freed. A run that stopped mid-round keeps its documents until it finishes, so a resume
  needs no second fetch.
- **Run folders are kept**: about 1 MB a morning (estimate), and they are what moves to S3 later.
- Without cleanup a 10-case morning would add about 175 MB, and about 100 closures a month about
  1.7 GB (estimates).
- The 28 GB development cache is outside S3.3's scope: it lets development runs repeat without
  fetching thousands of documents again.

## 9. Money

**Expected cost** (estimates, from the held-out loop run's $3.9270 computed and $2.0610 billed for
400 cases, scripted, `docs/results/s32-claims-heldout.txt`): about $0.0098 a case computed and
$0.0052 billed. The backfill, perhaps 60 to 100 cases by the first morning, about $0.60 to $1.00
computed; fresh closures, about 100 a month, about $1 a month computed. S3.3 in total: about $2 to
$4.

**The caps, each enforced in code before any call** (Andy, 2026-10-07):

- **$0.30 a case**, the cap version 1 was measured with on held-out (decision 0144), not the code's
  $0.15 default. With the daily limit, the worst possible day is $3.
- **$5 a calendar month for live runs.** Before each morning, the command adds this month's live
  spend to the queue's expected cost and refuses if that passes $5. The cases stay queued.
- **S3.3 stops for Andy when its own spend reaches $10.** Its own spend is S3's spend, counted by
  commit on `s3-` branches at billed cost (decisions 0128, 0135), less the $11.46 S3.1 and S3.2
  spent; so S3.3 stops at $21.46 on the line. This is enforced in code, which S3.2's own share was
  not (S3.2 As-built, "Known issues").
- The $40 monthly guard (0083) and S3's $50 line still apply.

*Example:* a month with a 60-case backfill (about $0.60) and 100 closures (about $1) spends about
$1.60, and the $5 cap never bites. If a fault made every case run to its $0.30 cap, the cap would
stop the shadow after about 16 cases, and the rest would wait.

**AWS.** S3.3 adds no AWS resource. Its only use of AWS is downloading the store each morning
(62 MiB), inside AWS's free allowance of 100 GB a month of data transfer to the internet (external,
<https://aws.amazon.com/blogs/aws/free-data-transfer-out-to-internet-when-moving-out-of-aws/>,
read 2026-10-07). For reference, the recorder costs about $0.40 a month (external, AWS Cost
Explorer, 1 September to 5 October 2026, read 2026-10-06: Fargate about $0.29 a month, the task's
public IP address about $0.10, S3 and the image registry about a cent).

**Paid mornings.** Andy is asked before the first paid morning, with its cost and duration stated.
After that, each morning may run within the $5 cap without asking again (Andy, 2026-10-07), and
each morning's cost and duration are reported.

## 10. Scoring and the report

**Each closure run is scored the same morning** against the verdict in the case record, which the
scorer may read and Ellery never sees (decision 0013). The measures are the board's: the first
occurrence code right; the NTSB's first code among Ellery's three but not first; different; plus
abstains and failures by reason (the S5 Draft, §4). Per-case scores stay in the run folder.

*Why:* it rehearses S4's scoring on real closure records, where evaluation never looked: an NTSB
code missing from the code tables Ellery and the scorer share, a case closed as N/A, a verdict not
yet in the record on the night. It costs nothing, and version 1 is frozen, so the number cannot
tempt anyone to tune it.

**The results file**, `docs/results/s33-live-shadow.txt`, written by
`scripts/s33_live_report.py` (`make s33-report`), counts only:

- **mornings:** runs, cases coded per run, the queue's length, days waited, time from first round
  to last;
- **money:** cost per case and per month, computed and billed;
- **outcomes:** the three grades with a 95% interval on "first code right", abstains, failures by
  reason (format, guard refusal, cap, prompt-size ceiling, fetch);
- **the new checks:** closures that still held a preliminary narrative, fingerprint refusals, NTSB
  codes missing from the code tables, closures without a verdict, closures as N/A;
- **the backfill list:** its count and SHA-256 (§3.2);
- **for S5:** closures per recorder night, from 23 September 2026 (the S5 Draft's §16 item 8
  asks for this script).

**It is printed alone.** Live and held-out numbers never share a figure (the roadmap's risks;
decision 0021), so no held-out score appears beside it. At about 50 to 100 cases its interval is
about ±10 points wide: an early sign, not a result.

*Example (invented):* "47 closure runs: first code right on 11, right code in another position on
6, different on 27, abstained 0, not coded 3 (format 2, guard 1). Interval for first code right:
13% to 37%."

## 11. When S3.3 closes

Fixed now, before any run (Andy, 2026-10-07):

**S3.3's live runs end once the backfill has drained and either at least one fresh closure has
been coded, or 14 days have passed since the first live morning with none coded.** Both parts are
read on the morning's UTC date. A fresh closure that arrives while the backfill is draining joins
the queue behind it, so it is coded after the drain. If the 14-day limit is what ends the runs, the
results file says so.

*Why:* the backfill, at 10 a day, exercises the queue over several mornings; one fresh closure
proves a new night's closures are picked up, which is the trigger S4 depends on. Closures come in
bursts, so the 14-day limit stops S3.3 waiting weeks for one. *Ruled out:* closing after the
backfill alone (it never shows a fresh closure being picked up) and four fixed weeks (more cases,
but S4's board will gather them anyway).

*Example:* the backfill is fixed at 52 cases on the first morning and drains over six mornings; on
the ninth day, three cases that closed overnight are coded; S3.3's live runs end. Had none closed,
the runs would have ended on the fifteenth day after the first morning.

After S3.3 closes, `ntsb-live run` stays available, and closures in the gap before S4 are covered by
S4's backfill rule (0155).

## 12. Order of work

1. **Records** (§15).
2. **The rendered-text fingerprint** (§7), with its continuity check on `fd6053f` and its mutation
   test, before any other S3.3 code touches the loop's modules.
3. **`paid_run.sh`**: `--locked`, `UV_LOCKED`, and a behaviour test with stand-in commands (§7.3).
4. **The store's read-only methods; the `live` package; `ntsb-live`; the fence** (§3, §4, §6, §8),
   with the tests of §14. Free.
5. **A free dry run** (`ntsb-live run --dry-run`): the checks, the store read, the queue and the
   fetch for the first case, with no model call; it prints what a morning would do.
6. **The first paid morning, with Andy's go-ahead**, limited to the queue's first case, to see one
   case end to end (estimate: about a cent, 15 to 30 minutes). It fixes the backfill list.
7. **Mornings** until the closing rule (§11), each within the caps.
8. **The report** (§10), then the close-out.

## 13. What S3.3 does about S3.2's carried issues

From the S3.2 As-built, "Known issues carried to S3.3":

- **`scripts/paid_run.sh` is checked statically only**: fixed (§7.3), because every morning now
  depends on it.
- **The frozen-label test fails on any dependency update that changes the tool schemas as sent**:
  replaced by the `+t` test (§7.2).
- **S3.2's share was not enforced in code**: S3.3's $10 stop is (§9).
- **Left, with the reason:** `ntsb-eval tools` has no resume, and arm B's stage-2 refinement and
  retries are not checked against the ceiling (arm B does not run in S3.3); `agent/drive.py`
  copying `loop._turn_chars` (unchanged, still pinned by a test); a resumed, partly answered round
  whose batch is cancelled (no new test; a live run resumes as any run does); `resolve_latest` and
  a non-UTF-8 `spec.json` (not on the live path); the wording points in decisions 0128, 0146 and
  0150 (corrected in the S3.2 As-built).

## 14. Tests and continuous integration

S3.3 adds tests that:

- `+t` renders every fixed text; each text-building string, changed, moves `+t` or fails a test;
  `+t` on `fd6053f`'s code equals `+t` on S3.3's; a live run with any other `+t` refuses before a
  call;
- the queue orders oldest first with the case-key tie-break; allows at most 10 cases per UTC day
  across runs; fixes the backfill list on the first morning and never changes it; removes coded and
  "not coded" cases; returns cases that failed before being seen; resumes an unfinished run rather
  than starting a new one;
- `live` cannot reach the store's upload, and a write to the store copy fails;
- the preliminary narrative never reaches Ellery's text, and its presence is recorded;
- a run folder copied elsewhere verifies against its manifest and reads back; it holds no absolute
  path and no secret; the trail holds no title or text; the closure record holds titles and
  statuses only, never document text;
- cleanup deletes documents only after a finished run;
- the $5 monthly cap, the $10 stop, the $40 guard and S3's line each refuse before any call;
- every development and evaluation command refuses a `live` run; the counts file holds no case
  number or case key;
- `paid_run.sh`, run with stand-in `git`, `uv`, `pass` and `make`, installs with `--locked`, sets
  `UV_LOCKED`, and keeps its existing refusals (main, unpushed commits, a dirty checkout).

The new import-linter contracts run in CI.

## 15. Decisions S3.3 takes

Written in the plan's first task, numbered from 157 on:

1. **0157** — S3.3's scope under decisions 0154 to 0156: closure runs and the backfill rehearsal,
   the queue at 10 a day, one run per case, the closing rule. *Session:* the entry rule, option A;
   the daily limit, queue and 10; the close, option A.
2. **0158** — Live runs on Andy's Mac in S3.3, at the batch price; amends the roadmap's §4 note on
   the live path; S4 moves them to AWS and chooses its own service. *Session:* where, option A;
   the price, batch.
3. **0159** — Closure runs are scored the same morning, as counts only, printed alone. *Session:*
   scoring, option A.
4. **0160** — The `live` package and its three seams; local run folders built to move to a private
   bucket; the open-split fence in code; the live document cache; cleanup; the closure record's
   document statuses, with the correction to decision 0154 item 5's premise that a document can be
   "classed as synthesis" (§8.2). *Session:* storage, option A with Andy's move rule; the package
   named `live`.
5. **0161** — The rendered-text fingerprint `+t` replaces `+p` (applies 0143, amends 0133), with
   version 1's old and new labels; a live run refuses on a mismatch; `--locked`, `UV_LOCKED` and
   the lockfile's checksum. *Session:* the fingerprint, option A; Andy's lockfile point.
6. **0162** — The preliminary narrative is left out of live runs and counted; answers the S3
   specification's §20 open question. *Session:* the preliminary narrative, option A.
7. **0163** — The caps: $0.30 a case, $5 a month for live runs, S3.3's $10 stop within S3's line,
   each in code. *Session:* the caps, option A.
8. **0164** — What no longer arises: the structured expected-change field (0148 item 4) moves to
   version 2, because it changes Ellery's text; `later.py` stays unused on live cases; Ellery is not
   told more documents may arrive, because at closure the docket is complete. *Session:* the
   summary after decisions 0154 to 0156.

## 16. Done means (S3.3)

1. The records of §15 are committed, and `+t` is built and shown continuous on `fd6053f` before any
   other S3.3 code touches the loop's modules.
2. `ntsb-live run` codes a queue end to end, resumably; every test of §14 passes in `make check`
   and in CI.
3. The live runs meet the closing rule of §11.
4. `docs/results/s33-live-shadow.txt` is committed, from its script.
5. The As-built record is appended to this document, the plan deleted, and the version set to
   0.10.0 (0017); the pull request is titled `S3.3: live shadow` and merged with a merge commit
   (0033).

## 17. Not in S3.3

- Any change to Ellery's text, tools, steps or limits; tuning; version 2 and the precedent tool
  (0140, 0156).
- The fixed pipeline (arm B) on live cases (0156; version 2's registered comparison needs it).
- Runs on open cases before closure; answers locked before the verdict (0154).
- Anything on AWS: the cloud task, its schedule, its key, its spend count (S4).
- The predictions tables, the hashed ledger and publishing (S4, S5).
- The structured expected-change field (version 2, §15 item 8).
- Transcription, the masked condition and the staged replay (still paused, decisions 0120, 0123,
  0151).

## 18. Risks

- **The fingerprint does not match on `fd6053f`**, or the mutation test finds a text the made-up
  inputs miss: work stops before any live run, and Andy decides.
- **A large burst before the first morning** makes the backfill long: at 10 a day, more than about
  100 cases would take more than ten mornings. If the backfill list holds more than 100 cases, Andy
  decides whether S3.3 waits for it to drain.
- **The verdict is not yet in the record on the closure night:** the case is coded and left
  unscored, and the count says how often; S4 learns when to score.
- **The NTSB uses a code the tables lack:** scoring counts it; the tables are not changed in S3.3.
- **A batch is slow or lost:** the run resumes (S3.1, S3.2); the queue keeps the day's cases.
- **The AWS login has expired** in the morning: the store read fails before any spend; log in and
  start again.
- **Disk space:** the cleanup of §8.4 keeps live documents to one run's worth.
- **Live results look different from held-out.** They are printed alone, with their interval, and
  read as a sign only (§10).

## Glossary

- **Arm B (the fixed pipeline):** every readable document, then every coding tool in a fixed order,
  then the ordering check. It measured better than the loop on held-out cases.
- **Backfill:** coding every watched case that closed between the declared start (23 September
  2026) and launch. S3.3 rehearses it once.
- **Batch price:** the provider's half-price service; requests wait in a queue and answers usually
  come back within minutes, at most 24 hours.
- **Billed cost / computed cost:** what the provider charged after cached-prompt discounts, and every
  token at the list rate.
- **Case key (mkey):** the NTSB's internal number for a case; it fixes the order of cases that
  closed on the same night.
- **Closure / closure run:** the night the NTSB closes a case and publishes its verdict; coding the
  case then, from the docket as published, with the verdict withheld.
- **Closure record:** the per-case line in a live run folder holding what S4 and the site need.
- **Ellery, version 1:** the loop frozen at `fd6053f`, as it runs on the board (0156).
- **Fence:** a rule held by code and tests, not by a sentence.
- **Fingerprint (`+t`):** a short code computed from the exact text the model receives.
- **Fresh closure:** a case that closes after the backfill list is fixed.
- **Guard refusal:** the split's check found withheld text, such as the NTSB's probable cause, in a
  document; the case is not shown to the model.
- **Interval (95%):** the range the true rate very likely lies in, given the number of cases.
- **Manifest:** a list of every file in a run folder with its size and checksum.
- **Mutation test:** a test that changes the code on purpose and checks that a check notices.
- **Open split:** cases with events from 2024 on; they enter a measurement only as numbers (0024).
- **Preliminary narrative:** the investigator's early account, published weeks after the accident
  and deleted by the API at closure.
- **Queue:** the closed cases not yet coded, oldest first, at most 10 coded a day.
- **Seam:** a narrow point where one implementation can be swapped for another without touching the
  rest.
- **Second draw:** running the same case again. Answers vary between identical runs, so choosing
  the better draw would flatter the result.
- **Seen:** a case whose first model call has been sent. After that, a failure is final.
- **Shadow setting:** the `live` package writing local run folders that are never published.
- **Training cut-off:** the last date the model's training data covers; 18 May 2026 for GPT-6 Luna.
- **`uv.lock` / `--locked`:** the file that pins every package version, and uv's mode that refuses to
  run if the file would need changing.
