# S2.7 — Coding guidance: design

*Drafted 2026-09-26 from a design session with Andy, after S2.6 closed (v0.6.0). Status: Implemented (2026-09-29, pull request #17).
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

## As built

*Closed 2026-09-30. The stage's pull request, #17, was merged on 2026-09-29 before this record
was committed; the record, the status changes and the plans' removal came in a follow-up pull
request (below).*

S2.7 closed on its development results. It measured where arm B's `dev-400` misses come from
(Round 0), kept GPT-6 Luna as an ordering check after the answer (Round 1), ran five guidance
rounds (Round 3 kept; Round 6 kept by override, decision
[0106](../decisions/0106-round-6-kept-by-override.md)), re-tested the transcriber (Qwen stays)
and turned transcription off by default (decision
[0120](../decisions/0120-qwen-stays-and-transcription-is-off-by-default.md)), and checked the
final setup once on the sealed sample. The final setup is arm B at evidence version v1, with the
guidance `r3-loc-stall` then `r6-aircraft-control` (prompt version `s1-v6+ge17fecdc66ec`) and
the Luna check. No held-out case was read, scored or transcribed, so S2.4's held-out arm B
(`docs/results/s24-bars.txt`) stays the bar.

### Delivered

- **S2.7's spend, counted by commit** (§10). `scripts/stage_spend.py` (`make stage-spend`)
  sums the spend recorded against the commits from the S2.6 merge `971ee40` on every local
  branch that holds S2.7's first commit `94f5d42` and is named `s27-` (`STAGE_BRANCH_PREFIX`),
  `main` and HEAD excepted, and prints the branches it counted (decisions
  [0102](../decisions/0102-a-parent-branch-with-a-branch-per-track.md),
  [0107](../decisions/0107-s27-spend-counts-its-own-branches-only.md)). Given `--estimate`, it
  exits non-zero if the spend plus the estimate would pass the $25 line (0098 item 6); every paid
  `s27-` target calls it first. `gitinfo.py` gains `commits_between`, `is_committed` and
  `branches_containing`.
- **The sealed sample** (§3.1, §9, decision
  [0095](../decisions/0095-a-sealed-development-sample.md)). `scripts/draw_sealed.py` drew
  `dev-seal-400` with `samples.draw` (seed 20260926, every `dev-400` case excluded) into
  `tests/fixtures/eval/dev_seal_400_ids.csv`; `--verify` re-draws it from the processed file.
  `samples.refuse_sealed` refuses the sample until `docs/rounds/s27-sealed.md` is committed. It
  is called by `ntsb-eval run` (which fetches the dockets), `check`, `transcribe` and
  `baseline`, and by five S2.6 scripts that take a free-form sample. A shared
  `samples.refuse_unless_development` replaces the per-script held-out checks.
- **The statistics pool** (§3.2, decision
  [0094](../decisions/0094-coding-statistics-from-a-pool-outside-the-samples.md)).
  `scoring/coding_stats.py` (`PoolCase`, `CodingStats`, `build`, `load_stats`; the counts are
  read through `defining_given`, `pair`, `event_pair`, `group_phases`, `group_n`, `group_top`
  and `findings_given_event`). `scripts/coding_stats.py` (`make s27-coding-stats`) builds the
  committed table `scoring/tables/coding_stats.json` and `docs/results/s27-coding-stats.txt`
  from development cases in classes C, F and L outside both samples. The contamination test is
  `tests/test_coding_stats_script.py::test_check_pool_refuses_a_sample_case_or_a_non_development_case`.
- **Round 0's scripts** (§4). `scoring/misses.py` (`GROUPS`, `miss_group`, `finding_depth`,
  `EVENT_PHRASES`, `names_event`). `scripts/occurrence_misses.py` is extended with the six
  groups, finding depth, confidence by group, the model's own words and churn against a second
  run. `scripts/judge_outcomes.py` prints the four outcomes and their movement between runs.
  `scripts/round0_handread.py` (`cards`, `score`) builds Andy's marking page and scores the
  validation rule. Make targets: `s27-noise-floor`, `s27-judge`, `s27-round0-cards`,
  `s27-round0-results`.
- **The ordering check** (§5, decisions [0096](../decisions/0096-the-ordering-check.md),
  [0101](../decisions/0101-the-clear-habit-safeguard.md)). `scoring/ordering.py` holds the
  candidate list (`candidates`, at most eight codes), the clear-habit test (`clear_habit`, at
  least 60% of at least 20 pool cases), the plain rule (`plain_rule`), the push count
  (`toward_more_common`), the Luna check's text and its parser, and the Jev questions for `jev`
  and `jev2`. `scoring/checkpass.py` runs the check as a post-pass over a finished run:
  `ntsb-eval check RUN_ID --way rule|luna|jev|jev2` (`make s27-check`) writes a derived folder
  `<run id>-check-<way>` whose cases carry a second step, `tool="ordering_check"`, with its
  input fingerprint, model and cost. It checks the source read-only (`checkpass.preflight`)
  before it reserves the budget or builds a client, and refuses a held-out, unfinished, ablation
  or already-derived source, and the sealed sample before its registration. `metrics.rescore_occurrence` re-scores the occurrence
  codes; finding scores are carried over.
- **The Jev client** (decision
  [0097](../decisions/0097-jev-as-an-ordering-check-model-on-development-cases.md)).
  `model/typesafe.py`, ported from the `typesafe-probe` branch with its saved replies under
  `tests/fixtures/typesafe/`; `jev2` pins `jev-1.13.0` (`JEV_PINNED`). Only the ordering check
  (`ntsb-eval check`) calls it. `sources.JEV` holds its price; `Settings` reads `TYPESAFE_API_KEY`.
- **Round 1's reports.** `scripts/round1_report.py` (`make s27-round1-results`) applies 0096
  item 5's rule; `scripts/round1_jev2_report.py` (`make s27-round1-jev2-results`) applies
  decision [0103](../decisions/0103-a-registered-second-jev-check.md)'s.
- **Guidance and its registration** (§6, decision
  [0098](../decisions/0098-guidance-rounds-stop-rule-and-prediction.md)). Guidance files live in
  `src/ntsb_probable_cause/scoring/guidance/` (`r2-phase-families`, `r3-loc-stall`,
  `r4-fuel-power`, `r5-sub-phases`, `r6-aircraft-control`) and enter the answering turn's system
  text under `prompt.GUIDANCE_HEADING`, never the payload. A guided run's prompt version is the
  base version, `+g` and the first 12 characters of the guidance fingerprint
  (`prompt.prompt_version`); `RunRecord.guidance` and `RunRecord.guidance_sha256` record the
  names and the full fingerprint, and `report.provenance` prints them. `ntsb-eval run
  --guidance NAME` (repeatable, in stacking order) refuses a round whose registration
  (`docs/rounds/s27-round-<N>.md`, template in `docs/rounds/README.md`) is not committed.
  `scripts/check_guidance.py` (`make s27-check-guidance`) checks every guidance sentence against
  every development case's narratives and probable cause, locally. `make s27-round` refuses an
  empty `GUIDANCE` unless `NO_GUIDANCE=1`.
- **A round's reading.** `scripts/round_result.py` (`make s27-round-result`, `FINDING=1` for a
  finding round, `SUPPLEMENT=1` for decision 0105's line) applies 0098 item 4 and appends the
  result to the registration. `scripts/round_comparisons.py` (`make s27-round-comparisons`)
  reproduces the figures behind decision 0106.
- **Six codes join the code tables** (decision
  [0105](../decisions/0105-codes-missing-from-the-dictionary-join-the-tables.md)).
  `scoring/tables/supplement.csv`, merged by `codes.read_supplement` into the dictionary tables,
  which are unchanged; the base prompt version is `s1-v6`.
- **The v2 reading on run records** (§7.5). `RunSpec` and `RunRecord` gain `transcriber` and
  `page_rule`, set by `ntsb-eval run --transcriber --page-rule` for v2 runs.
  `runner.refuse_unnamed_reading` refuses a v2 run that does not name both, and a v1 run that
  names either; `ntsb-eval run` refuses a v2 run whose sample is not fully transcribed with that
  transcriber and rule; and `report.refuse_cross_version` refuses two v2 runs that differ in
  either field without `--versions-compared` (a record with neither reads as S2.6's,
  `S26_V2_READING`).
- **The sealed report.** `scripts/sealed_report.py` (`make s27-sealed-results`) prints the
  sealed run beside Round 6's checked `dev-400` run and scores the prediction; `make
  s27-sealed-run` names the two guidance files itself.
- **Named page rules** (track 2, §7.3, §7.5). `docket/transcribe.py` gains `PageRule`,
  `PAGE_RULES` (`all`, `image-only`, `image-only+thin-layer`), `PAGE_RULE = "all"` and
  `THIN_LAYER_MAX_CHARS = 200`; `pages_to_read`, `page_choice` and `ReadingLookup` take the
  rule, and every finished-transcription marker names it. `ntsb-eval transcribe` gains
  `--model` and `--page-rule`. `scripts/page_value.py` (`make s27-page-value`) measures what
  each rule keeps.
- **The transcriber shortlist and probe** (track 2, §7.2). `scripts/transcriber_shortlist.py`
  (`fetch`, `shortlist`, `probe`, `batch-image`, `batch-poll`; `lowest_reasoning`,
  `S27_CANDIDATES`; `make s27-models-fetch`, `s27-shortlist`, `s27-transcriber-probe`,
  `s27-batch-image`). `sources.py` holds the shortlisted models' prices and lowest reasoning
  levels; the eight passed candidates' probe replies are committed under
  `tests/fixtures/openrouter/transcription/`.
- **The transcriber re-test** (track 2, §7.4, decision
  [0100](../decisions/0100-the-transcriber-retest-and-page-rule.md)).
  `scripts/transcriber_retest.py` (`verify`, `run`, `automatic`, `pages`, `score`,
  `readable-split`, `routing-pages`, `routing-tally`; the rule is `choose_against_qwen`). Make
  targets `s27-retest-verify`, `-run`, `-pages`, `-automatic`, `-score`, `-readable`,
  `s27-routing-pages`, `s27-routing-tally`. It reuses S2.6's keys and scoring from
  `scripts/transcriber_test.py`, which gains a shared card loop and an optional expected cost
  per page, with S2.6's outputs unchanged.

#### What was measured

- **The statistics pool** (`docs/results/s27-coding-stats.txt`): 7,177 development cases from
  2009–2014 and 5,314 from 2015–2019, 12,491 in all, none in either sample.
- **The six miss groups** (`docs/results/s27-round0-dev.txt`, `scripts/occurrence_misses.py`).
  On B-v1 (399 scored cases), by first guess: exact 83, right event with the wrong phase 61, in
  the sequence but not defining 45, a later guess in the sequence 44, the event under another
  phase 74, nothing in common 87, abstained 5. Of 1,111 flagged findings, 114 were found, 48 had
  the item right and the modifier wrong, 103 the category right and the item wrong, and 846 the
  category wrong. The model's own words named the NTSB's defining event in 100 of 225 misses
  with a phrase list (44.4%); 118 of 221 (53.4%) on B-v2.
- **The noise floor** (same file). B-v1 against its repeat (`20260927T111202-fbab38a-dev-400-B`,
  identical settings): occurrence top-1 +4.0% [+0.5%, +7.5%] on 399 cases, finding recall@10
  -1.7% [-3.3%, -0.2%]; the same first guess on 246 of 399 cases, top-1 gained 35 and lost 19.
  The repeat alone scores top-1 16.8%, against B-v1's 20.8%. Between the two runs' Luna-checked
  folders, top-1 differs by +1.0% [-3.0%, +5.0%] (`docs/rounds/s27-round-2.md`).
- **The four outcomes and label churn** (same file). The judge's outcome changes on 123 of 399
  cases between two identical runs, and on 155 between v1 and v2. The judge cost $2.43 for the
  three runs (Departures, Round 0).
- **Andy's hand-read** (same file). 50 cards, 46 decidable. The judge agreed with Andy on 32 of
  46 (69.6% [55.2%, 80.9%]) against the 75% rule, with 3 generous and 11 harsh errors: **the
  narrative label is not validated**, so the four outcomes carry no claim (decision
  [0099](../decisions/0099-the-judges-narrative-label-and-four-outcomes.md)). Andy's reasons for
  the misses: coding convention 19, wrong phase 15, misread or missing fact 4, the NTSB's code
  arguable 2.
- **Round 1, the ordering check** (`docs/results/s27-round1-dev.txt`). Paired top-1 against no
  check, on B-v1 and on the repeat: plain rule +2.0% [+0.5%, +3.8%] and +1.8% [+0.0%, +3.5%];
  GPT-6 Luna +6.8% [+3.3%, +10.3%] and +9.8% [+6.0%, +13.8%]; Jev +5.3% [+2.0%, +8.5%] and +7.3%
  [+3.8%, +11.0%]. Against the plain rule: Luna +4.8% [+1.0%, +8.5%] and +8.0% [+4.0%, +12.3%];
  Jev +3.3% [-0.3%, +6.8%] and +5.5% [+1.8%, +9.3%]. Outcome: `luna`. Luna also breaks 16 of
  B-v1's 83 exact first guesses (13 of the repeat's 67).
- **The second Jev check** (`docs/results/s27-round1-jev2-dev.txt`). `jev2` against Luna: -4.0%
  [-7.0%, -1.0%] and -4.5% [-7.8%, -1.3%]; against no check +2.8% [-0.8%, +6.5%] on B-v1. Outcome:
  "luna stays".
- **The guidance rounds** (`docs/rounds/`, each result by `scripts/round_result.py`; checked
  scores decide, read against the checked noise pair's 1.0 points of top-1, or 1.7 points of
  finding recall for a finding round):
  - Round 2, phase families: top-1 +2.5% [-1.8%, +6.8%]; dropped
    (`docs/rounds/s27-round-2.md`).
  - Round 3, loss of control against stall/spin: top-1 +4.8% [+0.8%, +8.8%], finding recall@10
    -0.9% [-2.5%, +0.8%]; kept (`docs/rounds/s27-round-3.md`).
  - Round 4, fuel before loss of engine power: top-1 -4.0% [-7.8%, -0.3%]; dropped
    (`docs/rounds/s27-round-4.md`).
  - Round 5, sub-phase over the general phase code: top-1 -3.5% [-7.5%, +0.5%]; dropped, and
    with two drops in a row the occurrence rounds ended (`docs/rounds/s27-round-5.md`).
  - Round 6 (finding round 1), Aircraft control / Pilot: finding recall@10 +11.4% [+8.2%,
    +14.6%], top-1 -6.3% [-10.5%, -2.5%]; dropped by the do-no-harm rule, kept by override
    (decision 0106; `docs/rounds/s27-round-6.md`). Against Round 4, Round 5 and the repeat, its
    top-1 difference includes zero (-2.3%, -2.8%, -1.5%) and its recall gain holds (+12.3%,
    +12.7%, +10.5%) (`docs/results/s27-round-comparisons-dev.txt`).
  - Checked top-1 of each run (same file): B-v1 27.6%, the repeat 26.6%, Round 2 29.1%, Round 3
    31.3%, Round 4 27.3%, Round 5 27.8%, Round 6 25.1% [20.8%, 29.6%]; Round 6's finding
    recall@10 22.6% [19.8%, 25.6%], against 12.1% for the repeat.
  - The judge on the kept rounds: the misread count moved from 116 (the repeat) to 99 (Round 3),
    and from 99 to 109 (Round 6), both inside the label churn of 123 cases.
- **The sealed sample** (`docs/results/s27-sealed-dev.txt`, `scripts/sealed_report.py`). Run
  `20260929T114049-9cbe5c5-dev-seal-400-B`, checked with Luna: top-1 27.5% [23.3%, 32.0%] (109
  of 397), finding recall@10 22.0%. The `dev-400` run it is read beside (Round 6, checked): top-1
  25.1% [21.1%, 29.5%] (100 of 399), finding recall@10 22.6%. The prediction (0098 item 7):
  `dev-400` top-1 between 30% and 36%, **not met** (25.1%); the sealed sample lower by less than
  5 points, **not met** (it was 2.4 points higher); the misread share, **not scored** (the label
  is not validated).
- **The transcriber shortlist** (`docs/results/s27-transcriber-shortlist.txt`). Of OpenRouter's
  model list of 2026-09-27, 14 models were eligible. Eleven were tried in order and 8 passed the
  probe; two failed on the account's 18+ setting and one returned a reply that did not parse.
  The probe cost $0.0034 for 9 calls. The batch service accepted, then failed, the one image
  request.
- **The re-test** (`docs/results/s27-transcriber-retest.txt`). Qwen's second-pass figures were
  reproduced exactly from the cache (1036 of 1548 handwriting lines right, 54 inventing lines,
  measured $0.0015362713 a test page). All eight candidates are out on measures that need no
  marks: seven invent on 65 to 181 lines of 1548; DeepSeek reads 100 of 1548 lines right and
  costs $0.0033132 a test page. Outcome: "no candidate meets all seven: Qwen stays". The
  post-hoc split by page readability (`docs/results/s27-transcriber-retest-readable.txt`) gives
  the same verdict: on the 13 fully readable pages Qwen reads 620 of 779 lines right, and no
  candidate more than 458.
- **The page rule** (`docs/results/s27-page-value.txt`). `all`: 12,458 pages, $13.25;
  `image-only`: 3,596 pages, 82.6% of the characters, $5.39; `image-only+thin-layer`: 5,398
  pages, 84.2%, $6.92. Only `all` keeps 90% of the characters, so it is chosen.
- **Routing, exploratory** (`docs/results/s27-routing-scans.txt`). On S2.6's 25 full-page scans,
  invented added words: `z-ai/glm-5.3-flash` 0, `openai/gpt-6-luna-pro` 1, `qwen/qwen3.7-flash`
  1. Outside 0100's rule; it changes nothing.
- **Spend.** $15.10 on S2.7's own branches ($13.34 evaluation runs, $1.76 preparation spend
  rows), `uv run python -m scripts.stage_spend`, 2026-09-29, against the $25 line; the
  specification estimated $15–25.

### Done means, with evidence

1. `docs/results/s27-coding-stats.txt` exists, built from the pool, with the contamination test
   green — met — `scripts/coding_stats.py` (`make s27-coding-stats`),
   `docs/results/s27-coding-stats.txt` (12,491 pool cases); the contamination test
   `tests/test_coding_stats_script.py::test_check_pool_refuses_a_sample_case_or_a_non_development_case`
   passes.
2. `docs/results/s27-round0-dev.txt` holds the six groups, the finding misses, the noise floor,
   the four outcomes for three runs and the validation result — met —
   `docs/results/s27-round0-dev.txt` (`make s27-round0-results`) holds the six groups, finding
   depth and churn for B-v1, B-v2 and the repeat; the noise floor (B-v1 against the repeat,
   top-1 +4.0% [+0.5%, +7.5%]); the four outcomes for the three runs with their movement; and
   the validation result, "not validated".
3. `docs/results/s27-round1-dev.txt` holds the four ways on both answer sets and the outcome of
   §5.4's rule — met — `docs/results/s27-round1-dev.txt` (`scripts/round1_report.py`) holds the
   plain rule, GPT-6 Luna and Jev, each against no check (and the models against the rule), on
   both answer sets, and ends "outcome (decision 0096 item 5): luna". The second Jev check is
   in `docs/results/s27-round1-jev2-dev.txt` ("luna stays").
4. Every guidance round has its registration and appended result in `docs/rounds/`, and the
   stop rule's outcome is stated — met — `docs/rounds/s27-round-2.md` to `s27-round-6.md`, each
   committed before its run with its result appended by `scripts/round_result.py`. The
   occurrence rounds ended on two drops in a row (Rounds 4 and 5; stated in Round 5's note);
   Andy ended the finding rounds after one (Departures below). Round 6 is kept by override
   (decision 0106), stated in its registration.
5. Track 2's three results files and its decision record exist, and its branch is merged back —
   met — `docs/results/s27-transcriber-shortlist.txt`, `docs/results/s27-page-value.txt`,
   `docs/results/s27-transcriber-retest.txt`; decision 0120; `s27-transcriber` merged into the
   parent at `87f74f1`.
6. The meeting-point comparison is published, and Andy's decisions on v2 and v3 are recorded —
   **not met as written** — the meeting point was skipped on Andy's decision of 2026-09-29 ("A,
   skip it and carry on here"), because decision 0120 had already settled v2's default:
   transcription is off by default, for cost. So no v1-against-v2 comparison under the final
   guidance was run or published. The decision on v2 is 0120. v3 (the picture probe) was not
   taken up in S2.7 and stays deferred (0090): a name only, which every run refuses.
7. `docs/results/s27-sealed-dev.txt` exists, and the prediction of §9.2 is scored — met —
   `docs/results/s27-sealed-dev.txt` (`scripts/sealed_report.py`), sealed run
   `20260929T114049-9cbe5c5-dev-seal-400-B`; the prediction is scored: two parts not met, the
   misread part not scored because the label is not validated.
8. Tests and CI green; `scripts/check_docs.py` passes; the As-built record is appended and both
   plans deleted — met — this pull request's close-out commit; `uv run python -m
   scripts.check_docs` clean; `make check` green on the close-out tree (1,857 tests, 97.8%
   coverage), and CI on pull request #17 runs the same checks.

### Departures from this specification

Every entry in both plans' Deviations sections is here, grouped by topic and rewritten plainly,
with the walkthrough decisions each plan took before any code. Lint-only rewrites of the plans'
code are listed together at the end.

#### What S2.7 did not do

- **The meeting point (§8, track 1 Task 17) was skipped** (Andy, 2026-09-29: "A, skip it and
  carry on here"). Decision 0120 had already settled v2's default for cost, so a v1-against-v2
  comparison under the final guidance could not change it. Not spent: about $1.85 (a v2 run at
  about $1.33 and the judge at $0.50, estimates). Not measured, as a result: whether
  transcription helps once coding is improved, the question 0090 item 2 hoped S2.7 would free;
  it moves to S3, where reading a transcription is the agent's own choice. The sealed run is
  therefore at v1.
- **Transcription is off by default, for cost** (decision 0120, Andy: "Im swaying towards B
  because in the grand schema of things the transcription didn't provide the big boost i was
  hoping for"; "yes that shape i think makes sense" to "off by default, a tool the agent can
  choose later"). Runs and new batches of cases read text layers only (v1); in S3, transcribing
  a document becomes a tool the loop may call. §8 kept v2 open as S2.7's evidence: instead v2 is
  not the default, and §8 step 1 re-reads nothing (Qwen stays with rule `all`, and `dev-400`'s
  readings are cached). 0120 amends 0074's default; 0074 stays in place with an appended note.
- **The picture probe (v3) was not taken up.** §8 item 4 left it to Andy at the meeting point,
  which was skipped. It stays deferred (0090): v3 is a name only, and every run refuses it.

#### Choices made before any code (track 1's walkthrough, 2026-09-27)

- **W1, the phase codes of a phase group are learned from the pool** (Andy: "A with a 'clear
  habit' safeguard."). An ad-hoc probe, re-derived by Task 3, found every phase code used for a
  defining event under exactly one of 12 phase groups; on B-v1 the first guess's phase was the
  NTSB's on 210 of 394 answered cases. On Andy's concern that counts would push every case toward
  the most common combination, decision 0101 amends 0096 item 4 and 0098 item 2: the plain rule
  moves only on a clear habit (at least 60% of at least 20 pool cases; `ordering.clear_habit`
  replaces `RULE_MIN_CASES`), guidance names a habit only when it is clear, and every check
  step, Round 1's report and every round's result count first codes moved toward a more common
  option. Tasks 8, 10, 11, 14 and 15 were edited before any code.
- **W2, the ordering check is a post-pass** (Andy: A). `ntsb-eval check` writes a derived folder
  `<run id>-check-<way>` instead of running inside the runner before the refinement turn (§5.5).
  The check changes only the occurrence codes and the refinement turn only the findings, so the
  order between them changes no score; the runner is untouched, batch and synchronous runs are
  treated alike, and Round 1 re-uses the recorded answers.
- **W3, the Luna check runs synchronously at the standard price** (Andy: "A is fine"), not on
  batch as §5.3 and §10 priced it. Estimated at about $0.36 an answer set, against the spec's
  $0.12; it cost $0.24 for two (Round 1, below).
- **W4, the judge writes into S2.6's B-v1 and B-v2 folders in place** (Andy: A), after checking
  neither held a `judge.jsonl`. The folders gain `judge.jsonl` and a `<run id>-judge` cost row
  carrying S2.7's commit; their answers are untouched.
- **W5, the prompt version is the base version and a short fingerprint** (Andy: "Could we use
  version and short fingerprint?"): `s1-v5+g` and the first 12 characters of the guidance
  fingerprint, not a hand-bumped `s27-g1` (§6.1). The names and the full fingerprint are recorded
  beside it.
- **W6, two checks of §12 run locally, not in CI** (Andy: "I guess A"). "No sentence shared with
  a development narrative" and "the draw is reproducible" each split into a data-free CI test
  and a local check at fixed steps: `scripts/check_guidance.py` before each registration, and
  `scripts/draw_sealed.py --verify` at the draw and before the sealed run. CI holds no case data
  (rule 4).
- **W7, a miss group with fewer than 8 cases gives all its cases** to the hand-read, with no
  top-up (Andy: A). None was under 8.
- **W8, a parent branch with a branch per track** (Andy set the layout; names "A is fine";
  decision 0102, amending 0093 item 3 and §11, which put track 1 on the stage branch). The parent
  is `s27-coding-guidance`; track 1 is `s27-guidance`, track 2 `s27-transcriber`. Task 1 was
  done on the parent, Tasks 2–15 on `s27-guidance`, Tasks 16–19 on the parent. Spend is traced
  on every branch grown from the parent (later narrowed by 0107, below).

#### Choices made before any code (track 2's walkthrough, 2026-09-27)

- **W1, each candidate's reasoning level comes from a fixed rule** over the saved model list
  (`transcriber_shortlist.lowest_reasoning`: the lowest listed effort; else `minimal` if
  reasoning is mandatory; else `none`), which reproduces S2.6's levels (Andy: A). §7.2 left the
  level unstated. A candidate refusing its level would fail the probe and be replaced.
- **W2, the one batch-with-image call is kept** (Andy: A), with the invented probe page, only for
  a shortlisted candidate with a `:batch` variant.
- **W3, Andy marks photograph and scan cards only for candidates still in the running** after
  every measure that needs no marks (Andy: the alternative), since 0100 item 3 makes the others
  unchoosable. `automatic` (`make s27-retest-automatic`) was added; `s27-retest-pages` takes
  `MODELS`; `score` takes `marked`. The results file therefore does not give every candidate's
  invention counts on the two marked keys. Task 9's card test was corrected at the same time to
  state S2.6's rule (an `[illegible]` reading counts as holding a word).
- **W4, every finished-transcription marker names its page rule**, `all` included (Andy: B).
  S2.6's `dev-400` marker no longer matches; it stays on disk unused, and the marker was
  re-created free from the cache before any v2 run.
- **W5, fewer than eight candidates**: the re-test runs on those that pass, with no top-up from
  outside the filter (Andy: A).
- **W6, the filter requires structured output** (`response_format` in the listing's supported
  parameters), because every transcription call uses a strict JSON schema (Andy: A). A
  departure from §7.2's filter.
- **W7, the recheck file pair is chosen by reproducing Qwen's published figures**, trying the
  `pass2/` pair first, which Andy recalled as final (the re-marking after the stamped "Photo"
  label, decision 0086 item 1). The track would stop if neither pair reproduced them.

#### Foundation: spend, the sealed draw and the pool (track 1, Tasks 1–3)

- Adding `dev_seal_400_ids.csv` to the evaluation fixtures made
  `test_evaluation_cases_are_held_out_by_event_date` fail, since it expected every list but
  `dev_400_ids` to be held-out. `dev_seal_400_ids` joins the exclusion; the sealed list's purity
  is checked by its own test (Task 2).
- **The pool build** (Task 3 Step 11) gave 12,491 pool cases (7,177 in 2009–2014, 5,314 in
  2015–2019; the spec said about 12,490, ad-hoc) and a 958 KiB `coding_stats.json`; no
  case-number pattern was found in either output. The commit hook's 500 KB limit refused the
  JSON, so both large-file hooks exclude it, as they already exclude `tests/fixtures/words.txt`;
  it is a committed table, not raw data (rule 4).

#### Round 0 (track 1, Tasks 4–7)

- **Development-only refusals read the run record first** (Task 5 and Task 6 review rounds).
  `judge_outcomes._load` and `round0_handread._run` read `run.jsonl` and refuse a run recorded
  on a held-out sample before `cases.jsonl` is read, not only a run whose id says so. Tests
  added, including a happy-path `main` call with three run folders. The first Task 5 build had
  no `main` test, because `scripts/` is outside the coverage gate.
- **The hand-read's scoring refuses mismatches** (Task 6 review). `cards` writes a `run_id`
  column and `score` refuses a sheet drawn from another run; a sheet case with no judge label
  is refused naming only its row, never a case id.
- **The noise-floor run was started by Claude** (Task 7 Step 3), on Andy's authorisation ("you
  can perform the run now its the weekend"), at 11:12 UTC from a clean tree at `fbab38a`:
  `20260927T111202-fbab38a-dev-400-B`, 401 cases, $1.1593, B-v1's settings.
- **The judge ran on the three runs** (Task 7 Steps 4–5, Andy: "Yes do it now") from a clean,
  detached checkout at `228281b`, because the track worktree held uncommitted edits: $0.8084,
  $0.8081 and $0.8110, 399 labels each, **$2.43 against the plan's $1.50** (the judge's
  $0.00125-a-case estimate was about 60% low). The 50 cards were built free (10 hits, 8 from
  each miss group); the page names no case and shows no judge label.
- **The hand-read's score prints Andy's reasons by miss group** (Task 7 Step 7), because Task 15
  chooses the first round by miss group; the existing lines are unchanged.
- **The results** (Task 7 Steps 6–8). Andy's marks are kept privately under `data/`. The label
  was not validated (32 of 46), so `LABELS=unvalidated`. The noise floor, +4.0 points of top-1
  between B-v1 and the repeat, was larger than the plan assumed; between their Luna-checked
  folders it is +1.0. Because checked scores decide, every round was read against the checked
  pair: 1.0 points of top-1, or 1.7 points of finding recall for a finding round (the round
  registrations).

#### Round 1 and the Jev checks (track 1, Tasks 8–12a)

- **A tie in the Jev ranking test goes by code** (Task 8), so the expected order is (loss of
  control, stall, CFIT), not the brief's (loss of control, CFIT, stall).
- **The Jev client was ported from `typesafe-probe`** (Task 9) with its fixtures and tests,
  renumbered to 0097. The spell-check hook's own exclude list gained the TypeSafe fixtures,
  whose NTSB labels carry a source-data misspelling.
- **The post-pass, as built** (Task 10). The Luna check's empty evidence payload renders as
  `"{}"`, the same placeholder the judge sends. A runtime error replaces an `assert` in `src/`.
  `resolve_latest` skips derived check folders, a guard kept though the folder pattern already
  excludes them. The boundary test of the check's payload was shown to fail on a mutation that
  leaked the probable cause, then restored.
- **Task 10 review, round 1.** The `luna` and `jev` ways reserve the budget under the derived id
  before any client is built, and the check settles it; the derived folder is refused only once
  it holds results, not on its presence, since the reservation creates it. An ablation source
  (exclusions or includes) is refused before its cases are read, because the check would read
  the withheld phase group back from the processed record. An unfinished source and an
  already-derived source are refused. Tests cover the Jev checker's ranking and price and the
  rule way's happy path.
- **Task 10 review, round 2: nothing refusable after the reservation.** `checkpass.preflight`
  does every refusal read-only before the reservation; any failure between the reservation and
  the pass releases it. Three tests, each shown to fail on the earlier code (checked without
  `git stash`).
- **`round1_report` reads the run record first** (Task 11), like the Round 0 scripts; tests
  added.
- **Round 1's runs** (Task 12 Steps 2–5). The plain rule ran free. Andy authorised the Luna
  check ("you have a yes on the luna spend"); from a clean checkout at `b0cdcc2` it cost $0.1210
  and $0.1196, **$0.24 against the plan's $0.72** (W3's estimate was about three times high),
  and every reply parsed. Andy chose to include Jev; Claude's attempt was refused by the
  session's permission check on reading the TypeSafe key, so Andy ran both Jev checks himself
  ($0.0195, $0.0196). Outcome `luna`, so `CHECK=luna` for every later round.
- **A second, registered Jev check, `jev2`** (Task 12a, decision 0103; Andy: "Yes that sounds
  good"). Designed from TypeSafe's documentation and three independent projects that measured
  Jev, with every threshold from 0096 or 0101. Its design and win rule (beat no check, the plain
  rule and Luna on both answer sets, or Luna stays) are fixed in
  `docs/rounds/s27-round1-jev2.md`, committed before any code. Round 1's outcome and results
  file are unchanged.
- **`jev2` as built** (Task 12a). `checkpass.CHECK_WAYS` (Round 1's ways plus `jev2`) is what
  `check --way` accepts, so Round 1's report is unchanged; `CodingStats.group_n` was added for
  the phase-group base; each step records every option's probability; the report reads the
  derived folders through the same refusals as the sources, and a missing comparison fails the
  win rule.
- **A tie at the top between `none_of_these` and a code** was not settled by the registration.
  Andy chose A: `none_of_these` wins, so the answer stays as the model gave it. The
  clarification was dated in the registration and committed (`f078d9e`) before the code change
  and before any call; the first build had let the code win.
- **Task 12a review.** Every `jev2` step records Jev's full ranked order after the tie rules
  (`arguments["jev_order"]`), and the report reads "none of these ranked first" from it. A
  boundary test for `jev2`'s body was added and shown to fail on a mutation. The `jev2` report
  refuses the sealed sample.
- **`jev2`'s runs** (Task 12a Steps 8–9). Andy ran both from a clean checkout at `8c40dbd`
  ($0.0313, $0.0314). Outcome: "luna stays": `jev2` was below Luna on both answer sets and did
  not clearly beat no check on the first. Published as it came out.

#### The guidance rounds (track 1, Tasks 13–15)

- **Tests beyond the brief** (Task 13): the system text without guidance is byte-for-byte
  unchanged, and `report.provenance` prints the guidance line.
- **Task 13 review.** `make s27-round` refuses an empty `GUIDANCE` unless `NO_GUIDANCE=1`, so an
  unguided paid run cannot skip the registration check by accident. The judge's cost row carries
  the judged run's guidance. `report.provenance` uses `prompt.FINGERPRINT_CHARS`.
- **`round_result` reads the run record first** (Task 14), for every run it reads; tests added.
- **Some guidance counts are cited from the committed table, not the results file.** Four of
  the five Round 3 pairs are not among the 40 commonest pairs `docs/results/s27-coding-stats.txt`
  prints; they are cited from `scoring/tables/coding_stats.json` through `load_stats().pair`, as
  the registration says. Round 4's summed pair counts (through `event_pair`) and Round 5's
  per-group phase counts (through `group_phases` and `group_n`) are not printed in the results
  file either; each registration names its accessor (completed at the final review, Minor 7).
- **Three rounds were submitted outside the 01:00–12:00 UTC batch window** the plan set: Round 3
  at 14:44 UTC ("just go now"), Round 4 at about 17:00 ("Sounds sensible") and Round 5 at about
  18:30 ("Yes run it now"), each on Andy's instruction.
- **`CodingStats.event_pair`** (Round 4) sums a code pair's counts over every phase, so the
  guidance's counts come from code rather than an ad-hoc sum.
- **Six codes the data dictionary lacks join the code tables** (between Rounds 4 and 5,
  decision 0105): phases 553 and 601, events 281, 282, 284 and 850, through
  `scoring/tables/supplement.csv`; the prompt version moves to `s1-v6`. Not in the plan or the
  specification, which fixed the tables by 0025. It applies from Round 5 and is not read under
  0098 item 4. `round_result --supplement` (`SUPPLEMENT=1`) prints the cases an added code
  touches; Round 5's registration states that its run has the fix and its reference does not.
- **Round 3's judge comparison** ($0.8132) is against the repeat's unchecked folder, because the
  repeat's checked folder, the reference, was never judged. The registration says so.
- **A lesson from Round 4** (ad-hoc counts): its counts were conditioned on the NTSB coding both
  events, which the model cannot know. The model put a fuel event first in 40 cases (13 to 17 in
  earlier runs); of the 14 where it moved from a power loss to a fuel event and the NTSB kept the
  power loss, the NTSB coded no fuel event at all in 13. Later rounds' counts, the finding
  round's included, start from what the model can see: an evidence field, or a code the model
  chose.
- **Finding counts joined the pool** (before the first finding round): flagged findings by
  defining code (`PoolCase.findings`, `CodingStats.findings_given_event`), rebuilt from the same
  pool. Every earlier count is unchanged, checked key by key; four lines of the results file now
  show the labels 0105 added where they showed `?`.
- **Round 6 was kept by override** (decision 0106, Andy: "I think option B"). The rule dropped it
  on harm to top-1 against Round 3 (-6.3% [-10.5%, -2.5%]) with finding recall +11.4% [+8.2%,
  +14.6%]. Round 6's checked run became the reference; the sealed registration and this record
  state the override.
- **The stop rule** (Task 15 closed). Rounds 2–6 ran: 2 dropped, 3 kept, 4 and 5 dropped, 6
  kept by override. The occurrence rounds ended on two drops in a row (4, 5). Andy ended the
  finding rounds after one ("option A"), leaving unused the second round 0098 allows. The judge
  ran on each kept round (3 and 6).
- **A dropped round's guidance file stays in `scoring/guidance/`**, where its registration and
  run name it; it leaves the stack (§6.4's "removed").
- **Round 4's result line gives the wrong reason** (found at close-out). It reads "dropped: the
  gain's interval includes zero", but its interval, -4.0% [-7.8%, -0.3%], lies wholly below
  zero: `round_result.read` gives that reason whenever the lower bound is not above zero. The
  outcome, dropped, is right under 0098 item 4; the committed result is left as written, and the
  wording is a known fault of the script.

#### Branches, merges and the v2 reading (track 2 Tasks 1 and 9; track 1 Task 16)

- **Track 2's branch was cut by track 1's session** (its Task 1 Step 16, decision 0102), from the
  local parent at `21dca2b` rather than from the remote, and pushed. Track 2's Task 1 only
  confirmed it and ran `make check` (1514 tests, 97.71% coverage); `stage_spend --estimate 0`
  counted the three S2.7 branches at $0.00.
- **The first re-test run stopped at the $25 check before any model call** (track 2 Task 9
  Step 6, Andy: option A). Track 1's runs now wrote two new `RunRecord` fields (`guidance`,
  `guidance_sha256`), which track 2's `RunRecord`, forbidding unknown fields, could not read, so
  the spend checks failed. Track 1's identical four lines were landed on the parent (`42e67a7`)
  and the parent merged into `s27-transcriber` (`5d2bc2d`); track 2 still never edited
  `scoring/records.py` itself. Claude then ran the re-test on Andy's go-ahead ("can you run it
  for me?"), not Andy as planned.
- **The tracks merged into the parent** (track 1 Task 16 Step 1). Track 2 merged first
  (`87f74f1`); the parent was merged into track 1 on 2026-09-28 (`973eff1`, conflicts in the
  `Makefile`, `apps/eval/__main__.py` and the decisions index resolved there as unions); track 1
  then merged into the parent without conflicts (`c08ca2c`; Andy: "yes go ahead and merge").
  `make check` on the parent: 1,847 passed, 97.82% coverage.
- **The v2 reading on run records** (Task 16 Steps 2–4, as planned, with three details). The
  refusal is one helper, `runner.refuse_unnamed_reading`, called after the evidence-version
  check, so arm A and the ceiling keep their earlier message at v2. `report.refuse_cross_version`
  reads a record with no reading fields as S2.6's (`S26_V2_READING`), and `provenance` prints the
  reading on every v2 record. The "not fully transcribed" message names the exact `transcribe`
  command. The S2.6 v2 tests run unchanged.

#### Budget and spend

- **September's budget was raised to $50** (decision
  [0104](../decisions/0104-september-2026-budget-raised-to-50.md)). Round 2's first attempt was
  refused by the monthly guard before any call ($39.63 spent in September, $1.68 reserved). Andy
  raised September's line to $50, applied as `NTSB_MONTHLY_BUDGET_USD=50` in each paid command's
  environment until 30 September; the code's default stays $40.
- **S2.7's spend counts only its own branches** (decision 0107, amending 0102 item 3).
  `scripts/stage_spend.py` had counted every branch holding S2.7's first commit, which by then
  included two later stages' branches cut from `s27-guidance`, and it counted HEAD. It now
  counts only branches named `s27-`, and not HEAD. The total was unchanged by the fix ($13.81 at
  that time).

#### Track 2: page rules and markers (Tasks 2–4)

- The comment on `ReadingLookup.done_file` points to Task 3 Step 6, which re-creates S2.6's
  marker, not Task 2's Step 5, which only confirms it no longer matches.
- Every existing test that depends on S2.6's rule states `page_rule="all"` explicitly, except the
  two tests whose purpose is the default itself.
- The dry-run test expects `"rule all,"` in the projection line; the unknown-rule test checks
  argparse's own message.
- The shared test stub serves only image-only pages, so a test on it could not show the rule
  working. A stub subclass with one text-and-image page was added: under `image-only` the page is
  never sent, and (review fix) under `all` it is.
- Task 3 Step 6's "the projection line ends ..." is read as "contains": the real line ends with
  the skipped-documents clause.
- **`dev-400`'s marker was re-created free** (Task 3 Steps 6–7). The dry run projected 12,458
  pages, 0 unread, $0.00 (8 documents could not be listed, fetched or parsed). The real command
  read 0 pages, made no job, reservation or call, counted 59 of 12,458 failed (within the 2%
  line) and wrote the new marker, `dev-400-60ddd78408f8.json`, naming the model, rule `all` and
  150 dots per inch. S2.6's `dev-400-940436639bbd.json` stays on disk unused.
- **T3 skips a case whose docket listing fails** (Task 4), counting it and printing the count
  separately after the report, as the transcription job does; the results file's fields are
  unchanged.

#### Track 2: the shortlist and the probe (Tasks 5–7)

- The fetch date is taken in UTC, to match the `Makefile` target's `date -u`.
- Prices are printed exactly (at first at full float precision, then with `Decimal` arithmetic,
  for example `$0.1` rather than `$0.09999999999999999`), so Task 6 copied exact prices.
- **Free and unpriced listings are refused** (Andy's decision): a free or preview listing can be
  withdrawn or rate-limited, and it would win the cost comparison by default. This refused 7
  listings, dropping the eligible models from 16 to 14; two had reached the shortlist (ranks 1
  and 2), so reserves 9 and 10 moved onto it. Andy allowed an exception for NVIDIA's free
  listings if any qualified; none of the five did.
- **Prices were checked against the saved list** (Task 6). `openai/gpt-5.6-luna`'s existing
  entry already matched. `z-ai/glm-5.3-flash` is priced differently now ($0.045/$0.14 against
  the old $0.09/$0.30): a new constant, `S27_GLM_53_FLASH`, placed after the old ones, holds the
  current price; the old constants were left in place and flagged for Andy. The reasoning-level
  test asserts entry by entry, since S2.7 adds ten entries.
- `request_body` is called with `history=()`, which has no default on the real signature.
- **The batch-with-image call reserves and records spend** (not in the brief's code): a spend
  row at submission (cost 0.0) and, from `batch-poll`, one row with the real cost under its own
  job id. Review fix: that row is written once, only at a terminal status, so a re-poll or a
  partial cost is never counted twice.
- **Probe replies are saved privately first** under `data/s27/probe-replies/`; only a passed
  model's reply is copied into the committed fixtures. S2.6's reply-parsing test was narrowed to
  its four fixtures by name, and S2.7's fixtures have their own test.
- `cmd_probe` is its own function, mirroring S2.6's reserve, spend and settle order, because
  S2.6's is fixed to its four candidates and its script was not in Task 7's files.
- `S27_CANDIDATES` was defined empty until the probe ran.
- The probe tests use invented model ids, added to the price and reasoning tables by
  monkeypatching.
- **The probe and the batch call were run by Claude** (Task 7 Steps 6–7), on Andy's go-ahead
  ("You can run those now it's Sunday!") at about 13:10 UTC on `076ce08`, not by Andy as
  planned.
- **The probe's outcome** (Task 7 Step 7). The two Meta models failed with a 403 from
  OpenRouter's 18+ age setting, not from reading the page, and were replaced in order by
  reserves 9 and 11 (W5); reserve 10, `qwen/qwen3.8-flash`, returned a reply that did not parse.
  The eight that passed are `S27_CANDIDATES`; their replies are committed, and the unparsable
  reply stays under `data/` only.
- **The batch service still refuses images** (W2). The call for `deepseek/deepseek-v4.1-flash`
  was accepted, then failed: base64 images are rejected. Every re-test call stays synchronous at
  the standard price.

#### Track 2: the re-test (Tasks 8–10)

- **The recheck pair is set once in the `Makefile`** (`HW_RECHECK`, `PHOTO_RECHECK`, defaulting
  to the `pass2/` pair), and `s27-retest-verify`, `-automatic` and `-score` all use it, not the
  brief's fallback to the top-level pair, which contradicted W7.
- `absolute_notes` takes 0080's photograph and scan limits from S2.6's constants, turned into
  exact fractions, so exactly 1 in 20 prints "within".
- Every division in the rule and the notes goes through S2.6's exact `_fraction` helper, which
  gives 0 for an empty denominator.
- The script's Status paragraph names only what was built at each stage; tests beyond the brief
  cover the boundary arithmetic, the cost tie-break, the 1-in-20 edge, the recheck and `main`.
- **`verify` reproduced every one of Qwen's published second-pass counts** with the `pass2/`
  pair, matching Andy's recollection (Task 8 Step 5). The top-level pair does not (1551 key
  lines and 55 inventing lines against the published 1548 and 54).
- `word_cards`' interface line gives its real signature, with the photograph card as default.
- **The re-test reuses S2.6's code** (Task 9): S2.6's `cmd_run` gains an optional expected cost
  per page ($0.003 for the re-test), and the card loop moved into a shared `_version_cards`.
  S2.6's five marking outputs were rebuilt byte-identical before and after the change, and every
  S2.6 test passes unedited.
- The re-test's card shuffles use S2.6's seed with their own bases (300, 400); the candidates are
  sorted first, so the same set gives the same cards in any order; `pages` refuses a candidate
  with key pages the cache holds no reading of.
- **`pages` refuses a rebuild that would move saved marks** (Task 9 review): marks are kept in
  the browser by row, and the shuffle depends on the candidate set. A rebuild with the same set
  rewrites every file byte for byte.
- **DeepSeek's retry stopped at its reservation** (Task 9 Step 6, Andy: option A; $0.2861 against
  $0.2820, 63 of 94 failed pages re-read, 31 unread), which ended the command before five
  candidates were retried. `run` gained `--models`, and the one retry was finished for the other
  five. DeepSeek's 31 pages were left unread: its first pass alone cost $0.0031 a test page, twice
  Qwen's, so the cost condition rules it out. First pass $1.40 for all eight; $1.71 before the
  finishing retry.
- The plan's file table gains `s27-retest-automatic`.
- **Qwen's cost bar stays S2.6's rounded $0.00154** (Task 8 review). `automatic` and `score`
  compute Qwen's row from the cache and print its measured cost, $0.0015362713, beside the bar;
  a candidate costing between the two would have been flagged for Andy. None was.
- The results file states the retries, including DeepSeek's 31 unread pages, scored as failed.
- **Safeguards beyond the brief** (Task 10): `automatic` and `score` re-verify Qwen's row first;
  both refuse a candidate with a key page never read; `score` refuses a candidate still in the
  running that is not marked, and a sheet holding another model's cards; the header names the
  recheck pair and whether it is the one Andy recalled.
- **`automatic` put all eight candidates out** (Task 10 Step 5, free): seven on inventing lines
  (65 to 181 of 1548, against Qwen's 54) and handwriting accuracy, some also on line format or
  typed errors; DeepSeek on handwriting accuracy, typed errors and cost. No candidate lay between
  Qwen's measured cost and $0.00154. "To mark: none".
- **Andy's marking was skipped** (Task 10 Step 6), as the step allows; the results file prints
  "not marked (already out on an automatic measure, walkthrough W3)".
- **`score` wrote `docs/results/s27-transcriber-retest.txt`** (Task 10 Step 7): "no candidate
  meets all seven: Qwen stays".

#### Track 2: routing, the readable split and the transcriber decision (Task 11)

- **Routing pages** (Andy, "now"). While deciding the page rule, Andy asked whether different
  models could read pages by how much text they hold. Three cheaper candidates made fewer typed
  errors than Qwen, but under W3 nobody had marked whether they invent words on the full-page
  scans. `routing-pages` builds the scan page for named candidates in its own folder, and
  `routing-tally` writes `docs/results/s27-routing-scans.txt`. Both are free and exploratory
  evidence for 0120's open routing idea; neither changes 0100's rule or the re-test's outcome.
- **The routing cards gain a fourth choice** (Andy: A), "can't judge — I can't read this part
  of the page", counted apart, not as invented; S2.6's pages keep their three choices. The sheet,
  card numbers and saved marks were unchanged. `routing-tally` refuses a model the page was not
  built for, a page with no model list, and an unknown choice.
- **A post-hoc check on Andy's challenge**: do the handwriting key's `[illegible]` lines decide
  the rejection, since any word written there counts as invented (0079)? `readable-split`
  (`make s27-retest-readable`) scores readable and `[illegible]` pages apart with the committed
  scorer and checks that the two parts add up to each model's totals. An ad-hoc count had given
  Qwen 1041 lines right, not 1036, because it skipped 0086's format rule; calling the scorer
  itself removes that gap. The verdict holds.
- **The page rule was not brought to Andy as a separate decision.** T3's outcome under 0100
  item 4 is `all`, and with transcription off by default it applies only if transcription is
  used again; 0120 item 4 records `PAGE_RULE = "all"` and `TRANSCRIBER` for that case (Andy: "Ok
  suppose we need to stick with qwen and the costs").
- **Task 11 Step 3 was not needed**: neither `TRANSCRIBER` nor `PAGE_RULE` changes, so
  `docket/transcribe.py` was untouched. The planned re-read of `dev-400` at the meeting point is
  replaced by 0120 item 5.

#### The sealed run (track 1, Task 18)

- **`scripts/sealed_report.py` as planned, plus finding recall@10** for both runs (Round 6 moved
  it) and a held-out refusal; four tests. `s27-sealed-run` names the two guidance files itself,
  so the sealed run cannot start with another stack; `s27-sealed-results` fixes the `dev-400`
  side to Round 6's checked run. At v1, the planned transcription step does not apply: the run
  fetches the sealed dockets itself.
- **The first attempt was refused** (Task 18 Steps 6–7, run by the controller on Andy's
  instruction, "Can you just get this started now for me"): at 11:40 UTC the monthly guard
  refused it before any call ($1.68 projected plus $47.75 spent, against the code's $40
  default), because the launch script had not set 0104's `NTSB_MONTHLY_BUDGET_USD=50`. It left a
  folder holding only `spec.json`, `20260929T114018-9cbe5c5-dev-seal-400-B`, kept under
  `data/runs` and unused.
- **The sealed run** is the second attempt, `20260929T114049-9cbe5c5-dev-seal-400-B`: commit
  `9cbe5c5`, clean tree, prompt `s1-v6+ge17fecdc66ec`, 401 cases, $1.1802; 397 answered, 3
  refused by the leakage guard, 1 reply-format failure. Its batch was submitted at 14:34 UTC,
  inside the slow window, and finished at 15:06. The Luna check cost $0.1133.
- **The judge was not run on the sealed sample**, though §9.1 item 3 said "with the judge": the
  narrative label failed validation (0099), and `ntsb-eval judge` refuses a sample other than
  `dev-400` without `--validated`. The misread part of the prediction is "not scored".

#### Close-out fixes (the final whole-branch reviews)

- **The sealed guard at every entry point** (Important 1). `ntsb-eval baseline` and five S2.6
  scripts that take a free-form sample (`page_kinds.py`, `analysis_handcheck.py`,
  `narrative_coverage.py`, `name_coverage.py`, `docket_leak_scan.py`) could read the sealed
  sample before its registration; each now calls `refuse_sealed` first. Tests added, including
  one for `ntsb-eval check`, which already refused it.
- **One shared development-only refusal**: `samples.refuse_unless_development(run_id, sample)`
  replaces the six scripts' hand-copied checks, which accepted `dev-seal-400` as a plain
  development sample (defence in depth: no sealed run could exist before registration). It takes
  the sample name, not the run record, to keep the import-linter contract. Each script's refusal
  wording is kept. `scripts/coding_stats.py` still reads the sealed ids, to leave them out of the
  pool.
- **The prompt version is printed** (Minor 1): `report.provenance` prints `prompt=`, and
  `round_result`'s `run:` line prints both runs' versions, since from Round 5 a guided run's
  `s1-v6` can differ from its reference's `s1-v5`.
- **Unfinished and mismatched runs are refused** (Minor 3): `round_result` and both Round 1
  reports refuse a run whose `finished` is empty, and runs that do not share sample, arm and
  evidence version. The check's "already exists" message says a dead pass's folder must be
  deleted by hand.
- **The Luna check's boundary test asserts every withheld window** (Minor 4), not the first 80
  characters of each field, like `jev2`'s; a mutation showed it fails on a leak, then was
  reverted.
- **`coding_stats.processed_rows` parses the raw record only for development rows** (Minor 5);
  nothing had leaked. The table and results file were rebuilt byte-identical.
- **§12's Jev refusal is not in the client** (found at close-out). §12 said the Jev client
  refuses any call that is not the ordering check on a development run. As built,
  `model/typesafe.py` has no such refusal: only `ntsb-eval check` builds the client, and the
  check refuses any source that is not a finished development arm B run before any client is
  built (`checkpass.preflight`; `tests/test_eval_app.py`'s held-out check test). The same end,
  enforced one layer up.
- **The ported Jev fixture holds a real case's evidence** with no case id beside it (Minor 6).
  It was identified locally as a 2009 development-split case, recorded in
  `tests/fixtures/typesafe/README.md`, and `test_typesafe_fixture_case_is_development_split`
  checks its split by event date.
- **Decision 0106's numbers now come from a script** (Important 2, Minor 2). They were ad-hoc
  counts. `scripts/round_comparisons.py` writes `docs/results/s27-round-comparisons-dev.txt`;
  every figure matches 0106's table and Round 6's note. A line was appended under Round 6's
  override and a "Source of the numbers" section to 0106; nothing above either was edited.
- **Track 2's output filter was stricter than written** (Important #2): the shortlist refuses a
  listing whose output is not text only, where §7.2 and 0100 item 1 say "returns text". It
  refused 13 listings and changed nothing on the shortlist: the one image-and-text listing among
  them would have ranked as reserve 15. 0120's Context now says "three conditions".
- **Part of the shortlist results file was written by hand** (Minor #1): its probe and batch
  sections come from the probe's printed output, the spend file and the batch service's reply,
  not from the script; the two 403 lines are shortened. The numbers are left as they are.
- **`page_value.py` prints the near-empty share only for text-and-image pages** (Minor #7), not
  for each page kind as §7.3 describes. It does not affect the rule's choice; not regenerated.

#### Lint-only rewrites of the plans' code

In each case the formatter, the linter or `mypy --strict` required another form, and behaviour
is unchanged. Track 1: a docstring split to fit 100 columns (Task 13); typed helper functions in
place of `list.append(...) or ...` lambdas, `noqa` marks on fixed git calls and wrapped lines
(Tasks 1, 2); a typed `_sorted_dict`, an explicit `__all__`, fixture-row annotations and an
import moved to the top (Task 3); a Status sentence appended to the existing section, a `noqa`
for `miss_group`'s early returns and wrapped lines (Task 4); a typed row read with a runtime
check, a wrapped docstring, a named constant, import order and annotations (Task 5); import
order, wrapped lines and annotations (Tasks 6, 14, with a stray `type: ignore` removed in 14);
wrapped lines, a `noqa` for `check_text`'s signature, a named constant, import order, a split
assertion, a typed helper and a `cast` (Task 8); an import folded into an existing line (Task
9); lint fixes in the check's tests, typed test factories, a real `datetime` for `finished` and
imports merged at the top of the boundary test (Task 10); wrapped docstrings, a named constant,
a typed helper, a renamed loop variable and `__all__` (Task 11). Track 2: an annotated
page-rule literal and imports kept unduplicated (Task 2), `collections.abc.Set` in place of a
name that does not exist (Task 5), imports hoisted to the top (Task 7), `RESOLUTION` imported
from its home module (Task 8), a typed integer read (Task 9) and an unused fixture removed
(Task 10).

### Decisions taken during the stage

Records 0093 to 0100 were written with this specification; 0101 to 0107 and 0120 during the
build.

- [0093](../decisions/0093-s27-runs-as-two-tracks-guidance-on-v1.md) — S2.7 runs as two
  tracks: coding guidance on v1, transcription alongside (item 3 amended by 0102).
- [0094](../decisions/0094-coding-statistics-from-a-pool-outside-the-samples.md) — coding
  statistics come from development verdicts outside the samples.
- [0095](../decisions/0095-a-sealed-development-sample.md) — a sealed development sample,
  `dev-seal-400`, opened once.
- [0096](../decisions/0096-the-ordering-check.md) — the ordering check: what it sees, what it
  may choose, and that a model must beat the plain rule (item 4 amended by 0101, item 5 by
  0103).
- [0097](../decisions/0097-jev-as-an-ordering-check-model-on-development-cases.md) — Jev is
  admitted as an ordering-check model on development cases only.
- [0098](../decisions/0098-guidance-rounds-stop-rule-and-prediction.md) — guidance rounds:
  sources, registration, reading rule, stop rule, the $25 line and the prediction (item 2
  amended by 0101; item 4's outcome for Round 6 overridden by 0106).
- [0099](../decisions/0099-the-judges-narrative-label-and-four-outcomes.md) — the judge's
  narrative label gives four outcomes, validated by Andy's hand-read before it is cited; it
  was not validated.
- [0100](../decisions/0100-the-transcriber-retest-and-page-rule.md) — the transcriber re-test
  is judged against Qwen, and the page rule is measured before it is chosen.
- [0101](../decisions/0101-the-clear-habit-safeguard.md) — counts act only on a clear habit,
  at least 60% of at least 20 pool cases.
- [0102](../decisions/0102-a-parent-branch-with-a-branch-per-track.md) — a parent branch with
  a branch per track; spend traced on the branches grown from the parent (item 3 amended by
  0107).
- [0103](../decisions/0103-a-registered-second-jev-check.md) — a second Jev check, designed
  from TypeSafe's documentation and registered before it runs; Luna stays.
- [0104](../decisions/0104-september-2026-budget-raised-to-50.md) — the monthly budget is $50
  for September 2026 only.
- [0105](../decisions/0105-codes-missing-from-the-dictionary-join-the-tables.md) — six codes
  the NTSB uses, missing from its data dictionary, join the code tables; prompt version
  `s1-v6`.
- [0106](../decisions/0106-round-6-kept-by-override.md) — Round 6 is kept by override of the
  do-no-harm rule.
- [0107](../decisions/0107-s27-spend-counts-its-own-branches-only.md) — S2.7's spend counts
  only its own `s27-` branches, not a later stage's, and not HEAD.
- [0120](../decisions/0120-qwen-stays-and-transcription-is-off-by-default.md) — Qwen3.5 122B
  stays the transcriber and the page rule stays `all`; transcription is off by default, for
  cost, and becomes a tool the S3 loop may choose (amends 0074's default).

### Implementation record

- Pull request: #17 (https://github.com/floyda/ntsb-probable-cause/pull/17), merged 2026-09-29 as
  `1d2a12d` with a merge commit (decision 0033)
- Close-out: a follow-up pull request from `1d2a12d`, holding only this record, the status
  changes, the plans' removal and the version (decision 0017)
- Plans, at their last commits: https://github.com/floyda/ntsb-probable-cause/blob/bb6a0451d6113197775d17cb3767b37a01f3c9a5/docs/plans/2026-09-26-s27-track1-coding-guidance.md and https://github.com/floyda/ntsb-probable-cause/blob/87f74f188cf50ca683b68a2d72553a94441a5838/docs/plans/2026-09-26-s27-track2-transcriber.md
- Commits: from `94f5d42` to `bb6a045`, both included (121 commits before the close-out commit)
- Spend: $15.10 on S2.7's own branches ($13.34 evaluation runs, $1.76 preparation spend rows),
  `uv run python -m scripts.stage_spend`, 2026-09-29, against the $25 line.
- Release: v0.7.0 (decision 0018). The tag was first created on `1d2a12d`, before the
  close-out; Andy moved it on 2026-09-30 to the close-out's own commit, so the release holds
  S2.7 and its close-out and nothing merged after them (the S3 probe, pull request #18)

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
