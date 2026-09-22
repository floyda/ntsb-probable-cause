# 0072 — The recorder's call to `split_record` is the one link exempted from the synthesis-and-verdict import rule

## Context

Spec §5.2 requires every record the recorder sees to pass through `split_record`
(`records/split.py`), so only evidence reaches it and the synthesis and verdict roles are
dropped before anything is compared or written (0013). Spec §11 puts `store` and `recorder` on
the import-linter contract "Only the splitter constructs synthesis and verdict", which forbids
its source modules from importing `records.synthesis` and `records.verdict`, directly or
through a chain.

The two requirements cannot both hold literally. `split_record` itself imports
`records.synthesis` and `records.verdict`, to construct the `Synthesis` and `Verdict` objects
it returns. import-linter checks chains by default, so any module that calls `split_record`
is reachable from it to both forbidden modules, whether or not that module ever names them
itself. `recorder/cases.py` calls `split_record` and discards the `Synthesis` and `Verdict`
values unread (`evidence, _synthesis, _verdict = split_record(raw)`), and the contract still
failed on the chain.

There is a precedent already in the codebase: `scoring/runner.py` is the only other caller of
`split_record`, and it is not on the contract's `source_modules` list. Only scoring modules
that never call the split (`scoring.baseline`, `scoring.codes`, `scoring.hypothesis`,
`scoring.prompt`, `scoring.samples`) are.

## Decision

One edge is exempted on the contract, naming the caller and the module it calls, not the
forbidden modules themselves:

```
ignore_imports = ["ntsb_probable_cause.recorder.cases -> ntsb_probable_cause.records.split"]
```

This was verified two ways. A direct import of `records.synthesis` or `records.verdict` added
temporarily to `recorder/cases.py` still fails the contract with `lint-imports`, exactly as
before the exemption; it was removed after the check. And no other recorder module is
exempted — if `recorder/dockets.py` imported `records.split`, `lint-imports` would fail,
because the ignored edge names `recorder.cases` alone. The `store` package keeps the full
rule, chains included: nothing in `store` calls `split_record`, so it needs no exemption and
none was added.

## Why

1. **It is the narrowest exception that still lets §5.2 hold.** One caller, one callee, named
   exactly; every other module and every other route to `records.synthesis` or
   `records.verdict` is still checked.
2. **Everything else keeps the full rule.** A broader exemption would have to be justified
   again for every module it covers; this one covers exactly the call the spec requires.
3. **The gap the rule cannot close is covered by a test that has been shown to fail.** No
   import rule can stop `recorder/cases.py` from taking the `Synthesis` and `Verdict` objects
   `split_record` returns and writing them to the store — that is a data-flow question, not an
   import question, and import-linter checks imports. The store boundary test in
   `tests/test_boundary.py` covers it instead: it reads a closed `recorder.sqlite` file as
   bytes (the `.sqlite` file plus any not-yet-checkpointed `-wal` file) and fails if any
   withheld text is present, raw or JSON-escaped, in windows short enough to catch text split
   across SQLite pages (`tests/boundary.py:withheld_windows`). Its mutation tests prove this:
   `test_store_boundary_test_fails_when_the_split_is_bypassed` proves a leak through the
   preliminary-narrative table is caught, and `test_store_boundary_test_fails_when_a_snapshot_role_leaks`
   proves a leak through an ordinary evidence field (`field_snapshots`, JSON-escaped) is
   caught too. `test_store_never_holds_synthesis_or_verdict` and
   `test_store_never_holds_synthesis_or_verdict_for_every_fixture` are the positive checks
   these two mutations are run against.
4. This choice is a judgement, not a measurement: there is no script or number behind
   "narrowest exception" — it is a design call about how tightly an import rule should be
   drawn once it cannot be met literally.

## What this rules out

- **A separate recorder contract with `allow_indirect_imports = true`.** Simpler to read, but
  weaker: it would allow every chain out of the recorder, including one that reached
  `records.verdict` through an unrelated scoring module, not only the one call §5.2 requires.
- **Taking `recorder.cases` off the contract's `source_modules`, as `scoring/runner.py` is.**
  Same practical effect for that one module, but coarser and less visible: the exemption would
  not say which import it was for, and a reader would have to work out why the module is
  missing from the list.
- **Keeping recorder out of the chain check entirely and relying only on the byte test.**
  Drops the direct-import check the exemption still gives: a stray `from
  ntsb_probable_cause.records.synthesis import Synthesis` anywhere else in the recorder would
  go unnoticed by import-linter and wait for the byte test, or a fixture that happens not to
  exercise it, to catch it instead.

## Status

Accepted, 2026-09-22. Narrows 0016's import layer for one edge; amends spec S2.5 §11.
