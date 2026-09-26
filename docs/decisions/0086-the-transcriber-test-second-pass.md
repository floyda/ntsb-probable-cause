# 0086 — The transcriber test gets a second pass, with three corrections fixed before re-marking

Amends the scoring of [0080](0080-the-transcriber-test-and-its-choice-rule.md) for S2.6's
transcriber test. 0080's gates, margins and cost rule, and Andy's three decisions of
2026-09-25 recorded in the S2.6 plan (handwriting first, the pilot-form top-up, failed pages
counted as wrong), are unchanged.

**This is a post-hoc second pass.** It was decided after the first pass was scored and seen.
The first pass stands, published unchanged in `docs/results/s26-transcriber-test.txt`; the
second pass is published beside it, labelled, in `docs/results/s26-transcriber-test-pass2.txt`.

## Context

Under 0080's rule, fixed before the test, the first pass chose no transcriber: every candidate
failed a gate. Four things found after scoring, from counts only (ad-hoc checks recorded in the
S2.6 plan's Deviations, 2026-09-25), make that result a poor measure of the candidates:

1. **A stamped label.** 160 of the 192 model outputs on photographs hold the word "Photo". Andy
   saw that almost every photograph carries a docket label whose "Pho" is hidden by an icon,
   and that the models wrote the whole word. Guidance given during marking ("filling in hidden
   characters is a guess") made each such card "some invented". Of the photographs marked
   invented, every one for Qwen (13 of 13) and all but one to three for the others hold "Photo".
2. **One-line replies.** Gemini 3.1 Flash Lite returned each handwriting page as a single line
   (25 of 25 pages). Its line accuracy is 0%, yet its invented-line rate looks low (1.1 per 100
   key lines), because a whole page counts as one line. The gate can be passed by ignoring the
   line format.
3. **Keys anchored on the draft.** 13 of the 25 handwriting keys equal the prefilled draft
   exactly (drafts from GPT-6 Luna on 10 pages, Qwen on 11, Gemini 3.6 Flash on 4). Where the
   key is one model's draft, that model's misreadings are in the key and the others' correct
   readings count against them.
4. **Andy's judgement from the marking:** "95-99% of what was presented added value".

## Decision

A second pass, scored with three corrections that are fixed here, before any re-marking:

1. **The stamped "Photo" label is not an invention.** A word printed on the page as part of the
   docket's photo label, even partly hidden by the icon, counts as on the page. Anything else is
   judged as before (a misread registration is still invented). Andy re-marks only the 69 cards
   he marked "some invented", on a page that lists just those; every other photograph mark
   stands.
2. **A reply that ignores the line format fails that page.** When a model returns fewer than
   half as many lines as Andy's key has for a handwriting page, that page counts as wrong for
   that model (none of its lines right). A model that does so on more than 1 in 20 handwriting
   pages is out, as a further gate.
3. **The 13 draft-anchored keys are re-checked.** Andy checks each of the 13 handwriting pages
   whose key equals the draft against its image, on a page showing just those, prefilled with
   his first-pass key; the other 12 keys stand.

The gates' limits (2 invented lines per 100 handwriting lines; 1 in 20 photographs; 1 in 20
full-page scans), the margins, "handwriting first", failed pages counted as wrong, and the cost
rule are **not** changed. If a model then fails only narrowly on a limit, that goes to Andy as a
separate, explicit decision with its numbers, recorded as a post-hoc limit change.

## Why

1. **The corrections fix measurement, not limits.** Each removes a way the first pass measured
   something other than transcription quality: a stamped label, a reply format, a key that
   copies one candidate. None of them is chosen to favour a named model; each is stated for
   every candidate alike.
2. **The later runs are the real test.** Whether transcription helps the agent is decided by
   B-v1 against B-v2 on `dev-400`, then on `heldout-400`, under rules already fixed. A
   transcriber chosen in a post-hoc pass that adds noise will show up there.
3. **Nothing is hidden.** The first pass is published unchanged beside the second.

## What this rules out

- **Loosening a gate's limit in this pass.** That is the most post-hoc change there is; it
  needs its own decision, with its numbers, if it comes up at all.
- **Re-marking cards Andy did not mark invented, or re-keying pages he edited.** Only the three
  named corrections apply.
- **Treating the second pass as pre-registered evidence.** It is labelled post-hoc wherever
  its result is cited.

## Status

Accepted, 2026-09-25 (Andy: "maybe it will need to be a second pass"; the three corrections
approved as proposed, before any re-marking).
