# S5 step 6a — Navigation and the Quiet look: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (Andy's choice for S5: Claude runs the tasks in the session, one fresh review at the end). Steps use checkbox (`- [ ]`) syntax. Tick a step in the same commit as its code (decision 0017). Log every departure in **Deviations**. Tasks marked **Controller** need Andy.

**Goal:** Give every page a way around, and make the site look finished. Today there is no header, no footer and no way back; you can only follow links in the text. After this step:
- every page has the same top bar and footer;
- every long page has a rail that shows where you are;
- case and trail pages lead back;
- every page has the Quiet look from the mock-up.

**Architecture:** Navigation lives in the shared layout (`layouts/Base.astro`), so no page can leave it out. What the top bar holds is one list in `lib/site.ts`. Each long page passes its own list of places to the layout, which draws the rail. One small self-hosted script marks the place being read. Without the script, the rail is a plain list of links and nothing is hidden. The look is tokens in `styles/tokens.css` and two small parts: an amber section sign and a white panel.

**Tech Stack:** Astro 7, TypeScript strict, Vitest over the built pages, Playwright with axe (WCAG 2.2 AA; light, dark and phone projects).

**Spec:** docs/specs/2026-10-04-s5-public-site-design.md

The spec's §21 note of 2026-10-16 is the design; §3.1 covers the rail and footer, §10 the look, §11 colour, §12 items 7 and 8 motion and access.

**Mock-up:** `docs/specs/2026-10-04-s5-mockups/route-v2.html`, the Quiet theme, with snap off (<https://claude.ai/artifact/45h5oxFhQj4yPTchLZbVgc>).

## Choice for Andy before execution

1. **The footer's "Built by Andy Floyd" link.** §3.1 says it links to "his main profile page", but no address is recorded anywhere in the repository.
   - Give me the address (for example your LinkedIn page or a personal site).
   - Or, until you choose, the line is plain text with no link.

Decided here, so no question is needed; each can be changed at the preview:
- **The top bar does not stay on screen as you scroll.** On a phone, the rail's strip already stays at the top. Two bars would take a fifth of a small screen.
- **The first page's rail lists the three stops that exist today:** the question, the board, one case. Step 6b adds the other three.
- **Path's rail lists the ladder and the eight questions** by short names (for example "3 · The docket"). **Methods' rail lists its nine sections.**
- **A "Skip to content" link comes first on every page.** The top bar and the rail come before the content, so a keyboard user needs a way past them (WCAG 2.4.1).

## Global Constraints

- **The step 1–5 constraints hold.** Every number comes from the numbers file by key; every worded claim is a guard in `lib/claims.ts`; billed costs only; development, held-out and live never share a figure.
- **CSP:** `default-src 'self'`. No inline script or style. The rail's script is a module Astro bundles to a file, as `scripts/open-row.ts` is. `inlineStylesheets: "never"` stays.
- **Content is complete without script** (§3.1, §12 item 7). The rail is a list of real links. The script only adds "you are here".
- **Quiet theme** (§10, §21 note):
  - dot letters only on the board and the name ELLERY;
  - plain headings, each with an amber sign as its label;
  - no new colour for meaning; results keep shape and words (§11).
- **WCAG 2.2 AA on every page** (§12 item 8). The new parts include:
  - the sign's amber against its ink;
  - the panel's edge;
  - the rail's "you are here" mark, which must not be colour alone (it is also bold and has a bar);
  - targets at least 24px;
  - a visible focus ring.
- **Phone width:** the page body never scrolls sideways. The rail's strip scrolls inside itself, and the board keeps its own frame (§4).
- **Open cases** is not linked anywhere until step 6c builds its page. The rule against linking to pages that don't exist yet (step 2) still holds.
- **Clinical tone, no victim names** (rule 6). Nothing new carries case text.

## Review Focus

1. **A link to a place on a page lands with its heading visible, not hidden under the phone's sticky strip.** Examples: `/path/#choosing`, `/methods/#withheld`. Every place a rail names gets `scroll-margin-top` at least the strip's height. Task 3 tests it on the phone project.
2. **Without script, nothing is hidden or broken.** The rail is links, the top bar is links, and no "you are here" mark appears. Task 3 runs one page with JavaScript off.
3. **Dark mode contrast** of the amber sign, the white panels' dark-mode counterpart and the rail mark. The accessibility run covers dark; Task 1 also checks the token pairs by number.
4. **A keyboard user reaches the content first.** "Skip to content" is the first focusable element and moves focus to `main`. Task 2 tests it.
5. **Every rail link resolves on its own page,** and every page's top bar marks exactly one page as current, or none on case and trail pages. Task 3 adds both to the built-page checks.

## File map

| file | responsibility |
|---|---|
| `site/src/styles/tokens.css` | ground, paper, sign and panel tokens in light and dark; the type scale; spacing (Task 1) |
| `site/src/components/Sign.astro`, `Panel.astro` | the amber section label; the white panel with a thin edge (Task 1) |
| `site/src/lib/site.ts`, `site.test.ts` | the top bar's pages; a page's places, and their checks (Tasks 2, 3) |
| `site/src/components/SiteHeader.astro`, `SiteFooter.astro` | the top bar with "Skip to content"; the footer (Task 2) |
| `site/src/components/Rail.astro`, `site/src/scripts/rail.ts` | the rail as links; the script that marks where you are (Task 3) |
| `site/src/layouts/Base.astro` | the header, rail, main and footer around every page (Tasks 2, 3) |
| `site/src/pages/*.astro`, `case/[case]/*.astro`, the figure components | places, signs, panels, back links (Tasks 3–5) |
| `site/tests/dist.test.ts`, `site/tests/a11y.spec.ts` | the checks (Tasks 1–5) |

---

## Task 1: The look's tokens, the sign and the panel

**Files:** modify `site/src/styles/tokens.css`; create `site/src/components/Sign.astro`, `site/src/components/Panel.astro`; test in `site/src/lib/contrast.test.ts` (new).

**Interfaces:** produces the tokens `--paper`, `--sign`, `--sign-ink`, `--panel-edge`, `--space-section`, `--step-0` to `--step-3`, and the components `<Sign>{text}</Sign>` and `<Panel>…</Panel>`.

- [ ] **Step 1: Failing contrast test.** `contrast.test.ts` reads `tokens.css` and computes the WCAG ratio for each pair in light and dark: ink on ground and on paper, muted ink on ground and on paper, sign ink on sign, the board's ink on its ground. It requires at least 4.5:1 for text pairs and 3:1 for the panel edge against the ground. A small `ratio(hexA, hexB)` is written in the test, from the WCAG formula.
- [ ] **Step 2: Run it.** It fails, because the new tokens don't exist yet.
- [ ] **Step 3: The tokens.** In `tokens.css`, the bare `:root` holds the light values and the dark media query redefines them, as now:
  ```css
  :root {
      --ground: #f6f7f8;   /* the page: very light grey, not flat white */
      --paper: #ffffff;    /* panels for figures and code lists */
      --panel-edge: #c9d0d7;
      --sign: #f2c94c;     /* the board's amber, as a wayfinding sign */
      --sign-ink: #0d1117;
      --step-0: 1rem; --step-1: 1.2rem; --step-2: 1.5rem; --step-3: 2rem;
      --space-section: 2.5rem;
  }
  @media (prefers-color-scheme: dark) {
      :root { --ground: #111418; --paper: #171b21; --panel-edge: #39424d; }
  }
  ```
  The existing `--ink`, `--ink-muted`, `--rule`, `--bar`, `--bar-dim` and board tokens stay. Any value the test rejects is adjusted, and the adjustment is logged.
- [ ] **Step 4: `Sign.astro`.** Draws `<span class="sign">` with the slot's text: uppercase, letter-spaced, in the sign colours, with 2px corners. It is a label, not a heading: the heading beside it stays the real `h2`.
- [ ] **Step 5: `Panel.astro`.** Draws `<div class="panel">`: paper ground, a 1px `--panel-edge` border, 4px corners, padding `0.9rem`. It may be wider than the 65-character text column, up to the main column's width.
- [ ] **Step 6:** Run the contrast test; it passes. Run `make check`. Commit `S5 step 6a Task 1: the Quiet look's tokens, the sign and the panel`.

## Task 2: The top bar and the footer, on every page

**Files:** create `site/src/lib/site.ts`, `site/src/lib/site.test.ts`, `site/src/components/SiteHeader.astro`, `site/src/components/SiteFooter.astro`; modify `site/src/layouts/Base.astro`, every page that uses `Base`; extend `site/tests/dist.test.ts`.

**Interfaces:**
- Produces `PAGES` and `type PageId = "home" | "path" | "methods"`.
- `Base` gains the prop `current?: PageId`; case and trail pages pass none.
  ```ts
  /** The top bar's pages (spec §21 note, 2026-10-16). Open cases joins in step 6c. */
  export const PAGES = [
      { id: "path", label: "The path", href: "/path/" },
      { id: "methods", label: "Methods", href: "/methods/" },
  ] as const;
  export type PageId = "home" | (typeof PAGES)[number]["id"];
  ```

- [ ] **Step 1: Failing tests.** `site.test.ts`: `PAGES` holds no address twice, and every `href` ends in `/`. In `dist.test.ts`, for every built page:
  - the first focusable element is "Skip to content", pointing at `#content`, and `main` has `id="content"`;
  - the header holds ELLERY linking to `/`, then each of `PAGES` in order;
  - exactly one link has `aria-current="page"` on `/`, `/path/` and `/methods/`, and none on a case or trail page;
  - the footer holds "Built by Andy Floyd" (a link only if choice 1 gave an address), the repository, and Methods;
  - no page links to `/open/`.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: `SiteHeader.astro`.**
  - "Skip to content" is visually hidden until focused.
  - Then a dark band (`--board-ground`) holding ELLERY in the dot font, in `--board-ink`, linking to `/` (with `aria-current="page"` when `current` is `home`).
  - Then a `nav` labelled "Site" listing `PAGES`. The current page is marked with `aria-current="page"`, the sign colour and a 2px underline, so the mark is not colour alone.
  - On a phone the list wraps onto a second line; there is no menu button.
- [ ] **Step 4: `SiteFooter.astro`.** The same dark band, holding:
  - "Built by Andy Floyd" (choice 1);
  - "The repository" (`repoUrl("")`'s root: add `repoRoot()` to `words.ts` if `repoUrl` cannot give it);
  - Methods.
- [ ] **Step 5: `Base.astro`.**
  - The order is header, then `<main id="content" tabindex="-1">`, then footer.
  - The body's `max-width` and padding move from `body` to an inner wrapper, so the dark bands run the full width.
  - Each page passes `current`: `index.astro` `home`, `path.astro` `path`, `methods.astro` `methods`.
  - The pages' own `h1` stay.
- [ ] **Step 6:** Run the tests and `make check`, including the accessibility run. Commit `S5 step 6a Task 2: the top bar and the footer on every page`.

## Task 3: The rail of places within a page

**Files:** create `site/src/components/Rail.astro`, `site/src/scripts/rail.ts`; modify `site/src/layouts/Base.astro`, `site/src/lib/site.ts` and its test, `index.astro`, `path.astro`, `methods.astro`; extend `site/tests/dist.test.ts` and `site/tests/a11y.spec.ts`.

**Interfaces:**
- Consumes `Base`'s `current`.
- Produces `interface Place { id: string; label: string }`, a new optional `Base` prop `places?: readonly Place[]`, and `checkPlaces(places)`, which throws on an empty list, an empty label, or an id used twice.

- [ ] **Step 1: Failing tests.**
  - `site.test.ts`: `checkPlaces` refuses each of those three.
  - `dist.test.ts`: on every page with a rail, each rail link's `#id` exists on that page, in the rail's order.
  - `dist.test.ts`: the first page's rail names three places, Path's nine, and Methods' nine.
  - `a11y.spec.ts`, every project:
    - scrolling to the third place marks that link `aria-current="location"`;
    - on the phone, `/path/#choosing` puts its heading below the strip, not under it (Review Focus 1);
    - with JavaScript off, every rail link is present and none is marked (Review Focus 2).
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: `Rail.astro`.** One `nav` labelled "On this page" with an ordered list of links. The same list is styled two ways by CSS:
  - **from 1000px**, a column in the right margin, sticky, with a number and a label per place, and a left rule;
  - **below 1000px**, a strip of tabs across the top, sticky at `top: 0`, scrolling sideways inside itself.

  The "you are here" mark is bold text, the ink colour and a 2px bar (wide) or a filled tab (phone): never colour alone. The page grid becomes `minmax(0, 1fr) 13rem` only when a rail is passed.
- [ ] **Step 4: `scripts/rail.ts`.** It finds the rail's links and their places, and watches the places with an `IntersectionObserver` (`rootMargin: "-35% 0px -60% 0px"`). It marks the one in view with `aria-current="location"` and the class `on`, and on the phone scrolls that tab into view inside the strip with `block: "nearest"`, so the page itself never moves. It sets the CSS variable `--strip-h` to the strip's height. Each place gets `scroll-margin-top: calc(var(--strip-h, 0px) + 0.75rem)`, so a heading reached by a link is not hidden. With no rail on the page it does nothing. It is loaded from `Base.astro` as `<script>import "../scripts/rail.ts";</script>`, so Astro bundles it to a file under the CSP.
- [ ] **Step 5: The places.**
  - `index.astro`: wrap its parts in sections with the ids `question` (the h1 and the caveat), `board` and `case`, keeping the existing heading ids, and pass three places.
  - `path.astro`: `ladder-heading`'s section, then the eight stop ids, with short labels from a list in the page (for example `{ id: "docket", label: "3 · The docket" }`).
  - `methods.astro`: its nine section ids. The page's own "On this page" contents list is removed, because the rail does its job.
- [ ] **Step 6:** Run the tests and `make check`. Take one phone screenshot of each page to check the strip. Commit `S5 step 6a Task 3: a rail of places on the long pages`.

## Task 4: The way back on case and trail pages

**Files:** modify `site/src/pages/case/[case]/index.astro`, `site/src/pages/case/[case]/trail.astro`; extend `site/tests/dist.test.ts`.

- [ ] **Step 1: Failing test.** Every case page opens its `main` with a link "← All closed cases" to `/#board`. Every trail page opens with that link and "← This case", to `/case/<number>/`.
- [ ] **Step 2: Run it.** It fails.
- [ ] **Step 3:** Add a `nav` labelled "Back" with those links, above the `h1`. The arrow is in the link text, and screen readers hear it as "All closed cases", because the arrow is in an `aria-hidden` span.
- [ ] **Step 4:** Run the tests and `make check`. Commit `S5 step 6a Task 4: the way back from case and trail pages`.

## Task 5: The look, page by page

**Files:** modify `index.astro`, `path.astro`, `methods.astro`, `components/PathStop.astro`, the figure components (`Ladder`, `ExampleCase`, `FirstCodes`, `BeliefPath`, `MissPairs`, `PageKinds`, `ClosuresStrip`, `SplitDiagram`), `components/OpenedCase.astro`, `components/Trail.astro`; extend `site/tests/dist.test.ts`.

- [ ] **Step 1: Failing test.** On `/`, `/path/` and `/methods/`, every `h2` that is a place in the rail has a sign just before it, and no sign stands alone without a heading. A sign's letters are made uppercase by CSS, so its source text stays in normal case for screen readers.
- [ ] **Step 2: Run it.** It fails.
- [ ] **Step 3: Signs.**
  - `PathStop` gains its sign ("Question 3"), from its `n`.
  - The first page's three sections each get one ("1 · The question" and so on).
  - Each Methods section gets one.
  - The ladder's section on Path gets "The ladder".
- [ ] **Step 4: Panels.**
  - Each Path figure sits in a `Panel`.
  - So do Methods' rows, its diagram and its glossary, and the opened case's code lists and trail blocks.
  - The board keeps its own dark frame, gaining a 1px `--board-rule` edge so it stays distinct in dark mode.
- [ ] **Step 5: Type and spacing.**
  - Headings take `--step-2`, and the page's `h1` `--step-3`.
  - Sections are separated by `--space-section` and a rule.
  - Running text stays within 44rem; panels may use the main column's full width.
  - Each page's own `p { margin-block: 0 }` and grid gaps stay as they are.
- [ ] **Step 6:** Run the tests and `make check`, including the accessibility run in all three projects. Take one screenshot of each page at phone and desktop width, in light and dark, and compare it with the mock-up. Fix what differs, and log it. Commit `S5 step 6a Task 5: the Quiet look on every page`.

## Task 6: Preview (Controller)

- [ ] **Step 1:** Rebuild the private phone link (the preview artifact of step 5, the same address) from this branch's build, and serve the build locally from the worktree, never from the main checkout. Send phone screenshots, light and dark, of each page's top and of a rail in use.
- [ ] **Step 2:** Andy reviews. His answers are recorded in Deviations.
- [ ] **Step 3:** Run one fresh review of the step (Opus) and its fix pass; push.

---

## Deviations

- **Andy's choice (2026-10-16):** "Built by Andy Floyd" links to <https://floyda.dev>.

## Glossary

- **Top bar:** the dark band at the top of every page, with ELLERY and the site's separate pages.
- **Rail:** the list of places within the page being read. It sits in the right margin on a wide screen and is a strip of tabs on a phone, and it marks where the reader is.
- **Place:** a section of a page that the rail names, such as one Path question.
- **Sign:** the small amber label above a section's heading, like an airport wayfinding sign.
- **Panel:** a white box with a thin edge that holds a figure or a list of codes.
- **Quiet theme:** the look §10 chose. Dot letters only on the board and the name; everything else in plain signage type.
- **`aria-current`:** the HTML attribute that tells a screen reader which page (`"page"`) or place (`"location"`) is the current one.
- **Skip link:** a link, first on the page and shown only when focused, that takes a keyboard user past the navigation to the content.
