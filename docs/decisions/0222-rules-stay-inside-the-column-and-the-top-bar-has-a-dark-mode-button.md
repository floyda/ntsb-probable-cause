# 0222. Rules stay inside the column, and the top bar has a dark mode button

## Context

Decisions 0219 and 0221 gave Ellery a look related to floyda.dev. The change went live on
2026-11-15 (pull request #69). Andy then compared the two sites side by side and named two
differences:

- **The rules' width.** On floyda.dev the rules under the top bar and above the footer stop at
  the edges of the column. Only the grid runs to the edges of the screen. On Ellery the top
  bar's rule, the footer's rule and the rule closing the gridded band all ran the full width of
  the screen, as the mock-up drew them.
- **The dark mode button.** floyda.dev's top bar has a "Dark mode" button. Ellery had none: it
  followed the system's setting only. Andy: its loss "is a bit noticeable when flicking between
  the two pages".

Andy also saw that floyda.dev's highlight is orange and Ellery's is amber, and said he does not
mind that difference.

The full-width rule had a cost of its own. It passed through the rail on a wide screen, so
0221 item 6 made the first page's rail scroll away with the band and fade in at the second
stop.

## Decision

1. **Every rule stops at the column's edges:** under the top bar, above the footer, and closing
   the first page's gridded band. The grid itself still runs to both edges of the screen.
2. **The first page's rail stays in place on a wide screen**, as on every other page. This
   replaces 0221 item 6. The script and styles that moved the rail are removed.
3. **The top bar ends with a "Dark mode" button**, built as floyda.dev's is:
   - it switches between light and dark;
   - the choice is kept in the reader's browser under the key `theme`, the same key name
     floyda.dev uses, and nothing is sent anywhere;
   - its state is given by `aria-pressed` and by a round mark that is hollow for light and
     filled for dark, never by colour alone;
   - without scripts the button is not shown, and the site is dark.
4. **The script is a file of its own**, `site/public/theme.js`, loaded in the page's head before
   the page is drawn. The Content-Security-Policy allows no inline script, and a script loaded
   later would show dark for a moment to a reader who chose light.
5. **Dark is the default, whatever the system's setting** (Andy, 2026-11-15, for both sites).
   Light applies only when the reader chooses it with the button. `tokens.css` no longer reads
   the system's setting, and `site/src/lib/contrast.test.ts` fails if it does again. The browser
   checks for light and for phone width start as a reader who chose light.
6. **The orange and the amber stay different.** 0219 already ruled out floyda.dev's orange
   beside Ellery's amber signs.

## Why

1. **Andy asked for both**, after seeing the two published sites together. A mock-up could not
   show this: the difference only appears when a reader moves between the sites.
2. **Rules inside the column remove the rail problem at its cause.** No rule reaches the rail,
   so the rail needs no special behaviour on one page.
3. **A reader who picks dark on floyda.dev expects the same control on the next page.** The
   two sites have different addresses, so a browser keeps their choices apart and one site's
   choice cannot carry to the other. The same button in the same place is the nearest thing.
4. **Both themes were already designed and checked** (S5 specification §10). The button only
   lets the reader pick one, and both still pass the accessibility rules in the browser check.
5. **Dark by default is Andy's choice of first impression** (judgement). The board is dark in
   both themes, and floyda.dev takes the same default, so a reader moving between the sites
   starts in the same theme on each.

## What this rules out

- **Keeping full-width rules.** Its strongest case: it is what the approved mock-up showed, and
  it marks the band strongly. It is the one visible difference from floyda.dev's frame, and it
  needed special rail behaviour.
- **Sharing the choice between the two sites.** It would save the reader one click. It needs a
  cookie on the shared parent domain or a value passed in the link, for a setting that takes
  one click to make.
- **Following the system's setting by default.** Its strongest case: it respects a choice the
  reader has already made for every site, and it is what Ellery did until now. A reader whose
  system is light now sees dark first and needs one click to change it, once.
- **An inline script.** It is the usual way to avoid a flash of the wrong theme, and floyda.dev
  uses one. Ellery's Content-Security-Policy allows scripts from its own files only, and
  loosening that for one button is a poor trade.
- **Copying floyda.dev's orange.** See 0219.

## Status

Accepted. Amends 0221 item 6.
