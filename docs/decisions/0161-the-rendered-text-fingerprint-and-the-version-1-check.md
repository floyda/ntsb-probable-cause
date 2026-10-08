# 0161 — The rendered-text fingerprint `+t` replaces `+p`, and a live run refuses unless it is version 1

From the S3.3 design session with Andy (2026-10-07). Detail:
[the S3.3 specification](../specs/2026-10-07-s3-3-live-shadow-design.md) §7. Applies
[0143](0143-the-fingerprint-should-cover-what-the-agent-receives.md); amends
[0133](0133-unreadable-dockets-are-listed-and-the-text-is-fingerprinted.md).

## Context

1. **0133's `+p`** hashes the source of ten modules and two schemas as sent, so a comment or a
   refactor moves the label though the model sees the same words.
2. **0143** set the principle (hash what the agent receives) and placed the build in S3.3, before
   S4, with a mutation test and continuity on `fd6053f`.
3. **0156** puts "Ellery, version 1" on the board: the loop frozen at `fd6053f`, whose runs recorded
   `s3-v1+ge17fecdc66ec+p947fac1c86a4`.
4. **`scripts/paid_run.sh` installed with `uv sync --frozen`**, which uses the lockfile without
   checking it still matches `pyproject.toml`; CI and the image use `--locked`.

## Decision

1. **`+t`** renders every fixed text the loop or arm B's tool post-pass can send, by driving both
   state machines over invented inputs with scripted replies, and hashes the model-facing part of
   each request as sent. It replaces `+p` everywhere `+p` is used. The prompt version becomes
   `s3-v1+ge17fecdc66ec+t<12>`; `+r` stays the tuning round's mark.
2. **It cannot miss a text:** a reach test requires every model-text literal of the text modules to
   appear in the rendered requests or be listed as not model text with a reason; a mutation test
   changes one text in each module and checks that `+t` moves, and changes a comment and checks it
   does not.
3. **Continuity:** `+t` computed on `fd6053f`'s code equals `+t` on S3.3's code; both labels are in
   `docs/results/s33-fingerprint-continuity.txt`, and version 1's are pinned in code
   (`agent/version.py`: `SOURCE_LABEL_V1`, `VERSION_1`).
4. **Every live run computes its prompt version before any call and refuses unless it equals
   `VERSION_1`**, naming both values.
5. **`paid_run.sh` installs with `uv sync --locked` and exports `UV_LOCKED=1`**, so every `uv run`
   refuses a lockfile that would change; **each live run records the SHA-256 of `uv.lock`**.

## Why

1. **A label should move when the model's input moves, and only then** (0143, Why 1). Dependency
   updates that leave the text unchanged become safe again.
2. **The board's "version 1" becomes a check, not a promise.** A change of text is a new version,
   which needs a registered comparison before it reaches the board (0156 item 4).
3. **The lockfile pins the environment that produced each run.** Andy: "Yes A, we should make use
   of uv lock if we don't already".

## What this rules out

- **Record and continue on a mismatch.** Rejected: the board could run a different agent under the
  name "version 1" unnoticed.
- **Relying on CI's frozen-label test alone.** It catches a change before merge but does not guard
  the paid-runs checkout at the moment of the run.
- **Keeping `+p` beside `+t`.** Rejected: `+p` would keep moving on comments, the false change 0143
  set out to end.

## Status

Accepted, 2026-10-07 (Andy, S3.3 design session; specification approved 2026-10-07).

## Glossary

- **`+t`**: the prompt version's fingerprint of the rendered text.
- **Reach test**: every text-building string must turn up in what the agent receives.
- **`--locked`**: uv's mode that refuses to run if the lockfile would change.

**Note, 2026-10-08 (final review, before any live record carried the first value):** the value
pinned on 2026-10-07 (`+tc6497367ee94`) was re-pinned to `+te7811b387b31`
(`s3-v1+ge17fecdc66ec+te7811b387b31`) because the renderer was extended, not because the agent's
text changed. A per-literal mutation sweep (969 literals, 19 modules) showed that "It cannot miss
a text" in Decision, item 2, overstated the reach test: a literal can appear in a request by
coincidence while the text the model reads comes from elsewhere. The sweep found texts a live run
sends that the fingerprint did not follow: a one-page document's menu word and header, the
partly-readable header, the amateur-built label, the owner or operator label, the page marker, the
success line of `describe_codes` for an item, and `past_findings` for an unknown occurrence code.
`agent/rendered.py` now sends each of them (a hand-built PDF read by `docket.extract.extract_pdf`
gives the page markers and joins), the reach test also covers `fields.py`, `docket/attach.py`,
`docket/extract.py` and `docket/listing.py`, and `make s33-mutation-sweep` lists any literal whose
edit leaves the fingerprint unchanged and which the list in
`tests/fixtures/rendered/not_model_text.toml` does not explain. The extended renderer gives the same
value on `fd6053f` and on the current code (re-checked by `make s33-continuity`). Settings that
change what the model receives without being text (the temperature, the model, the reply budget,
the statistics file and `items.csv`, the pass-reasoning switch) are pinned in
`live.morning.VERSION_1_SETTINGS`, which a morning compares before it opens the store. Decision
item 4 still holds: a new text is a new version; a wider renderer on unchanged text re-pins
"version 1" once, here, and the test `tests/test_agent_version.py` ties the value to the
continuity file.
