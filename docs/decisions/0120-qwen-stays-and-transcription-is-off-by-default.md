# 0120 — Qwen3.5 122B stays the transcriber; transcription is off by default, for cost

The outcome of [0100](0100-the-transcriber-retest-and-page-rule.md): S2.7 track 2's re-test and
page rule. It **amends the default of [0074](0074-words-in-images-are-read-in-the-build.md)**;
0074 stays in place. Words in images can still be read, but a run does not read them unless
that is chosen. The rules and limits of [0080](0080-the-transcriber-test-and-its-choice-rule.md),
[0086](0086-the-transcriber-test-second-pass.md) and 0100 are unchanged. Qwen was first chosen
post hoc ([0087](0087-the-transcriber-is-qwen-provisionally.md)); it now stays by 0100 item 3, a
rule fixed before the re-test.

## Context

**What transcription bought, and what it cost** (`docs/results/s26-armB-v2-dev.txt`). On
`dev-400`, arm B with transcribed pages (evidence v2) was paired against arm B on text layers
only (v1). Occurrence top-1 moved +1.3% [-2.5%, +4.8%] on 399 cases, and +2.5% [-3.0%, +8.6%]
on the 198 fatal cases. Both intervals include zero, so the true gain may be nothing. Answering
the 401 cases at v2 cost $1.3301 in all (v1: $1.1805). Transcribing their pages cost $13.06
attributed to cases, $0.0337 a case: about ten times the answering (13.06 ÷ 1.3301,
arithmetic). Transcription is paid once per new batch of cases; a re-run on `dev-400` reuses the
cached readings and pays only for answering. Andy's cost line, 2026-09-28, in his words (one
typing slip corrected): "I really need to be getting costs down to about $4-5 per
batch of 400 if I am going to be able to keep saying yes to these tests".

**T1, the shortlist and probe** (`docs/results/s27-transcriber-shortlist.txt`). OpenRouter's
model list of 2026-09-27, filtered by 0100 item 1 plus three conditions added in the track's
plan: the listing offers structured output (walkthrough W6), it is not free or unpriced (Andy,
2026-09-27), and its output is text-only (stricter than spec §7.2's and 0100 item 1's "returns
text"; it refused 13 listings and changed nothing on the shortlist, since the one image-and-text
listing among them would have ranked as reserve 15). 14 models were eligible. The probe of
2026-09-27 passed eight. Two Meta models
failed on the account's OpenRouter 18+ age setting, not on reading the page, and reserves took
their places (W5). One reserve, `qwen/qwen3.8-flash`, returned a reply that did not parse. The
one batch call with an image (W2) was accepted, then failed: the batch service still refuses
base64 images, so transcription stays synchronous at the standard price.

**T2, the re-test** (`docs/results/s27-transcriber-retest.txt`). All eight candidates are out on
measures that need no marks, so no photograph or scan marking was needed (W3). For example:

- Invented handwriting lines may be at most 3.5 per 100 key lines (Qwen: 54 in 1548). Seven
  candidates invent on 65 to 181 lines in 1548.
- Handwriting lines right must be at least 61.9%. Qwen reads 1036 of 1548 (66.9%); the best
  candidate, `inclusionai/ling-3.0-flash-vl`, reads 802 (51.8%).
- `deepseek/deepseek-v4.1-flash` invents on only 9 lines, but reads 100 of 1548 right, makes
  40.91 typed errors per 100 characters, and costs $0.0033132 a test page, over the $0.00154 bar.

Qwen's figures were reproduced exactly from the cache with the `pass2/` recheck pair, as Andy
recalled (W7). DeepSeek's retry stopped at its reservation with 31 pages unread (the plan's
Deviations, Task 9 Step 6); its cost rules it out whatever those pages hold. The file's outcome:
"no candidate meets all seven: Qwen stays".

**Andy's challenge, a post-hoc check** (`docs/results/s27-transcriber-retest-readable.txt`).
Andy asked whether the key's `[illegible]` lines decided the result, since any word a model
writes there counts as invented ([0079](0079-transcribed-text-is-marked-and-never-guessed.md)).
37 of 1548 key lines hold `[illegible]`, on 12 of 25 pages. On the 13 fully readable pages,
`openai/gpt-6-luna-pro` invents on 18 lines against Qwen's 19. But Qwen reads 620 of 779 lines
right, with 10.9 character errors per 100; every candidate reads far fewer right (at most 458)
and makes at least 21.9 errors per 100. The verdict holds without the unreadable pages.

**T3, the page rule** (`docs/results/s27-page-value.txt`, from `dev-400`'s cached readings).
`all`: 12458 pages, $13.25. `image-only`: 3596 pages, 82.6% of the characters, $5.39.
`image-only+thin-layer`: 5398 pages, 84.2%, $6.92. 0100 item 4 takes the rule with the fewest
pages that keeps at least 90% of the characters; only `all` does. The page rule saves nothing.

**Routing, exploratory** (`docs/results/s27-routing-scans.txt`; outside 0100's rule). Andy
marked three cheaper candidates' readings of S2.6's 25 full-page scans. Invented added words:
`z-ai/glm-5.3-flash` on 0, `openai/gpt-6-luna-pro` on 1, `qwen/qwen3.7-flash` on 1 (Qwen: 0 in
S2.6). Cautions: 25 pages is a small sample; words left out are not measured (glm added no words
at all on 15 of the 25); and a text-and-image page can hold handwriting, which T2 shows these
models read badly.

## Decision

1. **The transcriber stays `qwen/qwen3.5-122b-a10b`**, by 0100 item 3.
2. **Transcription is off by default, for cost.** Runs and new batches of cases read text layers
   only (evidence version v1). A batch is transcribed only when Andy decides it for that batch.
   `ntsb-eval run --evidence-version` already defaults to `v1`; no code changes. The cached
   `dev-400` readings and S2.6's v2 results stay citable.
3. **When the agent loop is built (S3), transcribing a document becomes a tool the loop may
   call**, paid only when the loop chooses it. Whether that pays is for the loop to prove, as for
   any tool: [0022](0022-loop-must-beat-call-every-tool-arm.md) item 4 warrants the loop only if
   it beats arm B at equal cost, or matches it at lower cost.
4. **If transcription is used again**, it uses `TRANSCRIBER = "qwen/qwen3.5-122b-a10b"` and
   `PAGE_RULE = "all"`, both unchanged in `src/ntsb_probable_cause/docket/transcribe.py`: the
   measured choices of this track.
5. **For S2.7's meeting point** (spec §8 step 1), an instruction the parent branch
   `s27-coding-guidance` acts on when this track merges: `dev-400` is not re-read with a
   transcriber, and v2 is not the default evidence for S2.7's runs. By item 2 the sealed sample,
   a new batch, is not transcribed. This record edits none of track 1's files. Whether spec §8
   step 2's v1-against-v2 comparison still runs is not decided here; on `dev-400` it would pay no
   transcription, since the readings are cached.
6. **Routing text-and-image pages to a cheaper model** stays an open idea for a later stage, with
   the numbers and cautions above. Its rule is fixed before any run.
7. **The demo publishes this caveat:** handwritten and scanned docket pages are not read by
   default; the agent sees typed text (text layers) only.

## Why

1. **Transcription did not give the gain its cost needs.** +1.3% top-1, with an interval from
   -2.5% to +4.8%, for about ten times the answering cost. Andy: "the transcription didn't
   provide the big boost i was hoping for".
2. **No measured way of transcribing meets Andy's line of $4-5 per batch of 400.** Three figures
   describe `dev-400`'s transcription, and they count different things: $13.06 is the cost
   attributed to `dev-400`'s 401 cases (Context, above); $13.25 is the page-value script's cost
   of the cached readings under the `all` rule (T3); $13.56, cited in
   `docs/specs/2026-09-26-s27-coding-guidance-design.md` §7.1, is what S2.6 actually spent,
   including retried pages. Whichever figure is used, transcription alone costs far more than
   $4-5. `image-only`, which fails 0100's 90% floor, still costs $5.39 before any answer. The
   eight cheaper models all failed the re-test. With transcription off, answering `dev-400` at
   v1 cost $1.1805.
3. **A tool puts the cost where it can pay.** A page is read only when the loop judges it needed,
   and 0022's comparison with arm B measures whether that choice was worth its cost. 0074's
   reason, equal evidence for arm B and the loop, is kept at the tool level: under 0022 item 1,
   arm B calls every available tool. How arm B does so at equal cost is for S3's design.
4. **Qwen stays by a rule fixed before the results**, and the post-hoc check on readable pages
   agrees with it.

## What this rules out

- **A cheaper transcriber chosen on cost alone.** `z-ai/glm-5.3-flash` costs $0.0006885 a test
  page, under half Qwen's $0.0015362713, but invents on 75 handwriting lines against Qwen's 54
  and reads 661 of 1548 right against 1036. The agent weighs an invented word as fact (0080 Why 2).
- **Transcribing every page of every new batch by default.** $13.25 of transcription for
  `dev-400`, against about $1.33 of answering.
- **A thinner page rule chosen for its price.** `image-only` keeps 82.6% of the characters, under
  0100 item 4's 90%. Choosing it now would choose the rule after seeing its cost.
- **Loosening 0080's or 0100's limits** until a cheaper model passes.
- **Adopting routing now**, on 25 pages, with omissions unmeasured.
- **Removing transcription.** The code, the cache and the rule stay; S3 builds the tool on them.
- **Hiding the gap.** The caveat in item 7 is published with the demo.

## Status

Accepted, 2026-09-28. Item 1: Andy, "Ok suppose we need to stick with qwen and the costs". Item
2: Andy, "Im swaying towards B because in the grand schema of things the transcription didn't
provide the big boost i was hoping for", with the cost line quoted in Context. Item 3, on the
shape "off by default, a tool the agent can choose later": Andy, "yes that shape i think makes
sense". Items 4 to 7 apply these decisions and 0100's rules. The whole record, items 5 and 7
included, signed off by Andy on 2026-09-28: "yes this child branch track is signed off".

## Glossary

- **Transcription, transcriber**: a vision model copies the words on a page image into text; the
  model that does it is the transcriber.
- **Text layer**: the typed text stored inside a PDF page, read without any model.
- **Evidence version**: v1 is text layers only; v2 adds transcribed pages (0076).
- **Batch of cases**: a set of cases run together, such as `dev-400`'s 401. Not the same as the
  **batch service**, OpenRouter's half-price queue, which refuses images.
- **Key**: Andy's hand-checked text of a test page, the answer a reading is scored against.
- **Inventing line**: a line of a reading holding any word absent from the key for that page
  (0087), including a word where the key has `[illegible]`.
- **`[illegible]`**: the mark written where a word cannot be read, instead of a guess (0079).
- **Page rule**: which image-bearing pages are sent to the transcriber (`all`, `image-only`,
  `image-only+thin-layer`).
- **Text-and-image page**: a page with both a text layer and an image. Most are **full-page
  scans** that already carry a machine-read text layer; words a model adds beyond that layer are
  what the scan cards mark.
- **Routing**: sending some kinds of page to a different, cheaper transcriber.
- **Arm B**: every tool called in a fixed order, then one answer; **the loop** (arm C) chooses its
  tools (0022).
- **Post hoc**: decided after the results were seen, and labelled so wherever cited.
- **Paired difference, interval**: the change on the same cases between two runs, and the range
  the true change probably lies in; an interval that includes zero does not show a gain.
