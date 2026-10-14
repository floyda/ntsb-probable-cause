# S5 step 4b — The Path page's last figures: implementation plan

**Spec:** docs/specs/2026-10-04-s5-public-site-design.md

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (Andy's choice for S5: Claude runs the tasks in the session, one fresh review at the end). Steps use checkbox (`- [ ]`) syntax. Tick a step in the same commit as its code (decision 0017). Log every departure in **Deviations**. Tasks marked **Controller** need Andy.

**Goal:** Step 4 left three of §7.4's figures and one rerun for later, because each needs a new script. This step builds them:

- **Question 1:** one closed, non-fatal development case as the NTSB published it: its cause and its codes.
- **Question 5:** the misses rerun on S3's fixed pipeline (§7.4, "rerun on S3's runs"; Andy, 2026-10-14).
- **Question 6:** one cause sentence the NTSB used word for word on many cases, with the different first codes those cases received.
- **Question 7:** each case's belief before reading and at the answer, against the NTSB's first code.

No model call is made, and nothing is paid for. Every figure follows step 4's rule: a script writes it from committed or local data, the site reads it by key, and a test fails when the committed file is stale.

## Choices for Andy before execution

Each is set out with its trade-off. I will take them one at a time in the chat. The recommended option is first.

1. **Question 1's case.** Nine development records are committed as test fixtures (`tests/fixtures/records/`), already redacted of owner and operator by `scripts/make_fixture.py` (decision 0015). Taking the case from a fixture means the site never reads raw data for it.
   - **(Recommended)** `ANC09CA020`: no injuries; the cause is "The pilot's misidentification of the runway surface during landing", with a contributing factor. It is the case whose final-report link was verified in step 2.
   - Another non-fatal fixture: `ANC09CA024` (a ground loop), `ANC09CA027` (an unsuitable landing area), `ANC09LA022`, `ANC10LA044` or `CEN11CA664`.
   - **Why non-fatal:** §7.4 says a non-fatal case keeps the first example gentle.
2. **Question 5's framing.** S2.6's figure is the measurement that led to coding guidance and the ordering check. A rerun on S3's fixed pipeline shows the misses that remain after those changes. The two answer different questions.
   - **(Recommended)** Keep S2.6's figure as the answer (the Path is a history of decisions), and add one line and a second table: "after the guidance and the check, on S3's fixed pipeline: …".
   - Replace S2.6's figure with S3's. The page is then current, but it loses the measurement that justified the decision.
3. **Question 6's sentence.** The rule that picks the sentence must be fixed before the script looks at the data. Otherwise the page could show the most dramatic group and call it typical.
   - The largest group of cases that share an identical probable-cause sentence, in S3's statistics pool (development only). If two groups tie, the one whose sentence sorts first.
   - The group with the most different first codes. It is more striking, but it is chosen for being striking.
4. **Question 7's source.** Decision 0153 fixed the held-out diagnosis's six breakdowns before any was read, and "prints those six and no others". A new reading of S3.2's held-out trails needs its own decision record first.
   - **(Recommended)** Draw the figure from counts already committed in `docs/results/s32-heldout-diagnosis.txt`. Before reading: 43 of 394 cases right. At the answer: 94 of 394. From the first to the second, 60 fixed and 9 broken. Of those, the coding step fixed 20 and broke 7. This needs no new held-out reading. It shows "before reading" and "the answer" but not "after reading" as its own checkpoint.
   - A new counts-only reading with three checkpoints (before reading, after the last read choice, the answer) and every transition between them. A decision record, registered before the script runs, would name the breakdowns. This gives the figure §7.4 describes, but adds a decision and a second reading of a used held-out sample.

## Global Constraints

- **The step 1–4 constraints hold.** Every number on a page comes from the numbers file by key. Every paired figure carries its cases. Every worded claim is a guard in `lib/claims.ts`. Billed costs only.
- **Development and held-out never share a figure** (§9). Questions 1, 5 and 6 are development. Question 7 is held-out.
- **Counts only for exploratory readings** (decision 0024, 0059): no case number and no model text. Question 1's case is the exception: §7.4 publishes one development case on purpose, from a redacted fixture.
- **No victim names** (rule 6). Question 1's cause and question 6's sentence are NTSB text. A test fails if either holds a capitalised word that is not at the start of a sentence and not on a short allow list ("NTSB", aircraft and part names found in the code tables). Andy reads both before they are committed (Task 6).
- **Clinical tone.** Question 7's figure can go either way, and its words say what it shows without praise or blame.

## Review Focus

1. **Question 1's text on the page is the fixture's, word for word,** and every code's label comes from the project's code tables, not from typing.
2. **Question 6's rule was fixed before the data was read.** The script prints the rule first, and its output does not depend on the order of rows.
3. **Question 7's figure adds up.** If choice 4's first option is taken: 43 + 60 − 9 = 94. A build-time guard fails when the committed counts stop adding up.
4. **Question 5's rerun reads a development run only.** `scripts/occurrence_misses.py` already refuses held-out runs. The rerun must name the derived run (`…-tools-check-luna`) that is S3's full fixed pipeline.

## File map

| file | responsibility |
|---|---|
| `scripts/site_example_case.py`, `tests/test_site_example_case.py`, `site/data/example-case.json` | question 1's case from a fixture (Task 1) |
| `docs/results/s5-occurrence-misses-s3-dev.txt` | question 5's rerun, written by `scripts/occurrence_misses.py` (Task 2) |
| `scripts/exploratory/s5_one_sentence.py`, `docs/results/s5-one-sentence-dev.txt` | question 6's sentence and its first codes (Task 3) |
| `scripts/site_numbers.py`, `site/data/numbers.json` | new entries and lists; format `site-numbers/2` adds `texts` for question 6's sentence (Tasks 2–4) |
| `site/src/components/ExampleCase.astro`, `FirstCodes.astro`, `BeliefPath.astro` | the three figures (Tasks 1, 3, 4) |
| `docs/decisions/0186-…`, `scripts/exploratory/s5_belief_path.py`, `docs/results/s5-belief-path-heldout.txt` | question 7's reading (Task 4, choice 4 B) |
| `site/src/pages/path.astro`, `site/src/lib/claims.ts`, `site/tests/dist.test.ts` | the stops, guards and checks (Task 5) |

---

## Task 1: Question 1's case

- [x] **Step 1: Failing tests** in `tests/test_site_example_case.py`:
  - the written file holds the fixture's probable cause word for word, its event date, and its occurrence codes in the NTSB's order, each with its table label;
  - its findings are listed with whether each is in the probable cause;
  - the case is development split and non-fatal, or the script refuses it;
  - the names check: no capitalised word outside a sentence start and the allow list;
  - the committed `site/data/example-case.json` is current.
- [x] **Step 2: The script.** `scripts/site_example_case.py --case <number>` reads `tests/fixtures/records/<number>.json` through the project's record parsing (never a second assembler, rule 1), labels codes from the code tables, and writes `site/data/example-case.json`. Status paragraph (decision 0059): free, offline, reads one committed fixture.
- [x] **Step 3: `ExampleCase.astro`.** The case number linked to its NTSB final report (`caseReportUrl`), the date, "no injuries", the cause, the occurrence codes in order (event words first, the full label in small type, as on the board), and the findings in two groups: in the probable cause, and other findings.
- [x] **Step 4:** `make check`; commit `S5 step 4b Task 1: question 1's case, from a committed fixture`.

## Task 2: Question 5's rerun

- [x] **Step 1:** Run `uv run python -m scripts.occurrence_misses --run 20260929T053953-674c92e-dev-400-B-tools-check-luna --out docs/results/s5-occurrence-misses-s3-dev.txt`, with `NTSB_DATA_DIR` pointed at the main checkout's `data/`. If the script does not read a derived run, extend it with a test, and log the extension.
- [x] **Step 2:** Entries `q5.s3.first_right`, `q5.s3.in_sequence` and list `q5.s3.pairs` in `site_numbers.py`, with tests.
- [x] **Step 3:** Commit `S5 step 4b Task 2: question 5's misses rerun on S3's fixed pipeline`.

## Task 3: Question 6's sentence

- [x] **Step 1:** The rule from choice 3 is written into the script's docstring and printed at the top of its output, in a commit before the script first runs.
- [x] **Step 2: Failing tests** over a small invented pool: the rule picks the right group; ties are broken by the sentence's sort order; row order does not change the output; held-out rows are refused.
- [x] **Step 3: The script.** `scripts/exploratory/s5_one_sentence.py` reuses `s3_coding_consistency.py`'s exact-twin grouping over S3's statistics pool. It writes the sentence, the group's size and each first code with its label and count, most common first. Counts only, with no case number.
- [x] **Step 4:** Run it (free, offline) to write `docs/results/s5-one-sentence-dev.txt`. Add `q6.sentence` (a text), `q6.group` (a count) and list `q6.codes` to the numbers file.
- [x] **Step 5: `FirstCodes.astro`.** The sentence in quotation marks, then one bar per first code, sized by count, with the counts in a table. The page repeats the results file's own caution.
- [x] **Step 6:** `make check`; commit `S5 step 4b Task 3: question 6's sentence and its first codes`.

## Task 4: Question 7's figure

Built to choice 4's answer. The first option is described here; the second adds a decision record and an exploratory script, and is planned in Deviations if chosen.

- [ ] **Step 1:** Entries from `s32-heldout-diagnosis.txt`: `q7.h0_right` (43 of 394), `q7.answer_right` (94 of 394), `q7.h0_answer.fixes` (60), `q7.h0_answer.breaks` (9), `q7.coding.fixes` (20), `q7.coding.breaks` (7), with tests.
- [ ] **Step 2: A guard** in `claims.ts`: before-reading right + fixes − breaks = answer right. It is tested to fail when a count moves.
- [ ] **Step 3: `BeliefPath.astro`.** Two columns, "before reading" and "the answer", each split into cases that matched the NTSB's first code and cases that did not. The fixed and broken cases are drawn between them, with the coding step's share named. The same counts are in a table. Its sentence states the counts, with no claim beyond them.
- [ ] **Step 4:** Commit `S5 step 4b Task 4: question 7's figure from the committed diagnosis`.

## Task 5: The stops and checks

- [x] **Step 1:** `path.astro`: question 1 gains `ExampleCase`, question 5 the line and table from choice 2, question 6 `FirstCodes` and question 7 `BeliefPath`. Each stop's sources list its new results file and script.
- [x] **Step 2:** `dist.test.ts`: the new entries appear in their formats; question 1's cause is on the page word for word; the page holds no case number other than question 1's.
- [x] **Step 3:** `make check`; commit `S5 step 4b Task 5: the figures on the Path page`.

## Task 6: Preview (Controller)

- [x] **Step 1:** Andy reads question 1's cause and question 6's sentence for names before anything is pushed.
- [x] **Step 2:** Phone and desktop screenshots, light and dark, with the choices for his eye.
- [ ] **Step 3:** Record his answers; run the final review and its fix pass; push.

---

## Deviations

- **Andy's choices (2026-10-14):**
  1. Question 1's case is `ANC09CA020`.
  2. Question 5: keep S2.6's figure and add S3's rerun ("keep the history and add S3").
  3. Question 6: **B**, the sentence whose cases received the most different first codes, "as it proves the point". Ties go to the group with more cases, then to the sentence that sorts first. The figure says plainly how it was chosen ("This is the sentence whose cases received the most different first codes. Across all repeated sentences, the first code matched in about one case in three."), so it is never passed off as typical.
  4. Question 7: **B**, a new counts-only reading with three checkpoints, recorded first as decision 0186. S4 reserved four numbers for S5, from 0186, so there is no clash at merge. Task 4 is rewritten below.
- **Task 4, rewritten for choice 4 B:**
  - [x] Step 1: decision 0186 is committed before the script exists (`401e384`).
  - [x] Step 2: failing tests over invented trails, covering the checkpoints, the cases left out and the cross-check against the diagnosis's committed counts.
  - [x] Step 3: `scripts/exploratory/s5_belief_path.py` reuses `s32_heldout_diagnosis.py`'s `loop_cases`, `hypothesis_top1`, `answer_point` and `transition`. It reads through the same held-out path and refusals.
  - [x] Step 4: one run from a clean commit writes `docs/results/s5-belief-path-heldout.txt`, committed alone.
  - [x] Step 5: its entries go in the numbers file. The claims guard checks that before + fixed − broken = after for each move.
  - [x] Step 6: `BeliefPath.astro` draws three columns, before reading, after reading and the answer, with the moves between them.

## Glossary

- **Fixture:** a real development record committed to the repository for tests, with owner and operator fields removed (decision 0015).
- **Exact twins:** cases whose NTSB probable-cause sentences are the same word for word, ignoring case and punctuation (`s3-coding-consistency-dev.txt`).
- **First code:** the NTSB's first occurrence code for a case, its defining event; the one the headline scores.
- **Fixed / broken:** a case whose first code went from not matching the NTSB's to matching it (fixed), or the other way round (broken), between two of the agent's beliefs.
- **Derived run:** a run folder made by a post-pass over an earlier run (`-tools`, `-check-luna`); S3's full fixed pipeline is the run ending `-tools-check-luna`.
- **Task 1 (2026-10-14):**
  - Labels follow S4's board rule (`live/board.py` on S4's branch, not yet merged): an occurrence is "phase / event" and a finding "item - modifier", so question 1 reads like the board. The rule is repeated in the script, with a comment pointing to S4's code.
  - The names check allows only "NTSB", "FAA", "VFR", "IFR", "VMC" and "IMC" mid-sentence. The plan's "aircraft and part names from the code tables" was not needed for this cause.
  - `make site-example-case` regenerates the file.
  - The dist test also checks that the page names no case number except question 1's and the board's own closed cases in question 8's strip.
- **Task 2 (2026-10-14):**
  - `occurrence_misses.py` read the derived run unchanged; no extension was needed.
  - On S3's fixed pipeline, the first guess was the NTSB's first code in 110 of 399 cases (S2.6: 88) and in its sequence in 148 of 399 (S2.6: 140). The commonest misses now run both ways between stall/spin and loss of control (14 and 11).
  - The review's tie rule (keep every pair tied with the fifth) shows nine rows for S3, because five pairs have 6 cases each. Both tables are drawn by one component, `MissPairs.astro`.
  - The page adds one line of counts and no claim about them.
- **Task 3 (2026-10-14):**
  - The rule and its tests were committed (`37f3459`) before the one run.
  - The rule chose "A loss of engine power for undetermined reasons.": 33 cases with 18 different first codes, out of 374 exact-twin groups. The codes differ mostly by phase of flight and by total against partial power, which the sentence does not state. The page's caution ("the same sentence can follow accidents whose sequences of events differ") covers this, and it is raised for Andy's preview.
  - The numbers file moves to format `site-numbers/2`, adding `texts` for the sentence.
  - `q6.one.distinct` (18) and `q6.one.cases` (33) are two plain counts. A count with an `n` reads as "18 of 33", which would be wrong here.
  - The build refuses the file unless the codes' counts add up to the cases and their number equals the distinct count.
- **Task 4 (2026-10-14):**
  - Decision 0186's one reading ran from the clean commit `bfcc8fa`, and its result was committed alone (`2c70cf5`). It agreed with the diagnosis's committed figures.
  - Of 394 answered cases, right before reading 43, after reading 82, at the answer 94. Reading fixed 47 and broke 8; the coding step fixed 20 and broke 8. 25 cases recorded no belief after a read choice.
  - The coding step's 8 broken, against the diagnosis's 7, counts right and wrong alone. It includes the diagnosis's one "score changed with the first code kept" case. The cross-check uses the diagnosis's own count (a change of first code), which agrees.
  - Each count is its own numbers-file entry. A guard in `claims.ts` (`q7.path_adds_up`) fails the build unless each move carries one checkpoint's count to the next over every case. It is tested to fail when a count moves.
  - The figure is three bars, one per checkpoint, each of all 394 cases with the right ones dark, and each step's fixed and broken counts between them. Hidden tables carry the same counts.
- **Task 5:** built along the way in Tasks 1 to 4, as each figure's checks went in with it: question 1's cause word for word, no other case number, question 6's sentence and codes, and every new entry on the page in its format.
- **Task 6, names check (Andy, 2026-10-14):** question 1's cause and question 6's sentence are clear of names.
- **Task 6, preview choices (Andy, 2026-10-14):**
  1. Question 1 stays exact: the NTSB's finding labels as published (A).
  2. Question 5 keeps both tables, S3's nine rows included; it may be shortened later (A).
  3. Question 6 shows "the top 50%": the commonest first codes until they cover at least half the sentence's cases, keeping any code tied with the last one shown. That is 5 codes, covering 17 of 33 cases. The other 13 codes, covering 16 cases, sit behind a disclosure, "And 13 more codes, across the other 16 cases", so nothing is removed from the page. The rule is `lib/first-codes.ts`, tested, and both tables are `FirstCodesTable.astro` on one scale.
  4. Question 7 keeps its figure and adds one line (A): "This shows the loop improving as it works. It does not compare the loop with the fixed pipeline: against that, the loop was −9.5 points [−14.0, −5.2] on 400 cases, as above." "Improving" is the guarded claim `q7.path_improves` (before < after < the answer), tested to fail.
