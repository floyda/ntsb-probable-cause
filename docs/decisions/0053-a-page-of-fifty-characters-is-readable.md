# 0053 — A page with 50 characters is readable; the boundary belongs to one side

Resolves the defect [0052](0052-arm-b-attaches-every-readable-document.md) records under
"Depends on an open defect". Adjusts the page-level half of
[0047](0047-pypdf-extracts-docket-text-no-ocr.md)'s extraction outcome. `SCAN_PAGE_MAX_CHARS`
keeps its value of 50.

## Context

Two functions in `docket/classify.py` read the same character counts and both compare against
`SCAN_PAGE_MAX_CHARS = 50`, each strictly, in opposite directions:

- `classify_pages` calls a document a **scan** when its mean characters per page is **under** 50.
- `readable_pages` counts a page readable when it has **more than** 50 characters.

Neither comparison includes 50 itself, so a document averaging exactly 50 characters a page is
not a scan — it gets status `"read"` and is attached as evidence — while none of its pages counts
as readable. Verified directly:

| mean characters per page | `classify_pages` | `readable_pages` |
|---|---|---|
| 49 | `scan` — never attached | 0 |
| **50** | **`partial` — attached** | **0** |
| 51 | `partial` — attached | 1 |

After 0051 such a document renders the header "…, 1 page, of which 0 held readable text." After
0052, which makes the extraction outcome the *only* admission test, this boundary is the sole
thing between "extraction found nothing" and "the agent is given it".

The defect was introduced by a task brief of mine asserting that status `"read"` implies at least
one readable page. That assertion was never true; it was stated as a fact and not checked.

## Decision

A page with **50 or more** characters is readable; a page with **fewer than 50** is a scan page.
`readable_pages` counts `chars >= SCAN_PAGE_MAX_CHARS` rather than `chars > SCAN_PAGE_MAX_CHARS`.
`classify_pages` is unchanged — it already treats "under 50" as the scan side.

## Why

1. **It makes the invariant hold by arithmetic, not by luck.** At least one page always has at
   least the mean. So if the mean is 50 or more the document is not a scan, and at least one page
   has 50 or more characters and is therefore readable. "Attached as evidence" now implies "has a
   readable page" for every possible input, and would continue to if the threshold changed.
2. **One boundary, one side.** The bug was not the value 50; it was that 50 belonged to neither
   side. Any consistent choice fixes it. Andy chose the inclusive one: "we have a simple
   boundary so lets say >= 50 then a readable page, <50 likely a scan page".
3. **It cannot remove evidence.** The change only ever moves a page from unreadable to readable,
   so no document that was attached stops being attached.

## What this rules out

- **Measuring how many corpus documents sit on the boundary before fixing it.** Considered and
  rejected by Andy as not worth the half hour: the fix is right whatever the frequency, and a
  consistent boundary is not a matter of taste. The two published results files that consume
  `readable_pages` are regenerated instead, which settles the frequency as a side effect.
- **Changing `SCAN_PAGE_MAX_CHARS` itself.** Out of scope: 50 is 0047's measured value and this
  record does not revisit it.
- **Guarding the header against zero readable pages.** Unnecessary once the invariant holds, and
  it would have hidden the inconsistency rather than removed it.

## Consequences to carry out

`readable_pages` feeds two published results files, which must be regenerated so they still
reproduce: `docs/results/s2-shape-dev.txt` (its "scanned pages" line) and
`docs/results/s2-doctype.txt` (its "at least one readable page" count). It also feeds
`readable_pages` in the committed docket fixture manifests, which no test pins against the code —
a known gap already carried in the S2 close-out list.

## Status

Accepted, 2026-09-20 (Andy: "not worth it, we have a simple boundary so lets say >= 50 then a
readable page, <50 likely a scan page").
