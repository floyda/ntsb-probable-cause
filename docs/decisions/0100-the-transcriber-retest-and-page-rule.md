# 0100 — The transcriber re-test is judged against Qwen, and the page rule is measured before it is chosen

## Context

No candidate passed 0080's limits in either pass of S2.6's test, Qwen3.5 122B included; 0087
chose Qwen provisionally and openly. Its second-pass figures
(`docs/results/s26-transcriber-test-pass2.txt`): 3.5 invented handwriting lines per 100; 2 of 50
photographs with invented words; 0 of 25 full-page scans with invented added words; 2 of 25
handwriting pages failing the line format; 66.9% of handwriting lines right; 12.29 typed errors
per 100 characters; $0.00154 per test page. Newer vision models list input prices of a tenth of
Qwen's or less (external, OpenRouter, read 2026-09-26). In the `dev-400` transcription cache,
text-and-image pages were 59% of the cost and 87% of them returned under 20 characters (ad-hoc,
re-derived by T3).

## Decision

1. **Shortlist** (`scripts/transcriber_shortlist.py`): accepts images, returns text, released on
   or after 2026-06-01, input price at or below Qwen's, not one of S2.6's four candidates; the
   eight cheapest by input price; one probe page each, a failed probe replaced by the next; one
   call testing whether batch accepts an image. The model list read is saved.
2. **Re-test** on S2.6's four keys, instruction t1, 150 dots per inch, 0086's corrections.
3. **Choice rule.** A candidate replaces Qwen only if it meets all of: invented handwriting
   lines at most 3.5 per 100; photographs with invented words at most 2 of 50; full-page scans
   with invented added words at most 0 of 25; format-failed handwriting pages at most 2 of 25;
   handwriting lines right at least 61.9%; typed errors at most 13.29 per 100 characters;
   measured cost per test page below $0.00154. Of those, the cheapest. If none, Qwen stays.
   0080's absolute limits are reported beside each candidate and are not loosened.
4. **Page rule** (`scripts/page_value.py`, from the `dev-400` cache): of all pages, image-only
   pages only, and image-only pages plus text-and-image pages with under 200 characters of text
   layer, the rule with the fewest pages that keeps at least 90% of the characters S2.6's rule
   transcribed.
5. v2 runs record `transcriber` and `page_rule`; a comparison across either is refused unless
   labelled.

## Why

1. **Qwen is the working choice, so a replacement must beat it**, on invention first; the margins
   for accuracy are 0080's own.
2. **Invented text is still the worst error** (0080 Why 2): every invention measure is at or
   below Qwen's.
3. **Most of the money went on pages that returned nothing**; the rule is chosen by measurement,
   and its effect on answers is tested at the meeting point.

## What this rules out

- **Loosening 0080's limits** until someone passes.
- **Choosing by list price.** Each model counts an image differently; cost is measured per page.
- **A page rule chosen by eye.**

## Status

Proposed, 2026-09-26: written with the S2.7 specification (Andy: "maybe before we do all this we
need to find a cheaper way to transcribe"). Accepted when Andy approves the specification.
