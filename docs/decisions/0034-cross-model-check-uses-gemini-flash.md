# 0034 — The cross-model sanity check uses Gemini 3.1 Flash Lite, not Sonnet 5

Amends point 3 of [0031](0031-default-model-gpt-luna-model-axis-after-s3.md), which stays in
place. Every other part of 0031 is unchanged.

## Context

0031 point 3 committed S1 to one cross-model comparison: Sonnet 5 against Luna, ceiling only,
on `dev-400`, as a sanity check, estimated at about $5. Its stated purpose, from 0031's *Why*,
is narrow and worth quoting: it "catches a model that fails the format rather than the task".

S1's development runs are now in, and they sharpen what that check has to settle. The ceiling
scored 8.7% top-1 [6.3, 11.9], below the no-model baseline's 17.7%. So the open question is
not whether Luna is a good model in general. It is whether 8.7% measures the difficulty of
naming a probable cause without the docket, or measures a weakness particular to Luna. A bar
that turns out to be an artefact of one model would be worthless, because S3's agent is
compared against it.

Prices were re-read from the OpenRouter models API on 2026-09-16, per run of 401 `dev-400`
cases at the measured token profile:

| model | family | batch price per Mtok | est. run |
|---|---|---|---|
| `anthropic/claude-sonnet-5:batch` | Anthropic | $1.00 / $5.00 | $6.26 |
| `anthropic/claude-haiku-4.5:batch` | Anthropic | $0.50 / $2.50 | $3.13 |
| `google/gemini-3.1-flash-lite:batch` | Google | $0.12 / $0.75 | $0.87 |
| `google/gemini-3.8-flash:batch` | Google | $0.38 / $1.88 | rejects our requests |
| `openai/gpt-5.6-luna:batch` (default) | OpenAI | $0.10 / $0.60 | $0.44 |

Sonnet 5 costs more than 0031 estimated, not less.

## Decision

1. The S1 cross-model sanity check runs **`google/gemini-3.1-flash-lite`**, batch variant, ceiling
   arm, on `dev-400`, against the Luna ceiling on the same cases as a paired difference.
2. A ten-case check on the development split runs first and confirms the model accepts the
   strict schema, before the full run is submitted. This is not a formality: the first model
   tried, `gemini-3.5-flash-lite`, failed all ten cases for $0.025 rather than failing 401
   for $1.28.
3. **Not every model can be compared against at all.** Stage 2 sends the model's own stage-1
   reply as the last message, so the request ends on a model turn. Gemini 3.5 and newer
   reject that outright ("Requests ending with a model turn are not supported"), as does
   Mistral Medium 3.1 ("Prefix does not match the response format"). MiniMax M2 and Qwen
   3.5-35B accept it but spend their whole token budget reasoning and return empty content.
   Probed on 2026-09-16; `gemini-3.1-flash-lite` is the newest Gemini that accepts our shape
   and answers cleanly. The request shape is **not** changed to suit a comparison model:
   bending the thing being measured to fit the instrument would defeat the measurement, and
   would invalidate the five completed development runs and the frozen `s1-v5` prompt.
4. 0031's rule for acting on the result is unchanged: the comparison is reported, changes
   nothing by itself, and if the gap is large Andy decides before any held-out run.
5. Prices for both Gemini variants are recorded in `sources.py` with the date they were read,
   as 0030 requires. Sonnet's entries stay: nothing here rules Sonnet out of the model axis
   after S3.

## Why

1. **A different family answers the question; a cheaper peer does not.** Luna is OpenAI. A
   second model at the same price tier would most likely be similar in capability, and two
   weak models scoring alike is equally consistent with "both weak" and "the task is hard" —
   it distinguishes nothing. Gemini 3.1 Flash Lite is a recent model from a
   different company, with different training data and different failure modes. If it also lands near 9%, that is
   evidence about the task. That is the whole point of the check.
2. **Sonnet is poor value for this particular question.** At $6.26 it is nearly five times
   the chosen model for a result that is, if anything, harder to interpret: Sonnet is the model
   the spike used, so a good Sonnet score invites the reading "we picked the wrong model"
   rather than "the docket is what is missing".
3. **The budget is real.** $25 a month (0030), with tasks 14 and 15 budgeted at about $12 and
   roughly $3.23 already spent. Choosing $1.28 over $6.26 leaves room for the held-out runs
   to be re-run if something goes wrong, which on this stage's evidence is not a remote
   possibility.
4. **The smoke test is what actually protects against the format failure mode** 0031 was
   worried about, and it costs about $0.03. Paying five times more for the full run does not
   buy that protection; running ten cases first does.

## What this rules out

- **Sonnet 5 as S1's comparison.** It is not ruled out of the post-S3 model axis, where
  comparing strong against cheap models is the actual question.
- **A same-price comparison model.** Explicitly rejected above: it would spend money and
  settle nothing.
- **Skipping the comparison to save money.** Without it, the bar rests on a single model with
  no evidence that it is representative, and the bar is the stage's deliverable.
- **A broad model comparison inside S1.** The probing above shows the two-stage design
  limits which models can be compared at all — a portability cost that lands on 0031 point 4,
  the model axis proper after S3. If that axis matters, stage 2 should be restructured to end
  on a user turn. That is a change to make between stages, never mid-measurement.
- **Reading the comparison as a model recommendation.** It is a sanity check on one number.
  0031 point 2 still holds: the bar is measured on one model, the agent is compared on the
  same model, and a cross-model table is never mixed into the bar.

## Status

Accepted.
