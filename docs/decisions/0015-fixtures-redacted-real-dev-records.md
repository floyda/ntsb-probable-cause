# 0015 — Fixtures are redacted real development records

## Context

Continuous integration has no raw data and no API key, but the leakage, provenance and
contamination tests must run there. The repository is public. Raw records carry owner and
operator names, addresses, zip codes and certificate numbers (M3 in
`scripts/exploratory/s0_design_measurements.py`); in general aviation the owner or operator
is often the pilot, who may have died. Separately, NTSB case numbers use the federal fiscal
year: 3,796 of 19,641 filtered cases carry a year in their number different from their
event year, including 16 of the 70 labelled cases (M2). Detail:
`docs/specs/2026-09-13-s0-foundation-design.md` §9.

## Decision

- Record fixtures are **real API records from the development split**, created only by
  `scripts/make_fixture.py`, which refuses any case with an event year after 2019 and removes
  a declared list of personal-data fields: `registeredOwner`, `ownerIndividual`,
  `ownerAddress`, `ownerZip`, `operatorName`, `operatorIndividual`,
  `operatorDoingBusinessAs`, `operatorAddress`, `operatorZip`, `operatorCertificateNumber`.
- About ten records, chosen for coverage (classes C, L, F; multi-aircraft; missing METAR;
  several events and findings; a duplicated narrative). One redacted API page for the client.
- Evaluation fixtures are case-ID lists with event dates, copied by script from the spike's
  labelling sheets at commit `9760e42`.
- A test and a pre-commit hook fail if any redacted field is present in a fixture.
- **Splits are always derived from the event date, never from the case number.**

## Why

1. **Real shapes, not invented ones.** Rule 2 forbids guessing API details. Synthetic records
   would be authored shapes that can drift from the API without any test noticing.
2. **No personal data in a public repository.** The fields removed are not evidence and no
   test needs them.
3. **Development-only records keep the contamination rule simple:** a record fixture is from
   2019 or earlier by its own `eventDate`, and evaluation lists are the only place held-out IDs
   appear.

## What this rules out

- **Synthetic records.** No personal-data risk and no split question. Rejected because shapes
  would be authored rather than observed.
- **No committed records; tests needing data skip in continuous integration.** No risk at all.
  Rejected because the leakage test would not be enforced where it counts, which contradicts
  S0's definition of done.
- **Real records committed verbatim.** Simplest. Rejected: it publishes private individuals'
  names and addresses.

## Status

Accepted, 2026-09-13.
