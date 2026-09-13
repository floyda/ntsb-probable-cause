# 0012 — Typed constants and settings replace `config.yaml`

## Context

The spike kept its field map, splits, filters, API details, model prices and weather
parameters in one `config.yaml`, read as untyped dictionaries. `CLAUDE.md` says to carry
the field map over as-is, and this repository's `.gitignore` planned to track a
`config.yaml`. Detail: `docs/specs/2026-09-13-s0-foundation-design.md` §5.

## Decision

There is no `config.yaml`. The spike's content moves into three library modules and a
settings object:

- `fields.py` — field roles and the raw paths each role reads. Frozen and typed.
- `splits.py` — split years and filters. Frozen and typed.
- `sources.py` — NTSB API facts and model prices, each with a comment citing the OpenAPI
  spec, the saved response, or the price page and date it came from.
- `settings.py` — per-run values (API key, rate limit, data paths; later model and
  effort) from environment variables and command-line flags, via pydantic-settings. Each
  run records the resolved values in its output.

Two content changes: the Sonnet 5 price is corrected to $2 / $10 per million tokens
($1 / $5 batch), as 0009 required; the factual narrative moves from evidence to
synthesis (0013).

## Why

1. **The file mixed values that must never change casually with values that change every
   run.** Changing a split or a field role invalidates every reported number. In code, the
   change appears in a diff and needs a decision record; in an editable file it does not.
2. **Types catch mistakes that dictionaries do not.** The spike's scripts looked up
   `cfg["fields"]["evidence"]` by string throughout, which mypy cannot check.
3. **It removes a failure mode and a parser.** There is no "config missing" error and no
   loader.
4. **Run parameters belong with the run.** Recording them in each result makes a number
   reproducible; a shared file edited between runs does not.

"Carry the field map over as-is" still holds for the content: the paths are identical.

## What this rules out

- **Keeping `config.yaml`, validated into frozen pydantic models at start-up.** Closest to
  the spike, and values can change without touching code. Rejected because method
  constants would stay editable without review.
- **A hybrid: constants in Python, API facts and run defaults in YAML.** Less to move.
  Rejected because it leaves two places to look for one kind of fact.

## Status

Accepted, 2026-09-13.
