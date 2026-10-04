# S5 — The public site: structure, content and reader experience

Status: Draft, 2026-10-04. Nothing here is built. This note is written early, on its own branch,
while S3.2 runs, because the site's design is a large piece of work and its page list decides
what S4's store must answer (roadmap §8). It is revised and approved as S5's specification when
S5 starts. It covers what the site says and how a reader moves through it. It does not cover the
site generator, the hosting or the build pipeline; those are S5's own and depend on S4's store.

Every choice below was made by Andy in a design session on 2026-10-04, one question at a time.
Where a point is still open it is listed in §12 and §16, not guessed.

## 1. Why the site exists

The site is the demo. A reader does not run the agent or read the repository; they read the
site. The demo criteria ask for a result that is falsifiable in public, measured, honest about
negative results, and legible to a non-expert (`ntsb-spike/docs/demo-criteria.md`, in the
spike's folder).

**Success is not a high score.** The project is an experiment in how to find out whether an
agent loop earns its keep. At the time of writing the loop is level with the fixed pipeline on
the first code. The site shows that as the present state of an honest experiment.

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
| Open cases | every watched open case | a plain link; not promoted |
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
| 6. The path taken | the eight questions, each with a one-line answer (§7.2) | Path (§7) |

A slim rail of the six stops stays in view and marks the stop being read: at the left on a
wide screen, across the top on a phone.

**The caveat sits in stop 1, above the board.** It says plainly that the agent agrees with the
investigator on a minority of cases and that a simpler method does about as well. This meets
the roadmap's rule that caveats come before results, without burying the board.

**Each stop animates in as the reader reaches it** (Andy, 2026-10-04). The parts of a stop
rise into place; the board's rows turn over one after another, as a terminal display does; the
ladder's bars grow from the left in order; the trail's beliefs and the path's questions appear
in sequence.

**One stop fills the screen, and the next is not seen until it animates in** (Andy,
2026-10-04). Each stop is at least one screen tall. A stop's parts stay unseen until the stop
has risen about a third of the way up the screen, so the reader never sees the next stop
waiting below. Each stop ends with a plain "Next" link naming the stop that follows, so the
reader knows the page continues. A stop taller than the screen, such as the opened case on a
phone, scrolls in the ordinary way.

Four limits apply:

- Each animation runs once, is short (under about a second for a stop), and never repeats or
  loops. The board does not flip again when a row is chosen.
- The reader keeps control of the scroll. The page may settle gently on a stop, but nothing
  pins it or holds it.
- With a reduced-motion setting, or with scripts off, everything is shown at once, with no
  animation. No content depends on the animation to be read.
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
- **Same codes, other order** (half mark): the two lists share a code, but not in first place.
  This grade matters because the project found the NTSB's coding order, more than missing
  evidence, behind what the fixed pipeline missed
  (`docs/results/s26-occurrence-misses-dev.txt`).
- **Different** (open mark).

**A case the agent abstained on has its own row** (Andy, 2026-10-04): "No answer" in the agent's
column and "Agent abstained" as the result, with a dashed mark. Its opened case gives the
agent's stated reason beside the NTSB's cause. Leaving such cases off would be selection. A
failed case (a guard refusal or a format failure) needs a row on the same principle; its
wording is open (§12).

The exact rule for the middle grade is fixed when this note is approved; it must be one a
script computes from the two code lists.

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

1. **A line of facts.** Date closed, time to close, aircraft type, state, kind of flight,
   injury level, documents read, cost of the run.
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

It ends with links to the trail view and to the NTSB's own page for the case.

## 6. The trail view

The trail view shows one case as numbered steps, top to bottom, in plain type.

**Beliefs are the spine.** A belief is the agent's hypothesis at a checkpoint: before reading,
after each read choice that read something, and the answer (decision
[0122](../decisions/0122-h0-and-later-triggers.md)). Each belief block shows its first code, a
short explanation, its confidence, and whether it changed from the belief before.

**Actions sit between beliefs.**

- A **read choice** lists every docket document as read, skipped, or scan only. For each
  document it shows what the agent expected the document to show, and the belief after it shows
  what changed. Expected against observed is the direct evidence of whether choosing mattered.
- The **coding step** lists each lookup the agent made in the code tables and past usage.

**Cost runs beside every step**, with the case total at the top.

**The NTSB's verdict comes last**, after the agent's answer, with a line saying which belief was
closest to it.

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

The Path page tells how the project decided what to build. It has three parts.

### 7.1 The ladder

One figure with four steps: no model; one model call without the docket; the fixed pipeline
that reads every readable document; the loop. Each step shows its score and its cost. A plain
sentence beneath states the present result.

All four steps must come from **one sample on one model**, or the figure compares unlike
things. S3.2's held-out runs provide that. The ladder's shape is fixed now; its numbers wait
for S3.2. The page works whichever way S3.2 comes out.

### 7.2 Eight questions

Each has a measured answer, the decision taken from it, and a link to its script and results
file. Dead ends stay in.

1. **Is there an answer key nobody had to write?** Yes. The NTSB codes every closed case.
2. **Is one model call enough?** No. It scored below a baseline that uses no model
   (`docs/results/s1-bars.txt`).
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
7. **Does choosing what to read beat reading everything?** On development cases the loop is
   level on the first code, behind on the top three, at a higher cost
   (`docs/results/s3-armc-a-vs-s3-armb-full-dev.txt`). S3.2 decides.
8. **Does it hold on newly closed cases?** The board answers this in public.

### 7.3 What could come next

A short list of candidate improvements, each to be run as a registered, measured experiment:
transcription of scanned pages; the precedent tool the agent questions (decision
[0140](../decisions/0140-the-precedent-tool-after-s4-as-a-measured-v2.md)); the weather
archive; the model comparison. When the second version of the agent runs, the site needs a
place to show the first against the second on the same cases (§12).

## 8. The Open cases page

A separate page, complete, reached by a plain link. Andy's view is that this data may not be
interesting, so it is not on the main path.

Most open cases have no docket until closure, so the agent has little to read. The few whose
docket arrives before closure get their own section, labelled **answers locked before the
verdict**. Their results are never added into the board's tallies. How many such cases exist is
to be counted by a script from the recorder's store, as a number only (decision
[0024](../decisions/0024-open-split-enters-measurements-only-as-numbers.md)), before this note
is approved.

What a row for an open case with no answer shows is open (§16).

## 9. The Methods page

The reference page for the second reader. Every number on the site links to its entry here:
the sample, the model, the commit, the script, the interval, and the count it rests on. It
states the three arms, the baseline, the ablations, and the caveats. Its layout is open (§16).

Closed-case numbers from the board and held-out numbers from evaluation never share a figure
(decision [0021](../decisions/0021-agency-measured-as-hypothesis-trail.md)).

## 10. Appearance

- **The theme is an airport, used quietly.** The pixel look has one home: the board, drawn as
  a terminal display in dot-matrix letters. Everything else is plain signage type.
- **Small airport cues are allowed outside the board**: an amber wayfinding sign as a label,
  for example. No drawings of aircraft, and none of accidents.
- **Long text never goes on the board.** Dot letters are hard to read in sentences. Cause
  statements live in the opened case.
- **Light and dark** are both designed. The board is dark in both.
- **Meaning is carried by shape and words, not colour alone.** No red and green.

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

Raised on 2026-10-04 and not yet decided. Each needs a choice before approval.

1. **The author.** Settled: one line at the foot, linking to Andy's profile page (§3.1).
2. **A three-minute route.** Settled: the first page is one scrolling route of six stops
   (§3.1).
3. **Caveats before results.** Proposed in §3.1: the caveat sits in stop 1, above the board.
   Its exact wording waits for S3.2's result.
4. **Terms for a non-expert.** "Occurrence code", "finding" and "docket" need a plain
   explanation at the point of use. Each belief already carries an explanation written for a
   non-expert; whether the opened case shows it is open.
5. **Failures on the board.** Abstains are settled (§4). The wording of a row for a case that
   failed (a guard refusal, a format failure) is open.
6. **The thin board at launch.** The board must look complete with few rows, and on a night
   with no closures.
7. **Motion.** Settled: each stop animates in on arrival, within the four limits of §3.1. No
   scrolling text.
8. **Reading the board without sight.** Dot-matrix letters need a plain-text equivalent for
   screen readers, and enough contrast.
9. **Uncertainty.** Every score on the Path and Methods pages carries its interval and count.
   How a ladder step draws an interval is open.
10. **Totals on the first screen.** Whether the board carries a running tally of the three
    grades, and how to state it so that it is not a scoreboard.
11. **Links out.** Each case links to the NTSB's own page and docket. Whether the case number
    and registration are shown as text is open; a registration can identify an owner.
12. **Shared links.** Each case and each Path question needs its own address, and a preview
    that reads well when a link is posted.
13. **The first against the second version.** Where the comparison of agent versions sits once
    the precedent tool runs (§7.3).
14. **Freshness.** The board states when it was last rebuilt, in UTC.

## 13. What this asks of other stages

- **S4: the main run happens at closure.** The roadmap describes predictions locked on open
  cases and scored at closure. With few dockets before closure, the run that matters is the
  one made when the case closes, with the verdict withheld by the same split and guard as
  evaluation. Locking before the verdict applies to the early-docket cases (§8). S4's own
  specification decides how the site can show that the verdict was withheld.
- **S4 or S5: document titles.** The trail view needs each document's title, joined from the
  docket listing by position. A document classed as synthesis is shown as withheld, without
  its text.
- **S4: the store answers these pages.** For each closed case: the facts on the board, both
  code lists, both cause statements, the findings, the trail, and the costs.
- **S3.2: the ladder's numbers.** Four steps on one sample and one model.
- **The masked condition is paused** (decision
  [0123](../decisions/0123-the-staged-replay-is-paused.md)), so the Methods page describes
  one availability condition, not two.

## 14. What changes in the roadmap at merge

This note edits no shared file while S3.2 is open. When it merges, the roadmap's §8 is amended:
five pages become the six of §3; the live board becomes the board of closed cases; the
hypothesis trail is described as checkpoints, not a belief after every call; "two availability
conditions" becomes one. The top-level and repository `CLAUDE.md` files follow.

## 15. Decisions to record at merge

Decision numbers are assigned at merge, after S3.2's, so the two branches do not clash.

1. The primary reader, the second reader, and the link rule (§2).
2. The board lists closed cases; open cases have their own page (§3, §4, §8).
3. The agent's main live run is at closure (§13); this amends what S4 was to build.
4. The theme: an airport terminal display for the board only (§10).
5. Injury level in the opened case only (§11).
6. Beliefs as the spine of the trail view (§6).
7. The Path page: a ladder from one sample, then eight questions (§7).
8. The first page is one scrolling route of six stops, with the caveat above the board and the
   author line linking to Andy's profile page (§3.1).
9. Abstained cases have their own row on the board (§4).

## 16. Open questions for Andy

1. The exact rule for the middle result grade (§4).
2. What an open case with no answer shows (§8).
3. The layout of the Methods page (§9).
4. Every point in §12.
5. Whether the board shows documents read and cost, which carry impressions 1 and 3, or leaves
   them in the opened case as now.

## Glossary

- **Abstain**: the agent's statement that the evidence is too thin to answer.
- **Belief**: the agent's hypothesis at a checkpoint; the project's records call it H0, H1, H2
  and the answer.
- **Board**: the list of recently closed cases on the first screen, drawn as an airport
  terminal display.
- **Closure**: the moment the NTSB closes a case and publishes its codes and probable cause.
- **Docket**: the NTSB's public folder of supporting documents for a case.
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
