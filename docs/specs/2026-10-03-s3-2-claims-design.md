# S3.2 — The claims: design

*Drafted 2026-10-03 from a design session with Andy, the same day S3.1 closed (pull request #21,
release v0.8.0, merge commit `1c79dde`). Status: Approved (2026-10-03, Andy: "all looks good"). This is the
specification for sub-stage S3.2 of
[the S3 specification](2026-09-30-s3-agent-loop-design.md) (§3, §11), which holds the design S3
shares and S3.1 in full. The implementation plan is written from this document separately, in
`docs/plans/`.*

**How to read this.** Each section says what is done, then why, with an example where one helps.
Terms in **bold** on first use are in the glossary at the end. Numbers here are of four kinds,
and each is labelled:

- **scripted** numbers cite the committed script and results file that produced them;
- **run records** are read from a run folder's `run.jsonl` (not committed); S3.2's cost script
  re-derives each one it relies on;
- **ad-hoc** numbers were counted during the design session by a throwaway command. They are
  not citable, and S3.2 re-derives any it relies on with a committed script;
- **estimates** are arithmetic, and are replaced by measured figures in the As-built record.

**Decision records.** The records this design needs are written in the plan's first task, not
with this document. They are numbered from 141 on; §16 lists them.

---

## 1. What S3.2 is for

The project has to answer "why does this need an agent at all?" with a measurement. Decision
0022 fixed the test, and 0121 reworded it for S3's loop: the loop (arm C) is warranted only if it
beats the fixed pipeline (arm B) on accuracy at equal cost, or matches it at lower cost. S3.1
built the loop and measured how much its score moves by chance. It made no claim (0128).

**S3.2 makes the claim.** It answers three questions, each on cases the loop has never been
read or tuned on:

1. **Agency.** Does the loop beat arm B, or match it at lower cost?
2. **The docket.** Does reading the investigators' documents matter inside the loop?
3. **Trust in the number.** When the board shows a confidence, is the answer right that often?

**S3.2 builds nothing new into the agent.** No prompt change, no new tool, no tuning. It writes
the rules down before it runs, fixes the plumbing a once-only run depends on, runs five paid
runs, and publishes what they say.

**Why the rules come first.** The `dev-400` readings were seen before this design was written:
there, the loop is level with arm B on occurrence top-1 and findings and behind on top-3 (§13).
So `dev-400` cannot carry a claim, and every rule that turns a held-out result into a verdict is
fixed and committed before held-out is touched.

## 2. Where S3.2 starts

- **The loop under test** is the one frozen at commit `fd6053f`, prompt version
  `s3-v1+ge17fecdc66ec+p947fac1c86a4` (decision 0139). It is **version 1 (v1)** of the agent; the
  precedent tool comes after S4 as v2 (0140).
- **Arm B** is S3's four-part fixed pipeline (0127): S2.7's answer with the two kept guidance
  files, every coding tool on its own top three in a fixed order, one more answer, then S2.7's
  ordering check (`luna`), with S3's statistics.
- **Arm A** is start facts only, one call (0127 item 1).
- **Model and settings** are unchanged: GPT-6 Luna at reasoning `medium` (0073), batch, reply
  budget 8,000 tokens (0084), evidence v1 (0120), S3's statistics file (0129).
- **Spend:** S3 has spent $5.11 of its $50 line (scripted, `scripts/stage_spend.py --stage s3`,
  2026-10-03; the S3 specification's Implementation record).

## 3. What runs

Five runs. Andy cut the S3 specification's outline (§11) from about ten runs to five, to keep
S3.2 cheap and fast.

**On `dev-400`, one run:**

1. **The loop without its coding tools** (`run --arm C --without coding`): the answer is the
   latest hypothesis, then the refinement. It tests where the agency is meant to sit.
   *Example question:* "does the loop do worse if it answers straight from its last hypothesis,
   without checking its codes?"

**On `heldout-400` (400 cases), four arms, each once:**

2. **Arm A.** The start-facts-only score: what a live case knows on its first day.
3. **Arm B**, in three commands: the answer run, the tool post-pass (`ntsb-eval tools`), then
   the ordering check (`ntsb-eval check --way luna --stats s3`). Each writes a held-out ledger
   row.
4. **The loop (arm C).**
5. **The loop without the docket** (the docket roles excluded). This is CLAUDE.md goal 2's
   ablation: "an ablation with the docket tool removed must show a real loss".

**Reused, not re-run.** The `dev-400` readings of the loop and arm B already exist, at the
frozen loop's text: the two noise-floor runs (`20261001T201506-fd6053f-dev-400-C`,
`20261001T201648-fd6053f-dev-400-C`) and S3's full arm B
(`20260929T053953-674c92e-dev-400-B-tools-check-luna`, whose post-pass carries the same
`+p947fac1c86a4`). The coding ablation is read against the two noise-floor runs. The
calibration curve is fitted on the noise-floor runs (§8), as decisions 0126 and 0130 planned.

**Dropped from the outline, and why:**

- **The sealed sample (`dev-seal-s3-400`) stays sealed.** It was meant as a second check on
  fresh cases for a loop tuned on `dev-400`; this loop was never tuned (0139), and held-out
  gives the fresh-case check. Unopened, it is kept for v2's development test (0140 item 3).
  *What is given up:* if held-out surprises, S3.2 cannot tell whether held-out is unusual or
  `dev-400` was.
- **The `suggest_codes` ablation.** It shows only whether one tool earns its place; it does not
  bear on the claim.
- **The no-docket ablation on `dev-400`.** The held-out run is the one goal 2 needs.
- **Re-running arms A, B and C on `dev-400`.** The existing runs answer every question the
  outline asked of them. Nothing on `dev-400` is a claim either way.

**Estimate:** about $6.50 billed for the five, at the noise-floor runs' and arm B's billed costs
(§6): the coding ablation about $1.20, arm A about $0.30, arm B about $2.20, the loop about
$1.90, the loop without the docket perhaps $0.50 to $1 (not measured).

## 4. "Frozen" and what is fixed first

### 4.1 The rule

**Frozen means the model sees exactly the same text.** The prompt version's `+p` part is a
fingerprint of the source of ten files and of the tool definitions as sent
(`agent/texts.py:TEXT_SOURCES`, `agent_text_sha256`; decision 0133). Any edit to those files,
a comment included, changes it. So:

- **S3.2 edits none of the ten fingerprinted files**: `scoring/prompt.py`, `scoring/hypothesis.py`,
  `scoring/codes.py`, and `agent/` `texts.py`, `steps.py`, `tools.py`, `schemas.py`, `later.py`,
  `loop.py`, `armb.py`.
- **A test asserts the loop's prompt version is `s3-v1+ge17fecdc66ec+p947fac1c86a4`**, so the
  rule is held in code, not by this sentence. The held-out loop runs then carry the same label
  as the `dev-400` runs they are read beside.
- **A dependency update that changes the tool definitions as sent** (for example a `pydantic`
  release that writes the schemas differently) would change what the model sees, and the test
  would fail. Such an update waits until S3.2 closes.

*Why:* the coding ablation is compared with the noise-floor runs, and the held-out loop with
every `dev-400` reading. Under one label, those comparisons are like for like.

### 4.2 The fingerprint's principle, built in S3.3

Andy's view, taken as a decision for later: **the fingerprint should cover what the agent
receives, not the source that builds it.** Today a comment or refactor moves the label though
the model sees the same words; decision 0133 accepted those false changes as safe. The better
fingerprint renders every fixed text the loop can send (the system text, the tool definitions,
step instructions, menus, tool-result wording, refusal lines, a later trigger's opening) from a
fixed set of made-up inputs, and hashes the output. Its one risk is a text built on a path the
made-up inputs never reach; the defence is a mutation test that changes each text-building
string and checks that the hash moves or a test fails.

**It is built in S3.3, before S4 locks any prediction**, because S3.2 touches none of the
fingerprinted files, S3.3 is where the loop's text is next likely to change, and S4 is where the
label becomes public. Continuity is shown then by computing the new fingerprint on `fd6053f`'s
code and on S3.3's, which must match. The record is written in S3.2 (§16).

### 4.3 Fixed before held-out

From the S3 specification's "Known issues carried to S3.2", all outside the fingerprint:

1. **A resumed round that was partly answered** (`agent/drive.py`). Today a call with no reply
   counts as a failed attempt, one of its case's two, instead of being sent again. *Example:*
   the laptop sleeps during the held-out loop run; on resume, a dozen cases fail that would have
   answered. A once-only run cannot carry this.
2. **A completed round the provider reports as cancelled** stops the run (`agent/drive.py`). One
   more resume continues it today; it is fixed with item 1, in the same code.
3. **An unreadable `spec.json` reads as "no ablation"** (`apps/eval/__main__.py`). S3.2 runs two
   ablations; a report must refuse rather than label one the plain loop.
4. **Two tests:** `month_spent` with a dead round that reported a cost; and the temperature each
   call sends, pinned.

**New work, also outside the fingerprint:**

5. **Arm B's tool post-pass and ordering check accept a held-out run.** Today both refuse any
   held-out run (`scoring/checkpass.py:_refuse_unless_development`, which `agent/armb.py`'s
   `preflight` calls). They accept one held-out arm B run, only after S3.2's registration is
   committed, each appending a held-out ledger row and refusing an uncommitted tree (0026), as
   `ntsb-eval run` does. The plan confirms this can be done in `scoring/checkpass.py` and
   `apps/eval/__main__.py` without editing `agent/armb.py`; if it cannot, work stops and Andy
   decides.
6. **The sealed sample's lock moves.** `samples.refuse_sealed` unlocks `dev-seal-s3-400` when
   `docs/rounds/s3-registration.md` is committed (0129 item 2), which is the file S3.2 commits
   first. The unlock moves to `docs/rounds/s3-sealed.md`, written only when the sample is used
   (for v2, 0140). A test proves the sample is still refused after S3.2's registration lands.
7. **One cost cap of $0.30 a case** (§5).

### 4.4 Left as they are, with the reason

- **The room held at a read choice does not count the documents about to be read** (`agent/loop.py`,
  fingerprinted). The cap still holds; a case may stop at the cap before it answers. The $0.30
  cap (§5) is what guards against it.
- **A case forced to answer at H0 still gets the listing in its refinement** (`loop.py`). It
  cannot happen at this cap.
- **The coding step catches every exception** (`loop.py`). Broad, but it has worked; changing it
  changes the label.
- **Arm B's post-pass:** its over-budget refusal comes after the dockets are read; its
  `+tools-<name>` label is not checked against the statistics; one refusal's wording
  (`armb.py`, fingerprinted). Ordering and wording only.
- **Arm C's `spec.json` also holds arm B's `prompt_version`** beside `agent_prompt_version`.
  Cosmetic; changing the file's keys would break the key-for-key comparison with the noise-floor
  runs.
- **Not used by S3.2:** `scripts/reply_budget.py` misreading arm C; the precedent probes' pool by
  event date; `make s3-miss-kinds` overwriting its results file; `AgentCall.offered=()` before
  decision 0134 (the noise-floor runs postdate it).

The last known issue, the noise pair never read under decision 0136's rule, is not a bug: §7.3
reads it, free.

## 5. One cost cap for every arm

Decision 0022 item 1 requires the same per-case cap for every arm. Today arms A and B use $0.05
(`RunSpec.cap_usd`) and arm C $0.15 (`agent/run.py:CAP_USD`); neither was reached on `dev-400`.
**Every S3.2 run uses $0.30 a case**: arm A, each part of arm B, the loop and both ablations.
The cap is checked against the computed price, which errs high (0135 item 4).

*Why $0.30:* it is how §4.4's `loop.py` issue is guarded. On `dev-400` the dearest loop case
cost $0.089 and $0.1055 computed in the two runs (ad-hoc); held-out fatal dockets may be larger.
At $0.30 the issue practically cannot arise. For arm B, a higher cap can only let it read more
of a very large docket, never less, which makes the bar stronger. Money stays bounded: each run
still reserves its expected cost, and the run budget and the monthly guard still stop it.

**The check.** The loop also stops its coding calls early when the room left for the answer
runs short. A committed script counts, in the noise-floor trails, any case whose coding was cut
short that way at $0.15. If there is one, raising the cap would change what such a case does,
and this choice comes back to Andy before any S3.2 run.

Every S3.2 `make` target passes the value (`--cap-usd 0.30`). The defaults in code stay as
they are, so the records of earlier runs stay true.

## 6. Equal cost

**Why it matters.** 0121 item 5's test and its result 2 both turn on cost.

**What `dev-400` showed** (seen before this rule was written):

- **Billed**: the loop $1.84 and $1.97 (scripted, `docs/results/s3-noise-floor-dev.txt`); arm B
  $2.19 for its three parts, the answer $1.12, the tool post-pass $0.96, the ordering check
  $0.11 (run records). By the bill, the loop is about 10% to 16% cheaper.
- **Computed** (every token at the list rate): the loop $4.57 and $4.45; arm B $2.43 (the
  answer $1.21, the post-pass $1.11, the check $0.11). By that measure, it costs about twice as
  much.

The gap is prompt caching: the loop resends its growing conversation on every call, and the
provider bills what it has recently seen at a lower rate.

**The rule** (Andy, option A):

1. **Each arm's cost is what was billed for its held-out run**, on the same cases, failed cases
   included (that money was spent). Arm B's is the sum of its three parts. A batch run's billed
   figure is its `reported_batch_cost_usd`; the ordering check runs synchronously, and its
   replies carry the provider's own cost, so its `cost_usd` is what was billed.
2. **The band.** The loop's cost is **lower** when more than 10% below arm B's, **greater** when
   more than 10% above, and **equal** otherwise. *Why 10%:* the loop's two identical runs
   differed by 7% on their bills ($1.84 against $1.97), so a smaller gap is within chance.
3. **Printed beside, never deciding:** each arm's computed cost and its prompt and reply
   tokens, so a reader sees how much work each did.

Arm B's answer run does record a billed figure; decision 0135 counted arm B at the computed
price for spend only, so that past totals stayed as they were. The comparison uses arm B's
billed figure without rewriting any spend record.

*Why billed is defensible though the numbers were seen:* it is the money paid, and what the live
board will pay; and the loop's cache-friendly shape (the same tool definitions on every call, a
conversation appended to at the end only; decision 0124) was decided before any cost was
measured. **Ruled out:** computed for both (it prices the loop at about twice what anyone pays);
"lower only if lower under both measures" (with `dev-400`'s figures it restates computed
pricing's outcome).

## 7. The headline test

### 7.1 Which score decides

**Occurrence top-1 decides**: is the agent's first occurrence code the NTSB's first code? It
has been the headline since S1, and the bars use it. **Finding recall@10 (flagged)** is reported
under the same rule as its own result and does not decide. **Top-3** is reported beside, and does
not decide: its gap is mostly the ordering check, which only arm B runs. On `dev-400` that check
added +8.3% [+5.5%, +11.3%] to arm B's top-3 (scripted, `docs/results/s3-armb-full-dev.txt`) and
+9.1% [+6.1%, +12.2%] to the loop's in the diagnostic (scripted,
`docs/results/s3-check-diagnostic-dev.txt`).

### 7.2 Beats, matches, worse, undecided

The loop and arm B answer the same held-out cases. The difference is the paired mean (loop
minus arm B) with its 95% interval, as every report prints it.

- **Beats:** the interval lies wholly above zero (as the S2 specification first wrote the bar).
- **Matches:** the bottom of the interval is above **−6 points**, and it does not beat.
- **Worse:** the top of the interval is below zero.
- **Undecided:** anything else, published as "not shown to match".

**Why a margin of 6 points.** Without a margin, "the interval includes zero" would count as a
match, and a small or noisy test would always match. With about 390 paired cases the interval
is about ±4.3 points wide (the `dev-400` comparisons). If the loop were exactly as good as arm B,
the bottom would land above −5 only about 63% of the time, above −6 about 78%, and above −7
about 89% (estimates, normal arithmetic on that width). At 5 points a truly equal loop would be
marked "not shown to match" about one time in three. **What the margin costs:** on a score of
about 27%, it lets the loop get about one in five fewer cases right and still "match". The
margin was chosen after seeing `dev-400`, while Andy expected the two arms to be equal; that
expectation is registered as prediction 1 (§12). Every report prints the bottom of the
interval, so a reader can apply a stricter margin.

*Example*, from `dev-400` (seen): against arm B, noise-floor run b's top-1 difference is +1.0%
[−3.6%, +5.6%] and run a's is −1.0% [−5.3%, +3.3%]
(`docs/results/s3-armc-{b,a}-vs-s3-armb-full-dev.txt`). Under this rule both match; under a
5-point margin, run a would not. Chance alone sorts identical runs differently near the margin.

### 7.3 Failed cases

- **A guard refusal** (`leak: ...`) **removes the case from the comparison for both arms.** The
  refusal comes from our leakage guard protecting the test, not from the agent. The loop is
  offered the same documents arm B reads, so it can meet only a refusal arm B also meets, and it
  can avoid one by skipping the document. Counting that against arm B would hand the loop points
  for dodging the guard, which no live case needs: open cases have no analysis to leak.
- **Every other failure counts as wrong, in the arm where it happened** (decision 0136's
  reason): format or tool (`failed: <step>`), the round limit (`failed: rounds`) and the cap. For
  findings, a failed case scores zero when the NTSB flagged findings.
- **Where it applies:** every paired reading in S3.2, the ablations included.
- **Printed beside:** the "both answered" reading, on the cases both arms scored, as earlier
  stages reported.
- **The noise floor under the same rule.** A committed script reads the noise-floor pair under
  this rule (all 401 cases, guard refusals removed, other failures wrong), so the noise and the
  claim are measured alike.

The model's own abstain flag is scored as the reports already score it (counted wrong for
top-1), in both arms. The abstain threshold of §8.3 does not change the comparison.

*Expected:* S2.4's held-out arm B had 40 guard refusals (`docs/results/s24-bars.txt`); with about
360 cases left, the interval widens a little, to about ±4.5 points (estimate).

### 7.4 Warranted

**The loop is warranted** when it **beats** arm B at **equal or lower** cost, or **matches** it at
**lower** cost. Every other combination is "not warranted". This is 0121 item 5's test with §6
and §7.2's words filled in.

## 8. Calibration and abstain

### 8.1 The problem

At its answer the loop states a confidence. Across the two noise-floor runs it averaged about
0.62, but the answers were right on occurrence top-1 about 27% of the time, and the stated
number barely sorts right from wrong. Summing the two runs' bands (scripted,
`docs/results/s3-noise-floor-dev.txt`): stated below 0.4, right 28 of 128 (22%); 0.4 to 0.6, 36
of 153 (24%); 0.6 to 0.8, 95 of 349 (27%); 0.8 or above, 55 of 155 (35%). Decision 0126: code,
not the model, turns the stated number into the confidence shown.

### 8.2 The curve

- **A logistic curve** from stated confidence to the chance that the first occurrence code is
  right: two numbers, always rising.
- **Fitted on the noise-floor runs' scored answers**, both runs pooled (785 answers; a case the
  model abstained on is counted wrong, as top-1 counts it; failed and refused cases have no
  answer and are left out).
- **Frozen before any held-out run**: its two numbers are committed in a file the held-out
  reading loads, with the results file that printed them.
- *Example:* from the bands above, it would turn a stated 0.9 into about 0.35 and a stated 0.3
  into about 0.22 (estimate).
- **Ruled out:** a step curve (isotonic), which bends to noise (run b's bands dip, then rise);
  fixed bands, which jump at their edges.

### 8.3 The test on held-out (result 3)

- The loop's scored held-out answers are put in **three equal groups by fitted value** (low,
  middle, high).
- In each group, the **average fitted value** is compared with the **share actually right**.
- **Calibrated:** in every group, the average fitted value lies inside that group's interval for
  the share right. The three intervals are each at 98.3% (that is, 1 − 0.05/3), so that a
  perfectly calibrated curve fails by chance at most 1 time in 20 overall.
- *Why not "the average gap is under 5 points":* each group holds about 120 cases, and by chance
  alone a perfect curve shows a gap of about 4 points in a typical group (estimate), so such a
  rule fails it too often.
- **Reported, not tested:** how well the confidence sorts right from wrong, as the share right in
  the high group minus the low group, with its interval. A curve can be calibrated and still
  useless if it gives every case about the same number.

### 8.4 Abstain

- **The loop abstains when its fitted chance is below 16.4%**, the no-model baseline's top-1 on
  development (scripted, `docs/results/s1-baseline.txt`, its development fit, n=1000). In plain
  words: if a lookup table would do better than the agent on this case, the agent says it does
  not know.
- *Why a meaning and not an optimum:* S1 chose its threshold by maximising a penalised score and
  chose 0.95, which answered no case at all (scripted, `docs/results/s1-threshold.txt`).
- **Expected:** from the `dev-400` bands, fitted values may run from about 20% to 35%, so it may
  seldom fire (prediction 8). If it does not, that is a finding: the confidence cannot yet tell
  thin evidence from good.
- **On held-out it is reported on its own:** how often it fires, and the share right among
  answered and abstained cases. It is not applied to the arm comparison (§7.3).

## 9. The four results that count against the loop

0121 item 5 lists them. S3.2 makes each measurable.

### 9.1 Result 1 — a pipeline in disguise

"Arm C reads every offered document on most cases, **or** calls the coding tools in arm B's
fixed order on most cases."

- **Reads every offered document:** across the whole case, both read choices together, every
  document on offer (`AgentCall.offered`) was read. A case with nothing on offer leaves the
  count.
- **Calls the coding tools in arm B's fixed order:** the order in which the case first uses each
  coding tool is exactly `describe_codes`, `occurrence_usage`, `past_findings`, `suggest_codes`.
- **Most:** more than half of the cases counted.
- **Reported beside:** the same counts by fatal and non-fatal, and by docket size, so a reader
  sees where the loop does choose.

**Seen before registration (ad-hoc, from the noise-floor trails):** the loop read every offered
document on 225 and 220 of 379 cases (59% and 58%), and used arm B's exact order on 1 and 0
cases of about 395. So the first half probably holds on held-out; the second will not. Counting
only cases with at least two documents gives 166 and 161 of 319 (52% and 50%). That definition
was **not** chosen: choosing it after seeing these numbers would be choosing the rule that might
dodge the result. Where the loop chooses is already visible: it left 452 documents unread on 121
fatal cases, against 62 on 33 non-fatal cases (scripted, the `unread` line of
`docs/results/s3-armc-a-vs-s3-armb-full-dev.txt`).

### 9.2 Result 2 — cost

"Arm C matches arm B only at the same or greater cost." **Holds** when the loop does not beat arm
B on top-1 (§7.2) and its billed cost is equal or greater (§6).

### 9.3 Result 3 — calibration

"Arm C's code-fitted confidence is not calibrated on held-out." **Holds** when §8.3's test fails.

### 9.4 Result 4 — the stated effects: not shown on v1

"The effect the agent states for a document it reads does not agree with the change observed
after reading it more often than chance."

**It cannot be tested as written on v1.** The stated effects describe what a document may show;
they do not predict how the hypothesis will move. An ad-hoc look at 15 effects drawn at random
from a `dev-400` trail found none that names a code or a direction of change. Three typical
ones: "The pilot's account may establish what occurred during initial climb…"; "Toxicology may
identify impairment…"; "Weather report may establish wind, visibility, and conditions…". The
loop's instruction asks for an "expected effect" in free text (`DocumentDecision.expected_effect`),
and the model answers with a description.

**So result 4 is published as "not shown"**, which is not "passed". A committed script prints,
for the held-out loop run, how many stated effects name an occurrence code or category, as the
measure behind the statement. **The fix comes with the agent's next text change** (S3.3, with
the fingerprint of §4.2): a structured field such as *expected change: none / confirms / changes
the answer to …*, which a later stage can test against what changed.

**Ruled out:** a judge model labelling each effect, checked first against 40 of Andy's marks. It
costs cents and about an hour of marking; S2.7's judge failed such a check (32 of 46, 69.6%,
against 75%; `docs/results/s27-round0-dev.txt`, decision 0099); and if it passed, almost every
effect would come back "no claim", leaving too few to test.

## 10. How the results are read together

Andy decided on 2026-10-01 that no single result gives a blanket verdict, and that S3.2 states in
advance how they are read (0121 item 5). They answer two questions, separately.

**Question 1, is the loop warranted?** Decided by §7.4 alone. Results 1 and 2 say how that
outcome came about; they do not overturn it.

**Question 2, can the board's numbers and reasons be trusted?** Results 3 and 4. They do not
change question 1; they decide what the board may show:

- if result 3 holds (not calibrated), the board shows its confidence with a plain warning;
- while result 4 is "not shown", the board labels a stated effect "the agent's note", never a
  prediction.

**The headline is one of these sentences, written now:**

- "On held-out cases, the loop beat the fixed pipeline at equal or lower cost." (warranted)
- "On held-out cases, the loop matched the fixed pipeline at lower cost." (warranted)
- "On held-out cases, the loop was not shown to improve on the fixed pipeline: it [matched it at
  equal or greater cost / beat it only at greater cost / was worse / was undecided]." (not
  warranted)

Results 1 to 4 follow, one line each, as they came out.

**Where any saving comes from.** If the verdict rests on cost, the report says how much of the
loop's saving comes from reading less and how much from cache discounts. A committed script
splits it from the token counts every run records: the difference in computed cost between the
arms is the work done; the difference between computed and billed within each arm is the
discount. *Why:* on `dev-400` the loop was cheaper only on the bill and did about twice arm B's
work at list price. A critic could fairly say that is good engineering rather than good
choosing, since a fixed pipeline built as one cached conversation might earn the same discount.

**The likely case, worked through** (if held-out looks like `dev-400`): "matched the fixed
pipeline at lower cost" (warranted); result 1 holds, mostly on small dockets, with its choosing
on large fatal ones; the saving is mainly cache discounts; result 3 as measured; result 4 not
shown. An honest, mixed result, and the page explains each part.

## 11. The ablations, read

- **Without coding tools (`dev-400`):** paired against each noise-floor run, under §7.3's
  failure rule; top-1, top-3 and finding recall@10. It is a development reading, with
  prediction 6.
- **Without the docket (held-out):** paired against the held-out loop run, under §7.3's rule. It
  is CLAUDE.md goal 2's ablation, with prediction 5. The loop without the docket still has its
  coding tools, so the size of the loss is an open question, not the fact of it.
- **Arm A (held-out):** printed with its interval as the start-facts-only score; it decides
  nothing.

## 12. The predictions

Registered in `docs/rounds/s3-registration.md` before any S3.2 run, each scored "met" or "not met"
and published either way. They were written after the `dev-400` readings were seen (§13); most
say "held-out will look like development", which can still fail. The rules of §6 to §9 apply.

**Accuracy and cost, on held-out, the loop against arm B:**

1. **Top-1:** the loop matches but does not beat arm B: the interval's bottom is above −6, and
   the interval is not wholly above zero. (Andy's stated expectation.)
2. **Cost:** the loop's billed cost is more than 10% below arm B's.
3. **Top-3:** the loop is below arm B, the interval wholly below zero.
4. **Findings (recall@10, flagged):** level, the interval including zero.

**The ablations:**

5. **Without the docket (held-out):** the loop loses at least 10 points of top-1: the paired
   difference (without minus with) is −10.0 points or lower. S2.4 found that reading the docket
   added +14.3% [+9.2%, +19.3%] to arm B's top-1 on held-out (scripted,
   `docs/results/s24-bars.txt`); the loop without its docket keeps its coding tools, which may
   win some of that back.
6. **Without coding tools (`dev-400`):** the loop is worse on top-1 than each noise-floor run, each
   interval wholly below zero. Arm B's coding step added +6.8% [+4.0%, +9.8%] to S2.7's answer
   (scripted, `docs/results/s3-armb-tools-vs-s27-armb-answer-dev.txt`).

**Behaviour and trust, on held-out:**

7. **Result 1:** the loop reads every offered document on more than half of the cases counted,
   and uses arm B's exact tool order on fewer than 5%.
8. **Calibration** passes §8.3's test, and **the abstain threshold fires on fewer than 5%** of the
   loop's scored cases.
9. **Format:** at most 8 of the 400 cases fail for format or tool reasons in the held-out loop
   run (S3.1's gate, 0130 item 5, counted as `scripts/s3_noise_floor.py` counts it).

**Not predicted:** the level of top-1. The held-out years (2020 to 2023) may run a few points
apart from development.

## 13. Disclosures

The registration file states, before any S3.2 run, that each of these was seen or chosen before
the predictions were written:

- **The learning probe** (pull request #18; 20 `dev-400` cases, twice), disclosed in 0121.
- **The noise-floor runs** and their accuracy (`docs/results/s3-noise-floor-dev.txt`).
- **The six comparisons of the loop with arm B on `dev-400`** (`docs/results/s3-armc-*`):
  against S3's full arm B, top-1 −1.0% [−5.3%, +3.3%] and +1.0% [−3.6%, +5.6%], top-3 −11.4%
  [−16.0%, −6.9%] and −12.8% [−17.9%, −8.2%], finding recall@10 +0.4% [−2.0%, +2.9%] and −1.5%
  [−3.9%, +0.6%] (the S3 specification's As-built, Departures, §10.5).
- **The ordering diagnostic** on the loop (`docs/results/s3-check-diagnostic-dev.txt`, 0137) and
  **Task 15's probes** (the S3 specification's As-built, Task 15).
- **This session's ad-hoc counts:** read-everything 225 and 220 of 379; fixed order 1 and 0; the
  dearest case $0.089 and $0.1055 computed; 15 stated effects read.
- **Rules chosen after seeing `dev-400`:** the billed-cost measure (§6), the 6-point margin (§7.2),
  and the result 1 definitions (§9.1).
- **The guidance files' overlap** with `dev-seal-s3-400` (0129 item 6): their counts come from a
  pool that held its cases. The sample is unused in S3.2 (§3).

## 14. Order of work

1. **The recorder re-check at 14 distinct nights** (about 6 October 2026; the S3 specification §9,
   decision 0123), with the same script (`make recorder-report`), its results file committed. If
   no docket has been seen to arrive before closure, S3.2 measures the full condition only and
   says so. If one has, the staged replay is reopened as a decision before the registration.
   It is free, and it falls inside the time the build takes.
2. **Build and free work** (§4.3; §5's check; §7.3's noise reading; §8.2's fit; the scripts of
   §9.1, §9.4, §10 and §15). No paid call.
3. **The registration**, `docs/rounds/s3-registration.md`: the five runs exactly, the frozen
   loop's version, the cap, the rules, the nine predictions and the disclosures. Committed before
   any S3.2 run.
4. **Run 1: the coding ablation on `dev-400`** (about 3 hours). It also shows the fixed code on a
   full run before anything touches held-out.
5. **Held-out, one command at a time, each ledger row committed before the next** (the
   dirty-tree guard refuses otherwise; 0026): arm A; arm B's answer; its tool post-pass; its
   ordering check; the loop; the loop without the docket. Six commands, each its own `make`
   target. Batches are sent between 01:00 and 12:00 UTC, when the provider's queue is quick.
6. **The results script and the write-up**, then the close-out.

**Paid runs are made by Andy**, in his terminal, from a separate clean checkout reset to the
branch tip before each run, with the API keys read from `pass` inside the run script and never
printed. The plan sets this up and states, for each command, the environment it needs
(`NTSB_DATA_DIR`), its expected duration, and what the tree looks like afterwards.

## 15. Results files and reports

Proposed names; the plan fixes them:

- `docs/results/s32-cap-check-dev.txt`: §5's count of coding cut short at $0.15.
- `docs/results/s32-noise-0136-dev.txt`: the noise pair under §7.3's rule.
- `docs/results/s32-calibration-dev.txt` and a committed curve file: §8.2's fit.
- `docs/results/s32-coding-ablation-dev.txt`: run 1 against each noise-floor run.
- `docs/results/s32-claims-heldout.txt`: the verdict (§7.4), the cost reading (§6) and saving
  split (§10), the four results (§9), calibration and abstain (§8.3, §8.4), the no-docket
  ablation, arm A, and the nine predictions scored. Every figure from a committed script.
- `docs/results/heldout-ledger.md`: six new rows.

## 16. Decisions S3.2 takes

Written in the plan's first task, numbered from 141 on in this order:

1. S3.2's five runs; the `dev-400` readings reused; the sealed sample stays sealed for
   v2 (amends 0129 items 2 and 3, and the places of 0127 item 5's ablations). *Session:* the run
   list, option A cut to five.
2. "Frozen" means an unchanged prompt version, held by a test; the carried issues fixed
   and left; arm B's later parts accept one held-out run. *Session:* frozen, option A.
3. The fingerprint should cover what the agent receives; built in S3.3, before S4 (it
   amends 0133 when built). *Session:* Andy's view; option 2.
4. One per-case cap, $0.30, for every arm and part. *Session:* the cap, option A.
5. Equal cost: billed for both arms, with a 10% band. *Session:* equal cost, option A.
6. The headline test: top-1 decides; beats, and matches with a 6-point margin; how failed
   cases count. *Session:* the margin; failed cases, option A.
7. Calibration: a logistic curve and the three-group test; abstain below the no-model
   baseline. *Session:* calibration; abstain, option A.
8. Results 1 and 4 made measurable; result 4 is "not shown" on v1. *Session:* the plain
   definitions; result 4, option A.
9. How the results are read together, with the saving's source. *Session:* the reading.
10. S3.2's share of S3's line: $12. *Session:* spend.

## 17. Spend

- **S3.2's share of S3's $50 line is $12**, about twice the estimate of §3. It is counted by commit
  on `s3-` branches (`scripts/stage_spend.py --stage s3`, decisions 0128 and 0135): S3.2's share
  is the line's total less the $5.11 S3.1 spent. If a re-estimate passes it, work stops and Andy
  decides (0083 item 2). That leaves over $30 of the line for S3.3, whose first pass is estimated
  at about $7.50.
- Each run reserves its computed cost when it starts and releases it when it ends: the held-out
  loop run reserves about $4.60 (estimate, the noise-floor runs' computed cost). The monthly guard
  ($40, 0083) has room for one run at a time.

## 18. Tests and continuous integration

S3.2 adds tests that:

- the loop's prompt version is `s3-v1+ge17fecdc66ec+p947fac1c86a4`;
- a resumed round sends again a call that has no reply, and costs its case no attempt; a round
  whose replies are all on disk continues when the provider reports it cancelled;
- a report refuses an unreadable `spec.json`;
- `month_spent` counts a dead round that reported a cost; each call's temperature is the one
  set;
- arm B's tool post-pass and ordering check refuse a held-out run before the registration is
  committed, and with an uncommitted tree; accept it after; append one ledger row each; and
  refuse a second post-pass or check on the same held-out run;
- `dev-seal-s3-400` is refused by every command after `docs/rounds/s3-registration.md` is
  committed, and until `docs/rounds/s3-sealed.md` is;
- every S3.2 `make` target passes `--cap-usd 0.30`;
- each S3.2 scoring script applies §7.3's failure rule, §6's band, §7.2's outcomes and §8.3's
  test, on made-up cases whose answers are known, and refuses a held-out run outside the ones
  the registration names.

## 19. Done means (S3.2)

1. The recorder re-check is committed, and its outcome applied (§14 item 1).
2. The fixes and new work of §4.3 are built, with the tests of §18; the prompt-version test
   passes at every commit.
3. The calibration curve and the free readings of §5 and §7.3 are committed before the
   registration.
4. `docs/rounds/s3-registration.md` is committed before any S3.2 run.
5. The five runs complete; the held-out ledger holds six new rows, each committed before the next
   held-out command.
6. `docs/results/s32-claims-heldout.txt` and `docs/results/s32-coding-ablation-dev.txt` are
   committed, from scripts, with the verdict, the four results, the reading and the nine
   predictions scored, whichever way they came out.
7. `make check` passes.
8. The As-built record is appended to this document, the plan deleted, and the version set to
   0.9.0 (0017); the pull request is titled `S3.2: the claims` and merged with a merge commit
   (0033).

## 20. Not in S3.2

- Any change to the loop's text, tools or steps (§4.1); tuning.
- The sealed sample (§3).
- The `suggest_codes` ablation and a `dev-400` no-docket run (§3).
- The rendered-text fingerprint and the structured expected effect (S3.3, §4.2, §9.4).
- Transcription as a tool; the model axis; the precedent tool (v2, after S4).

## 21. Risks

- **A held-out run is lost or interrupted.** §4.3's fixes make a resume exact. A batch the
  provider loses is sent again once on resume (S3.1, Task 9). If a held-out run cannot be
  completed, it is recorded in the ledger as aborted, and Andy decides whether it is re-run
  fresh, as in S2.4.
- **The cap check finds coding cut short at $0.15** (§5): the cap comes back to Andy before any
  run.
- **Arm B's held-out opening needs `agent/armb.py`** (§4.3 item 5): work stops and Andy decides.
- **The recorder shows a docket before closure** (§14 item 1): the replay is reopened as a
  decision before the registration.
- **Held-out costs more than estimated**, for example from larger fatal dockets: the share's stop
  (§17) applies.
- **The result is mixed or negative.** It is published as it stands; §10's sentences are written
  for every outcome.

## Glossary

- **Ablation:** the loop with one part removed, to measure what that part adds.
- **Abstain:** the agent declines to answer. Here, when its fitted chance is below the no-model
  baseline's.
- **Arm:** one way of answering, compared on the same cases. A is start facts only; B is the fixed
  pipeline; C is the loop.
- **Billed cost:** what the provider charged; cached prompt tokens are billed at a lower rate.
- **Cache discount:** the provider charges less for the start of a prompt it has seen recently.
- **Calibrated:** when the board shows 30%, the answer is right about 30% of the time.
- **Computed cost:** every token priced at the list rate, ignoring the cache discount.
- **Fingerprint (`+p`):** a short code computed from the files that build the text the model sees;
  an unchanged code means unchanged text.
- **Frozen:** the model sees exactly the same text as in the noise-floor runs.
- **Guard refusal:** the leakage guard blocks a document holding words from the NTSB's own
  conclusions.
- **Held-out:** cases from 2020 to 2023, used rarely and recorded in a ledger.
- **Interval (95%):** the span the true difference very likely lies in, given the number of cases.
- **Ledger row:** the line recording each held-out run, committed before the next.
- **Logistic curve:** a smooth S-shaped curve fixed by two numbers.
- **Margin:** how much worse the loop may be and still "match" arm B.
- **No-model baseline:** a lookup rule using only basic case facts, with no AI model.
- **Noise floor:** how much two identical runs differ by chance alone.
- **Paired difference:** both arms scored on the same cases; the mean gap, with its interval.
- **Registration:** the rules and predictions, committed before the run they govern.
- **Sealed sample:** cases set aside, unread and unscored, until one final check.
- **Stated effect:** the agent's one-line reason for reading a document.
- **Warranted:** the loop beats arm B at equal or lower cost, or matches it at lower cost.
