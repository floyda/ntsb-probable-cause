# S5 step 6c — Open cases and the preview cards: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (Andy's choice for S5: Claude runs the tasks in the session, one fresh review at the end). Steps use checkbox (`- [ ]`) syntax. Tick a step in the same commit as its code (decision 0017). Log every departure in **Deviations**. Tasks marked **Controller** need Andy.

**Goal:** Step 6c finishes the site that §21 describes:
- **The Open cases page**, as counts only, from S4's export (§8).
- **The preview cards** that a shared link shows (§12, item 12).
- **The Open cases link** in the top bar and the footer.
- **The test sample**, checked against S4's later additions to `board/1`.

After 6c, the remaining steps are Andy's accessibility pass and the launch.

**Architecture:**
- **The Open cases page is `pages/open.astro`.** It reads `index.counts` through `lib/export.ts` and reads nothing new. It shows:
  - the open cases watched;
  - how many of them have a docket so far;
  - the closures on each night.
  It never lists an open case.
- **Link-preview tags are written in one place, `Base.astro`.** Every page passes the card it uses. Without one, it uses the site card. The tags are `og:title`, `og:description`, `og:url`, `og:image`, `og:image:alt`, `og:type` and `twitter:card` (`summary_large_image`). Image addresses are absolute, from `astro.config.mjs`'s `site`.
- **Each Path question has a forwarding page, `/path/<anchor>/`.** Link-preview services drop the `#…` part of an address, so `/path/#choosing` would show the site card, not the question's own card. The forwarding page carries the question's card and sends the reader on to `/path/#<anchor>` straight away. It does this with a zero-second `<meta http-equiv="refresh">`, which is not a script, so the CSP allows it. It also has a plain link and a canonical link to `/path/`.
- **The cards are PNG files, 1200×630, made once by a script and committed.** `site/scripts/make-cards.mjs` draws each card as HTML in Playwright, using the site's own fonts from `node_modules`, and saves a screenshot to `site/public/cards/`. `cards.json` records the words each card shows. A Vitest test fails the build when those words no longer match the site's: the question and answer in `lib/route.ts`, or the site's line and title.

**Tech Stack:** Astro 7, TypeScript strict, Vitest over the built pages, Playwright with axe (and Playwright again, to draw the cards).

**Spec:** docs/specs/2026-10-04-s5-public-site-design.md

The design is §8 (Open cases), §12 item 12 (shared links), §11 (respect) and the §21 note of 2026-10-16 (6c).

## Choices settled with Andy before writing

1. **Each Path question has a forwarding page** (Andy, 2026-11-01: "Forwarding page makes sense"). The other option was one site card for every Path link. It is simpler, but every shared question would look the same.
2. **The cards are made once by a script and committed** (Andy, 2026-11-01: "Made once is fine"). The other option was to draw them on every build. That would add Playwright and a browser to the AWS build for images that change only when a question's words change. To stop the committed images going stale, a test compares the words drawn on each card with the words on the site.
3. **The site card's layout** (Andy, 2026-11-01: "Go with your recommendation"):
   - the board's dark panel;
   - "ELLERY" in the dot font, as in the top bar;
   - the site's question in the reading font (Atkinson Hyperlegible);
   - one line under it, the first page's own description: "An AI agent codes closed aviation accident cases from the evidence; its answers are set beside the NTSB's."

   This replaces §12's "the site's question in dot letters". A long question in the dot font would run to about four lines and be hard to read at the size LinkedIn shows a card.

Decided here; each can change at the preview:
- **A question's card:** the same dark panel, with "ELLERY" in dot letters. Below it, the question in bold and its one-line answer, both taken from `ROUTE_QUESTIONS`, so the card says what the first page says. No card shows a figure, a case or a code. Question 8's answer ("The board above answers this in public.") reads wrongly away from the first page, so its card uses "The live board answers this in public." That wording is recorded in `cards.json`, and the test checks it there.
- **The Path page gains a "Link to this question" under each question's heading.** It points to the question's forwarding page, so a reader who copies it shares the right card. Without it, nobody would find the forwarding pages.
- **The Open cases page's words** (§8, §11). It has the sign "Open cases" and the heading "Cases still under investigation". After those come three counted lines, then the table:
  - "923 open cases are being watched." (`open_watched`)
  - "2 of them have a docket so far." (`open_with_docket`)
  - "Ellery codes each case once, when the NTSB closes it. Most open cases have no docket to read until then."
  - A table of the closures each night, newest first, captioned "Cases closed each night since 23 September 2026".

  The table counts closures only. It never lists cases. The numbers above are those in the 20 October export.
- **The Open cases page has no rail.** It is one screen long.
- **The top bar's order** is ELLERY · The path · Methods · Open cases (§21 6a). The footer adds Open cases after Methods.

## Global Constraints

- **The step 1–6b constraints hold.**
  - Every number comes from the numbers file or the export, by key.
  - Every worded claim is a guard in `lib/claims.ts`.
  - CSP `default-src 'self'`: no inline script or style. A meta refresh is not a script.
- **Open-split cases enter only as numbers** (decision 0024, §8): the page shows counts, never a case number, a date of an accident, an aircraft or a state.
- **No card shows a case's details** (§12 item 12, §11). Individual accidents, often fatal, stay out of link previews.
- **Clinical tone, no names** (rule 6).
- **WCAG 2.2 AA** on every page, in light, dark and phone. A forwarding page redirects at once. WCAG fails only a timed refresh.

## Review Focus

1. **Every page's preview tags name an image that exists in `dist/`** at an absolute address on `https://ellery.demo.floyda.dev`, and each tag appears once.
2. **A card's words cannot drift from the site's.** Change a question's answer in `route.ts`, and the card test fails until `make-cards.mjs` is re-run.
3. **The Open cases page lists no case.** A test finds no case number from the export on the page, and no link to `/case/`.
4. **Each forwarding page sends the reader to the right anchor,** carries its own card, and is excluded from search engines by its canonical link.
5. **The top bar marks Open cases as current** on its page, and still wraps on a phone with nothing hidden.

## File map

| file | responsibility |
|---|---|
| `site/src/lib/site.ts`, `site.test.ts` | Open cases in `PAGES`; the card names |
| `site/src/lib/cards.ts`, `cards.test.ts` | the words each card shows, from `route.ts` and `site.ts`; the drift test against `public/cards/cards.json` |
| `site/scripts/make-cards.mjs` | draws the cards with Playwright into `site/public/cards/` |
| `site/public/cards/*.png`, `cards.json` | the committed cards and the words drawn on each |
| `site/src/layouts/Base.astro` | the link-preview tags |
| `site/src/pages/open.astro` | the Open cases page |
| `site/src/pages/path/[anchor].astro` | the eight forwarding pages |
| `site/src/pages/path.astro` | "Link to this question" under each heading |
| `site/src/components/SiteFooter.astro` | Open cases in the footer |
| `site/tests/dist.test.ts`, `site/tests/a11y.spec.ts` | the checks |

---

## Task 1: The Open cases page and its links

- [x] **Step 1: Failing tests:**
  - `site.test.ts`: `PAGES` ends with Open cases at `/open/`;
  - `dist.test.ts`: `/open/` shows `open_watched`, `open_with_docket` and one table row per night in `closures_per_night`, newest first;
  - `dist.test.ts`: `/open/` holds no case number from the export and no link to `/case/` (Review Focus 3);
  - `dist.test.ts`: every page's top bar and footer link to `/open/`, and the bar marks it current on its own page.
- [x] **Step 2: Implement** `pages/open.astro`, and add the page to `PAGES` and `SiteFooter.astro`. Remove the two "joins in step 6c" comments.
- [x] **Step 3: Check the test sample against S4.**
  - Compare `tests/fixtures/board` with `main`'s copy.
  - Confirm that it holds S4's later additions (`5c16e0d`, `65a5244`): `mkey`, `launched_on` and every `not_offered_reason`.
  - Record what was found in Deviations. Change the sample only if a field is missing.
- [x] **Step 4:** Run `pnpm test`, `pnpm check`, `pnpm test:a11y`, then `make check`. Commit `S5 step 6c Task 1: the Open cases page`.

## Task 2: The cards and the script that draws them

- [ ] **Step 1: Failing tests** in `cards.test.ts`:
  - `cardWords()` returns the site card and one card per `ROUTE_QUESTIONS` anchor, each with its title, question and line;
  - `public/cards/cards.json` matches `cardWords()` exactly (Review Focus 2);
  - every card named in `cards.json` has a PNG of 1200×630 beside it (read from the PNG header, with no image library).
- [ ] **Step 2: `lib/cards.ts`.** It returns the words for each card from `route.ts` and `site.ts`, plus the one wording change for question 8. It reads nothing from the export, so no case can reach a card.
- [ ] **Step 3: `scripts/make-cards.mjs`.**
  - It builds each card as an HTML page with the site's colours and fonts, from `@fontsource`'s files.
  - It draws each card at 1200×630 in Playwright's Chromium and saves `public/cards/<name>.png`.
  - It writes `cards.json`.
  - It is run by hand (`pnpm cards`), never by the build.
- [ ] **Step 4:** Run the script and commit the cards. Run the tests and `make check`. Commit `S5 step 6c Task 2: the preview cards`.

## Task 3: The preview tags and the forwarding pages

- [ ] **Step 1: Failing tests** in `dist.test.ts`:
  - every built page has each preview tag once, with an absolute `og:image` under `/cards/` that exists in `dist/` (Review Focus 1);
  - the first page, Path, Methods, Open cases and every case and trail page use the site card;
  - `/path/<anchor>/` exists for each of the eight anchors. It carries that question's card, a zero-second refresh and a plain link to `/path/#<anchor>`, and a canonical link to `/path/` (Review Focus 4);
  - each Path question has a "Link to this question" pointing to its forwarding page.
- [ ] **Step 2: Implement:**
  - `Base.astro` gains an optional `card` prop (the site card by default) and writes the tags;
  - `pages/path/[anchor].astro` builds the eight forwarding pages from `ROUTE_QUESTIONS`;
  - `path.astro` gains the eight links.
- [ ] **Step 3:** Add an axe check of one forwarding page in `a11y.spec.ts`, with the refresh stopped so axe can read it.
- [ ] **Step 4:** Run the tests and `make check`. Commit `S5 step 6c Task 3: preview tags and forwarding pages`.

## Task 4: Preview (Controller)

- [ ] **Step 1:** Rebuild the local live preview from this branch, with the live export. Send Andy the site card and two question cards as images.
- [ ] **Step 2:** Andy reviews the Open cases page and the cards. Record his answers.
- [ ] **Step 3:** Run one fresh review (Opus) and its fix pass; push.

---

## Deviations

- **Task 1 (2026-11-01):**
  - **The line "Most open cases have no docket to read until then" appears only while fewer than half the open cases have one.** S4's invented sample has 187 of 212 with a docket, so the line would be false on it. The live export has 2 of 923. The check is in `lib/open.ts` rather than `lib/claims.ts`, because it rests on the export, not the numbers file. A unit test covers both sides.
  - The page adds one line the plan did not name: "Cases that have closed are on the board", linking to the first page.
  - **The test sample needed no change.** `tests/fixtures/board` and `docs/schemas/board-1.schema.json` are identical to `main`'s (`142b026`). Every case file holds `mkey`, the index holds `launched_on`, and the sample uses all five `not_offered_reason` values the schema allows.
  - The step 6a test that no page linked to `/open/` is replaced by tests that every top bar and footer does.

---

## Glossary

- **Preview card:** the picture a social site or chat app shows when someone shares a link. It is read from the page's `og:image` tag.
- **Open Graph tags (`og:`):** the tags in a page's head that tell a link-preview service the page's title, description and picture.
- **Forwarding page:** a page that sends the reader straight on to another address. Here, it exists so that a shared link to one Path question shows that question's own card.
- **Fragment (`#…`):** the part of an address that names a place within a page. Link-preview services ignore it, which is why each question needs its own forwarding page.
- **Site card:** the one card shared by every page except the Path questions.
- **Drift test:** a test that fails when the words recorded for a committed card no longer match the words on the site.
