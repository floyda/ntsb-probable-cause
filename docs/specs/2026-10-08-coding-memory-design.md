# A coding memory learned from closed cases: design note

Status: Draft, 2026-10-08. Nothing here is built and nothing here is decided. This note
proposes a declared experiment on development cases. If Andy approves it, the decisions listed
in §10 are written as records first, and a plan follows. The memory reaches the agent only in
its second version (v2), beside the precedent tool of decision
[0140](../decisions/0140-the-precedent-tool-after-s4-as-a-measured-v2.md).

## 1. The idea in one paragraph

Today the agent improves only when someone changes it: a guidance round, a new tool, a new
prompt. This note proposes a **coding memory**: a short file of written lessons that a separate
**learner** builds by studying how the NTSB coded its closed cases. Each lesson states a
situation, what the NTSB usually codes for it, how consistent the NTSB is there, and what to
check in the evidence when it is not consistent. A script counts how far each lesson holds. The
learner revises or drops the lessons that the counts do not support, and repeats. The
answering agent never reads a verdict. It reads only the finished memory, the way it reads
guidance today.

## 2. Why this is worth testing

Four measured results point here.

1. **Most misses are coding, not reading.** Andy's hand-read of 40 `dev-400` misses put 34 down
   to coding (19 convention, 15 wrong phase) and 4 to a misread or missing fact
   (`docs/results/s27-round0-dev.txt`). On B-v2, the model's first guess was somewhere in the
   NTSB's sequence of occurrence codes on 140 of 399 cases (35.1%), but was the defining event
   on only 88 (22.1%); one of its three guesses was somewhere in the sequence on 192 (48.1%)
   (`docs/results/s26-occurrence-misses-dev.txt`). The agent usually knows what happened. It
   loses on which event the NTSB puts first, and in which phase.
2. **Guidance written by hand helped, but slowly and unevenly.** Of five S2.7 guidance rounds,
   one was kept on its merits, one was kept by override
   ([0106](../decisions/0106-round-6-kept-by-override.md)), and three were dropped. A learner
   can draft, test and revise many more lessons than a person can, against far more cases.
3. **The NTSB is consistent in some places and split in others, and the split is measurable.**
   Cases whose probable-cause sentences match word for word share their first occurrence code in
   619 of 1650 (37.5%); they share its event in 71.9% and its phase in 49.2%
   (`docs/results/s3-coding-consistency-dev.txt`). Their flagged findings agree far more:
   recall@10 74.1% (`docs/results/s3-finding-consistency-dev.txt`). A memory can say which is
   which. The counts in today's tools cannot.
4. **The counts already help, so the memory has a real bar to beat.** S3's fixed coding-tools
   step adds occurrence top-1 +6.8% [+4.0%, +9.8%] and finding recall@10 +4.7% [+2.5%, +7.0%]
   to S2.7's answer (`docs/results/s3-armb-tools-vs-s27-armb-answer-dev.txt`). The memory is
   worth having only if it beats those counts, not merely if it beats nothing.

**Why counts and lessons differ.** The coding tools (`occurrence_usage`, `past_findings`,
`suggest_codes`) are looked up **by code**: the agent must already name a code to learn how
often the NTSB used it. A lesson is looked up **by situation**, in words, and can carry a
condition. Example:

> "When the cause is the pilot's failure to keep airspeed on approach, the NTSB codes loss of
> control in flight first and the stall second. When an engine problem came first, it codes
> the power loss first."

No count table can hold the "when … first" part.

## 3. What the memory holds

Each lesson is one row in a versioned file:

| field | example | why it is there |
|---|---|---|
| statement | "Stall during approach: the NTSB codes loss of control in flight first, stall/spin second." | what the agent reads |
| kind | `convention`, `split` or `evidence` | tells the agent how far to trust it |
| scope | phase group, event, or a short description of the situation | when it applies |
| predicts | the codes, in order, with the shares seen | lets a script test it |
| support | the cases it applies to in the learning part, and how many agree | proves it, by count |
| history | the period it was written in, each revision, and why | lets a reader audit it |

The three kinds are the point of the design:

- **`convention`**: the NTSB codes this situation the same way nearly every time. The agent
  should follow it and put that code first, with high probability.
- **`split`**: the event is clear, but the phase (or the first code) divides. Example: "the event
  is loss of control in flight; the phase divides between Approach and Landing about 60 to 40;
  check where control was lost." (The shares here are for illustration; a real lesson carries
  counted ones.) The agent should place both phases among its three guesses,
  with probabilities near the shares. **This is how the memory raises top-3.** Top-3 is the
  NTSB's defining code anywhere among the agent's up to three guesses (`scoring/metrics.py`),
  so a known split placed across the guesses becomes a top-3 hit. Honest shares also give the
  agent's confidence something real to rest on, where today it barely separates right from wrong
  (S3.2 result 3).
- **`evidence`**: the memory cannot decide; the evidence must. Example: "the finding category
  is the aircraft's fuel system; which item depends on what failed, so read the maintenance
  records." This kind exists because S3's miss analysis found the finding item to be
  case-specific: the NTSB's item is the pool's commonest in only 46 of 213 item misses
  (`docs/results/s3-finding-misses-dev.txt`). A memory that pretended otherwise would be wrong.

**What the memory can and cannot reach in findings.** Of the loop's missed flagged findings,
46.0% are in a category it never named and 7.4% lose only the modifier; both are conventions a
memory can teach. A further 19.6% lose the item; that comes from the evidence
(`docs/results/s3-finding-misses-dev.txt`).

**Size.** The whole memory is read on every call, so it stays small: a cap of about 6,000
tokens to start (§11, question 3). A cap forces the learner to keep the lessons with the most
support and to merge the rest.

## 4. How it learns

Four steps, repeated over the pool one period at a time (a period is one or two event years).

1. **Propose.** The learner reads a batch of about 30 learning-part cases: for each, the
   NTSB's probable-cause sentence, its occurrence codes in order with labels, and its flagged
   findings with labels. It also reads the current memory. It returns new lessons, edits to
   existing ones, and lessons it thinks should go.
2. **Apply.** For each learning-part case, a short call decides which lessons apply to it,
   from its probable-cause sentence. Where a lesson's scope is a code or a phase group, a script
   decides instead, with no call.
3. **Count.** A script tallies each lesson's support: the cases it applies to, how many agree
   with its prediction, and how that changed from the last period. Every number in the memory
   comes from this step (rule 3), never from the learner.
4. **Revise.** Lessons whose support falls, or which disagree with more cases than they agree
   with, go back to the learner with a sample of the cases that disagree. It rewords, narrows,
   splits or drops them. Then the next period begins.

This is why the design makes many calls. Each one is small: a batch of sentences and codes and
the memory, about 15,000 tokens in and 2,000 out, against about 120,000 tokens a case for an arm
B answer that carries the docket (§8).

**Why it learns in time order.** Learning period by period, from 2009 forward, does two
things. It shows a learning curve (§6), which is the result Andy wants to see. And it lets a
lesson's support be weighted towards recent periods, because the NTSB's habits drift: the code
"Landing / Collision with terr/obj (non-CFIT)" appears in 310 of 6,956 pool cases from
2009–2014 but in 545 of 5,134 from 2015–2019 (`docs/results/s3-coding-stats.txt`). A lesson from 2010 that later
cases no longer support should lose its place.

## 5. What each part reads, and the guard

This design gives a model **verdict text as input**, which rule 1 forbids except for scoring
([0013](../decisions/0013-evidence-synthesis-verdict.md)). That is the main change, and it
needs its own record (§10). The case for it rests on keeping each part's reading narrow:

| part | reads | never reads |
|---|---|---|
| learner | verdicts of the **learning part**: the S3 pool less the steering slice | `dev-400`, any sealed sample, held-out, open cases, any evidence or docket |
| coding test (§6) | the steering slice freely; `dev-400` only at the milestones in §7 | sealed samples, held-out, open cases |
| answering agent | the finished memory file, as guidance | any verdict |

**The pool.** The S3 statistics pool: the development split less `dev-400`, `dev-seal-400` and
`dev-seal-s3-400`, 12,090 cases with event years 2009 to 2019
([0094](../decisions/0094-coding-statistics-from-a-pool-outside-the-samples.md),
[0129](../decisions/0129-s3s-sealed-sample-and-statistics.md)). A **steering slice** of 400 pool
cases is drawn once by a fixed seed and set aside. The learning part is the rest. The
statistics the coding test uses are rebuilt without the steering slice, because S3's file counts
it, and a case must not be scored with counts that include its own verdict. S3's statistics file
is never rewritten; the rebuilt one is a new file.

**Checks on the memory file**, run before any snapshot is used:

1. No lesson shares a sentence with the withheld text of any case it may be scored on, by the
   same check S2.7 runs on guidance (`make s27-check-guidance`).
2. No lesson copies a long run of words from any pool probable-cause sentence. Lessons are
   general statements, not quotations.
3. No case number, date, place, registration, name or operator appears in any lesson. These
   are fatalities; the memory is written in the clinical tone rule 6 asks for.

**Code boundaries.** The learner lives in its own package. It may import the verdict records;
the `agent` and `model` packages may not import it, and an import-linter contract proves this.
A memory snapshot reaches an answering run only as a named, fingerprinted file, the way guidance
does, so the run's prompt version changes when the memory changes.

**What this does not guard against.** GPT-6 Luna and the learner were both very likely trained
on public NTSB reports. The memory can be shown to improve on the same model without a memory.
It cannot be shown to work from nothing. Only cases closed after the models were trained, on
the live board, remove this.

## 6. How it is measured

**The coding test.** A cheap way to measure a memory without running the agent: give GPT-6
Luna the NTSB's own probable-cause sentence for a steering-slice case, the code tables, and the
material under test, and ask for the answer in the agent's format (up to three occurrence
guesses, then findings in the two stages of [0025](../decisions/0025-scoring-targets-from-ntsb-code-tables.md)).
Score it with the harness's own columns. It runs on the agent's model, through the agent's
transport, so what it measures is what the agent would receive. Three conditions:

| condition | gives the model | answers |
|---|---|---|
| tables | the code tables only | the floor |
| counts | the tables and the coding tools' output in a fixed order, as arm B's tools step | today's method |
| memory | the tables, the counts, and the memory | the proposal |

**The deciding comparison is memory against counts.** Memory against tables would credit the
memory with what the counts already do. The test measures coding given a perfect cause; the
agent never has a perfect cause, so the test bounds the gain and does not predict it. The
identical-sentence results in §2 bound what any coder reading only the sentence can score.

**The noise floor.** The tables and counts conditions run twice each, and a memory snapshot
must beat counts by more than the counts runs differ by. Two identical arm B answer runs once
differed by top-1 +4.0% [+0.5%, +7.5%] and kept the same first guess on only 246 of 399 cases
(`docs/results/s27-round0-dev.txt`); the coding test's own floor is measured, not assumed.

**The learning curve.** The coding test runs on the steering slice after each period. The
curve is its score against periods learned, beside the counts condition as a flat line and its
noise band. A memory that learns climbs above the band; one that only restates the counts stays
inside it.

**The transfer check.** The real question is whether the agent improves. Once, at the end of
the pilot if it passes, arm B runs on `dev-400` with the memory as guidance, through its usual
three parts ([0127](../decisions/0127-arms-ablations-and-the-ordering-check-in-arm-b.md)), and
is paired against S3's full arm B run on `dev-400`: top-1 27.6%, top-3 50.1%, finding recall@10
27.3% (`docs/results/s3-armb-full-dev.txt`), read by S3's round rule
([0136](../decisions/0136-s3-rounds-count-failed-cases-as-wrong.md)). No held-out case is used.
The memory's claim on held-out-like cases is tested in v2 on `dev-seal-s3-400`, which stays
sealed for v2 ([0141](../decisions/0141-s32-five-runs-and-the-sealed-sample-kept-for-v2.md),
[0153](../decisions/0153-a-counts-only-diagnosis-of-s32s-held-out-runs.md)).

**Why three samples.** The memory is revised again and again. Anything it is scored against
often, it slowly learns. So: it **learns** on the learning part; it is **steered** by the
steering slice, as often as needed; it is **measured** on `dev-400` only at the milestones; and
it is **confirmed** once on the sealed sample, in v2.

## 7. The pilot

A pilot of two periods answers the only question that matters first: does the curve move at
all? Each step is small, and the stop rule is registered before step 4 runs.

1. **Shape probe** on the second transport (§8): one learner call and one batch, to record the
   real request and reply shapes (rule 2). Cents.
2. **Draw the steering slice** and rebuild the statistics without it. Free.
3. **Coding test, tables and counts, twice each**, on the steering slice. GPT-6 Luna batch.
4. **Learn 2009 and 2010** (about 2,300 learning-part cases), then run the coding test with the
   memory after each period.
5. **Read it by the registered stop rule.** Proposed: the pilot stops, and is reported as it
   stands, unless the memory condition beats the counts condition by more than the counts runs'
   difference on at least one of top-1, top-3 or finding recall@10, and is not worse beyond that
   difference on any of them.
6. **If it passes:** learn the remaining periods to 2019, drawing the full curve; run the coding
   test once on `dev-400`; then run the transfer check (§6).

## 8. Transport and money

**Two transports, one role each.**

- **Learning** (propose, apply, revise) runs on Claude through the Claude API, paid from the
  monthly API credits included with Andy's Claude plan ($100 a month on Max 5x; credits expire
  at the end of each billing cycle and do not roll over; checked 2026-10-08 at
  `platform.claude.com/docs/en/about-claude/api-credits-for-subscribers`). This is a second
  transport for one declared role, as [0097](../decisions/0097-jev-as-an-ordering-check-model-on-development-cases.md)
  admitted Jev for the ordering check. The client refuses any call that is not a learning call
  on development cases, and a test proves it refuses. The wire shapes come from Anthropic's
  documentation and the shape probe's saved replies, never from memory (rule 2).
- **Answering and the coding test** stay on GPT-6 Luna through OpenRouter
  ([0009](../decisions/0009-model-access-via-openrouter.md)). The memory is measured on the model
  that uses it.

**Why the split.** Learning calls are small, so Claude's prices are affordable there. Answering
calls carry the docket, and are not:

| job | GPT-6 Luna batch | Claude Sonnet 5.5 batch | Claude Haiku 5.5 batch |
|---|---|---|---|
| price per million tokens, input / output | $0.05 / $0.25 | $1 / $5 | $0.05 / $0.25 up to 100,000-token prompts; $0.25 / $1.25 above |
| one arm B run on `dev-400` | $2.43 computed (measured) | about $49 (estimate) | about $2–12 (estimate) |
| one learning pass over the whole learning part | — | about $10 (estimate) | about $0.50 (estimate) |

GPT-6 Luna's prices are `sources.py`'s; Claude's are Anthropic's published batch prices, checked
2026-10-08. **The estimates are arithmetic, not measurements**: the arm B row scales arm B's
measured `dev-400` cost by the price ratio, and the learning row assumes about 30 cases, 15,000
tokens in and 2,000 out per call. Claude's tokenizer counts the same text differently from
GPT-6 Luna's. The shape probe and the pilot measure the real figures, and the plan reports those.

**What the pilot is expected to cost.** Learner calls for two periods: a few dollars of credit.
Coding tests: well under a dollar each on GPT-6 Luna batch, since a coding-test prompt has no
docket. The transfer check, if reached: about one arm B run, $2–3.

**Spend records.** Every learning call writes a spend row with its own kind and transport. Credit
spend is counted at its real price, never as zero, so the record stays honest about what the
method costs. It is fenced twice: by the project's budget guard, against a monthly line no larger
than the credit, and by a spend limit on its own Claude Console workspace.

## 9. What this rules out, and what it does not settle

- **It does not train the model.** The weights never change. The memory is text, so it is
  readable, auditable and reversible, and it can move to another answering model.
- **It does not learn from the agent's own answers.** That is a second design ("B"): run the
  agent once over pool cases, store its answers, and learn from its mistakes. It costs one paid
  answering pass over the pool and is worth testing only if this design shows promise.
- **It does not change the frozen loop, S3.3 or the bar.** The pilot touches development cases
  only and adds nothing to any run that S3.3 or S4 depend on.
- **It may compete with the precedent tool.** Both draw on past verdicts: the precedent tool
  hands the agent raw earlier cases; the memory hands it distilled lessons. v2 should test them
  apart and together.
- **The credits programme may change.** A credit for scripted Claude Code use was announced for
  2026-06-15 and paused the same day. The learning transport is kept replaceable: the memory
  file, not the transport, is the product of this work.

## 10. Decisions to record if approved

1. **Verdict text as learning input.** A model may read pool cases' verdicts to write lessons
   and in the coding test, on development cases only, under the reading table in §5.
2. **The coding memory as guidance.** A memory snapshot enters an answering run only as a named,
   fingerprinted guidance file that has passed the checks in §5.
3. **The second transport.** The Claude API, paid from plan credits, for learning calls on
   development cases only.
4. **The steering slice and the rebuilt statistics.** Drawn once, by a stated seed, excluded
   from learning and from the counts.
5. **The coding test and its reading rule.** The three conditions, the noise floor and the
   pilot's stop rule, registered before step 4.

## 11. Open questions for Andy

1. **When.** The pilot touches nothing S3.3 or S4 need, so it could run now as a side track.
   Or it waits until after S4 and is built with v2. The note assumes now, on its own branch, with
   its own spend line.
2. **The learner's model.** Sonnet 5.5 for proposing and revising, Haiku 5.5 for deciding which
   lessons apply? Or Opus 5.5 for revising, where the reasoning is hardest, at twice Sonnet's
   price?
3. **The memory's size.** About 6,000 tokens to start, which is about the size of the code
   tables the agent already reads. Larger holds more lessons and costs more on every agent call.
4. **The stop rule.** Is §7 step 5 the right rule, or should the pilot have to show a gain on
   finding recall specifically, since that is where the consistency results say the room is?
5. **Periods.** One event year each (eleven periods, a finer curve, more calls), or two?

## Glossary

- **Coding memory**: a short file of written lessons about how the NTSB codes accidents,
  built by the learner and read by the agent.
- **Learner**: the model, and the scripts around it, that write, test and revise the lessons.
  It never answers a case.
- **Lesson**: one statement in the memory, with its kind, its scope, what it predicts and its
  counted support.
- **Convention / split / evidence**: the three kinds of lesson. A convention is followed; a
  split is hedged across the three guesses; an evidence lesson points the agent back at the
  evidence.
- **Support**: how many learning-part cases a lesson applies to, and how many of them agree
  with it. Always counted by a script.
- **Pool**: the 12,090 development cases outside every sample, from which statistics and
  lessons are drawn.
- **Learning part / steering slice**: the pool split in two. The learner reads the learning
  part; the steering slice is kept back to measure the memory as it changes.
- **Coding test**: GPT-6 Luna coding the NTSB's own probable-cause sentence with and without
  the memory; it measures coding alone, with the reading of the evidence taken out.
- **Learning curve**: the coding test's score after each period learned.
- **Transfer check**: arm B on `dev-400` with the memory, paired against arm B without it; the
  test of whether the agent itself improves.
- **Period**: one or two event years of pool cases, learned together.
- **Defining event**: the occurrence the NTSB puts first; top-1 scores against it.
- **Top-3**: the defining event's code is any one of the agent's up to three guesses.
- **Plan credits**: the monthly Claude API credit included with some Claude plans; spent first,
  expiring at the end of each billing cycle.
