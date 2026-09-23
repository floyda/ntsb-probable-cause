# 0080 — The transcriber is chosen by a test on our own pages, by a rule fixed in advance

## Context

The published benchmark closest to docket pages (socOCRbench, read 2026-09-22; S2.6 spec §7.1)
ranks Gemini 3.1 Flash Lite within 0.01 of models six to ten times its price, and the agent's
model, GPT-5.6 Luna, at 0.39 on handwriting against 0.64. It is small (280 pages), historical and
multilingual, and does not count invented text separately. It says whom to test, not who wins.

## Decision

1. **Candidates:** `google/gemini-3.1-flash-lite:batch`, `google/gemini-3.6-flash:batch`,
   `qwen/qwen3.5-122b-a10b` (open weights), and the agent's model as a control. Lowest reasoning
   setting, recorded.
2. **Three answer keys.** Typed text: pages with a good text layer, rendered and transcribed,
   with the text layer as the answer (about 100 pages; a best case, stated). Handwriting: about
   25 pages; all candidates transcribe; lines where all agree are accepted, Andy resolves the
   rest and spot-checks a seeded 1 in 10 of the agreed lines. Invented text: about 50 photo pages
   with no words; any output words are shown to Andy.
3. **The rule, in order.** (a) Out if a model invents words on more than 2 in 100 handwritten
   lines or on more than 1 in 20 no-word pages. (b) Of those left, the cheapest within 5
   percentage points of the best handwriting line accuracy and within 1 error per 100 characters
   of the best typed accuracy. (c) If none passes, transcription stops and the reason is
   recorded.
4. **Resolution:** the chosen model at 150 and 200 dots per inch; 200 only if its handwriting
   accuracy is more than 5 points higher.
5. Answer-key sheets and page images are never committed; counts go to
   `docs/results/s26-transcriber-test.txt`. The choice is recorded in its own decision.

## Why

1. **Rules fixed before results cannot be fitted to a winner.** The same principle set S1's bars.
2. **Invented text is the worst error.** The agent weighs an invented word as fact and a missing
   one as absence.
3. **5 points matches the resolution of ~375 lines** (about ±4 points).
4. **Andy's time goes where only a person can judge** — disagreements — with a spot check that
   measures shared error rather than assuming none.

## What this rules out

- **Choosing from the benchmark alone.** Its pages are not ours.
- **Andy typing every page blind.** Cleaner, but two to three hours and fewer pages.
- **A stronger model as judge.** It would grade models on the task where the best score 0.65.

## Status

Accepted, 2026-09-23 (Andy: "All sounds sensible").
