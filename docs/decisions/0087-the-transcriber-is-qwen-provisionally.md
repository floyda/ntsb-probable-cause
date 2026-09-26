# 0087 — The transcriber is Qwen3.5 122B, provisionally: a post-hoc override

Overrides the outcome of [0080](0080-the-transcriber-test-and-its-choice-rule.md)'s rule for
S2.6, after [0086](0086-the-transcriber-test-second-pass.md)'s second pass. 0080's rule and its
limits are not changed; its outcome is set aside, openly, by this record.

**This is a post-hoc choice.** It was made after both passes of the transcriber test were
scored and seen. It is cited as such wherever the transcriber is named.

## Context

Both passes of the transcriber test chose no transcriber: every candidate failed at least one
gate (`docs/results/s26-transcriber-test.txt`, `docs/results/s26-transcriber-test-pass2.txt`).
In the second pass, with 0086's three measurement corrections:

- The handwriting invented-lines gate (limit 2 per 100 key lines) excludes
  `qwen/qwen3.5-122b-a10b` (3.5), `openai/gpt-6-luna` (4.4) and `google/gemini-3.6-flash` (5.8).
- `google/gemini-3.1-flash-lite` fails the line format on 25 of 25 handwriting pages.
- Qwen also fails the line format on 2 of 25 pages (limit 1 in 20).

A line counts as invented when it holds any word absent from Andy's key for that page, so on
dense forms one misread word counts the whole line. On that measure Qwen's 3.5 per 100 means
about 96.5 of every 100 of its lines hold only words from the page. Andy judged from marking
that "95-99% of what was presented added value".

## Decision

1. The transcriber for S2.6 is **`qwen/qwen3.5-122b-a10b`**, at its lowest reasoning level
   (`sources.LOWEST_REASONING`), synchronous at the standard price (images cannot be batched),
   with instruction t1. `docket.transcribe.TRANSCRIBER` holds it.
2. **Provisionally.** Whether transcription goes forward is decided by the agent's own
   pre-registered comparison: arm B at evidence version v1 against v2 on `dev-400` (S2.6 Task
   15). v2 reaches `heldout-400` only as that task's rule allows.
3. The resolution is 150 dots per inch unless 0080's resolution comparison, run on Qwen, says
   200; that result is added to the second pass's results file.
4. Before any transcription is paid for, the stage's cost is re-estimated against the $40 line
   (0083 item 2) and brought to Andy.

## Why

1. **Best of the candidates on every invention measure** (second pass): photographs with
   invented words 2 of 50 (the only candidate inside the limit), full-page scans with invented
   added words 0 of 25, invented handwriting lines 3.5 per 100 (the lowest of the three that
   keep the line format), and the best handwriting line accuracy, 66.9% [64.5%, 69.2%]. It
   costs $0.00154 per test page against GPT-6 Luna's $0.00073, a fraction of a cent either way.
2. **The decisive test is still pre-registered.** The transcriber test is a quality screen; the
   question that matters is whether transcriptions help the agent. If Qwen's wrong words hurt
   more than its readings help, B-v1 against B-v2 shows it, and v2 stops there.
3. **Nothing is hidden.** The rule's outcome, both passes and this override are all published.

## What this rules out

- **Loosening 0080's limits.** The limits stand; this record overrides one outcome, openly,
  rather than moving the bar until someone clears it.
- **`google/gemini-3.1-flash-lite`**: ignores the line format on every handwriting page.
- **`google/gemini-3.6-flash`**: the most invented handwriting lines (5.8 per 100) and 8 of 50
  photographs with invented words, at the highest cost ($0.00264 per page).
- **`openai/gpt-6-luna`**: cheaper, but worse than Qwen on every invention measure (4.4 per 100;
  3 of 50 photographs; 2 of 25 full-page scans).
- **Citing the transcriber choice as pre-registered evidence.**

## Status

Accepted, 2026-09-25 (Andy: option C, "provisional Qwen, agent test decides").
