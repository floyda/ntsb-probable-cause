# 0057 — An unset directory setting derives from `data_dir`

## Context

`Settings` (`src/ntsb_probable_cause/settings.py`) defined `data_dir`, `runs_dir` and
`docket_dir` as three independent literal defaults: `Path("data")`, `Path("data/runs")` and
`Path("data/docket")`. Nothing tied the latter two to the first at read time; they only
happened to agree because someone had typed matching strings.

On 2026-09-21 an evaluation run was launched with `NTSB_DATA_DIR` set to the main checkout's
data directory but `NTSB_DOCKET_DIR` left unset. `docket_dir` therefore kept its literal
default, `data/docket`, which resolved relative to the process's working directory — a git
worktree. Over roughly three hours, at the docket client's enforced rate of one request every
two seconds to `data.ntsb.gov`, the run fetched and cached 801 dockets there: 19 GB of
politely rate-limited requests to a government site. Because the destination was inside a
worktree rather than the intended data store, that cache would have been deleted with the
worktree. It was rescued by hand before that happened. `runs_dir` carries the identical risk
and had not yet caused a loss only by chance.

## Decision

A directory setting that the caller does not set explicitly — by environment variable,
`.env`, or constructor argument — derives from `data_dir` at read time: `runs_dir` becomes
`data_dir / "runs"` and `docket_dir` becomes `data_dir / "docket"`. A directory setting the
caller does set explicitly is used as given, even when `NTSB_DATA_DIR` is also set. With
nothing set, behaviour is unchanged: `data`, `data/runs`, `data/docket`.

Implemented as a `model_post_init` hook that checks `self.model_fields_set` and, for each of
`runs_dir` and `docket_dir` absent from it, writes the derived path with `object.__setattr__`
(the model is frozen). A `@model_validator(mode="after")` returning
`self.model_copy(update=...)` was the first attempt, matching the usual pydantic v2 pattern —
but `pydantic-settings` warns and discards the returned copy when the model is built through
`__init__`, which is how every `Settings()` call in this codebase constructs it, so the
derivation silently failed. `model_post_init` runs after that `__init__` has produced the real
instance and mutates it in place instead of relying on a return value that gets dropped.

## Why

1. **A partial environment override should not silently split the data store.** Setting only
   `NTSB_DATA_DIR` is the common case — pointing a run at a different data root — and the
   previous defaults made that setting incomplete without warning: two of the three locations
   it should have moved stayed behind.
2. **The failure is expensive and specific to this project's constraints.** The docket client
   is rate-limited to protect a real government site; re-fetching 801 dockets is not a retry, it
   is another three hours against `data.ntsb.gov`. Losing the cache to a worktree's removal
   would have forced exactly that.
3. **Deriving from `data_dir` costs nothing an explicit override can't undo.** Anyone who
   genuinely wants `runs_dir` or `docket_dir` somewhere unrelated to `data_dir` still sets it
   directly, and that value still wins.

## What this rules out

- **Independent literal defaults for `runs_dir` and `docket_dir`.** This is what caused the
  incident: two settings that only look related because their string defaults were typed to
  match, with nothing enforcing that relationship once one of the three is overridden.
- **Always deriving `runs_dir` and `docket_dir` from `data_dir`, ignoring an explicit
  override.** Rejected: some future run may legitimately want the docket cache on a different
  volume from everything else (size, disk pressure) while keeping `data_dir` for index and
  processed files. Removing the override would trade one silent-split failure mode for another.

## Status

Accepted, 2026-09-21.
