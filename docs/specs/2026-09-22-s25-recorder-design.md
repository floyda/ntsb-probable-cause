# S2.5 — The recorder: design

*Drafted 2026-09-21 and 2026-09-22 from a design session with Andy, after the release of S2
(`v0.3.0`, pull request #8). Status: Draft, awaiting Andy's review. This is the specification
for build stage S2.5 in `docs/specs/2026-09-12-architecture-and-roadmap.md` §11. It records
what S2.5 builds, why, the decisions S2.5 takes, and the condition for moving on. The
implementation plan is written from it separately.*

**How to read this.** Each section says what is built, then why, with an example where one
helps. Terms in **bold** on first use are in the glossary at the end. Numbers in this document
are of three kinds, and each is labelled: **scripted** numbers cite the script that produced
them; **ad-hoc** numbers were counted during the design session over the local raw store or
by a throwaway probe, are not citable, and are re-derived by a script in this stage before
they appear anywhere else; **estimates** are arithmetic and are replaced by measured figures
in the As-built record. Nothing here is a result: S2.5 produces the results.

Decision records written with this specification: 0060 to 0071 (section 12).

---

## 1. What S2.5 is for

Every stage so far has read cases that were already closed. A closed case's docket is
complete, and its record is final. A live case is different: its evidence arrives over months,
and nothing the NTSB publishes says when each piece arrived. The spike found that this timing
cannot be reconstructed afterwards. The API deletes the preliminary narrative when a case
closes, the docket listing carries no date for each document, and the web server's
`Last-Modified` header cannot be trusted (spike report §9; decision 0007).

S2.5 builds the **recorder**: a job that looks at every open investigation once a day, writes
down what it sees, and so records the day each piece of evidence first appeared. It is the
only stage with a hard clock on it. Every day it is not running is a day of timeline that can
never be recovered, which is why it is built before the agent loop (0007).

Three things come out of it.

1. **A store.** The first tables of the project's SQLite store, holding what the recorder
   observes. The recorder is the store's first writer and shapes it (roadmap §13).
2. **A nightly run**, on a schedule, unattended, in the project's AWS account, with the same
   command runnable on a laptop.
3. **Measurements the later stages need**: how many days after an accident each structured
   field and the docket first appear (for the masked condition, 0023), and how many open cases
   change on a typical night (for sizing the agent's live runs in S4).

**What S2.5 is not.** No model is called. No document is downloaded. No verdict is read. No
prediction is made. The recorder writes down what is public and when it became public, and
nothing else.

An analogy. The evaluation harness marks a student against a finished case file. The recorder
is a clerk who checks the post every morning and notes the date on each envelope as it comes
in, so that later we can hand the student the file exactly as it stood on any given day.

---

## 2. The stage in one page

- **Which cases**: every ongoing aviation case flown under Part 91, plus those whose
  regulation is not yet recorded (§4.1). About 905 cases today (ad-hoc).
- **How often**: every watched case, once a day, at 03:00 UTC, with no tiers (§4.2).
- **From the API**: the full record of every watched case, by re-fetching the event months
  that hold one (§5). Compared with last night's copy; only changes are written.
- **From the docket site**: the docket's listing page only, fetched fresh each night (§6). The
  documents are never downloaded.
- **What a "first seen" is**: an interval, "last seen absent, first seen present", between
  two run timestamps. A missed night widens the interval and never produces a false date (§3).
- **Closure**: a status change is an event like any other; the docket is watched for 30 days
  after it; the preliminary narrative is kept; the verdict is never stored (§7).
- **Where it runs**: one scheduled AWS Fargate task and one S3 bucket (0004), defined in CDK,
  with Andy's Mac running the same command as a bridge until the stack is deployed (§9).
- **Cost**: an estimated $0.50 a month on AWS, stated from the bill at close-out (§9.4).

---

## 3. One rule for every timestamp

The recorder never knows when something happened. It knows only when it looked and what it
saw. So every "when" in the store is an **interval** between two runs:

- **last seen absent** — the timestamp of the last run that did not see the thing;
- **first seen present** — the timestamp of the first run that did.

Example. A docket shows 3 documents at the run on 2 March and 4 at the run on 3 March. The
fourth document's row reads: last seen absent 2026-03-02T03:04Z, first seen present
2026-03-03T03:05Z. If the run on 3 March had failed, the row would read 2 March to 4 March:
less precise, still true.

Why this rule. The measurements this stage feeds are "days from the event to first
appearance". An interval one day wide gives that to the day. A single stamped date would
look more precise than the recorder can honestly be, and a missed night would then produce
a date that is simply wrong. Intervals are between run timestamps, not calendar days, so a
run that starts late still produces true intervals. Every timestamp is UTC.

---

## 4. Which cases, how often

### 4.1 Which cases

A case is **watched** when all of these hold:

- `mode` is aviation;
- `completionStatus` is `Ongoing` — not "anything but `Completed`", because foreign-authority
  cases carry verdicts under `N/A` (CLAUDE.md rule 5);
- the regulation the flight was conducted under is `091`, **or the field is empty**.

A watched case whose regulation is later recorded as anything other than `091` stops being
watched that night; the rows already written are kept. A case is also watched for 30 days
after its status leaves `Ongoing` (§7).

Why include the empty ones. The regulation is recorded by investigators and may be filled in
later. A case watched from day one and dropped on day 20 has cost 20 requests. A case ignored
on day one and found to be Part 91 on day 20 has lost 20 days that cannot be recovered. Ad-hoc,
14 of 1,061 ongoing cases have the field empty, and 891 are `091`, so the extra cost is small.
Whether the regulation changes after it is first recorded is not known; the recorder
snapshots the field, and the 8-week report (§10.2) counts the changes. If they turn out to be
common, watching every aviation case becomes a recorded decision with a number behind it.

### 4.2 How often

Every watched case, once a day, with no tiers. The run starts at 03:00 UTC, after the NTSB's
working day has ended.

Why daily. The unit of the measurement is the day, so daily polling gives exactly the
precision the measurement uses. A full pass is about 905 listing requests at one every two
seconds, about 30 minutes (estimate).

Why no tiers. Tiered polling — daily for active cases, weekly for quiet ones — was designed
and rejected in the session. It would save an estimated 10 to 15 cents a month of compute,
cost permanent precision on exactly the cases whose behaviour nobody has measured, and add a
rule, a parameter and a check script to a stage that should stay simple. Decision 0060 records
it as considered and rejected, and names the two conditions for revisiting it: the nightly
run exceeding an hour, or the NTSB asking for a lower request rate.

---

## 5. The case side: records from the Enterprise API

### 5.1 The month window

The API returns cases by the month of the event, up to 1,000 records a page, and a month holds
about 140 aviation cases (ad-hoc), so one month is one request. Each night the recorder
fetches every month from the **earliest event month of any watched case** to the current
month. Today that is about 56 months (ad-hoc; the oldest ongoing case is from 2022).

The window sets itself from the store. On the very first run the store is empty, so the run
walks backwards from the current month and stops when 12 consecutive months hold no ongoing
Part 91 case. Nobody types a start date, and the window shrinks on its own as old cases close.

Example. Tonight the oldest watched case is from March 2022, so the fetch covers March 2022
to September 2026. If that case closes in November, its tail ends in December, and the window
then starts at the next-oldest watched case.

### 5.2 What is written

Each record passes through `split_record`, the project's one split, so only **evidence** roles
reach the recorder; the synthesis and verdict roles are dropped before anything is compared or
written (0013, 0016). The evidence is compared with the case's last snapshot field by field.

- A new case writes a `cases` row and one `field_snapshots` row per field that has a value.
- A changed field writes one `field_snapshots` row with the new value and the interval.
- A changed status writes a `status_events` row (§7).
- A preliminary narrative that is new or changed writes a `prelim_narratives` row.
- A watched case missing from its month writes a `status_events` row, "not returned".
- A record identical to last night's writes nothing.

The pages are compared and discarded; the raw records are not stored.

### 5.3 The change feed, stored beside the months

`/api/Common/v1/GetCasesByModifiedDateRange/` was probed once in the design session with a
throwaway script, and the data discarded. What it returned (ad-hoc, to be re-established by
`scripts/change_feed_probe.py` with a saved fixture):

- a JSON list, not a page object, of 30-field summary rows: `mkey`, `ntsbnumber`,
  `eventDate`, `caseClosed`, `lastChangeDateTimeUtc`, `stepNumber`, `stepId`, publication
  dates. No evidence fields at all;
- it reports open cases: 93 of 195 aviation rows in a 7-day window were not closed;
- the `mode` parameter has no effect: railroad and marine rows were returned with it set;
- no paging was seen: 564 rows for 30 days came in one response;
- `lastChangeDateTimeUtc` and `stepNumber` exist on no other endpoint.

What the probe could not show is whether every change to an evidence field moves
`lastChangeDateTimeUtc`. A feed that ignores small edits looks exactly like a quiet case. So
the feed cannot be the source of truth yet. Each night the recorder makes one call for the
last two days and stores each aviation row's change timestamp, step number and closed flag in
`change_feed`. After 8 weeks `scripts/recorder_report.py` counts how many of the field
changes the month re-fetch found the feed also reported within a day (§10.2). If it reported
all of them, switching to feed-first fetching — one call for the changed cases, then only
their months — becomes a decision with a measurement behind it. This is a departure from the
roadmap's "incremental ingestion by modification date", recorded in 0065.

---

## 6. The docket side: the listing page

### 6.1 Fetching

For every watched case the recorder fetches `https://data.ntsb.gov/Docket?ProjectID={mkey}`
with the S2 docket client, **with its cache switched off** (`cache_dir=None`: fetch, use,
discard). The client's cache replays a stored `listing.html` forever, which is right for
closed dockets and would make the recorder compare a listing with itself; S2 handed this
forward as the precondition for this stage. The evaluation cache is left as it is, and no
open-split page ever enters it (0024). The client only fetches; the recorder keeps its own
copies (§6.4). Decision 0066.

**No document is ever downloaded.** The recorder needs only the listing: which documents exist
and what the page says about each. The files stay on the NTSB's server. This bounds storage
and load, and it means the recorder cannot see a document's content change behind the same
number; it does see a change of title, page count or photo count, which the listing carries,
and records that as a revision. Decision 0061.

### 6.2 The outcome of a poll

Three different situations can look the same to the S2 parser, which returns zero entries for
a page with no rows: the case has no public docket yet, the docket exists and is empty (the
spike found 2 of 160 closed dockets empty), or the NTSB changed the page layout. A recorder
that confused them would record a layout change as every document disappearing.

So every poll writes one `docket_polls` row with one of four outcomes:

| outcome | when |
|---|---|
| `read` | the page carries the "Docket Information" block that every saved page has, **and** its declared item count matches the rows parsed |
| `no-docket` | the site says there is no docket for this case (the exact response is fixed by the probe, §10.1) |
| `empty` | a `read` page with zero declared items |
| `failed` | anything else: an HTTP error, a missing block, a count mismatch, a transport error. The reason is stored. |

Only a `read` poll updates the documents. A `failed` night leaves every "last seen absent"
where it was, so intervals widen and no date is written.

The row also keeps three dates the page carries at docket level and the S2 parser discards:
**Creation Date**, **Last Modified** and **Public Release Date**. In the seven saved pages
Last Modified sometimes falls years after Creation Date, so it may be a free change signal.
`listing.py` is extended to parse the block; a later script compares Last Modified with the
changes the recorder saw itself, which tests the spike's statement about these dates, a
statement that has no script behind it today.

### 6.3 Documents: the key and the events

A listing row gives position, title, page count, photo count, file format and link. The link
carries a **document number** (`docBLOB?ID=40469808`). In the saved pages this number does
not follow row order — in one saved docket the fourth of five rows carries a number about
1,100 higher than its neighbours — so it belongs to the document and not to its place in the list. It is the key.
Decision 0062.

Three events, each one `document_events` row with its interval:

- **appeared** — the number was absent last time and is present now. The `documents` row is
  created with the interval.
- **revised** — the number is unchanged and the title, page count or photo count changed. The
  old and new values are stored.
- **disappeared** — the number was present and is gone. The row is kept and stamped, never
  deleted.

A change of position alone is not an event. The current position is stored; no history of
positions is kept.

One thing about the number is not measured: whether it survives when the NTSB re-publishes a
docket. If the NTSB issued new numbers, the recorder would see every document disappear and a
matching set appear on the same night. So when one poll shows a disappearance and an
appearance with identical title and page count, the pair is counted as a **suspected
re-number** in the run summary. The full link is stored as well, so the rows can be re-keyed
later if the number proves unstable. The assumption is turned into a number the recorder
reports.

### 6.4 The page itself

Whenever a poll's page hash is new for that case, the compressed page is stored in
`listing_pages`. A quiet night writes nothing. The seven saved pages compress from 26–42 KB to
4–6 KB each (scripted in the session by `gzip`; re-measured by `recorder_report.py`), so at a
guessed 25 changes a night the store grows by about 45 MB a year (estimate). Decision 0063.

Why keep them. If the parser has a bug, the document number proves unstable, or a later stage
wants a column the parser ignored, every observation can be rebuilt with its original
timestamp from the stored pages. Without them the error is permanent, because arrival timing
cannot be collected a second time. This is the one place in the stage where a small storage
cost buys back the ability to fix a mistake that would otherwise be unrecoverable. The titles
on these pages are open-split text; 0024 permits them in the recorder's store, and they never
enter the repository or an evaluation.

---

## 7. Closure

Three things change together when a case closes: `completionStatus` leaves `Ongoing`, the API
deletes the preliminary narrative, and the verdict appears in the record. The rules,
decision 0064:

1. **A status change is an event.** A `status_events` row with the old status, the new status
   and the interval, in the same form as a document arrival. `Ongoing` → `N/A` (a foreign
   authority took the case), a case the API stops returning ("not returned"), and a
   `Completed` case returning to `Ongoing` are all recorded the same way.
2. **Nothing is deleted.** The stored preliminary narrative stays after the API removes it.
   That is the reason the recorder captures it.
3. **The verdict is never stored.** Every record passes through `split_record`, and the
   closing record's probable cause, codes and narratives are dropped before anything is
   written. Reading the verdict to score a prediction is the S4 watcher's job under its own
   rules. The recorder keeps the status and the NTSB's publication dates, which are dates and
   not conclusions.
4. **Same-poll changes carry no order.** If a case is seen `Ongoing` with 2 documents one
   night and `Completed` with 9 the next, both events carry the same interval and the store
   makes no claim about which came first.
5. **The docket is watched for 30 days after closure, then not at all.** Held-out evaluation
   reads each docket as it stands years after closure; a live agent reads it as it stands
   before. The roadmap's risk table lists this as "held-out and live evidence differ". A
   30-day tail measures it: how many documents arrive at or after closure, which a live agent
   never saw. About 100 cases close a month (from the scripted 1,000–1,400 a year), so the
   tail adds about 100 cases, about 3 minutes, to the nightly pass. The 30 days is a
   judgement; the run summary will show whether changes still arrive late in the tail.

Rule 4 may describe the common case. It is plausible, though nothing this project has
measured says so, that a public docket often opens near the end of an investigation. If so, a
live agent gets most of its documents days before the verdict, or none at all, and that would
shape S4 and the live board. The recorder is how the project finds out.

---

## 8. The store

One SQLite file, `recorder.sqlite`. Every row carries the run that wrote it. Nothing is
deleted or overwritten; a change adds a row. Tables are created by numbered migrations, so a
later stage adds tables without touching these.

| table | one row per | holds |
|---|---|---|
| `runs` | nightly run | start and end time, commit SHA and dirty flag (0018), cases polled, cases changed, new documents, failures, suspected re-numbers, minutes |
| `cases` | watched case | `mkey`, case number, event date, regulation, current status, first seen, last seen, watch-until date |
| `status_events` | status change | old status, new status, interval |
| `field_snapshots` | evidence field that changed | field role, new value, interval. Values come out of `split_record`, so only evidence roles can be written |
| `prelim_narratives` | narrative version | the text and the interval. Kept after the API deletes it. Live board only (0023, 0024) |
| `docket_polls` | case per night | outcome, reason if failed, declared item count, the page's three dates, page hash |
| `listing_pages` | distinct page content | the compressed page, keyed by hash |
| `documents` | document per case | number, link, position, title, pages, photos, format; last seen absent, first seen present, last seen present, disappearance interval |
| `document_events` | appeared / revised / disappeared | kind, interval, old and new values for a revision |
| `change_feed` | feed row per night | `mkey`, NTSB change timestamp, step number, step id, closed flag, when seen |

Example of one night for one case whose docket gained a document: one `docket_polls` row
(`read`, 5 items), one `listing_pages` row (new hash), one `documents` row, one
`document_events` row (appeared, absent 3 March, present 4 March), and a `change_feed` row if
the feed listed the case. Nothing else.

What is not stored: any document, any synthesis or verdict field, any raw API record, any
label guessed from a title.

**The store package**, `src/ntsb_probable_cause/store/`, is the only code that touches
SQLite: it opens the file, runs migrations, and offers one function per kind of write and
read. It joins the import-linter list of modules forbidden from importing synthesis or
verdict, so the store cannot hold a probable cause even by mistake. The S4 watcher, which must
read a verdict to score, will live outside it, as the verdict-aware scoring modules already do.

**What leaves the store.** Only numbers, by script (0024): day-count distributions for the
mask, the run summaries, the feed comparison. The evaluation harness never opens this file.

---

## 9. Where it runs

### 9.1 The nightly run

One command, `ntsb-record run`, in `apps/recorder/`, in this order:

1. **Open the store.** On AWS, download `recorder.sqlite` from S3; on the Mac, open the local
   file. Write the `runs` row.
2. **Compute the month window** (§5.1).
3. **Fetch the months** with the existing API client and write the case-side rows (§5.2).
4. **Fetch the change feed** for the last two days, one request (§5.3).
5. **Poll the dockets** of every watched case, cache off, and write the docket-side rows (§6).
6. **Close the run.** Fill the summary, save the store: on AWS, upload it.

Failure rules. One case failing on either side is a `failed` row and the run continues; every
failure is counted. If the API is down, dockets are still polled from the case list already in
the store; if the docket site is down, fields are still snapshotted. The store is saved once,
at the end: if the task dies mid-run, tonight's rows are lost and tomorrow's run sees a wider
interval, never a false date. Every write is in a transaction, so a half-written night cannot
exist. The scheduler stops the task at 90 minutes; a normal night is about 40 (estimate).

Logging. One line per case per side — `mkey`, what was fetched, the outcome, what was written
("2 field snapshots", "1 document appeared", "no change") — and never case text. One line per
step with its duration, and the summary last. Every failure logs the exception with the case
and URL, and the same reason string goes in the `failed` row, so the log and the store agree.
`--verbose` logs each diff decision: which fields differed, which document numbers were
compared. Output goes to standard output; on AWS, Fargate sends it to CloudWatch Logs, kept
30 days.

```
docket mkey=201234 outcome=read items=5 new=1 revised=0 gone=0
docket mkey=201240 outcome=no-docket
run done cases=903 changed=27 new_docs=41 failed=2 renumber_suspects=0 minutes=38
```

### 9.2 The AWS pieces

Andy has no AWS background, so each piece is explained here in one line, and the runbook
`docs/runbooks/recorder-deploy.md` walks every step with the command, what it does, what it
costs and how to check it worked, ending with a glossary. All four are defined in one **CDK**
Python file under `infra/` (0005) and deployed with one command.

- **S3 bucket** — a file store. Holds `recorder.sqlite`. Versioning on, so every night's upload
  is kept as a version; **old versions expire after 30 days**, otherwise they would grow by
  about 3.6 GB a year (estimate). No public access.
- **Parameter Store entry** — a locked drawer for the NTSB API key. Andy writes it once from
  `pass`: `aws ssm put-parameter --name /ntsb/api-key --type SecureString --value "$(pass show
  api/ntsb)" --profile ntsb`. The key never appears on screen, in the image, in CDK code or in
  git. Free. Decision 0069. No OpenRouter key is needed in this stage.
- **Fargate task** — runs the container for about 40 minutes, then stops; billed by the
  second, no server to look after. Smallest size. **Public subnet, no NAT gateway**: a NAT
  gateway costs about $35 a month, more than the project's whole AWS budget. Reads the key
  from Parameter Store at start, runs `ntsb-record run`.
- **EventBridge schedule** — the alarm clock: 03:00 UTC daily, 90-minute limit.

The container image is built by GitHub Actions on each merge to `main` and pushed to **ECR**,
AWS's image registry, keeping the latest five. The Dockerfile installs the project with `uv`
and sets `ntsb-record run` as the command.

### 9.3 The bridge

From the day the recorder merges, `launchd` on Andy's Mac runs `ntsb-record run` nightly
against a local file. When the stack is deployed, the local file is uploaded once as the first
S3 version and `launchd` is switched off. Bridge and cloud run the same code; the store's
location is one environment variable, `NTSB_STORE` (a local path or an `s3://` URL). Days the
laptop is closed are wide intervals, not lost data, by §3.

### 9.4 Cost

Estimates, replaced by the billed figures at close-out: Fargate about $0.30 a month (40
minutes a day at the smallest size), S3 and ECR under $0.10, Parameter Store, EventBridge and
CloudWatch free at this volume. Total about $0.50 a month. Model cost: none.

---

## 10. Measurements

### 10.1 Before the first poll: the ongoing-docket probe

Nobody has fetched the docket page of an ongoing case; every docket measured so far belonged
to a closed one. `scripts/ongoing_docket_probe.py` fetches the listing page of 100 ongoing
cases, stratified by days since the event, with the cache off, and writes
`docs/results/s25-ongoing-dockets.txt`: how many returned an HTTP error and which, how many a
page with no rows, how many a listing with documents; for the last group the distribution of
document counts and of days since the event. Counts only — no case numbers, no titles,
nothing cached (0024). The `no-docket` outcome in §6.2 is then fixed from what the site
really does, before any nightly row is written.

### 10.2 After 8 weeks: the recorder report

`scripts/recorder_report.py` reads the store and prints, counts only:

- the run summaries: cases polled, changed, new documents, failures, minutes, per night;
- **the feed comparison** (§5.3): of the field changes the month re-fetch found, how many the
  feed reported within a day;
- **regulation changes** (§4.1): how many watched cases changed regulation after first seen;
- **arrival distributions**: days from the event to first appearance, for each evidence field
  and for the docket (present, and number of documents), as percentiles. These replace the
  provisional mask in `scoring/samples.py` (`MASK_LIFTS_AT_DAY = 14`) when S3 builds the masked
  condition;
- the 30-day tail: how many documents appeared at or after closure;
- suspected re-numbers.

Every number in the As-built record comes from this script. "How many cases change on a
typical night" is the figure S4 uses to size the agent's live runs: at S2's measured
$0.0050 a case for arm B, the monthly model cost becomes a multiplication of two measured
numbers rather than an estimate.

### 10.3 What the mask can and cannot take

The agency design §6.2 says the mask uses "the first appearance of each field and each
document type". S2 then found the title-based type label 58–72% accurate with 16% of
documents in `other`, and removed every job it had in the live path (0054–0056). The recorder
therefore records arrival **per document, with no type label**, and the mask's docket rule
becomes "docket present, with K documents, by day N". Since every readable document goes to
the agent, that is also the shape of what a live agent receives: the whole docket, fed in as
it arrives. With a first-seen interval per document, S3 can replay a closed case's docket in
arrival order. Decision 0068 records this as an amendment of §6.2, with the reason. How the
mask groups arrivals beyond that is decided in S3, when the numbers exist.

---

## 11. Tests and continuous integration

All offline; `pytest-socket` refuses every socket in the suite. Fixtures are the seven
listing pages S2 committed (development split, 0037), edited in code, not new pages.

- **Diff tests.** A page and an edited copy — one document added, one renamed, one removed,
  one moved, one re-numbered pair — produce exactly the expected events; a move produces none;
  the re-numbered pair increments the suspect count.
- **Outcome tests.** A 404, a page without the Docket Information block, a declared count
  that disagrees with the rows, and a genuine empty docket each map to the right outcome and
  never to `read`.
- **Interval tests.** Two runs under a fake clock give "absent at run 1, present at run 2";
  a failed night between them widens the interval and writes no date.
- **The store boundary test.** A closing record carrying a probable cause and both narratives
  is fed through the recorder; the resulting SQLite file, read as bytes, contains no verdict
  or synthesis string. Its mutation test removes the `split_record` call and must fail, as
  `tests/test_boundary.py` does for payloads (0016).
- **Window tests.** A store with cases from 2022 and 2026 yields a window from 2022; an empty
  store walks back until 12 empty months.
- **Idempotence.** The same night run twice writes nothing the second time.
- **Fixture checks.** No fixture the recorder's tests use has an event date in 2020–2023.
- **Import-linter.** `store` and `recorder` join the modules forbidden from importing
  synthesis or verdict.
- **CI additions.** The image build-and-push job on merge to `main`; the vendored word list
  replacing the 0058 install step (decision 0070).

Coverage stays at the 90% gate. The store's download and upload sit behind a two-function
interface with a local-file implementation, so no test needs AWS.

---

## 12. Decisions S2.5 takes

Each is a numbered record, written with this specification, one decision per record.

| # | decision |
|---|---|
| 0060 | Every watched case is polled once a day, with no tiers; tiering considered and rejected, with the two conditions for revisiting it |
| 0061 | The recorder reads the listing page only and never downloads a document |
| 0062 | The document number in the link is the key; three events; suspected re-numbers are counted |
| 0063 | A compressed copy of the listing page is kept whenever its hash is new |
| 0064 | Closure: status changes are events, nothing is deleted, the verdict is never stored, same-poll changes carry no order, the docket is watched 30 days after closure |
| 0065 | The event months are re-fetched nightly as the source of truth; the change feed is stored beside them and compared by script at 8 weeks — a departure from the roadmap's "by modification date" |
| 0066 | The recorder fetches with the docket client's cache off and keeps its own copies; the evaluation cache is unchanged |
| 0067 | Watched cases are Part 91 plus those with the regulation empty; regulation changes are counted at 8 weeks |
| 0068 | Arrival is recorded per document with no type label; the mask's docket rule is presence and count — amends agency design §6.2 |
| 0069 | The NTSB key reaches the task from AWS Parameter Store, encrypted |
| 0070 | The word list is vendored into the repository — amends 0058 |
| 0071 | The leakage guard's coverage threshold is deferred to the start of S3, reframed: mark such cases, do not refuse them, and score the marked group against the rest |

---

## 13. Build order within S2.5

1. The ongoing-docket probe (§10.1), so the outcome rules are written from real data.
2. `listing.py`: the docket-level dates and the Docket Information check.
3. The store package and its migrations, with the boundary test.
4. The recorder package: the window, the case side, the docket side, the diff.
5. `apps/recorder` and the bridge on Andy's Mac — the clock starts here.
6. The change-feed probe script and the recorder report script.
7. The Dockerfile, the CDK stack, the runbook, the deployment, the first cloud run.
8. The vendored word list, at any point.

---

## 14. Done means

1. `docs/results/s25-ongoing-dockets.txt` exists from the probe, numbers only.
2. The recorder has run on at least 14 consecutive nights, on the bridge or on AWS, and
   `runs` holds a row for each.
3. `scripts/recorder_report.py` prints the run summaries and counts from the store, and every
   number in the As-built record comes from it.
4. The stack is deployed, one nightly run has completed on AWS with its log visible in
   CloudWatch, and Andy has followed the runbook rather than only read it.
5. The store boundary test and its mutation test pass; CI is green; `scripts/check_docs.py`
   passes.
6. The stage's AWS cost is stated from the billing console.

---

## 15. Not in S2.5

- The `predictions` and `steps` tables. Their fields are already fixed (0021, roadmap §S4)
  and they are created in S3 and S4 by the same migration mechanism; nothing here designs
  them.
- Any model call, and any OpenRouter key on AWS.
- Downloading documents; OCR.
- The live board and the static site (S5); the DNS delegation.
- The leakage guard's coverage threshold (0071, S3).
- Tiered polling; feed-first fetching (both wait on the 8-week numbers).
- The 8-week numbers themselves: the report script ships in this stage, and its first
  citable output is written when the data exists.

---

## 16. Risks and open questions

| risk | how it is handled |
|---|---|
| The site returns something unexpected for a case with no docket | The 100-case probe runs first; the outcome rule is fixed from its result |
| The document number is not stable across re-publications | Counted as suspected re-numbers; the link and the page are stored, so rows can be re-keyed |
| The change feed misses small edits | It is never the source of truth in this stage; the comparison at 8 weeks says whether it can be |
| The page layout changes | A missing block or a count mismatch is `failed`, never `read`; nothing is recorded as disappeared |
| The laptop bridge misses nights | Wide intervals, not false dates (§3); the stack is deployed in the same stage |
| The docket only opens at closure | Then the live agent has little to read before the verdict; the recorder measures this and S4 is designed from the number |
| A run overruns | 90-minute scheduler limit; the run summary shows minutes every night |
| Cost estimates are wrong | Every AWS figure here is labelled an estimate and is replaced from the bill at close-out |

---

## Glossary

**Bridge.** Andy's Mac running the same nightly command as the cloud, from the day the code
merges until the AWS stack is deployed, so that no nights are lost.

**CDK.** AWS Cloud Development Kit: a Python file that describes the cloud pieces, so one
command builds them and one command removes them.

**Change feed.** The API endpoint that lists cases the NTSB changed in a date range, with a
change timestamp. It returns a summary of each case, not the case.

**CloudWatch Logs.** AWS's log store. The task's output lands there and can be read in the
console.

**Docket.** The NTSB's public folder of documents for one case, on `data.ntsb.gov`. The
**listing page** is the web page that lists them.

**Document number.** The integer in a listing link (`docBLOB?ID=…`), which identifies the
document independently of its position in the list.

**ECR.** AWS's registry for container images.

**Evidence, synthesis, verdict.** The three roles every field of a record is split into
(0013). Only evidence may reach a model or, here, the store.

**EventBridge Scheduler.** AWS's alarm clock: it starts the task at 03:00 UTC.

**Fargate.** AWS's way of running a container without a server: it starts, runs, stops, and
is billed by the second.

**Interval.** The two run timestamps between which a thing appeared: last seen absent, first
seen present. The only form a "when" takes in the store.

**Masked condition.** Evaluating the agent on a closed case with only the evidence a live
case would have had at day N (0023). The recorder supplies the day counts.

**mkey.** The NTSB's internal integer key for a case, used in the docket URL and as the
store's key. It is not the case number.

**NAT gateway.** An AWS component that gives a private network a route to the internet. It
costs about $35 a month, so the task runs in a public subnet instead.

**Parameter Store.** AWS's store for settings and secrets, free at this size. The NTSB key
lives there, encrypted.

**Part 91.** The US regulations for general aviation. The project's corpus is Part 91 only.

**Preliminary narrative.** The short account the NTSB publishes while a case is open, deleted
from the API when it closes.

**Run.** One execution of `ntsb-record run`: one night.

**S3.** AWS's file store. One bucket holds the SQLite file.

**Suspected re-number.** A disappearance and an appearance with the same title and page count
in one poll, counted as a sign that the NTSB may have issued a new document number.

**Watched case.** A case the recorder polls: ongoing, aviation, Part 91 or regulation empty,
or within 30 days of leaving `Ongoing`.
