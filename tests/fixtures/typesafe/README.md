# Saved TypeSafe responses

Written by `scripts/typesafe_probe.py` on 2026-09-17 with model `jev-latest` (decision 0097). Ids and key material are redacted. Usage blocks: `{"choices": {"input_tokens": 4344, "output_tokens": 1911}, "nouls": {"input_tokens": 7154, "output_tokens": 2994}}`.

## The case behind `choices.json` (final review, Minor 6)

`choices.json` (ported from the `typesafe-probe` branch, S2.7 Task 9) carries a real case's
evidence state -- the `request.state` field -- but no case id, so the contamination tests could
not confirm it was a development case. Identified by matching its evidence values (the
registration `N418SP` is unique) against the processed file, checked locally:

- Case id: `ANC09CA020`
- Event date: 2009-02-16
- Split: development (`dev`, by event date -- CLAUDE.md rule 5)

Every other evidence value in `request.state` (aircraft make/model, engine type, injury level,
phase of flight, pilot certificates and hours, weather condition) matches this case's record in
`data/processed/cases.parquet` exactly, confirming the identification.
`tests/test_contamination.py::test_typesafe_fixture_case_is_development_split` checks this case
id's split by event date, the same way the other fixture-purity tests in that file do.
