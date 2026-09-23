# 0082 — The v3 probe: pictures alongside the text, on development cases only

## Context

Andy asked for "give it everything" to be built up before S3 asks whether choosing does better:
the agent should also see the photographs, as an analyst does, alongside the text rather than
instead of it (0038's principle). Two problems were raised in the design session and one
dismissed:

- The leakage tripwire compares text and cannot see inside an image. A scanned page quoting the
  probable cause would let the agent read the answer off the picture, and nothing in its output
  would look wrong. This protects the *score*.
- How much a model gains from pictures depends on how well it reads pictures.
- Names inside images are **not** a problem for this: 0049 draws the line at the public surface
  this project produces, where output is checked, not at what the model reads.

## Decision

1. B-v3 against B-v2 on `dev-400`, one run each, paired. Pages whose kind is photograph, diagram
   or mixed go to the agent as images alongside the text. Text pages stay text.
2. Per image: if its page's transcription passed the tripwire, it is sent. If the transcription
   tripped on the probable cause, a code or a whole withheld text, the case is refused, as today.
   If the transcription **failed**, the image is still sent and the case is marked
   `unguarded_images` with the count.
3. The result is reported from the same run on all cases and without the `unguarded_images`
   cases.
4. It runs on the agent's model and is labelled with it. Images are added in page order until the
   per-case cap; cases cut short are counted.
5. It is not a bar. Whether v3 ever runs on held-out or in S3 is decided on its result: if it
   shows a real gain, S3's loop gets an image tool and is compared against B-v3; if not, S3
   compares on v2.

## Why

1. **It completes the ladder** — no docket, text, transcriptions, pictures — so "everything" is
   measured before the loop is judged against it.
2. **Mark, not refuse (Andy).** A failed transcription leaves the image unguarded; marking it and
   scoring with and without shows whether that matters, at no extra cost.
3. **Development only** keeps held-out touches for results that earn them.

## What this rules out

- **Images of text pages.** The agent's model reads handwriting worse than the transcriber
  (0.39 against 0.64, S2.6 spec §7.1), and the guard could not check them.
- **A second model describing photos in words.** Interpretation by a model we have not measured;
  showing the picture to the agent is the direct form.
- **Deferring v3 wholly to after S3.** Andy's call: S3 needs to know what "everything" is worth.

**Limit, stated.** A transcription that succeeds but misreads the answer looks like a pass. The
transcriber test bounds how often that happens; it does not close the gap.

## Status

Accepted, 2026-09-23 (Andy).
