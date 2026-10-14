# S5 — The public site: structure, content and reader experience

Status: Approved (Andy, 2026-10-12), as S5's specification. Drafted 2026-10-04. Nothing here is built. This note is written early, on its own branch,
while S3.2 runs, because the site's design is a large piece of work and its page list decides
what S4's store must answer (roadmap §8). It is revised and approved as S5's specification when
S5 starts. §1 to §16 cover what the site says and how a reader moves through it. *Added
2026-10-11:* §17 to §22 cover the site generator, the hosting and the build pipeline, designed with
Andy once S4's export format, `board/1`, existed.

Every choice below was made by Andy in a design session on 2026-10-04, one question at a time.
Where a point is still open it is listed in §12 and §16, not guessed.

## 1. Why the site exists

The site is the demo. A reader does not run the agent or read the repository; they read the
site. The demo criteria ask for a result that is falsifiable in public, measured, honest about
negative results, and legible to a non-expert (`ntsb-spike/docs/demo-criteria.md`, in the
spike's folder).

**Success is not a high score.** The project is an experiment in how to find out whether an
agent loop earns its keep. S3.2's registered held-out reading is that the loop was worse than
the fixed pipeline, at an equal bill (`docs/results/s32-claims-heldout.txt`). The site shows
that as the present state of an honest experiment.

**The board runs the loop, as version 1** (Andy, 2026-10-05). The fixed pipeline measured
better, and running it on the board was considered and declined. The reason: the loop is the
thing being improved, and version 1 was given exactly the evidence and tools the fixed pipeline
had, so its result is a fair starting point, not a handicap. The page says so in plain words:
the board runs version 1 of the agent, it measured worse than a simpler fixed method, and later
versions are measured too. A later version replaces version 1 on the board when it beats
version 1 in a registered comparison (§12, item 13). Every version is also measured against
the fixed method, which stays the bar for calling the loop warranted (§7.3).

## 2. The reader

**The primary reader is a hiring manager or engineering lead with about three minutes.** They
skim. **The second reader is a technical peer who checks the method.** The first reader must be
able to become the second with one click, from any claim.

Rule that follows: **no number or statement appears without a link to the method and the script
behind it.**

A short scan must leave three impressions. They are shown, not stated.

1. **Messy public files in.** The input is real docket documents, not a prepared dataset.
2. **Graded by the source itself.** The NTSB's own published verdict is the answer key. Nobody
   on the project marked anything.
3. **Each added piece of machinery was measured.** The loop had to prove itself against
   something simpler.

The first screen asks a question; it does not make a claim: *can an agent read an accident
docket and code the cause as the investigator did, and does it need to be an agent to do so?*

## 3. The pages

| page | what it is for | how a reader reaches it |
|---|---|---|
| First screen | the question, then the board of recently closed cases | the site's address |
| Opened case | one case: the agent's coding beside the NTSB's | a board row; it opens beneath the board |
| Trail view | one case: what the agent believed, read and spent | the opened case |
| Path | how the project decided what to build, step by step | the first screen |
| Open cases | counts of the open cases watched, never a list | a plain link; not promoted |
| Methods | every number, its sample and its script | any number on the site |

This replaces the roadmap's five pages (§8 there). Home and the live board become one screen.
The board lists closed cases, not open ones. Open cases move to their own page. §14 lists the
roadmap changes this needs at merge.

### 3.1 The first page is one scrolling route

Andy asked for a page that flows as the reader scrolls, and agreed that the first page should
offer one marked three-minute route. So the first page is one long page of six stops, read top
to bottom. Each stop is a short form of a page in the table above and links to the full one.

| stop | what the reader sees | the full page it links to |
|---|---|---|
| 1. The question | the question, two sentences on the task, and the caveat | none |
| 2. Closed cases | the board (§4) | none |
| 3. One case | the opened case for the chosen row (§5) | the case's own address |
| 4. Its trail | that case's beliefs as a strip of four blocks, with what was read between them | Trail view (§6) |
| 5. Was a loop needed? | the ladder and one plain sentence stating the result (§7.1) | Methods (§9) |
| 6. The path taken | the eight questions, each with a one-line answer (§7.2) | Path (§7), each question to its own stop |

A slim rail of the six stops stays in view and marks the stop being read: at the left on a
wide screen, across the top on a phone.

**The caveat sits in stop 1, above the board.** This meets the roadmap's rule that caveats
come before results, without burying the board. Wording approved by Andy on 2026-10-05, written after
S3.2's held-out reading was known, so it is not a registered prediction:

> Read this first. The board runs Ellery, version 1, an AI agent. It reads the same evidence, with the
> same tools, as a simpler fixed method. On 400 accidents it had never seen, its first code
> matched the investigator's in about one case in four. The fixed method matched in about one
> case in three. It runs here because it is the version being improved, and each new version is
> measured against that fixed method. This site is the record of how.

"Points" were dropped from the wording (Andy, 2026-10-05): a reader who does not know how a
percentage-point difference is defined cannot use it. The two rates are S3.2's, under its
failure rule (a failed case counts as wrong; decision 0146), from
`docs/results/s32-heldout-diagnosis.txt`: the fixed pipeline 33.0% [28.5%, 37.5%] and the
loop 23.5% [19.2%, 27.5%], each on 400 cases. The registered difference and its interval stay
on the Methods page.

**Each stop animates in as the reader reaches it** (Andy, 2026-10-04). The parts of a stop
rise into place; the board's rows turn over one after another, as a terminal display does; the
ladder's bars grow from the left in order; the trail's beliefs and the path's questions appear
in sequence.

**Wanted, not yet achieved: the next stop is not seen until it animates in** (Andy,
2026-10-04). Andy wants the reader never to see the next stop waiting below. A first attempt
made each stop one screen tall and held its parts back until the stop was well onto the
screen. It did not work on a phone, where stops are taller than the screen, and was withdrawn.
The mock-up shows the simpler behaviour above. How to achieve the effect on a phone is a
front-end design problem for S5's build, not settled here (§12).

Four limits apply:

- Each animation runs once, is short (under about a second for a stop), and never repeats or
  loops. The board does not flip again when a row is chosen.
- The reader keeps control of the scroll. Nothing pins the page or moves it.
- With a reduced-motion setting, or with scripts off, everything is shown at once, with no
  animation. No content depends on the animation to be read.
- Anything that reads the page without scrolling sees all of it: a link preview, a search
  engine, a printed copy. A render of the current example at a true phone width, on
  2026-10-04, fitted the screen but showed every stop below the first one blank in a
  whole-page capture, because each stop waits for a scroll. The built page must start with
  its content visible and hide it only once a script has confirmed the reader is scrolling.
- Motion is for arrival only. It never marks a result as good or bad, so nothing reads as a
  game (§11).

**The author.** The foot of the page carries one line, "Built by Andy Floyd", linking to his
main profile page, with links to the repository, Methods and Open cases. The site holds no
biography; the profile page does that work and is Andy's to update.

Mock-up: `docs/specs/2026-10-04-s5-mockups/scroll-route.html`
(<https://claude.ai/artifact/J9xBm7c1FUmfVR195s6oYF>). Its cases and its ladder figures are
invented examples.

## 4. The first screen and the board

**The board lists the most recently closed cases.** Closure is the event that matters: when the
NTSB closes a case it publishes its codes, and the agent codes the same case from the full
docket with the verdict withheld. The board puts the two codings side by side.

The board is drawn as an airport terminal display, in dot-matrix letters on a dark ground. One
row is one case. Columns, in order:

| column | example (invented) | why it is on the board |
|---|---|---|
| Closed | 12 Sep | the board is ordered by this, most recent first |
| Took | 14 mo | how long the human investigation ran; it gives the task its scale |
| Aircraft | Aeroplane, 1 piston | the fact a reader recognises fastest |
| Agent coded | Aerodynamic stall/spin | the agent's first occurrence code |
| NTSB coded | Loss of control in flight | the NTSB's first occurrence code |
| Result | Same codes, other order | one of three grades, below |

**The result has three grades**, each with a mark whose shape, not colour, carries the meaning:

- **Same first code** (filled mark): the agent's first code is the NTSB's first code.
- **Same codes, other order** (half mark): the NTSB's first code is among the agent's three,
  but not first (Andy, 2026-10-04). This is the harness's occurrence top-3 score less top-1,
  so the board's grades are the same measures the Methods page reports. A looser rule, any
  shared code, was rejected: "collision with terrain or object" ends many sequences, so nearly
  every case would share a code. This grade matters because the project found the NTSB's coding order, more than missing
  evidence, behind what the fixed pipeline missed
  (`docs/results/s26-occurrence-misses-dev.txt`).
- **Different** (open mark).

**A case the agent abstained on has its own row** (Andy, 2026-10-04): "No answer" in the agent's
column and "Agent abstained" as the result, with a dashed mark. Its opened case gives the
agent's stated reason beside the NTSB's cause. Leaving such cases off would be selection.
Such rows will be rare: on S3.2's held-out run the abstain cut-off could not fire on the
fitted confidence curve, and fired on none of 394 scored cases.

**A failed case has its own row too** (Andy, 2026-10-04): "Not coded" as the result, with a
mark of its own, distinct from the abstain mark, because an abstain is the agent's judgement
and a failure is the system producing no answer. The opened case gives the reason in one plain
sentence beside the NTSB's cause, for example "A document in the docket held the NTSB's
probable cause, so the case could not be shown to the agent" or "The agent's reply failed a
technical check twice". Failed rows count in any totals beside the board. Whether a technical
failure is retried is S4's decision; the board shows the result that stands.

How often this happens, today: on `dev-400`, the loop's two noise-floor runs failed 5 and 8 of
401 cases for format or tool reasons, and the guard refused 2 cases in each because a document
held a probable-cause sentence (`docs/results/s3-noise-floor-dev.txt`). Since S2.6 a docket
sentence shared with the analysis narrative reaches the agent and only marks the case
(decision [0077](../decisions/0077-analysis-sentences-in-docket-documents-mark-the-case.md)),
so S2.4's 40 guard refusals in 400 held-out cases do not describe the loop.

On a phone the board keeps Closed, Aircraft and Result. About eight rows are shown, so the
opened case stays within reach.

A line under the board says that the NTSB's own coding is not fully consistent, and links to
the Path page's question on it (§7). A reader must not read "different" as simply "wrong".

Mock-ups, in `docs/specs/2026-10-04-s5-mockups/` and published privately to Andy:

- `row-detail.html`: the board and the opened case
  (<https://claude.ai/artifact/Kga3DiTZYSsWktMMtB4CoL>).
- `theme-register.html`: the three strengths of theme that led to the board
  (<https://claude.ai/artifact/G8NmZpHfXoMhZ8jWFC8Nqe>).

Every case in a mock-up is invented.

## 5. The opened case

Choosing a board row opens the case beneath the board, in plain type. It has five parts.

1. **A line of facts.** NTSB case number, date closed, time to close, aircraft type, state,
   kind of flight, injury level, and documents read, stated as "3 of 7 documents read". Never
   the registration (§12, item 11). Cost is not in this line (Andy, 2026-10-04): it barely
   varies from case to case, and its story is told by the trail view, step by step, and by
   the ladder.
2. **One sentence on where the two differ.** Example: "Both name the same event. The NTSB put
   loss of control first. The agent put the stall first." Code writes this sentence from the
   two sets of codes. No model call is made for it.
3. **The two cause statements, side by side.** The agent's `probable_cause` and the NTSB's
   probable cause, unaltered.
4. **What happened, in each one's order.** Both ordered lists of occurrence codes. Each code
   carries a mark: same code in the same place, same code in another place, not in the other
   list.
5. **Why it happened.** Findings both named, findings only the NTSB named, findings only the
   agent named.

It ends with links to the trail view and to the NTSB's own page for the case, and with **one
plain line saying the verdict was withheld** (Andy, 2026-10-05), for example: "Coded 2 Oct
2026, 03:40 UTC, from the docket as published at closure. The NTSB's cause and codes were
withheld from the agent. Code version 4f2a9c1." The code version links to that commit, and the
line links to the split diagram on the Methods page (§9). No evidence fingerprint is shown.

Last comes **a sources line** (Andy, 2026-10-06), after the visible sources on Andy's reference
site: "Sources: the NTSB's case page · the case's docket · how this case was graded". The
first two link to the NTSB; the third links to the board's grading entry on Methods. Every
claim on the opened case can then be checked in one click, which is the link rule of §2 made
visible. Each Path question's stop already ends with its results file, script and Methods
entry (§7).

## 6. The trail view

The trail view shows one case as numbered steps, top to bottom, in plain type.

**Beliefs are the spine.** A belief is the agent's hypothesis at a checkpoint: before reading,
after each read choice that read something, and the answer (decision
[0122](../decisions/0122-h0-and-later-triggers.md)). Each belief block shows its first code, its
cause statement at that point, its confidence, and whether it changed from the belief before.
It does not show the explanation written for a non-expert (§12, item 4). Confidence is shown
as fitted, which S3.2's registered reading allows because the fit was calibrated on held-out
cases (result 3 does not hold). The fitted values sit close together and barely separate right
answers from wrong ones, so the trail shows the number plainly and makes no claim from it.

**Actions sit between beliefs.**

- A **read choice** lists every docket document as read, skipped, or scan only. For each
  document it shows what the agent wrote about it, labelled **"the agent's note"**, never a
  prediction, and the belief after it shows what changed. This follows S3.2's registered
  reading: the agent's stated effects are descriptions, not predictions of change (result 4
  not shown; `docs/results/s32-claims-heldout.txt`).
- The **coding step** lists each lookup the agent made in the code tables and past usage.

**Cost runs beside every step**, with the case total at the top.

**The NTSB's verdict comes last**, after the agent's answer, with a line saying which belief was
closest to it.

*Note, 2026-10-14 (step 3):* S4's export also carries each belief's account of the evidence
(`evidence_narrative`). It is **not shown** (Andy, 2026-10-14): S4's names step replaces only the
case's owner, operator and registration in prose, so a passenger's or witness's name from a
document could reach the page (§11). It can return behind a measured names check of its own.

What the loop already records (`agent/trail.py`, `scoring/hypothesis.py`,
`agent/schemas.py`): every belief in full (codes with probabilities, a cause statement, an
explanation written for a non-expert, confidence, the abstain flag); for every offered document
the read-or-skip decision and its expected effect; a reason for each read choice as a whole;
tokens and cost per call. **One thing is missing: document titles.** The trail holds a
document's position in the listing, never its title or text. §13 makes this a requirement.

Mock-up: `docs/specs/2026-10-04-s5-mockups/trail-view.html`
(<https://claude.ai/artifact/KXFtJPJkuZ4KHK88yKS6dn>). It was drawn before the check above and
shows one reason per read choice; the built page shows the expected effect per document.

## 7. The Path page

The Path page tells how the project decided what to build.

**It is a second scrolling route, built like the first page** (Andy, 2026-10-04), so the two
feel like one site. It opens with the ladder, then gives each of the eight questions its own
stop, then closes with what could come next. Each question's stop holds the question, its
measured answer, the decision taken, one small figure, and links to its results file, its script and its Methods entry. Each line of the first page's
last stop links to its question's stop here. The rail of stops and the motion rules of §3.1
apply unchanged.

It has three parts.

### 7.1 The ladder

One figure with four ways of coding an accident, each with more machinery than the one before.
Each step shows how often its first code matched the NTSB's, and its cost. A plain sentence
beneath states the present result. It appears on the first page's stop "Was a loop needed?"
and at the top of the Path page.

**The steps and their runs** (Andy, 2026-10-05). Every model step is from S3.2's held-out runs
on `heldout-400`, GPT-6 Luna, on 2026-10-04, under S3.2's failure rule (a failed case counts
as wrong), from `docs/results/s32-heldout-diagnosis.txt` and the project guide's S3.2 summary;
the no-model step is S1's honest baseline (`docs/results/s1-bars.txt`). Step 2's interval is
the harness report's; the build takes every step's interval from one script, so that one is
recomputed by S3.2's bootstrap before launch:

| step | plain words | run | top-1 | cost for 400 cases, list price |
|---|---|---|---|---|
| 1. No model | always guess the commonest code | S1 baseline, scored on all 4,241 held-out cases | 17.7% [16.6%, 18.9%] | none |
| 2. The case record only | the agent with the recorded facts, no documents | `20261004T184547-80c539e-heldout-400-C` (S3.2's no-docket ablation) | 15.0% [11.8%, 18.8%], n=400 | $0.98 |
| 3. Every document, fixed order | the fixed pipeline: answer, coding tools, ordering check | `20261004T111937-dd64854-heldout-400-B-tools-check-luna` and its two source runs | 33.0% [28.5%, 37.5%], n=400 | $2.34 ($2.13 billed) |
| 4. Choosing what to read | the loop, version 1 | `20261004T140804-e0dc881-heldout-400-C` | 23.5% [19.2%, 27.5%], n=400 | $3.93 ($2.06 billed) |

Step 2 is S3.2's own no-docket run, not S2.4's one-shot ceiling: it ran beside the loop with
everything equal but the documents, so steps 2 and 4 differ by the documents alone. The
ceiling stays on the Methods page as history. Step 2's interval includes the no-model rate,
so the page says the case record alone did **no better than guessing**, not worse.

The loop's step sits **below** the fixed pipeline's, and the ladder draws it that way: the
figure's point is that a step up in machinery is not a step up in result. Costs show billed
and list price, because the loop's bill equals the pipeline's only through the provider's
discount on cached prompts; at list price it does about two-thirds more work.

*Note, 2026-10-14 (Andy, step 4 preview):* the site shows **billed costs only**, on the ladder
and in question 7. The list price is the project's budgeting estimate; what was charged is
what matters. Step 2's bill is in its run folder, not a committed results file, so its cost
line reads "bill not recorded". The list price stays in `docs/results/s32-claims-heldout.txt`.

**How it is drawn.** Each step is a bar from zero with a thin whisker for its 95% interval. A
faint line at the no-model rate runs across all four bars, so every step reads against
"better than guessing?". The run-twice band does not go on the ladder: it was measured on
development cases, and the ladder is held-out; it goes to question 7's stop and to Methods.

### 7.2 Eight questions

Each has a measured answer, the decision taken from it, and a link to its script and results
file. Dead ends stay in.

1. **Is there an answer key nobody had to write?** Yes. The NTSB codes every closed case.
2. **Is the case record enough?** No. With the recorded facts alone, the agent did no better
   than always guessing the commonest code (§7.1, step 2). S1's one-shot ceiling, on an
   earlier stack, scored below that guess (`docs/results/s1-bars.txt`).
3. **Does reading the docket help?** Yes. It is the largest gain on the ladder
   (`docs/results/s24-bars.txt`).
4. **Does reading words in scanned pages help?** On development cases it was not shown to
   help (`docs/results/s26-armB-v2-dev.txt`), and it cost far more than answering, so it is
   paused (decision
   [0120](../decisions/0120-qwen-stays-and-transcription-is-off-by-default.md)). It is a
   candidate to return as a measured improvement (§7.3).
5. **Are the misses about evidence or about coding?** Mostly coding order
   (`docs/results/s26-occurrence-misses-dev.txt`). Guidance and an ordering check followed;
   of five guidance rounds, three were dropped (`docs/rounds/`).
6. **How consistent is the answer key itself?** Cases whose NTSB probable-cause sentences match
   word for word share their first code in 619 of 1650 (37.5%)
   (`docs/results/s3-coding-consistency-dev.txt`); their flagged findings agree far more
   (`docs/results/s3-finding-consistency-dev.txt`). The page repeats that file's own caution:
   this does not say the NTSB was inconsistent, because one sentence can follow accidents whose
   sequences differ. It bounds what any coder reading only the sentence could score.
7. **Does choosing what to read beat reading everything?** No. On held-out cases the loop
   was worse on the first code, the top three and the findings, at an equal bill that it
   reached only through cached-prompt discounts (`docs/results/s32-claims-heldout.txt`).
   Reading the docket still mattered: without it the loop lost more. The loop read every
   offered document in most cases, and skipped most often on large fatal dockets. Most of the
   fixed pipeline's lead came from its coding-tools step: against the pipeline's first answer
   alone, before that step, the loop was −4.2 points [−8.5, +0.0]
   (`docs/results/s32-heldout-diagnosis.txt`, decision 0153, exploratory).
8. **Does it hold on newly closed cases?** The board answers this in public.

### 7.3 What could come next

A short list of candidate improvements, each to be run as a registered, measured experiment:
transcription of scanned pages; the precedent tool the agent questions (decision
[0140](../decisions/0140-the-precedent-tool-after-s4-as-a-measured-v2.md)); the weather
archive; the model comparison. When the second version of the agent runs, the site needs a
place to show the first against the second on the same cases (§12).

### 7.4 One figure per question

Accepted by Andy as a first draft on 2026-10-04.

| question | figure | data |
|---|---|---|
| 1. An answer key | one closed, non-fatal development case as the NTSB published it: its cause and its codes | exists; a non-fatal case keeps the first example gentle |
| 2. The case record only | the ladder, first two steps lit | S3.2 (§7.1) |
| 3. Reading the docket | the ladder, third step lit | S3.2 |
| 4. Scanned pages | the share of each docket's pages that are scans only | exists, as counts (`make page-kinds`) |
| 5. Misses are coding | the commonest pairs of agent and NTSB first codes | exists (`docs/results/s26-occurrence-misses-dev.txt`); rerun on S3's runs |
| 6. Consistency | one cause sentence the NTSB used word for word on many cases, with the different first codes those cases received | a small new script; development split only |
| 7. Choosing what to read | each case's belief before reading, after reading and at the answer, against the NTSB's first code | a new script over S3.2's trails |
| 8. Newly closed cases | a strip of closed cases over time, one mark per case, shaped by result | S4's live data |

Two more sit outside the questions: a **docket strip** in the first page's trail stop, each
document a block sized by pages and marked read, skipped, scan only or not offered (with its
reason: not a PDF, photographs only, could not be fetched, already read at the first read choice,
or over the prompt-size limit); and the
**run-twice band**, showing how far the same agent moves when run again
(`docs/results/s3-noise-floor-dev.txt`), at question 7's stop and on Methods, not on the
ladder, because it was measured on development cases. The ladder lights each step as the story reaches it,
so the reader watches it being climbed. Question 7's figure is the direct evidence on agency
and can go either way.

Ruled out: a map of accident sites, which can identify people; agent minutes against
investigation months, which suggests the agent replaces the investigation; and a live
headline percentage, which makes the board a scoreboard.

## 8. The Open cases page

A separate page, complete, reached by a plain link. Andy's view is that this data may not be
interesting, so it is not on the main path.

Most open cases have no docket until closure, so the agent has little to read. **There is no
early-docket section** (Andy, 2026-10-05): the page carries one counted line instead, for
example "5 open cases have a docket so far", and those cases are coded at closure like every
other. The count below is why: such a section would be almost empty. Counted as numbers only
(decision [0024](../decisions/0024-open-split-enters-measurements-only-as-numbers.md)).

**The count, citable** (`docs/results/s5-recorder-report-2026-10-06.txt`, the recorder's
report over its first 14 finished nights, 23 September to 6 October 2026, the threshold at
which the report counts as citable; the earlier 12-night copy,
`docs/results/s5-recorder-report-2026-10-04.txt`, gave the same docket figures):

- Of the cases that closed while watched, none had a docket before closing. Every docket
  that appeared, 46 of them, appeared on the same nightly run as its case's closure.
- Of the 936 cases watched from the first night, 5 already had a docket. That is a lower
  bound on early dockets, about 0.5%, well below Andy's estimate of 2 to 5%.
- 300 documents appeared at those 46 closures.

So far, the closure run is the only run with evidence to read. Nights 13 and 14 brought no
closures and no new documents.

**The page shows counts, never a list of open cases** (Andy, 2026-10-11). An earlier draft gave
each open case a row of facts and status (accident date, aircraft type, state, and "awaiting
docket" or "docket: 4 documents"), never an answer. Andy dropped the rows: a list of open cases
says little a count does not, and the export S5 reads, `board/1`, holds nothing about an open
case beyond counts (S4's export decision, on the S4 branch until it merges). So the page states, from `board/1`'s `counts`: the open cases watched, how many hold a
docket so far, and the closures each night. No first belief is made or shown for any open case:
facts alone score below the no-model baseline. The page follows §11.

## 9. The Methods page

The reference page for the second reader. Every number on the site links to its entry here:
the sample, the model, the commit, the script, the interval, and the count it rests on. It
states the three arms, the baseline, the ablations, and the caveats.

**Layout: in the order the reader meets the numbers** (Andy, 2026-10-05). A plain page, not a
scrolling route, so a link from any page lands beside the entries around it:

1. **How to read the numbers.** What "first code matches" (top-1) and "among its three"
   (top-3) mean; what a 95% interval is; held-out, development and live cases, and why they
   never share a figure; billed cost and list price.
2. **The board.** The three grades, the counts since launch, failures and abstains, the
   declared start date.
3. **The ladder.** Each step's run, sample, model, commit, script, interval and count (§7.1).
4. **Each Path question in turn**, with its figure's source.
5. **S3.2's registered predictions**, given prominence: each prediction as written before the
   held-out run, and whether it was met (`docs/rounds/s3-registration.md`,
   `docs/results/s32-claims-heldout.txt`). Predictions made in advance and shown when not met
   are among the strongest honesty signals the site has.
6. **History.** S1's one-shot ceiling and S2.4's bars, which the ladder replaced.
7. **Limits.** The run-twice band, the per-case cost cap, failure counts.
7a. **How the verdict is withheld**, with a diagram of the split (Andy, 2026-10-05), reached
   from the line on every opened case (§5). It draws the real mechanism of decisions 0013,
   0016 and 0077, in plain words:

   ```mermaid
   flowchart LR
     R["One case: the NTSB record and its docket"] --> S{"The split, one function"}
     S -->|evidence| E["Recorded facts; docket documents classed as evidence"]
     S -->|synthesis| Y["The investigators' factual and analysis write-ups; docket documents classed as synthesis"]
     S -->|verdict| V["Probable cause; occurrence and finding codes"]
     E --> G["The guard: five checks"] --> A["The agent"]
     Y --> W1["Withheld"]
     V --> W2["Withheld until the agent has answered"]
     A --> C["Scoring: the answer against the verdict"]
     W2 --> C
   ```

   Beneath it, the guard's five checks in one line each: only declared fields are read; the
   evidence has a fixed shape; no field comes from a withheld part of the record; a test
   checks every value against its source; and a final check refuses the case if any verdict
   sentence or code appears in what the agent would see, while a sentence shared with the
   analysis write-up only marks the case. A last line says a test deliberately breaks the
   split to prove the checks catch it.

   *Note, 2026-10-14 (Andy, step 5 preview):* the page draws the mechanism as built, not the
   draft above. No docket document is classed or held back by its title: decision 0056 found the
   deny-list cannot be filled from titles, and `docket/filter.py` admits every document whose
   text could be extracted. The evidence route reads "the recorded facts, and every docket
   document with readable text", and the last check is what stops a document holding the
   verdict, by refusing the whole case. The fifth check is worded from `records/guard.py`:
   sentences of the factual write-up may appear in docket documents and weather reports, which
   it quotes; a sentence of the analysis write-up in a docket document only marks the case
   (0077).
8. **Glossary**, with the NTSB terms that the other pages show in small type (§12, item 4).

Closed-case numbers from the board and held-out numbers from evaluation never share a figure
(decision [0021](../decisions/0021-agency-measured-as-hypothesis-trail.md)).

## 10. Appearance

- **The theme is an airport, used quietly.** At launch the pixel look has one home: the board,
  drawn as a terminal display in dot-matrix letters. Everything else is plain signage type.
  Pixel-art vignettes are a later addition (§10.1). Pixel type for the site name, navigation
  and headings, as Andy's reference site uses, was considered and declined (Andy,
  2026-10-05): headings stay plain.
- **Small airport cues are allowed outside the board**: an amber wayfinding sign as a label,
  for example. Aircraft appear only in the Path vignettes, on the ground (§10.1). Nothing
  anywhere shows an accident.
- **Long text never goes on the board.** Dot letters are hard to read in sentences. Cause
  statements live in the opened case.
- **Light and dark** are both designed. The board is dark in both.
- **Meaning is carried by shape and words, not colour alone.** No red and green.

### 10.1 Pixel-art vignettes of people at work (deferred)

**Deferred, not part of S5's first version** (Andy, 2026-10-04). The Path page is designed to
work without them, and the site does not wait for them. What follows is the brief for when
they are made. Andy's visual reference is <https://pnn.watch/>; from it, role portraits in one
fixed template (a small bust in a square frame, a job title, no name, and one line on the
record that role produces) were proposed as a simpler form than the scenes below, and are
part of this brief. PNN's named characters, jokes, viewer counts and "LIVE" badges do not
transfer to a site about fatal accidents.

Andy asked for animated pixel art of engineers investigating, done carefully and subtly, and
widened it to engine work and roles around the airport, air traffic control among them
(2026-10-04). Each Path stop carries one small vignette.

**What the vignettes show: the people whose work becomes the docket.** An engine examination,
a controller's radar and radio log, a weather observation, a mechanic's logbook: each is a
document the agent reads. Showing those people tells the reader where the messy files come
from, which is the first of the three impressions (§2). Each vignette's caption names the
record that role produces, so the art says "this is what the agent reads", never "this is
what the agent does". The agent replaces the analysis, not the field work.

**The rule that keeps it respectful: normal operations only.** People at work, an intact
engine on a stand, an aircraft parked or taxiing at a distance. Never an accident, damage,
smoke or fire, wreckage, an emergency response, distress, or an injured person. No aircraft in
flight: on a site about accidents, an aircraft in the air reads as foreshadowing. An engine is
always shown whole; a damaged one would be wreckage.

Proposed scenes, one per question:

| question | the vignette | the record it stands for |
|---|---|---|
| 1. An answer key | an investigator places a closed report in a filing drawer | the published verdict |
| 2. One model call | a person holding a single card of basic facts | the start facts, all the one call sees |
| 3. Reading the docket | an engine on a stand, an examiner with a lamp and a clipboard | the engine examination report, often the document that settles a case |
| 4. Scanned pages | a mechanic writing in a logbook by hand | handwritten records arrive as scans the agent cannot read while transcription is paused |
| 5. Misses are coding | a hand choosing between two index cards | the NTSB's coding conventions |
| 6. The answer key's consistency | two desks, the same report, two different cards written | two coders, one account |
| 7. Choosing what to read | a controller at a radar screen, a weather observer at an instrument | radar, radio transcripts and weather data, which make up most large dockets; the agent chooses whether to read them |
| 8. Newly closed cases | a person at a terminal window, the display board beyond, an aircraft parked at the stand | the live test |

**How they look and move:**

- Small, beside the question, never larger than its figure. Two or three colours, all from
  the page's own tokens, so they sit in both light and dark.
- People have no faces and no names. There is no recurring character, so nothing reads as a
  mascot or a game.
- No agency's name, logo or uniform lettering. The NTSB is never drawn, so the site cannot be
  read as speaking for it.
- A few frames, such as a page turning or a lamp coming on. Each plays once when its stop
  arrives and rests on its last frame. With reduced motion, only the last frame is shown.
- Each has a plain text description for screen readers.

The first page carries no vignettes. Its stops hold real cases, and the art stays away from
them.

## 11. Respect

These are fatal accidents. The rules of the project apply to every page.

- No victim names anywhere. On amateur-built aircraft the make and model are replaced by the
  label `Amateur-built` (decision
  [0020](../decisions/0020-amateur-built-make-and-model-replaced-in-evidence.md)).
- Nothing reads as a game. The result words are "same" and "different", never "right", "wrong",
  "win" or "score". Motion marks arrival only, never a result (§3.1).
- **Injury level appears in the opened case only**, in plain type, as one fact among the
  others. It is not on the board. (Andy accepted this as a starting point; open to change.)
- Mock-ups and screenshots use invented cases or development-split cases only. No open-split
  case reaches design work (decision 0024).

## 12. Appearance and reader-experience points still to settle

Raised on 2026-10-04 and worked through with Andy on 2026-10-04 to 2026-10-06. Each item
says whether it is settled.

1. **The author.** Settled: one line at the foot, linking to Andy's profile page (§3.1).
2. **A three-minute route.** Settled: the first page is one scrolling route of six stops
   (§3.1).
3. **Caveats before results.** Settled: the caveat sits in stop 1, above the board, in the
   wording Andy approved on 2026-10-05 (§3.1).
4. **Terms for a non-expert.** Settled (Andy, 2026-10-04): plain labels first, the NTSB's
   term second in small type, for example "What happened · NTSB occurrence codes", "Why it
   happened · NTSB findings", "The case's evidence files · the docket". Full definitions sit
   in a glossary on the Methods page. The agent's own explanation written for a non-expert is
   **not shown**: the NTSB publishes nothing to compare it with, and on a site where every
   claim is measured, unscored text sits badly. It stays in the trail data and can return if
   it is ever graded.
5. **Failures on the board.** Settled: abstains and failed cases each have their own row and
   mark (§4).
6. **The thin board at launch.** The board must look complete with few rows, and on a night
   with no closures. The count (§8's source, 14 nights): 47 cases closed in the recorder's
   first 14 nights, in three batches, on 23 September, 1 October and 2 October; the other
   eleven nights had none (the per-night breakdown is from an ad-hoc read-only query of the
   store's status changes, re-run on 2026-10-06, to be replaced by a script before
   approval). So most
   nights bring no new rows, and closures arrive in bursts. Settled (Andy, 2026-10-05):
   - The board lists the most recent closures whatever their date, so it never empties, and
     its stamp names both the last rebuild and the last closures, for example "Updated 03:00
     UTC · last closures 2 Oct".
   - **At launch the board is backfilled from a declared start date**: the recorder's first
     night, 23 September 2026. Every watched case that closed on or after it is coded,
     abstains and failures included, so nothing is selected. Those rows carry the label
     "coded after launch, from the declared start". The verdict was public by then; the guard
     withholds it exactly as in evaluation and as on every live row. Starting the recorder
     early is what makes this possible: it holds when each case closed and when its docket
     appeared.
7. **Motion.** Settled: each stop animates in on arrival, within the four limits of §3.1. No
   scrolling text. Hiding the next stop until it arrives, which failed on a phone in the first
   attempt (§3.1), is set aside for now (Andy, 2026-10-05): the site stays with stops that
   animate in, with all content present for anything that does not scroll. Andy will find an
   example site that does the effect well, and it is revisited from that. The mock-ups here are sketches of content and order; none has been
   tested across devices, and the built site needs proper front-end work.
8. **Access.** Settled (Andy, 2026-10-05): the site aims to meet **WCAG 2.2 level AA** on
   every page, built in from the start, not added after. In particular:
   - The board is a real HTML table set in the dot font, never an image, so screen readers
     read it and its text can be searched and copied.
   - Every result mark carries its word ("same first code", "same codes, other order",
     "different", "agent abstained", "not coded"); shape is never the only signal.
   - The ladder and every figure have a data table behind them for screen readers.
   - Contrast meets AA in light and dark, the board's dim text included.
   - Motion never hides content from assistive technology, and reduced motion shows
     everything at once (§3.1).
   - The build runs an automated accessibility audit before launch and fails on AA errors;
     a manual keyboard and screen-reader pass covers what automation cannot.
9. **Uncertainty.** Settled: every score on the Path and Methods pages carries its interval and
   count; the ladder draws each step as a bar with a whisker for its interval (§7.1).
10. **Totals on the first screen.** Settled (Andy, 2026-10-04): one line under the board gives
    plain counts since launch for each grade, abstains and failed cases included, with no
    percentage. Example (invented): "Since launch: 41 same first code, 37 same codes in
    another order, 68 different, 6 abstained, 3 not coded." It links to the Methods page,
    where intervals appear once there are enough cases. The strip of closed cases on the Path
    page's last question shows the same tally as marks over time.
11. **Links out.** Settled (Andy, 2026-10-04): each case links to the NTSB's own page and
    docket, and shows the NTSB case number as text, so any row can be checked against the
    source. The registration is not shown: it adds nothing to the comparison, and it leads
    straight to an owner's name in the public aircraft register, often the pilot who died. It
    stays one click away on the NTSB's page; the choice is what the site puts forward, on the
    reasoning of decision 0020.
12. **Shared links.** Settled (Andy, 2026-10-05):
    - Addresses: a case page lives at its NTSB case number; each Path question has a short
      readable anchor, such as `/path#choosing`.
    - Preview cards by kind of page. The first page, Path, Methods, Open cases and **every
      case page** carry one site card: the board's dark panel with the site's question in dot
      letters, the title "Ellery", and one line on what it does. **Each Path question** gets
      its own card with its question and its answer, for example "Does choosing what to read
      beat reading everything? No.", because the findings are what readers should share.
      No card ever shows a case's details: individual accidents, often fatal, are kept out of
      social feeds (§11).
15. **The name.** Settled (Andy, 2026-10-06): the agent and the site are both **Ellery**, at
    **`ellery.demo.floyda.dev`**. On the site the agent is "Ellery, version 1", and later
    versions keep the name with a new number. The site calls Ellery "it". The name comes from
    Ellery Queen, the American detective of 1930s fiction, whose novels stopped near the end
    with a "Challenge to the Reader": the reader now held every clue the detective had. That
    is the site's premise: Ellery works from the evidence the investigators recorded, and every
    reader can check its answer against the NTSB's verdict. Methods says this in one line, and
    says the name stands for no real person. The caveat (§3.1) and the site card (item 12)
    use the name. The record of how the name was reached follows.

    **Certificate and DNS, checked 2026-10-06.** A public lookup of `floyda.dev` found its
    name servers are Amazon Route 53's (`awsdns`), so DNS is already in AWS and Squarespace
    holds only the registration; there is no CAA record, so no certificate issuer is
    restricted; the apex already points at AWS addresses. So S5's stack can request an exact-
    name certificate for `ellery.demo.floyda.dev` from AWS Certificate Manager (free,
    auto-renewing, in `us-east-1` because CloudFront requires it), validate it with a DNS
    record, and add the site's alias record, all in the existing hosted zone and all in code,
    with no change at Squarespace. The two-level name costs nothing with an exact-name
    certificate; it matters only for wildcards, where `*.floyda.dev` would cover
    `ellery-demo.floyda.dev` but not `ellery.demo.floyda.dev`, and `*.demo.floyda.dev` would
    cover every future demo. **Checked 2026-10-06: the two are different AWS accounts.** The
    `floyda.dev` hosted zone is in Andy's personal account, beside his profile site's bucket;
    the recorder runs in the project's own member account of the same organisation. The
    proposed answer, for S5's build: create a hosted zone for `demo.floyda.dev` in the
    project's account and delegate to it with NS records in the `floyda.dev` zone. That is
    four records, added once, all in Route 53 with nothing at Squarespace. S5's stack then
    makes Ellery's certificate and records in its own account, and every later demo under
    `demo.floyda.dev` can do the same. This is a second reason the two-level name was a good
    choice.

    Neither the agent nor the site had a name before 2026-10-05, and no earlier ideas were
    written down. "Probable cause", the NTSB's own term, was a placeholder. Settled first (Andy,
    2026-10-05): the site lives under Andy's domain, `floyda.dev`; the name should play on the
    analysis side of an investigation, the part the agent replaces. Whether it sits at a path
    or a subdomain is a hosting choice for S5's build. Rules for any name: no "NTSB" in it, no
    accident wordplay. Andy then chose a human name after all, invented, not a real person's,
    old-fashioned and American, beginning with A, in the spirit of "Analysing Arthur"
    (2026-10-05); the site calls the agent "it" whatever its name, and Methods says the name
    stands for no real person. A web search on 2026-10-05 for existing AI agents with the
    shortlisted names found: **Archie** crowded (several commercial AI agents and assistants,
    legal, finance, marketing, data catalogues); **Amos** to be avoided (AMOS is a known macOS
    information-stealing malware that disguises itself as AI agent tools); **Asa** colliding
    with "ASA", Amazon Web Services' agentic shopping assistant; **Ansel** used by several AI
    agent products; **Alonzo** lightly used (a small analytics engine named after Alonzo Church,
    and a small consultancy). This was a quick search, not a trademark search. Andy then
    widened the search beyond A to any name that plays on analysis or investigation
    (2026-10-06). A second search found: **Ellery** used only by one custom GPT on OpenAI's
    store; **Findlay** with no AI agent found; **Tracy** crowded (a supply-chain agent, a hiring
    agent and several more). Names set aside without searching, for their associations:
    Casey (Casey Jones died in a train wreck), Quincy (a television medical examiner),
    Sherlock, Watson (IBM's AI), Marlowe (an anchor on Andy's reference site), Dexter.
13. **The first against the second version.** Settled (Andy, 2026-10-05): a ninth stop on the
    Path page, "Does letting the agent question precedent help?", showing the second version
    against the first on the same cases, held-out and live kept apart. The board keeps showing
    the first version until the second wins its registered comparison, so the second version
    earns its place as the loop had to (§7.3).
14. **Freshness.** Settled: the board's stamp names the last rebuild, in UTC, and the last
    closures (item 6).

## 13. What this asks of other stages

- **S3.3: point the shadow at closure runs** (decision 0154 item 6). A nightly shadow on open
  cases would mostly run on the recorded facts alone, where the agent does no better than
  guessing; the runs worth exercising are closure runs and the backfill from 23 September
  2026 (0155). S3.3's specification decides how.
- **S4: the main run happens at closure.** The roadmap describes predictions locked on open
  cases and scored at closure. With few dockets before closure, the run that matters is the
  one made when the case closes, with the verdict withheld by the same split and guard as
  evaluation. The recorder's first count found no docket arriving before closure (§8), so the
  site shows no answers locked before the verdict. Whether S4 still runs and locks early
  answers is S4's decision; the count argues it is low value. A stored answer that cannot be
  edited afterwards is still worth having for every case, as proof that rows were not changed
  later, though it no longer proves anything about not knowing the verdict. The site shows a
  withheld-verdict line on each opened case (§5); S4 supplies its date, time and commit.
- **S4: the model's training cut-off.** A model can only have seen a verdict in training if
  the case closed before its training data was gathered. Cases closing now are likely after
  GPT-6 Luna's cut-off, which makes the live board the cleanest test the project has; this
  has not been verified. S4 records the model's published cut-off so the site can state it.
- **S4 or S5: document titles.** The trail view needs each document's title, joined from the
  docket listing by position. A document classed as synthesis is shown as withheld, without
  its text.
  *Note, 2026-10-11:* S4's `board/1` carries the titles. A document the agent could not be
  offered is `not_offered`, with its reason, never "withheld": a document holding the
  probable cause makes the whole case "not coded".
- **S4: the store answers these pages.** For each closed case: the facts on the board, both
  code lists, both cause statements, the findings, the trail, and the costs.
- **S3.2: the ladder's numbers.** Delivered (§7.1); one interval to recompute by one script.
- **The masked condition is paused** (decision
  [0123](../decisions/0123-the-staged-replay-is-paused.md)), so the Methods page describes
  one availability condition, not two.

## 14. What changes in the roadmap at merge

This note edits no shared file while S3.2 is open. When it merges, the roadmap's §8 is amended:
five pages become the six of §3; the live board becomes the board of closed cases; the
hypothesis trail is described as checkpoints, not a belief after every call; "two availability
conditions" becomes one. The top-level and repository `CLAUDE.md` files follow.

## 15. Decisions

**Recorded on 2026-10-06, because they bind S3.3 and S4:** decision
[0154](../decisions/0154-the-live-run-is-at-closure.md) (the live run is at closure, no
answers locked before the verdict; items 3 and 4 below in part, and §13),
[0155](../decisions/0155-the-board-is-backfilled-from-the-recorders-first-night.md) (the
backfill; item 12) and [0156](../decisions/0156-the-board-runs-ellery-version-1.md) (Ellery,
version 1, on the board; items 14 and 15).

**The rest are recorded when this specification is approved**, as S5's own decisions:

1. The primary reader, the second reader, and the link rule (§2).
2. The board lists closed cases; open cases have their own page, of counts only (§3, §4, §8).
3. The agent's main live run is at closure (§13); this amends what S4 was to build.
4. The theme: an airport terminal display for the board only (§10).
5. Injury level in the opened case only (§11).
6. Beliefs as the spine of the trail view (§6).
7. The Path page: a ladder from one sample, then eight questions (§7).
8. The first page is one scrolling route of six stops, with the caveat above the board and the
   author line linking to Andy's profile page (§3.1).
9. Abstained and failed cases have their own rows on the board; the middle grade is a top-3
   match that is not a top-1 match (§4).
10. The Path page is a second scrolling route, one stop per question, ending with the version
    comparison (§7, §12 item 13).
11. Pixel-art vignettes are deferred past S5's first version; when made, they show the people
    whose work becomes the docket, in normal operations only (§10.1).
12. At launch the board is backfilled from a declared start date, the recorder's first night
    (§12, item 6).
13. What the site puts forward about a case: the NTSB case number, never the registration;
    plain labels before NTSB terms; counts, not percentages, beside the board (§12).
14. The board runs the loop as version 1, stated as such, although the fixed pipeline measured
    better on held-out cases (§1).
15. The agent and the site are named Ellery, at `ellery.demo.floyda.dev` (§12, item 15).
16. WCAG 2.2 level AA on every page (§12, item 8); preview cards by kind of page, with cases
    kept out of social feeds (§12, item 12); a withheld-verdict line on every case and a
    diagram of the split on Methods (§5, §9).
17. The site is built with Astro, its packages managed by pnpm, locked and delayed 7 days (§17.1,
    §17.2).
18. The site is rebuilt by AWS CodeBuild when the export lands and after each merge to `main`,
    not by a scheduled GitHub workflow (§18.1).
19. CloudFront serves the site on the flat-rate Free plan (§18.3).
20. Every number on the Path and Methods pages comes from a script-written numbers file, quoted by
    name (§17.3).
21. Previews are private pages; the public address shows a holding line until Andy decides to
    launch (§20).

Items 17 to 21 are numbered after S4 merges, because S4's branch is still adding records.

## 16. Open questions for Andy

1. Settled: the middle result grade is a top-3 match that is not a top-1 match (§4).
2. Settled: an open case is never listed; the Open cases page shows counts only (§8; Andy,
   2026-10-11, replacing the 2026-10-04 rows of facts and status).
3. Settled: the Methods page follows the order the reader meets the numbers (§9).
4. Every point in §12 is settled, except hiding the next stop until it arrives, which waits
   for an example site from Andy (item 7).
5. Settled: the board keeps its six columns; the opened case states documents read as "3 of 7
   documents read" and leaves out cost (§5).
6. Settled: the vignettes come later, after S5's first version (§10.1). Their form, scenes
   or role portraits, and who draws them are decided then.
7. Accepted as a first draft (Andy, 2026-10-04): the figures of §7.4.
8. Still open: the per-night closure count needs a committed script (§12 item 6); the
   mock-ups predate most decisions here and are sketches only. The recorder's counts became
   citable at 14 nights on 2026-10-06 (§8).

## 17. How the site is built

§1 to §16 say what the site shows. §17 to §22 say how it is built, published and checked. Andy
chose each point in a design session on 2026-10-11, one question at a time; the reasons and what
each rules out are recorded as decisions when this specification is approved (§15, items 17 to
21).

**The starting rule is decision [0003](../decisions/0003-static-site-as-pure-function-of-store.md):**
the site is generated ahead of time as files and served from S3 behind CloudFront. Nothing is
computed when a reader arrives: no server, no database, no API. Everything below keeps that rule.

### 17.1 The generator: Astro

The site is an Astro project in `site/`, beside the Python packages.

*Why:* Astro builds plain HTML and sends no script unless a part asks for it. So the board, the
opened case and Methods work with scripts off and read well in a screen reader by default (§12,
item 8), and only the parts with behaviour carry script. It suits pages that are mostly text, one
table and a few figures.

*Ruled out:* **Python with templates.** One toolchain, but the scrolling route, the board and the
figures are where the JavaScript tools are strongest (Andy, 2026-10-11). **SvelteKit.** The best
built-in animation, but every page loads its runtime script, so working with scripts off needs
care on every page. **Eleventy.** The plainest, but all behaviour would be loose hand-written
script.

### 17.2 Dependencies: pnpm, locked and delayed

The site's packages are managed with pnpm. Andy asked that dependencies be locked and that new
releases not be taken too soon (2026-10-11), because a poisoned release is the commonest way a
supply-chain attack reaches a project. Each setting below is from pnpm's settings reference, read
2026-10-11:

- **A committed lockfile**, installed with `--frozen-lockfile` everywhere, so a build never
  resolves anything new.
- **`minimumReleaseAge: 10080`** (7 days, in minutes): pnpm refuses a version published less than
  a week ago. Most poisoned releases are found and removed within days. pnpm 11's default is one
  day; the site sets 7 explicitly.
- **No install scripts by default.** A package may run a build script only if it is named in
  `allowBuilds`; with `strictDepBuilds` an install fails if an unreviewed package tries.
- **`trustPolicy: no-downgrade`**: the install fails if a package's release is less trusted than
  its earlier ones, for example a release published without the usual signing.
- **`blockExoticSubdeps`** (on by default): only a direct dependency may come from git or a
  download link; every indirect one comes from the registry.
- **Dependabot** watches the site's packages weekly, with a 7-day cooldown. The same cooldown was
  added for the Python packages on 2026-10-11, in an incidental pull request outside S5.

The site's checks are held to the strictness of decision
[0011](../decisions/0011-tooling-uv-hatchling-strict-analysis.md): strict TypeScript, Astro's
type check, a linter, a formatter, a pinned Node version and a dependency audit, run by
`make check`, in CI and in the pre-commit hooks.

### 17.3 Inputs

The site reads two things, and nothing else.

1. **The export, `board/1`**, S4's nightly files: `index.json` and `cases/<case number>.json`. A
   loader checks every file against `docs/schemas/board-1.schema.json` and stops the build on a
   mismatch; the site's types are generated from the same schema. A missing key is read as null
   (S4's request). **Only the case files that `index.json` lists are read**: S4's task cannot
   delete, so a case file that drops out of the export stays in the bucket (§22). Development
   builds use S4's invented sample in `tests/fixtures/board/` unless a
   real export is named.
2. **The numbers file, `site/data/numbers.json`**, for every number on the Path and Methods pages
   (§7, §9). A Python script under `scripts/`, with its own tests, writes it. Each entry holds the
   value, its interval and count, the sample, the model, the run, the results file and the script.
   Example (the values are S3.2's, from `docs/results/s32-claims-heldout.txt`):

   ```json
   "ladder.loop.top1": {
     "value": 0.235, "low": 0.192, "high": 0.275, "n": 400,
     "sample": "heldout-400", "model": "openai/gpt-6-luna",
     "run": "20261004T140804-e0dc881-heldout-400-C",
     "results_file": "docs/results/s32-claims-heldout.txt",
     "script": "scripts/s32_claims.py"
   }
   ```

   A page names the number, `ladder.loop.top1`; the build writes "23.5% [19.2%, 27.5%], 400
   cases" and links it to its Methods entry, and the ladder draws its bar from the same entry. No
   number is typed into a page. The Methods page is generated from the entries. The file changes
   only when results change, and its diff shows which numbers on the site moved.

   The same script also copies the few **fixed sentences the site must quote from the code**,
   so none is retyped by hand. The first is the limit of the names step, `live/names.py`'s
   `NAMES_LIMIT` on S4's branch, which the Methods page states (§9, §11).

   *Ruled out:* **Astro reading the results files directly**, which are written for people, each
   laid out differently, so a change of wording could silently break a number. **Numbers typed
   into pages with a check** that each appears in its cited file, which is weak ("23.5%" can
   appear for another reason) and against the rule that every number comes from a script.

### 17.4 Pages and addresses

| address | page |
|---|---|
| `/` | the scrolling route of six stops (§3.1) |
| `/case/<case number>/` | the opened case (§5) |
| `/case/<case number>/trail/` | the trail view (§6) |
| `/path/` | the Path page; each question has a short anchor, for example `/path#choosing` (§7, §12 item 12) |
| `/methods/` | the Methods page (§9) |
| `/open/` | the Open cases page, counts only (§8) |

Made at build time, so they need no script: the board as a real HTML table in a self-hosted
dot-matrix font; each figure as SVG with a data table behind it; the sentence on where the two
codings differ, written in site code from the comparison marks (§5), never by a model; and the
preview-card images, one for the site and one per Path question (§12, item 12).

What runs in the reader's browser is small:

- **The stops** rise into place once as they reach the screen. All content is in the page before
  any script runs, and reduced motion shows everything at once (§3.1).
- **Choosing a board row.** Without script each row is a link to its case page; with script the
  case opens beneath the board. Either way the address can be shared.

Fonts and scripts are served from the site itself, never from another site at read time.

## 18. The rebuild and the AWS stack

### 18.1 Each morning

1. S4's nightly task rebuilds the export into `export/board-1/` in its private bucket, at about
   06:15 UTC (S4's specification, §5), and writes a finished mark last (§22).
2. The mark starts the site's CodeBuild job, through an EventBridge rule.
3. The job fetches the site's code from `main`, copies the export down, checks it against the
   schema, builds the site with Astro, and runs the checks of §19.
4. If all pass, it copies the site to the site bucket (§19.1 gives the order) and clears
   CloudFront's copies. Readers see the new board within minutes.
5. If any step fails, nothing is published, yesterday's site stays, and an email goes out through
   S4's alert topic.

A merge to `main` starts the same job, so a change to the site's code goes live the same way. The
Path and Methods pages change only when the numbers file is regenerated and committed.

*Why CodeBuild, not GitHub Actions:* both cost about nothing here (below). GitHub turns off
scheduled workflows in a public repository after 60 days without activity, so a quiet project
could leave the board stale with no alert. A build started by the export's arrival never goes
dormant, keeps its logs private, and can email on failure. *Ruled out:* **GitHub Actions on a
schedule**, for that reason; **the build inside S4's nightly task**, because a change to the site's
styling would then need a new live image.

### 18.2 The stack, `NtsbSiteStack`

A new CDK stack in Python, in the project's AWS account, beside `NtsbRecorderStack` and S4's live
stack.

- **DNS.** A hosted zone for `demo.floyda.dev` in this account. Andy adds four NS records once in
  the `floyda.dev` zone in his personal account, to delegate to it (§12, item 15).
- **Certificate.** An exact-name certificate for `ellery.demo.floyda.dev` from AWS Certificate
  Manager, in `us-east-1` because CloudFront requires it, validated by DNS and renewed
  automatically.
- **The site bucket.** Private, versioned, in `eu-west-2`, readable only by CloudFront.
- **The distribution.** CloudFront on the **flat-rate Free plan** (§18.3), HTTPS only, with
  standard security headers and an error page.
- **The build.** A CodeBuild project on the smallest machine, with a 15-minute limit. Its role may
  read `export/board-1/` and nothing else in S4's bucket, write the site bucket, clear CloudFront's
  copies, and publish to S4's alert topic.
- **The rules.** S4's finished mark starts a build; a merge to `main` starts a build, through a
  GitHub connection that Andy approves once; a failed build sends an email.
- **Who does what.** Andy runs `cdk deploy`, since the stack creates roles, as for the earlier
  stacks; adds the NS records; and approves the GitHub connection.

### 18.3 Cost

About **$0.50 a month**, nearly all of it one fixed charge. Prices are external, from AWS's
pricing pages, read 2026-10-11; volumes are estimates.

| part | cost | basis |
|---|---|---|
| hosted zone `demo.floyda.dev` | $0.50 a month | Route 53: "$0.50 per hosted zone per month"; alias lookups to CloudFront are free |
| CloudFront, flat-rate Free plan | $0 | 1 million requests and 100 GB a month; "no overage charges … even during traffic spikes or attacks"; includes 5 GB of S3 storage credit |
| site bucket | $0 | a few megabytes, inside the plan's credit |
| CodeBuild | about $0 | 100 free build minutes a month on the smallest machine, which do not expire after the first year; a build is estimated at 2 to 3 minutes, so about 60 to 90 minutes a month; past that, the page's example rate is $0.005 a minute |
| certificate, event rules | $0 | |

A visit is roughly 10 to 20 requests (estimate), so the Free plan carries something like 50,000 to
100,000 visits a month. The step up, if ever needed, is the Pro plan at $15 a month.

*Why the flat-rate plan:* decision 0003 promises a hosting bill that does not move with traffic.
Pay-as-you-go pricing still bills a spike of readers; a flat-rate plan does not. *Ruled out:*
**pay-as-you-go**, for that reason.

**To check before relying on it:** what CloudFront does when the Free plan's allowance is passed,
and whether CDK can choose the plan or Andy sets it once in the console. The runbook records the
answer.

*Checked 2026-10-12 (S5 step 1, Task 5), from AWS's CloudFront developer guide on flat-rate
plans and the CloudFormation reference, read that day:*

- **The plan is set in code.** CloudFormation's `AWS::PricingPlanManager::Subscription` (in CDK as
  `aws_pricingplanmanager.CfnSubscription`, available in `eu-west-2`) subscribes the distribution
  to the `FREE` tier, active at once. No console step.
- **It needs an AWS WAF web ACL** on the distribution, of `CLOUDFRONT` scope, so in `us-east-1`.
  `NtsbSiteEdgeStack` adds one: allow by default, and one rule that blocks an address making more
  than 600 requests in 5 minutes (the Free plan allows 5 rules; blocked requests never count
  against the allowance). Without the plan a web ACL bills pay-as-you-go, so the runbook checks
  the plan is active.
- **The plan also covers the `demo.floyda.dev` zone**, whose DNS it includes, so the site's
  expected bill is **$0 a month** rather than $0.50, while DNS queries stay within the plan's
  allowance.
- **Past the allowance** there is never an overage charge. AWS emails at 50%, 80% and 100% of the
  allowance; usage that "consistently and significantly" exceeds it over months may see delivery
  adjusted (served from fewer or more distant edge locations) until the plan is upgraded.
- An account may hold at most 3 Free plans.
- *Found at the first deploy, 2026-10-13:* the Free plan (and Pro) refuses **custom response
  header rules**. The standard security headers come from AWS's managed `SecurityHeadersPolicy`,
  and the Content-Security-Policy is added by a CloudFront Function, both allowed on Free.

## 19. Failures and checks

### 19.1 When something goes wrong

- **The export fails the schema, or any step fails:** nothing is published; yesterday's site
  stays; an email goes out.
- **S4's night fails, so no new export arrives:** no build starts and the board keeps its last
  state. The board's stamp shows the export's own build time (`stamp.built_at`), never the site's,
  so stale data never looks fresh (§12, item 14). S4 already alerts on a failed night.
- **Publishing order:** new styles and scripts first, then pages, then removal of files no longer
  used, so a reader mid-deploy never gets a page without its styles. The bucket keeps old
  versions; going back is a build at the previous commit.

### 19.2 Checks on every pull request

Run in CI and by `make check`:

- The site builds against S4's invented sample, and the sample passes the schema.
- Unit tests for the site's logic: the difference sentence, the grade marks, a missing key read as
  null.
- **Accessibility:** an automated WCAG 2.2 AA check of every built page, in light and dark, fails
  on any error (§12, item 8). Screenshots at a phone width of 390 pixels, by the method that renders
  true phone width on this machine. A manual keyboard and screen-reader pass covers what automation
  cannot, before launch (§20).
- **Links:** every internal link resolves, and every number links to an existing Methods entry.
- **The numbers file:** the script's tests, and a consistency check that each entry's value
  appears, formatted, in the results file it names. This catches a copy that has drifted from its
  source, although CI cannot re-run the parts that read run folders on Andy's Mac.
- **Respect (§11):** the built pages are scanned for the registration pattern, and every case page
  must belong to a row on the board, so no other case reaches the site. S4's export is already
  checked; this checks what is published.

## 20. Previews and launch

**Previews are private pages.** Each part, when ready, is built against S4's sample, or a real
export once one exists, and published as a private claude.ai page that Andy can open on any
device, labelled with its commit and checked at phone width before it is sent. No second AWS
setup is kept. *Ruled out:* **a password-protected preview address**, a second distribution and an
edge function for one reviewer; **publishing unfinished**, an unfinished page about fatal
accidents at Andy's own domain.

**Before launch the public address shows one holding line**, for example "Ellery: coming soon".
The stack is deployed early, so the certificate, the DNS and the builds are proven before launch.

**Launch is Andy's decision** (2026-10-11). These conditions are what Claude reports as ready;
they never trigger it:

1. S4 has merged, its first cloud night has run, and the backfill is coded, so the board starts
   complete from 23 September 2026 (decision
   [0155](../decisions/0155-the-board-is-backfilled-from-the-recorders-first-night.md)).
2. Every page is built, and every check in §19 passes.
3. Andy has made the manual pass on his phone and with a screen reader.

On launch day the holding line is replaced by the site, and the real address's certificate,
redirects and preview cards are checked.

## 21. Order of work

Each step ends in a private preview.

1. **The skeleton:** the Astro project, the pnpm settings, the checks in CI, and `NtsbSiteStack`
   serving the holding line.
2. **The board and the opened case**, against the sample.
3. **The trail view.**
4. **The numbers script and file**, then the Path page with the ladder.
5. **The Methods page**, generated from the numbers file.
6. **The Open cases page** (counts), the stops' animation, and the preview cards.
7. **Andy's manual accessibility pass.** Launch, when Andy decides.

The site works after step 5, without animation or preview cards; whether to launch then or after
step 6 is Andy's choice.

## 22. What this asks of S4

Passed to the S4 session on 2026-10-11:

1. **A finished mark**, written last, after every file of the night's export is written, so a build
   never reads half an export.
2. **The live bucket sends events to EventBridge**, so the mark can start the build.
3. **Read access for the site's build role** to `export/board-1/` only, if the live bucket's
   policy would otherwise refuse it.

S4's answer, 2026-10-11. Items 1 and 2 were pushed to S4's branch at `9c5be5d` on 2026-10-12.

- **The mark is `export/board-1/_finished.json`**, holding `{"format": "board-finished/1",
  "built_at": …, "commit": …}`. S4 uploads `cases/*`, then `index.json`, then the mark, and
  overwrites the mark each night. If an upload fails partway, the mark keeps the previous night's
  `built_at`, so **the build goes ahead only when the mark's `built_at` equals `index.json`'s**.
- **The live bucket gets `eventBridgeEnabled`.**
- **No change to the bucket's policy is needed.** Its one statement refuses requests not made over
  TLS. The site's role is given, in its own IAM policy, `s3:GetObject` on
  `export/board-1/*` and `s3:ListBucket` with an `s3:prefix` condition on `export/board-1/*`. The
  bucket's name is S4's stack output `LiveBucketName`.

Delivered by S4 on 2026-10-11, at Claude's request after reviewing the sample: optional `board/1`
fields for the NTSB's internal case key (`mkey`, for the links of §5), the launch date and a
backfill flag (§12, item 6), each document's page count (§7.4), and a reason for a document not
offered. S4's final review, 2026-10-12, added two reasons: `already_read` (at the second read
choice, a document read at the first) and `over_size_limit` (left out by the prompt-size ceiling;
the loop as built never produces it). It also replaced the case's owner, operator and registration
in document titles, with a published limit (§17.3).

## Glossary

- **Astro**: the tool that builds the site's pages ahead of time from the export and the numbers
  file (§17.1).
- **CloudFront**: AWS's service that hands the site's files to readers; on the flat-rate Free plan
  its bill does not grow with readers (§18.3).
- **CodeBuild**: AWS's build service; it builds and publishes the site each morning (§18.1).
- **Export (`board/1`)**: S4's nightly files that the board, cases and trails are built from.
- **Minimum release age**: pnpm's rule that a package version must be a set time old before it is
  installed (§17.2).
- **Numbers file**: `site/data/numbers.json`, every number on Path and Methods with its source,
  written by a script (§17.3).
- **Abstain**: the agent's statement that the evidence is too thin to answer.
- **Belief**: the agent's hypothesis at a checkpoint; the project's records call it H0, H1, H2
  and the answer.
- **Board**: the list of recently closed cases on the first screen, drawn as an airport
  terminal display.
- **Closure**: the moment the NTSB closes a case and publishes its codes and probable cause.
- **Docket**: the NTSB's public folder of supporting documents for a case.
- **Ellery**: the agent's name and the site's, after Ellery Queen's "Challenge to the Reader";
  version 1 is the loop of S3.1, frozen at `fd6053f`.
- **Finding code**: the NTSB's code for a reason the accident happened.
- **Fixed pipeline**: arm B. It reads every readable document in a fixed order and answers
  once.
- **Ladder**: the figure of four steps, each a more elaborate method, with its score and cost.
- **Loop**: arm C. The agent chooses which documents to read and which lookups to make.
- **Occurrence code**: the NTSB's code for what happened, given as an ordered sequence; the
  first is the defining event.
- **Opened case**: the comparison shown beneath the board when a row is chosen.
- **Read choice**: the step where the agent decides, for each offered document, to read it or
  skip it.
- **Scan only**: a document with no text layer, which the agent cannot read while
  transcription is paused.
- **Trail**: the record of one case's steps, beliefs and costs.
- **Verdict**: the NTSB's probable cause and codes. It is withheld from the agent.
