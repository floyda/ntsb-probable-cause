# S5 step 6b — The first page as a route: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (Andy's choice for S5: Claude runs the tasks in the session, one fresh review at the end). Steps use checkbox (`- [ ]`) syntax. Tick a step in the same commit as its code (decision 0017). Log every departure in **Deviations**. Tasks marked **Controller** need Andy.

**Goal:** The first page becomes the full three-minute route of §3.1. Today it ends after the opened case. It gains three stops:
- **4. Its trail:** the case's beliefs as four blocks, with what was read between them.
- **5. Was a loop needed?:** the ladder and its sentence.
- **6. The path taken:** the eight questions, each with a one-line answer.

It also gains the arrival motion §3.1 describes, and its rail names all six stops.

**Architecture:**
- **The trail strip lives inside the opened case's article.** When a reader taps a board row, `scripts/open-row.ts` swaps that article in, so the strip changes with it. The case page shows the strip too.
- **The ladder stop reuses `Ladder.astro`,** with its sentence.
- **The questions stop reads one-line answers from `lib/route.ts`.** Each answer that makes a claim is a guard in `lib/claims.ts`, so a re-run that changes a result stops the build.
- **The motion is one small self-hosted script, `scripts/arrive.ts`.** It hides nothing until it has seen the reader scroll. With reduced motion or with scripts off, nothing moves.

**Tech Stack:** Astro 7, TypeScript strict, Vitest over the built pages, Playwright with axe.

**Spec:** docs/specs/2026-10-04-s5-public-site-design.md

The design is §3.1 (the six stops, motion and its four limits), §6 (beliefs), §7.1 (the ladder), §7.2 (the eight answers) and the §21 note of 2026-10-16 (6b).

## Choices for Andy before execution

I will take them one at a time in the chat. The recommended option is first.

1. **The eight one-line answers.** §21's note says you read them before they go in. My draft, from the Path's measured answers. Numbers come from the numbers file; the words in brackets are guards that stop the build if a re-run makes them untrue:
   1. Is there an answer key nobody had to write? **Yes. The NTSB codes every closed case.**
   2. Is the case record enough? **No. Alone, it did no better than guessing.** (`q2.no_better_than_guessing`)
   3. Does reading the docket help? **Yes. It is the largest gain on the ladder.**
   4. Does reading words in scanned pages help? **Not shown to help, and costly, so it is paused.** (`q4.not_shown_to_help`)
   5. Are the misses about evidence or about coding? **Mostly the NTSB's coding order.**
   6. How consistent is the answer key itself? **Not fully: cases with the same cause sentence share a first code in about one case in three.** (the rate from `q6.twins`, worded by `oneIn`, which refuses a rate more than 20% from one in three)
   7. Does choosing what to read beat reading everything? **No. The loop was worse than the fixed pipeline, at about the same bill.** (`q7.loop_worse`, `q7.same_bill`)
   8. Does it hold on newly closed cases? **The board above answers this in public.**
2. **How much motion.** §3.1 lists four kinds:
   - a stop rising into place;
   - the board's rows turning over one after another;
   - the ladder's bars growing from the left;
   - the trail's beliefs and the questions appearing in sequence.

   The options:
   - **(Recommended) All four, as the spec has them,** within §3.1's limits: once only, under about a second, never a loop, nothing on a reduced-motion setting.
   - **Stops rising only.** Quicker to build and test, but plainer.

Decided here; each can change at the preview:
- **Stops 3 and 4 show the newest closed case that has a trail.** Today stop 3 shows the newest case. When that one has no trail (not coded, or abstained without one), the newest case that has a trail is shown instead.
- **The trail strip's four blocks:** before reading, after reading (the last belief after a read choice), after coding, and the answer. Each block shows its first code's event words and whether it was the NTSB's first code. Between the blocks: "read 3 of 5 documents", and "4 coding look-ups". The strip links to the full trail.
- **The rail's six labels:** "1 · The question", "2 · Closed cases", "3 · One case", "4 · Its trail", "5 · Was a loop needed?", "6 · The path taken".

## Global Constraints

- **The step 1–6a constraints hold.**
  - Every number comes from the numbers file or the export, by key.
  - Every worded claim is a guard in `lib/claims.ts`.
  - Development, held-out and live never share a figure: stop 5 is held-out, the board is live, and they are separate stops.
  - CSP `default-src 'self'`: no inline script or style.
- **Motion limits (§3.1):**
  - once only, under about a second, never a loop;
  - the reader keeps control of the scroll, and nothing pins or moves the page;
  - reduced motion or no script shows everything at once;
  - the page is complete before any script runs, and content is hidden only after a script has seen the reader scroll;
  - motion never marks a result as good or bad.
- **Clinical tone, no names** (rule 6). The strip shows codes and counts only, never the agent's account of the evidence (§6 note of 2026-10-14).
- **WCAG 2.2 AA** on every page, in light, dark and phone.

## Review Focus

1. **A whole-page capture, or a page read without scrolling, shows every stop** (§3.1). A Playwright test takes a full-page screenshot right after load and finds every stop's text present and visible.
2. **Reduced motion:** with `prefers-reduced-motion: reduce`, nothing has a transition, and nothing starts hidden.
3. **A tapped board row updates stops 3 and 4 together,** and the rail's "4 · Its trail" still lands on the new strip.
4. **The newest case has no trail.** The page falls back to the newest one that has a trail. With none in the export, stop 4 is left out and so is its rail place.
5. **The one-line answers stay true:** each guarded answer is tested to stop the build when its figure moves.

## File map

| file | responsibility |
|---|---|
| `site/src/lib/route.ts`, `route.test.ts` | the chosen case; the strip's four blocks; the eight one-line answers |
| `site/src/lib/claims.ts`, `claims.test.ts` | the answers' guards |
| `site/src/components/TrailStrip.astro` | stop 4, inside the opened case's article |
| `site/src/components/RouteQuestions.astro` | stop 6 |
| `site/src/pages/index.astro` | stops 4–6 and the six places |
| `site/src/scripts/arrive.ts` | the arrival motion |
| `site/tests/dist.test.ts`, `site/tests/a11y.spec.ts` | the checks |

---

## Task 1: The case shown and the trail strip

- [x] **Step 1: Failing tests** in `route.test.ts`, over the sample export:
  - `routeCase(index, cases)` returns the newest case with a trail; with none, undefined;
  - `stripBlocks(kase)` returns four blocks, each with its event words and whether it matched the NTSB's first code;
  - the counts between the blocks: documents read of documents offered, and coding look-ups.
- [x] **Step 2: Implement** `lib/route.ts` from `lib/trail.ts`'s `trailSteps` and `verdictView`, adding no new reading of the export.
- [x] **Step 3: `TrailStrip.astro`.**
  - The four blocks in a row from 640px, stacked below that, each on a panel.
  - The "read" and "coded" counts between them.
  - "The full trail →" linking to `/case/<n>/trail/`.
  - The id `trail-strip`, so the rail can name it.
  - It sits at the end of `OpenedCase`'s article, so a swapped-in case brings its own strip.
- [x] **Step 4:** Run the tests and `make check`. Commit `S5 step 6b Task 1: the trail strip`.

## Task 2: Stops 4 to 6 and the rail

- [x] **Step 1: Failing tests:**
  - `dist.test.ts`: the first page's rail names six places in order, each on the page;
  - `dist.test.ts`: stop 6 holds all eight questions, each linking to its Path anchor;
  - `dist.test.ts`: stop 5 holds the ladder and its sentence;
  - `claims.test.ts`: each guarded answer stops the build when its figure moves.
- [x] **Step 2: Implement.**
  - Stop 4 is the strip, with its sign "4 · Its trail" and a heading.
  - Stop 5 is a section with "5 · Was a loop needed?", the ladder, its sentence and "How each step was measured".
  - Stop 6 is `RouteQuestions.astro`: the eight questions as one list, each the question in bold, its one-line answer and a link to `/path/#<anchor>`.
- [x] **Step 3:** Run the tests and `make check`. Commit `S5 step 6b Task 2: stops 4 to 6`.

## Task 3: The arrival motion

- [x] **Step 1: Failing tests** in `a11y.spec.ts`:
  - right after load, a full-page capture finds every stop's heading visible (Review Focus 1);
  - with `reducedMotion: "reduce"`, no element has a running transition after a scroll (Review Focus 2);
  - with scripts off, nothing is hidden;
  - scrolling to stop 5 leaves its bars at their full widths within one second.
- [x] **Step 2: `scripts/arrive.ts`.**
  - It does nothing under `prefers-reduced-motion: reduce`.
  - On the first scroll, it marks the stops below the screen as waiting (`data-arrive="wait"`). Their parts are hidden by CSS from then on.
  - As each stop reaches the screen, it is marked `arrived`. Its parts rise in turn; the board's rows turn over one after another; the ladder's bars grow from the left; the strip's blocks and the questions appear in sequence.
  - Each run is under about a second and never repeats.
  - CSS does all the motion. The script sets only attributes.
- [x] **Step 3:** Run the tests and `make check`. Commit `S5 step 6b Task 3: the arrival motion`.

## Task 4: Preview (Controller)

- [ ] **Step 1:** Rebuild the local live preview and the private phone link from this branch, with the live export.
- [ ] **Step 2:** Andy reviews on his phone. Record his answers.
- [ ] **Step 3:** Run one fresh review (Opus) and its fix pass; push.

---

## Deviations

- **Andy's choice 1 (2026-10-21):** the eight one-line answers as drafted ("yes").
- **Task 1 (2026-10-21):**
  - **There is no "after coding" belief.** The trail records beliefs before reading, after each read choice that read something (h1, h2) and at the answer, and the coding look-ups lead straight to the answer. So the strip shows the beliefs a trail holds, two to four, not the plan's four fixed blocks. Between them it shows "read N of M documents offered" ("nothing on offer to read" when no document was), and "N coding look-ups".
  - Each belief shows its first code's event words and, once the NTSB has published, whether it was the NTSB's first code. That is said in words, and a match is also marked by a solid bar.
  - **The strip is its own stop, not part of the opened case's article.** Inside the article its heading would have been an `h3`, below the other stops' `h2`s. It is now a section of the first page, `#trail`, holding `#route-strip`. `scripts/open-row.ts` swaps that strip with the chosen case's, from the case page, which now shows the strip under "Its trail at a glance". A chosen case with no trail gets "This case has no trail to show."
  - `routeCase` picks the newest closed case with a trail. Stop 3 shows it too, or the newest case when none has a trail, in which case stop 4 and its rail place are left out.
- **Task 2 (2026-10-21):**
  - Stops 5 and 6 are sections `#loop` and `#path`. Stop 5 holds the ladder on a panel, with its sentence and its per-step Methods links. Stop 6 holds the eight questions (`RouteQuestions.astro`), each linking to its Path stop, and a link to the whole Path.
  - The answers are `ROUTE_QUESTIONS` in `lib/route.ts`. Question 6's "one case in three" is worded from `q6.twins` by `oneIn`. Question 3's "the largest gain on the ladder" gains a guard, `q3.largest_gain`: the rise from the case record alone to the fixed pipeline must be the largest between neighbouring steps. It is tested to fail. The first page now calls `assertPathClaims()`, so every guarded answer stops its build too.
  - An older test checked that the page's "table" stays visible after a row opens. The first page now also holds the ladder's hidden table, so it checks the board's table. It also checks that stop 4's strip follows the chosen case.
  - The "every place lands clear of the rail" test now includes the first page.
- **Andy's choice 2 (2026-10-21):** all four kinds of motion (A).
- **Task 3 (2026-10-21):**
  - **What arrives is each stop, and each figure inside one** (the ladder, the strip, the questions), not stops alone. Seen in the phone frames: the board's stop had its top edge on screen at load, so a stop-only rule never let its rows turn over.
  - **The board's rows each arrive on their own** as they reach the screen. Rows that arrive together turn over one after another (`--j`, 60ms apart).
  - A waiting stop's parts rise in turn. The ladder's bars grow from the left in order, then their whiskers show. The strip's beliefs and the eight questions appear in sequence. Every delay is capped, so each arrival ends within about a second; the test waits 1.2s and finds the ladder's bars at full width.
  - `styles/arrive.css` does all the motion inside `prefers-reduced-motion: no-preference`. `scripts/arrive.ts` sets only attributes and per-item CSS variables, through the CSSOM, which the CSP allows. It marks nothing until the first scroll, and nothing under reduced motion.
  - Tests in all three projects:
    - every stop's heading is visible, and nothing is marked, before any scroll;
    - an arrival is finished within 1.2s;
    - reduced motion marks nothing;
    - with scripts off, nothing is hidden.
- **Added at the preview (Andy, 2026-10-21):**
  - **Each arrival stays once per visit (A).** Andy asked whether the effect should reset when moving around the page, and kept it once only, as §3.1 has it.
  - **The board becomes a fixed window (A).** Andy asked for a fixed-height board whose rows shuffle like a departures board. He chose the once-only version over a cycling one.
    - The frame is `min(34rem, 72vh)` tall and scrolls inside, with sticky column names. It is focusable, as it was.
    - Each row ticks up and turns over as it comes into the window: those in view when the board arrives, older ones as the window is scrolled.
    - Rows have their own trigger, with no bottom margin, so no row in view is left blank.
    - A dated note in spec §4 records it, and a test scrolls the window and finds every row in view shown.
  - **Decision 0187 amended:** inside a word the lost character is an apostrophe, elsewhere a dash (`8dcd2de`).

## Glossary

- **Route:** the first page read top to bottom as six stops, about three minutes (§3.1).
- **Stop:** one section of the route, with its own sign and place in the rail.
- **Trail strip:** stop 4's four blocks, the beliefs before reading, after reading, after coding and at the answer, with what was read and looked up between them.
- **Guard:** a build-time check that stops the site building when a sentence's figures no longer support it (`lib/claims.ts`).
- **Reduced motion:** the reader's system setting asking pages not to animate. With it, the route shows everything at once.
