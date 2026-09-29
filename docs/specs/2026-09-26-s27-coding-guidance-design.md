# S2.7 — Coding guidance: design

*Drafted 2026-09-26 from a design session with Andy, after S2.6 closed (v0.6.0). Status: Approved (2026-09-26, Andy).
This is the specification for build stage S2.7, a stage added between S2.6 and S3 of
`docs/specs/2026-09-12-architecture-and-roadmap.md` §11. It records what S2.7 builds and
measures, why, the decisions it takes, and the condition for moving on. The implementation
plans are written from it separately, in `docs/plans/`: one per track (§11).*

**How to read this.** Each section says what is done, then why, with an example where one
helps. Terms in **bold** on first use are in the glossary at the end. Numbers in this document
are of four kinds, and each is labelled:

- **scripted** numbers cite the committed script and results file that produced them;
- **ad-hoc** numbers were counted during the design session by a throwaway script over the
  local run folders, the transcription cache or the processed file. They are not citable.
  Round 0 (§4) and T3 (§7.3) re-derive every one of them with a committed script before they
  appear anywhere else;
- **external** numbers come from a published list, cited by URL and date;
- **estimates** are arithmetic, and are replaced by measured figures in the As-built record.

Nothing here is a result: S2.7 produces the results.

Decision records written with this specification: 0093 to 0100 (§14). Track 1 takes the
numbers after 0100 for records written during the build, up to 119; track 2 takes 120 to 129
(§11). S2.6 used 0074 to 0091; S2.5's close-out took 0092.

**Depends on S2.6.** Every run in this stage uses the agent's model as S2.4 left it (GPT-6
Luna at `medium`, batch, decision 0073), the reply budget of 8,000 tokens (0084), and S2.6's
case marks (0077, 0078). The guidance rounds run on evidence version **v1** (0093).

---

## 1. What S2.7 is for

Arm B reads the whole docket and answers once. On `dev-400` it scores about one case in five
on occurrence top-1 (scripted, `docs/results/s26-armB-v2-dev.txt`, runs at commit `d19aafa`):

- B-v1 (text layers only): top-1 20.8% [17.1%, 25.1%], top-3 33.1% [28.6%, 37.8%], finding
  recall@10 10.4% [8.3%, 12.4%];
- B-v2 (with transcriptions): top-1 22.1% [18.3%, 26.4%], top-3 35.1% [30.6%, 39.9%], finding
  recall@10 11.0% [8.8%, 13.1%].

Top-1 is exact match against the NTSB's **defining event**: the one occurrence the NTSB flags
`isDefiningEvent` (decision 0025; `fields.occurrence_codes` lists it first, then the rest by
sequence number). Many misses are not failures to read the evidence. They are failures to code
it the way the NTSB codes (scripted, `docs/results/s26-occurrence-misses-dev.txt`, B-v2): the
model's first guess is somewhere in the NTSB's sequence on 140 of 399 cases (35.1%) but is the
defining event on 88 (22.1%); its first guess has the NTSB's defining event but the wrong phase
on another 64 (152 − 88, arithmetic on that file's counts). The commonest miss, 33 cases, is
"loss of control in flight" flagged where the model said "aerodynamic stall/spin".

The model is given the code tables as bare labels: 47 phases, 93 events, 130 finding
categories and 73 modifiers, each a code and a few words (`scoring/prompt.py:tables_block`).
It is told nothing about how the NTSB chooses between them.

A throwaway look at the recorded answers during the design session (ad-hoc, B-v2) made the
picture sharper:

- Of the 399 cases, only 73 have **nothing** in common with the NTSB's sequence: no code and
  no event, in any of the three guesses. The rest are right (88), right event with the wrong
  phase (64), a real code that is not the defining one (52), a second or third guess in the
  sequence (48), or an event match only under another phase (73).
- In 24 of the 33 stall/loss-of-control cases, the model's own narrative says "loss of
  control". It knew; it coded the other event.
- Only 18 of the NTSB sequences in the whole run hold both codes; loss of control is defining
  in 12 of them. So the NTSB often codes loss of control **without** a stall occurrence at all.
- The model's stated confidence is flat: median 0.82 on hits, 0.72 to 0.80 in every miss group.
- Between B-v1 and B-v2 the first guess changed on 181 of 399 cases; top-1 gained 31 and lost
  26. How much of that is the model answering differently on a repeat has never been measured.

S2.7 does four things:

1. **It measures the misses before changing anything** (Round 0, §4): which kind of miss is
   common, whether the model understood the accidents it miscoded, and how much results move
   when nothing changes.
2. **It tests a coding check after the answer** (Round 1, §5): historical statistics of how
   the NTSB orders codes, applied by a plain rule or by a model.
3. **It teaches the model the NTSB's coding habits** in small, pre-registered rounds (§6),
   occurrence first, then findings.
4. **It looks for a cheaper, better transcriber** alongside (track 2, §7), and decides whether
   transcription goes forward only at the end, with the final guidance in place (§8).

The final setup — guidance, check and evidence version — is checked once on a **sealed
sample** of development cases that nobody has read (§9).

**Why before S3.** Decision 0022 says the loop (arm C) must beat arm B at equal cost. If arm B
loses most of its points to coding convention, the loop inherits the same losses, and any
difference between B and C is measured inside that noise. Coding habits are not something to
choose from the docket; they belong to every arm. So they land before the loop, and the bar
S3 faces is set after them (0089 item 1 already said so).

**What S2.7 is not.** No agent loop. No held-out case is read, scored or transcribed. No
open-split case is used at all (rule 5, 0024). No picture probe (v3) unless Andy decides so at
the end (§8). The NTSB's factual narrative still reaches only the judge (0028), never the
answering model, the coding check or any guidance text.

---

## 2. The stage in one page

- **Three groups of development cases** (§3): `dev-400`, the working sample; `dev-seal-400`,
  drawn now and sealed; and the statistics pool, every other development case in the same
  classes. A test keeps the pool clean.
- **Round 0** (§4): a misses script (free); a repeat of B-v1 for the **noise floor** (about
  $1.18); the judge on three runs (about $1.50); Andy's hand-read of about 50 cards, which
  validates the judge's narrative label.
- **Round 1** (§5): the ordering check on the recorded answers, four ways — none, a plain rule,
  GPT-6 Luna, Jev. A model must beat the plain rule to be chosen.
- **Guidance rounds** (§6): one change per round, registered before it runs, kept only if it
  beats the noise floor and does no harm. Two dropped rounds in a row, or the $25 line, ends
  them.
- **Track 2** (§7), on its own branch: a shortlist of newer vision models, a re-test on S2.6's
  answer keys against Qwen, and a page-selection rule. It merges back before the meeting point.
- **The meeting point** (§8): v1 against v2 under the final guidance; Andy decides whether v2
  goes forward.
- **The sealed sample** (§9): the final setup, once. The prediction is scored.
- **Cost** (§10): about $15–25 in all, under a $25 stage line.

---

## 3. The three groups of development cases

### 3.1 The groups

The development split holds 13,560 cases from 2009 to 2019 (ad-hoc,
`data/processed/cases.parquet`). `dev-400` draws from classes C, F and L; outside `dev-400`
those classes hold 2,219 fatal and 10,673 non-fatal cases (ad-hoc).

1. **`dev-400`** — the working sample, unchanged (decision 0026). Every round is measured here,
   and it may be read and tuned on freely, Andy's hand-read included.
2. **`dev-seal-400`** — a sealed sample, drawn now by `samples.draw` exactly as `dev-400` was
   (200 fatal and 200 non-fatal, each split by class in proportion) with a new seed,
   20260926, and with every `dev-400` case excluded. Its case list is committed as
   `tests/fixtures/eval/dev_seal_400_ids.csv`. Nothing about it is scored, read, fetched or
   transcribed until its registration exists (§9, decision 0095).
3. **The statistics pool** — every other development case in classes C, F and L: about 12,490
   (arithmetic on the ad-hoc counts). Coding statistics come only from these (§3.2, decision
   0094).

**Why this split.** Guidance written from `dev-400`'s misses and chosen by its score on
`dev-400` can fit those 400 cases rather than the NTSB's coding in general. The sealed sample
is the one clean check that it does not, still on development cases, before anyone decides on
held-out. Halving `dev-400` instead was rejected: 200 cases give intervals of roughly ±6
points, wider than a round's likely effect.

### 3.2 The statistics

`scripts/coding_stats.py` builds, once, from the pool only:

- for each pair of occurrence codes that appear together in a case's sequence, how often each
  is the defining event;
- for each occurrence code that appears in a sequence, how often each code is the defining
  event (so "when stall/spin appears, loss of control is defining in N of M cases");
- for each phase group (the `cicttPhaseSOEGroup` the model is already given as evidence,
  decision 0016) and event, how often each phase prefix is used;
- for each phase group, the most common defining events;
- the same counts split into 2009–2014 and 2015–2019, so a habit that changed over the decade
  is visible.

It writes `docs/results/s27-coding-stats.txt`: codes and counts only, no case number, no text.
A count table the check or the guidance cites is this file, at the commit that built it.

**Why counts from other cases are allowed.** The no-model baseline (S1) already predicts from
the most common codes among development cases; this is the same kind of knowledge, finer
grained. It never uses the case being scored. That is what the contamination test (§12)
enforces.

---

## 4. Round 0: look before changing anything

### 4.1 The misses script

`scripts/occurrence_misses.py` is extended (it stays free, counts only, development runs only).
It runs on B-v1, B-v2 and the noise-floor repeat, and prints for each:

1. **Six occurrence groups**, each case in exactly one, by its first guess: exact / right event,
   wrong phase / in the sequence, not defining / a later guess in the sequence / an event
   matches only under another phase / nothing in common.
2. **Finding misses** at three depths, for each flagged finding the model missed: category
   right but item wrong; item right but modifier wrong; category wrong.
3. **Confidence by group.**
4. **"The model's own words name the NTSB's event"**: whether the model's evidence narrative or
   probable cause contains a phrase for the NTSB's defining event, from a fixed phrase list
   for the commonest events, committed in the script. So it is counted the same way every time.
5. **Churn**: how many first guesses differ between two runs, and how many top-1 hits are
   gained and lost.

### 4.2 The noise floor

B-v1 is run again on `dev-400` with identical settings (model, reasoning level, reply budget,
prompt version, batch), at S2.7's commit. The **noise floor** is two numbers:

- the paired top-1 difference between the two B-v1 runs, with its interval;
- the churn between them.

The v1-to-v2 churn of S2.6 (181 cases, ad-hoc) is read against it: whatever churn v1-to-v2
shows beyond the repeat's is what transcription added. Every later round is read against it
(§6.4). Estimate: $1.18, B-v1's cost.

### 4.3 The judge on three runs

The judge (decision 0028, Haiku 4.5, validated in S1 on its cause label:
`docs/results/s1-judge-validation.txt`, 346 of 401 agreements) runs on **B-v1, its repeat and
B-v2**. From its two labels each case falls into one of four **outcomes**:

| outcome | top-1 | the judge's narrative label |
|---|---|---|
| right | hit | any |
| understood, miscoded | miss | `consistent` |
| thin evidence | miss | `less_detailed` |
| misread | miss | `contradicts` or `adds_unsupported_facts` |

The cause label (`same_cause` / `related` / `different`) is printed beside each outcome.

**Why three runs.** B-v1 is what the rounds change. B-v2 shows what transcription buys in
understanding, case by case, which top-1 could not show (S2.6 measured +1.3 points
[-2.5%, +4.8%]): a case whose key fact sits only in a scan looks "thin" or "misread" on v1
through no fault of the model. The repeat measures **label churn**: labels move between two
identical runs because the model answers differently, so the v1-to-v2 movement counts only
beyond that. Results are also split fatal / non-fatal, since fatal dockets hold most image-only
pages.

**Caution.** The factual narrative the judge compares against was written by investigators
toward their conclusion. "Contradicts" can mean "framed differently from the investigator",
not "misread". This is why the narrative label is validated (§4.4) before it is cited.

Estimate: about $1.50 (three runs at the judge's conservative $0.00125 per case,
`scoring/judge.py:JUDGE_EXPECTED_COST_PER_CASE_USD`).

### 4.4 Andy's hand-read, which validates the narrative label

The narrative label was recorded in S1 but never validated: S1's hand-check tested the cause
label only (decision 0028 item 2; `docs/results/s1-judge-validation.txt`, "other labels").

**The cards.** About 50 from B-v1, seeded: 8 from each of the five miss groups of §4.1 and 10
hits. Built with `scripts/marking_page.py`, as in S2.6. Each card holds:

- left: the model's evidence narrative (about 640 characters, ad-hoc) and its chosen code,
  with its label in words;
- right: the NTSB's probable-cause sentence and its defining code, with its label in words;
- collapsed underneath: the factual narrative, opened only when Andy cannot tell without it.

No docket, no case number, no names. The judge's label is never shown, so the mark is blind.

**Two questions per card**, answered by clicking:

1. *Does the model's account contain the fact the NTSB's cause rests on?* yes / no / can't
   tell.
2. On misses only, *why did it miss?* coding convention / wrong phase / misread or missing fact
   / the NTSB's code is arguable / other.

**The validation rule, fixed now.** On the cards Andy could decide (not "can't tell"), map the
judge's narrative label to question 1: `consistent` means yes; `less_detailed`, `contradicts`
and `adds_unsupported_facts` mean no. The label is **validated** if Andy and the judge agree on
at least 75% of those cards and the judge's errors run in both directions (at least one card
each way), as S1 required of the cause label. Otherwise the four outcomes are printed
"unvalidated" everywhere and carry no claim. Decision 0099.

The rule validates what S2.7 needs the label to mean ("the key fact is there"), not the judge's
exact wording, since Andy reads the probable cause and the judge reads the factual narrative.

Question 2's counts say **why** the misses happen; they choose the order of the guidance
rounds (§6.5). Estimate of Andy's time: one to two minutes a card, so about an hour to an hour
and a half, in one or two sittings (the page keeps progress). Only counts are committed.

### 4.5 Output

`docs/results/s27-round0-dev.txt`, from the committed scripts: the six groups for three runs,
the finding misses, confidence by group, the own-words counts, the noise floor, the four
outcomes for three runs with their movement, the validation result, and Andy's miss types.

---

## 5. Round 1: the ordering check

A step **after** the answer, not an agent tool: it takes an answer and returns it with the
occurrence codes re-ordered. It changes nothing the model read.

### 5.1 What it receives

For each case:

- the model's three occurrence guesses, in its order;
- the **candidate list** (§5.2);
- the counts of `s27-coding-stats.txt` for those candidates;
- the phase group the evidence already gives;
- the model's own evidence narrative.

Never the verdict, the factual narrative, the analysis narrative or any docket text.

**Why the narrative.** Counts alone will always pick the majority code, including where the
model was right to differ. The narrative is the model's own account of what the evidence shows
(in 24 of the 33 stall cases it already says "loss of control", ad-hoc), and it is short. If
the narrative misread the evidence, the check inherits the error: it fixes coding, not reading.
The misread share (§4.3) measures how much that limits it.

### 5.2 The candidate list

At most eight codes, fixed by this rule before any statistic is computed (decision 0096):

1. the model's three guesses;
2. **linked codes**: for each guessed code, every code that is defining in at least 25% of the
   pool cases whose sequence contains the guessed code, where there are at least 20 such cases;
3. **group codes**: the two commonest defining codes in pool cases with the same phase group;
4. **phase variants**: the same event as any candidate, under another phase prefix within the
   phase group, seen as defining in at least 10 pool cases.

Duplicates are removed. The guesses come first, then the rest by pool count, cut at eight.

**Why not only the three guesses.** Re-ordering them is capped at top-3 (B-v1: 33.1% against
20.8% top-1, scripted). The two biggest fixable groups — loss of control where the model said
stall, and a low-altitude phase where it said "maneuvering" — often have the right code outside
the three. **Why not any code.** That is a second analyst, not a coding check; we could not
tell what it fixed.

### 5.3 The four ways

1. **No check.** The recorded answer as it is.
2. **The plain rule.** Of the candidates, the event the pool most often flags as defining when
   the model's first guess appears (§3.2, second count), where that count rests on at least 20
   cases; otherwise the model's first guess stands. Then, for that event, the pool's commonest
   phase within the phase group. Ties go to the model's own order. The second and third places
   are the model's remaining guesses, in its order.
3. **GPT-6 Luna asked.** One short call per case: the candidates with their labels and counts,
   the phase group and the narrative; asked which candidate the NTSB would flag as defining,
   with a ranked list of three from the candidates only (a strict JSON schema). Batch, at the
   agent's reasoning level, recorded.
4. **Jev asked.** TypeSafe's Jev, one Choice question over the candidate labels, with the same
   text as its state; ranked by its returned probabilities. Admitted for this role on
   development cases only by decision 0097. Its client comes over from the `typesafe-probe`
   branch, whose saved replies are the authority for its wire shape.

Each way runs on **two recorded answer sets**: B-v1 (`20260926T082427-d19aafa-dev-400-B`) and
Round 0's repeat. No new arm B run is needed. Estimate: GPT-6 Luna about $0.12 per answer set
(a short prompt at batch prices); Jev a fraction of a cent at its self-reported price; the
plain rule free.

### 5.4 How it is read (fixed now)

- **A way works** if its paired top-1 gain over "no check" has a lower interval bound above
  zero on **both** answer sets.
- **A model must beat the free rule.** GPT-6 Luna or Jev is chosen only if its paired gain over
  the plain rule has a lower bound above zero on both answer sets. Otherwise, if the plain rule
  works, it is chosen; if nothing works, no check is kept.
- Printed for every way: top-1, top-3, **fixes** and **breaks** separately, split fatal /
  non-fatal, and by the six groups of §4.1.

**Why both answer sets.** A check that helps one run's answers by luck should not survive the
second. **Why the rule is the bar for the models.** A model call costs money, time and a
transport; it has to earn its place over a lookup table.

### 5.5 Where it sits afterwards

The chosen way, if any, becomes a fixed step after the answer in arm B, before the finding
refinement turn (decision 0025 item 4). It is recorded as its own step in `steps.jsonl`, with
its input fingerprint, its output and its cost, and the unchecked answer is kept beside it. Every
later round is scored with and without it. `RunSpec` records which check ran.

### 5.6 Output

`docs/results/s27-round1-dev.txt`.

---

## 6. The guidance rounds

### 6.1 What a round changes

One piece of coding guidance, added to the system text next to the code tables
(`scoring/prompt.py`), never to the evidence payload: S0's provenance check reads the payload
unchanged. Each round's text is its own committed file under
`src/ntsb_probable_cause/scoring/guidance/`, the prompt version is bumped (for example
`s27-g1`), and the run record names both the version and the guidance files' hash.

### 6.2 Where guidance may come from

Only three sources, each named in the round's registration (decision 0098):

1. **The statistics** (`s27-coding-stats.txt`): coding habits as counts. Example: "When a loss
   of control and a stall both occur, the NTSB flagged loss of control as the defining event in
   N of M past cases."
2. **Official definitions**: the NTSB data dictionary, if it holds definitions for events and
   phases (our build reads labels only for these, `scripts/build_code_tables.py`; the source
   is checked first); otherwise the published CICTT definitions of occurrence categories, once
   their match to the NTSB's events is checked, not assumed. The dictionary's definitions of
   finding items are already shown in the refinement turn.
3. **Round 0's findings**: which miss group is biggest and why, which sets the **order** of the
   rounds. The wording never comes from a `dev-400` case's text.

**No worked examples from real cases.** Showing the model past cases with their answers is
similar-case retrieval by another name. It stays out unless it earns its own decision and the
retrieval-contamination test.

### 6.3 The registration

Before a round's run, a short file `docs/rounds/s27-round-N.md` is committed, holding:

- the change, and the guidance file it adds;
- the source (§6.2);
- the miss group it should shrink;
- the reading rule (§6.4, the same every time);
- the cost estimate;
- a one-line prediction.

The result is appended to the same file after the run, with the run ids. A round run from a
tree where its registration is uncommitted is refused (§12).

### 6.4 How a round is read

- It is compared, paired, against the **reference**: the last kept round's run, or for the
  first guidance round the Round 0 repeat (run at S2.7's code). It is scored with and without
  Round 1's check, if one was kept; the **with-check** scores decide, because that is the setup
  that goes forward, and the without-check scores are printed beside them.
- **Kept** if the paired top-1 gain has a lower interval bound above zero **and** the gain is
  larger than the absolute paired top-1 difference between Round 0's two identical runs.
- **Do no harm.** Not kept if finding recall@10's paired difference lies wholly below zero,
  even when top-1 rises. Finding rounds use the same rule the other way round: kept on finding
  recall@10, not kept if top-1 falls wholly below zero.
- A kept round **stacks**: its guidance stays, and the next round is measured on top. A dropped
  round's guidance is removed.
- The judge runs on each kept round (about $0.50), to show whether the misread share holds
  while "understood, miscoded" shrinks. If the misread share moves beyond the label churn of
  §4.3, the guidance is doing something other than coding, and the round's result says so.

### 6.5 Order: occurrence, then findings

Occurrence rounds come first, in the order Round 0 shows is worth most (the largest fixable
group first). When they stop, one or two finding rounds follow, for example modifier habits
("pilot" or "personnel"), which findings the NTSB puts in the probable cause, and category
definitions where the dictionary holds them. The two-turn finding answer of decision 0025 is
unchanged. Every round reports both occurrence and finding scores.

### 6.6 When the rounds stop

- **Two dropped rounds in a row**, or
- **S2.7's spend reaching $25** (§10), whichever comes first. The occurrence rounds stop under
  the first condition and hand over to the finding rounds; the second ends all rounds.

There is no score target. Decision 0098 holds the prediction (§9.2), which is published
whichever way it comes out.

---

## 7. Track 2: transcription

Track 2 runs on its own branch (§11) alongside the guidance rounds and changes nothing they
use: the rounds run on v1.

### 7.1 Why

The `dev-400` transcription cost $13.56 (scripted, S2.6 As-built). Where that money went
(ad-hoc, the transcription cache):

- **text-and-image pages**: 8,845 pages, $7.72 (59% of the cost); 7,728 of them (87%)
  returned under 20 characters, because their text layer already held the words; together
  they added about 0.67 million characters;
- **image-only pages**: 3,664 pages, $5.33, and about 3.35 million characters — 83% of the
  words transcribed.

Most of the cost is the page image sent in (a median of about 2,400 to 2,700 prompt tokens a
page, ad-hoc), not the words sent back. And 288 of OpenRouter's 458 models accept images
(external, `https://openrouter.ai/api/v1/models`, read 2026-09-26); several released since
June list input prices of $0.02 to $0.04 per million tokens, against Qwen3.5 122B's $0.26.
List price is not cost per page: each model counts an image differently, so cost is measured.

### 7.2 T1: the shortlist (cents)

`scripts/transcriber_shortlist.py` reads the model list and applies a fixed filter: accepts
images, returns text, released on or after 2026-06-01, input price at or below Qwen3.5 122B's,
not one of S2.6's four candidates. It keeps the eight cheapest by input price and saves the
list it read. Each is sent one probe page (a page drawn in code, as in S2.6's tests); one that
fails the probe is replaced by the next. One more call tests whether a batch variant now
accepts an image part (S2.6 found it did not, walkthrough W1); if it does, batch cost is
measured too. Rule 2 applies: the saved replies, not a guess, fix the request shape.

### 7.3 T3: the page-selection rule (free)

`scripts/page_value.py` reads the `dev-400` transcription cache and prints, for each page kind,
pages, cost, the share of pages returning under 20 characters, and characters added, with the
text-and-image pages split by text-layer size and image-area share. Three rules are compared:

- **all pages** (S2.6's rule);
- **image-only pages only**;
- **image-only pages, plus text-and-image pages whose text layer holds under 200 characters.**

The rule chosen is the one with the fewest pages that keeps at least 90% of the characters
S2.6's rule transcribed. Its effect on answers is tested at the meeting point (§8), not here.

### 7.4 T2: the re-test on S2.6's answer keys

The same four keys (100 typed pages, 25 handwriting pages of 1,548 key lines, 50 photographs
with no words, 25 full-page scans), the same instruction t1, 150 dots per inch, 0086's three
corrections. Scoring against the keys is automatic where the keys decide; Andy marks only what
they cannot (for example words on a photograph that may be the stamped label).

**The choice rule, fixed now (decision 0100).** No candidate passed 0080's absolute limits in
S2.6, Qwen included, and 0087 chose Qwen provisionally and openly. So candidates are compared
against Qwen's second-pass figures (scripted, `docs/results/s26-transcriber-test-pass2.txt`):

- invented handwriting lines: at most 3.5 per 100;
- photographs with invented words: at most 2 of 50;
- full-page scans with invented added words: at most 0 of 25;
- handwriting pages failing the line format: at most 2 of 25;
- handwriting lines right: at least 61.9% (Qwen's 66.9% less 5 points, 0080's margin);
- typed errors: at most 13.29 per 100 characters (Qwen's 12.29 plus 1, 0080's margin);
- measured cost per test page below Qwen's $0.00154.

Of the candidates meeting all seven, the cheapest by measured cost per test page is chosen. If
none does, Qwen stays. 0080's absolute limits are not loosened; they are reported beside each
candidate.

### 7.5 Output

`docs/results/s27-transcriber-shortlist.txt`, `docs/results/s27-page-value.txt` and
`docs/results/s27-transcriber-retest.txt`; a decision record (from 120) naming the transcriber
and page rule, or "Qwen stays". Track 2's branch then merges into the stage branch with a merge
commit (§11).

**The transcriber and page rule become part of the evidence version's record.** A v2 docket
read by another transcriber, or with another page rule, holds different evidence. `RunSpec` and
the run record gain `transcriber` and `page_rule` for v2 runs, and `report --against` refuses
two v2 runs that differ in either, as it refuses two versions (0076).

---

## 8. The meeting point

After both tracks:

1. **Apply track 2's outcome to `dev-400`.** If Qwen stays, the page rule costs nothing: its
   readings are cached. A new transcriber re-reads the pages the rule selects. Estimate: $1–7.
2. **v1 against v2 under the final guidance**, with the kept check, on `dev-400`: one v2 run
   paired against the last kept v1 run, with the judge on the v2 run. Estimate: about $1.80.
   It is reported as an evidence-version comparison (0076): top-1, top-3, finding recall@10,
   and the four outcomes.
3. **Andy decides whether v2 goes forward**, with the results in view, as 0088 did. There is
   no automatic rule; the reasons are recorded.
4. **Andy decides whether the picture probe (v3) runs** in S2.7, now that coding errors no
   longer hide a picture effect (0090 item 2).

---

## 9. The sealed sample and the prediction

### 9.1 The final check

When the setup is fixed — guidance, check, evidence version — a registration
`docs/rounds/s27-sealed.md` is committed naming it exactly. Only then:

1. `dev-seal-400`'s dockets are fetched (about 3,500 documents at 2 seconds per request, a few
   hours; estimate from `dev-400`'s 3,516 PDFs);
2. its image pages are transcribed, only if v2 went forward (estimate: $1–14, depending on the
   transcriber and page rule; `dev-400` cost $13.56 under S2.6's rule);
3. the final setup runs once, with the judge;
4. `docs/results/s27-sealed-dev.txt` reports it beside the same setup's `dev-400` result. The
   drop from `dev-400` to the sealed sample is printed, not hidden.

### 9.2 The prediction (fixed now, decision 0098)

- Occurrence top-1 on `dev-400`, final setup: **between 30% and 36%**.
- The misread share (if the label is validated) does not fall beyond its label churn during the
  guidance rounds: guidance fixes coding, not reading.
- The sealed sample scores lower than `dev-400` on top-1, by less than 5 points.

Each is published whichever way it comes out.

### 9.3 After the check

Andy decides whether and when the held-out runs happen (the transcription of `heldout-400`, if
v2 goes forward, and arm B there once), at S2.7's close or at S3's start. `ntsb-eval
transcribe` still refuses a held-out sample (0090) until that decision lifts it deliberately.

---

## 10. Cost

Estimates, against a **$25 stage line** (decision 0098) inside the $40 month (0083):

| step | estimate |
|---|---|
| Round 0: noise-floor run $1.18, judge on three runs $1.50 | $2.70 |
| Round 1: GPT-6 Luna on two answer sets; Jev | under $0.50 |
| Track 2: shortlist probes, batch test, re-test (8 candidates × 200 key pages) | $2–3 |
| Guidance rounds: $1.18 a run, plus $0.50 judge for each kept round | $5–15 |
| Meeting point: re-read `dev-400` ($1–7), v2 run and judge ($1.80) | $3–9 |
| Sealed sample: transcription ($0–14), run and judge ($1.70) | $2–16 |

The low end is about $15; the high end passes $25, which is why the line exists. **The meeting
point's costs decide how many guidance rounds fit**: a cheap transcriber and a narrow page rule
leave room for more.

S2.7's spend is counted by commit, from the S2.6 merge `971ee40` (the method of S2.6's
estimate, which counted by commit because a date filter caught another stage's runs).
`scripts/stage_spend.py` prints it and, given a step's estimate, refuses (exits non-zero) if
the spend plus the estimate would pass $25. Every paid Make target calls it first. The monthly
guard of 0083 is unchanged and applies separately.

---

## 11. Branches, plans and decision numbers

- **`s27-coding-guidance`**, cut from `main` at the S2.6 merge, holds this specification, its
  decision records and track 1.
- **`s27-transcriber`** is cut from it after this specification is committed, holds track 2,
  and merges back into `s27-coding-guidance` with a merge commit before the meeting point. The
  merge commit keeps every run's recorded commit reachable (0033).
- **Two plans** in `docs/plans/`, one per track, each naming this specification on its
  `**Spec:**` line. Both are deleted at close (0017).
- **One stage pull request**, titled `S2.7: coding guidance`, merged into `main` with a merge
  commit; one As-built record; one release.
- **Decision numbers.** Records written with this specification: 0093–0100. During the build,
  track 1 takes the next free numbers up to 119; track 2 takes 120 to 129. A clash at the merge
  is resolved by the track-2 record taking the next free number above its block.
- **Paid runs** start only from a clean, committed tree, with `NTSB_DATA_DIR` pointed at the
  main checkout's `data/` (0057). Track 2's shared-file edits (`sources.py` prices, `Makefile`,
  the decisions index) are kept small, so the merge back is simple.

---

## 12. Tests and continuous integration

- **The pool is clean** (the retrieval-contamination test the required components name,
  applied to statistics): `coding_stats.py` refuses, and a test proves it refuses, any case in
  `dev-400`, `dev-seal-400`, held-out or open.
- **The sealed sample stays sealed**: the runner, the docket fetch and `ntsb-eval transcribe`
  refuse `dev-seal-400` unless `docs/rounds/s27-sealed.md` exists and is committed.
- **The draw is reproducible**: `dev-seal-400` re-drawn from the processed file with its seed
  equals the committed list, and shares no case with `dev-400`.
- **The ordering check's payload** holds only codes, labels, counts, the phase group and the
  model's own narrative: a boundary test captures the body actually sent (0016, layer 5) and a
  mutation test proves the check can fail.
- **No case text in the count table or the guidance files**: a test fails on any case-number
  pattern and on any sentence shared with a development case's narratives.
- **Jev is refused anywhere else**: the Jev client refuses any call that is not the ordering
  check on a development run.
- **Registrations**: a guidance round's run refuses an uncommitted or missing registration file.
- **Versions**: v2 runs record `transcriber` and `page_rule`; `report --against` refuses two v2
  runs that differ in either without a labelled comparison.
- `scripts/check_docs.py` and `make check` pass.

---

## 13. Build order

Track 1 (`s27-coding-guidance`):

1. This specification and decisions 0093–0100.
2. The sealed draw, the statistics pool, `coding_stats.py` and their tests (free).
3. The misses script extension (free); the noise-floor run; the judge on three runs; the
   marking page; Andy's hand-read; `s27-round0-dev.txt`.
4. The ordering check: the plain rule, the GPT-6 Luna call, the Jev client and its tests;
   Round 1 on both answer sets; `s27-round1-dev.txt`.
5. Guidance rounds, each registered, run and appended, until the stop rule.

Track 2 (`s27-transcriber`), from step 2 onward, in parallel:

6. T3 (free) and T1 (cents); then T2 and Andy's marking; the decision record; merge back.

Then:

7. The meeting point (§8); Andy's decisions.
8. The sealed registration, the sealed run, the prediction scored.
9. Close-out (`close-stage` skill).

---

## 14. Decisions S2.7 takes

Written with this specification:

- [0093](../decisions/0093-s27-runs-as-two-tracks-guidance-on-v1.md) — S2.7 runs as two
  tracks: coding guidance on v1, transcription alongside on its own branch.
- [0094](../decisions/0094-coding-statistics-from-a-pool-outside-the-samples.md) — coding
  statistics come from development verdicts outside the samples.
- [0095](../decisions/0095-a-sealed-development-sample.md) — a sealed development sample,
  `dev-seal-400`, opened once.
- [0096](../decisions/0096-the-ordering-check.md) — the ordering check: what it sees, what it
  may choose, and that a model must beat the plain rule.
- [0097](../decisions/0097-jev-as-an-ordering-check-model-on-development-cases.md) — Jev is
  admitted as an ordering-check model on development cases only.
- [0098](../decisions/0098-guidance-rounds-stop-rule-and-prediction.md) — guidance rounds:
  sources, registration, reading rule, stop rule, the $25 line and the prediction.
- [0099](../decisions/0099-the-judges-narrative-label-and-four-outcomes.md) — the judge's
  narrative label gives four outcomes, validated by Andy's hand-read before it is cited.
- [0100](../decisions/0100-the-transcriber-retest-and-page-rule.md) — the transcriber re-test
  is judged against Qwen, and the page rule is measured before it is chosen.

---

## 15. Done means

1. `docs/results/s27-coding-stats.txt` exists, built from the pool, with the contamination test
   green.
2. `docs/results/s27-round0-dev.txt` holds the six groups, the finding misses, the noise floor,
   the four outcomes for three runs and the validation result.
3. `docs/results/s27-round1-dev.txt` holds the four ways on both answer sets and the outcome of
   §5.4's rule.
4. Every guidance round has its registration and appended result in `docs/rounds/`, and the
   stop rule's outcome is stated.
5. Track 2's three results files and its decision record exist, and its branch is merged back.
6. The meeting-point comparison is published, and Andy's decisions on v2 and v3 are recorded.
7. `docs/results/s27-sealed-dev.txt` exists, and the prediction of §9.2 is scored.
8. Tests and CI green; `scripts/check_docs.py` passes; the As-built record is appended and both
   plans deleted.

---

## 16. Not in S2.7

- The agent loop (S3), and any tool interface.
- Any held-out or open-split case.
- Worked examples from real cases, and similar-case retrieval (a later decision, with its own
  contamination test).
- The picture probe, unless Andy decides at the meeting point.
- Changing the headline metric: top-1 stays exact match against the defining event (0025).

---

## 17. Risks and open questions

- **The noise floor may be large.** If two identical runs differ by several points, rounds
  cannot show gains at n=400, and the stop rule ends them early. That is an honest result:
  guidance of this size is not measurable on this sample.
- **Coding habits may drift.** The pool is 2009–2019; held-out is 2020–2023. The statistics
  print both halves of the decade so drift is visible, and the held-out run, whenever it
  happens, is the real test.
- **A model-asked check may only echo the majority.** Then it will not beat the plain rule, and
  §5.4 keeps the rule.
- **The narrative label may fail validation.** Then the four outcomes are printed unvalidated
  and the misread share cannot carry a claim, in S2.7 or S3.
- **Guidance lengthens the prompt.** The cost per case rises; the per-case cap still applies,
  and each registration estimates its cost.
- **A page rule may drop a rare decisive word.** The meeting point's v1/v2 comparison runs with
  the rule, so its effect on answers is measured, not assumed.
- **Jev is in preview**, with a self-reported price; its access or shape may change. Its
  saved replies are the authority, and without it Round 1 runs three ways.
- **Open:** whether the data dictionary holds event and phase definitions (checked in the
  first round that would use them).

---

## Glossary

- **Defining event**: the one occurrence code the NTSB flags as defining the accident; top-1 is
  scored against it.
- **Phase prefix / event suffix**: the first and last three digits of a six-digit occurrence
  code — when it happened, and what happened.
- **Phase group**: the broad flight phase (for example "Maneuvering"), already given to the
  model as evidence.
- **Working sample**: `dev-400`; every round is scored on it and may be tuned against it.
- **Sealed sample**: `dev-seal-400`; drawn and committed now, opened once at the end.
- **Statistics pool**: every other development case in the same classes, used only to count
  how the NTSB codes, never scored.
- **Contamination**: a scored case leaking into material used to help answer it.
- **Noise floor**: how much results move when the same run is simply repeated.
- **Churn**: cases whose first guess changes between two runs.
- **Label churn**: judge labels changing between two identical runs.
- **Evidence narrative**: the model's own written account of the evidence, written before it
  chooses codes; its visible thinking.
- **Outcome (right / understood, miscoded / thin evidence / misread)**: what a case's code
  score and the judge's narrative label together say about it.
- **Validated**: checked against a person's judgement by a rule fixed in advance, so it can be
  cited.
- **Ordering check**: a step after the answer that re-orders the occurrence codes, choosing
  which one the NTSB would flag as defining.
- **Candidate list**: the codes the ordering check may choose among for one case.
- **Linked code**: a code the NTSB often flagged as defining when a guessed code also appears.
- **Fixes / breaks**: cases a change turns right, and cases it turns wrong.
- **Round**: one small change, registered before it runs, with its own result.
- **Registration**: the committed note that fixes a round's change and reading rule before it
  runs.
- **Stacking**: kept guidance stays in; later rounds build on it.
- **Do-no-harm rule**: a gain on one score does not count if it clearly costs another.
- **Page rule**: which docket pages are sent to the transcriber.
- **Meeting point**: where the two tracks come together and the final setup is fixed.
- **CICTT**: the international aviation safety taxonomy of occurrence categories and flight
  phases, with published definitions.
- **v1 / v2 / v3**: docket text layers only / plus transcribed words / plus pictures.
