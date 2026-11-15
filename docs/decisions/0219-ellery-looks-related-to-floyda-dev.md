# 0219. Ellery looks related to floyda.dev

## Context

Ellery's look is set by the S5 specification: §10 ("an airport, used quietly") and the note of
2026-10-16 in §21, "The look stays Quiet". In the Quiet look the header and footer are the
board's dark, ELLERY is set in the board's dot font, each section has an amber sign above a
plain heading, all text is in Atkinson Hyperlegible Next, and the page is pale grey.

In November 2026 Andy rebuilt his profile site, floyda.dev (its own repository, specification
of 2026-11-11). It has a look of its own:

- headings in Schibsted Grotesk, heavy;
- small labels in JetBrains Mono capitals;
- a warm paper ground (`#faf8f3`) in light and `#0e1116` in dark;
- a faint grid behind the opening;
- thick rules.

Its entry for Ellery already sets the name in the same dot font, Doto. Ellery's footer links to
floyda.dev ("Built by Andy Floyd"), and floyda.dev's case study will link to Ellery. Visitors
move between two sites that, apart from a near-black ground and one font, look unrelated.

On 2026-11-15 Andy was shown three options:

- make the sites look related ("option A");
- copy the profile exactly;
- change nothing.

He then saw a private mock-up of option A on Ellery's first page, in light and dark and at phone
width, beside the Quiet look, and said "Looks right".

## Decision

1. **The page around Ellery's content takes floyda.dev's look:**
   - headings in Schibsted Grotesk: the first page's question at weight 900, section headings at 800;
   - the top bar, the rail, a case's details and the footer in JetBrains Mono capitals;
   - floyda.dev's grounds, light and dark;
   - a gridded opening band on the first page, and 2-pixel rules between sections;
   - the top bar on the page's own ground, opening with "ANDY FLOYD /", which links to
     floyda.dev, then ELLERY in the dot font, underlined;
   - the footer opening with "© 2026 ANDY FLOYD".
2. **What carries Ellery's meaning stays as it is:**
   - the board, its dot font and its dark panel in both themes;
   - the amber signs, now set in JetBrains Mono;
   - Atkinson Hyperlegible Next for every sentence;
   - grades shown by a mark's shape and a word, never by colour (Rule 6, §11);
   - no pixel type for the site name, navigation or headings (§10, Andy, 2026-10-05).
3. **Amber that is text on the light ground is darkened** so it meets AA contrast, for example
   the question's final mark. Every new colour pair goes into `site/src/lib/contrast.test.ts`,
   and the axe checks (light, dark, phone) must pass. The new fonts are served from the site
   itself, like the present ones (§17).
4. **When:** the change is built once floyda.dev's new look is published at `floyda.dev`, in the
   same change that points `AUTHOR_URL` at its Ellery page. Its values are copied from
   floyda.dev's published look, with a comment naming where each came from. Andy chose to wait
   for the launch on 2026-11-15.

This amends the S5 specification's §10 and its §21 note of 2026-10-16 for the header, footer,
heading type and page ground. Everything else in §10 and the note stands.

## Why

1. **Ellery is the profile's main project, and readers arrive from it.** A reader who follows
   the link should see one author's work in two places, not two unrelated sites.
2. **Only the frame changes.** The parts that carry meaning were chosen for reasons that still
   hold. Atkinson Hyperlegible was chosen so long text is easy to read for readers outside the
   field, and Ellery's pages are long, while floyda.dev's are short. The board and the amber
   signs are the airport. The marks keep meaning out of colour.
3. **It is cheap and contained.** Every colour is in `site/src/styles/tokens.css`, the fonts are
   in `Base.astro`, and the frame is in the header, footer, sign and rail components. The
   contrast test, the axe checks and the preview-card test already guard the result.
4. **Waiting avoids doing it twice** (judgement). floyda.dev was still at a temporary address on
   2026-11-15. Copying a look that may still change would mean restyling Ellery a second time.

## What this rules out

- **Copying floyda.dev exactly.** Its strongest case: one identity across both sites, and one
  set of values to keep in step. It would put Schibsted Grotesk on Ellery's long pages
  untested, put floyda.dev's orange accent beside the amber signs, where the two compete, and
  undo §10's airport. Ellery would stop looking like itself.
- **Changing nothing.** Its strongest case: no work, no risk to a site that passes its checks,
  and the sites are already linked by the dot font. But the link from floyda.dev would lead to a
  site that looks like someone else's.
- **A shared package of values between the two repositories.** It would keep the sites in step
  automatically, but it would tie two independent builds together for about ten values that
  rarely change. Copied values, each with a comment naming its source, are enough.
- **Building now.** It would be done sooner, but against a look that is not yet published.

## Status

Accepted.
