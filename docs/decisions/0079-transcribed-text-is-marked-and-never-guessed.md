# 0079 — Transcribed text carries its own page marker and never guesses

Extends the page marker of [0047](0047-pypdf-extracts-docket-text-no-ocr.md) item 1.

## Context

A transcription can be wrong in a way a text layer cannot: the pilot wrote "800 ft" and the
transcriber read "300 ft". The agent should be able to weigh a reading differently from typed
text. On mixed pages (text layer and image together) a rendered image also contains the typed
text, so a naive transcription repeats it.

## Decision

1. A transcribed page is marked `[page N of M, transcribed from an image]`. A page read from its
   text layer keeps `[page N of M]`.
2. The transcriber writes `[illegible]` for a word it cannot read, and never guesses.
3. On a mixed page the text layer is kept, the transcriber is given that page's own text layer
   and asked only for words not already in it, and those are added under
   `[words in the page's images, transcribed]`. Which mixed pages are sent follows the inventory
   (0074): a page whose images are logos only is not.
4. No confidence score is attached to transcribed text.

## Why

1. **Provenance without a hint.** The marker says where text came from, not what it means, and a
   live case and an evaluation case look the same.
2. **`[illegible]` is measurable.** The handwriting answer key counts guesses where
   `[illegible]` was due (0080).
3. **No duplication on mixed pages.**

## What this rules out

- **Transcribed text indistinguishable from a text layer.** Simpler; the agent could not weigh a
  guessed word differently from a typed one.
- **A confidence score per line.** A model's stated confidence in its reading is poorly matched
  to how often it is right; it would look meaningful and not be.

## Status

Accepted, 2026-09-23 (Andy).
