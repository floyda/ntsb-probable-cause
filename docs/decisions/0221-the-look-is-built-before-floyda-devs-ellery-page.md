# 0221. The look is built before floyda.dev's Ellery page exists

## Context

Decision 0219 gave Ellery a look related to floyda.dev. Its item 4 said when: the change is
built once floyda.dev's new look is published, "in the same change that points `AUTHOR_URL` at
its Ellery page".

floyda.dev's new look was published on 2026-11-15 (its release 1.0). A check of the published
site and of its repository the same day found three things:

- **The Ellery page is not published.** `https://floyda.dev/projects/ellery/` returns 404. The
  page is floyda.dev's release 1.1, planned for early December 2026. Its entry has `page: false`
  and no text yet.
- **floyda.dev has no 2-pixel rule between sections.** Its top bar and footer rules are 1.5
  pixels, and its rules between rows are 2.5 pixels. 0219 says 2 pixels, which is what the
  approved mock-up drew.
- **Some values in the mock-up are not floyda.dev's.** The mock-up's grid squares are 32
  pixels, and floyda.dev's are 24. Its muted text is `#5c584f`, and floyda.dev's is `#6b675e`.
  Its darkened amber is `#8a5a00`, and floyda.dev uses `#8f6b00` for Ellery's name on its
  light ground. Its label letter-spacing is 0.1em, and floyda.dev's is 0.07em.

Andy was told these on 2026-11-15 and was offered two choices: wait for release 1.1, or build
the look now and move the link later. He said: "I want the 'look' now, I dont want to wait".

## Decision

1. **The look is built now, and `AUTHOR_URL` stays at `https://floyda.dev`.** A later, separate
   change points it at `https://floyda.dev/projects/ellery/` once that page is published. This
   replaces the "same change" rule of 0219 item 4. The rest of 0219 stands.
2. **"ANDY FLOYD /" in the top bar links to floyda.dev's first page**, now and after the footer
   link moves. It is a separate value, `AUTHOR_HOME`.
3. **Rules stay 2 pixels**, as 0219 says, in the ink colour, as floyda.dev's rules are.
4. **Where the mock-up and the published floyda.dev differ, the published value is used:** 24
   pixel grid squares, muted text `#6b675e` (light) and `#8a919b` (dark), amber text `#8f6b00`
   on the light ground, and 0.07em letter-spacing for mono labels. The amber signs keep their
   own 0.1em.
5. **The preview cards are not redrawn.** A card is the board's dark panel with ELLERY in the
   dot font, and the board does not change.
6. **On a wide screen the first page's rail leaves with the opening band.** The band's rule
   runs the full width, so a rail fixed in place would have the rule pass through it. The rail
   starts inside the band, scrolls away with it, and fades in at its fixed place when the reader
   reaches the second stop (Andy, 2026-11-15, on the live preview). With scripts off the rail
   stays fixed. The mock-up put the rail below the band; this keeps the page's structure.

## Why

1. **Andy chose it.** 0219's reason for waiting was to avoid copying a look that might still
   change. The look is now published, so that reason is met. Only the page the link points to
   is missing.
2. **A dead link in the footer of every page is worse than a link to the first page.** The
   present link works, and floyda.dev's first page already leads with Ellery.
3. **0219 item 4 says values are copied from the published look.** The mock-up was drawn from
   a temporary address before the launch. The published values are the ones a reader of both
   sites sees.
4. **2 pixels sits between floyda.dev's two widths** (judgement). Ellery has one kind of rule
   where floyda.dev has two. Andy approved the mock-up with 2 pixels.
5. **The published amber passes AA by a small margin.** `#8f6b00` on `#faf8f3` is 4.63:1,
   against the 4.5:1 that AA requires. `site/src/lib/contrast.test.ts` holds the pair, so a
   later change to either colour fails the test.

## What this rules out

- **Waiting for release 1.1.** Its strongest case: one change, as 0219 planned, and no second
  pull request. It would leave the two sites looking unrelated for about three more weeks,
  while floyda.dev's first page already sends readers to Ellery.
- **Pointing `AUTHOR_URL` at the Ellery page now.** It would save the second change, but every
  page's footer would hold a link that returns 404 until December.
- **Copying floyda.dev's 1.5 and 2.5 pixel rules.** Its strongest case: every value would then
  come from the published site. It would mean choosing which of Ellery's rules is which, for a
  difference of half a pixel that the approved mock-up did not show.
- **Keeping the mock-up's `#8a5a00` amber.** It has more contrast (5.58:1). But it is no one's
  published value, and floyda.dev already sets Ellery's name in `#8f6b00`.

## Status

Accepted. Amends 0219 item 4.
