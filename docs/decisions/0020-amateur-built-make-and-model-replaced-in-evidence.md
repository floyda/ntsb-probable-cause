# 0020 — The make and model of amateur-built aircraft are replaced in evidence

## Context

Decision 0015 removes owner and operator names, addresses and certificate numbers from committed
test fixtures. It does not touch the evidence the model reads, because those owner and operator
fields are not evidence roles.

Review of the S0 fixtures found another route for a private person's name. On an amateur-built
aircraft (a flying machine built by an individual, often from a kit), the NTSB's
`aircraftMake` field usually holds the builder's own name, copied from the aircraft's
registration, and the `aircraftModel` field sometimes does too. Both fields are evidence roles
(`aircraft_make`, `aircraft_model`), so the name reaches the model, which can repeat it in its
own account, and later the public board.

Measured over all 19,641 processed cases (`scripts/corpus_scan.py`,
`docs/results/s0-corpus-scan.txt`):

- 3,109 cases have the amateur-built flag (`aircrafts[0].aircraftAmateurBuilt`) set: 2,146
  development, 645 held-out, 318 open.
- Those cases carry 2,438 different make values, of which 2,257 occur in only one case. Only a
  few makes, the kit manufacturers, recur widely.
- They carry 1,611 different model values, of which 1,199 occur in only one case; in 61 cases
  the model contains the make.

A local reading of a sample of one-off make values (judgement, not a scripted count; no names
recorded) found that most are a full personal name, in registry order (surname, first name,
initial), and most of the rest a surname alone. Together with the accident date and place, or
the registration number, that identifies a specific person. In general aviation the builder is
often the owner and pilot, and in a fatal accident may be the person who died.

## Decision

1. When `aircrafts[0].aircraftAmateurBuilt` is `true`, the `aircraft_make` and `aircraft_model`
   evidence roles both hold the fixed label `Amateur-built` instead of the recorded values. The
   label is one named constant in `fields.py` citing this record.
2. Both roles declare `aircrafts[0].aircraftAmateurBuilt` as a source alongside their own field,
   so the path check (0016, check 2) and the boundary test's provenance check see where the
   value comes from.
3. Factory-built aircraft are unchanged. Registration number, owner and operator city, state and
   country, and every other evidence role are unchanged: they are public, and Andy judged them
   acceptable (2026-09-14).
4. Fixtures keep 0015's redaction and the builder-name screen; this decision adds to them.

## Why

1. **The project does not repeat a person's name.** Records of fatal accidents are handled in a
   clinical tone and victim names never appear (repository rule 6). A name in evidence is a name
   the agent can write back.
2. **Both fields, because either can carry the name.** Replacing only the make leaves names in
   the model field. Replacing the model only when it contains the make still misses a model that
   is a different name. Replacing both is the only version with no name-shaped gap.
3. **The label keeps the fact that matters.** Whether an aircraft was amateur-built is relevant
   to a probable cause; the builder's name is not.

## What this rules out

- **Replace the make only.** Smallest change. Rejected because the model field sometimes holds
  the name.
- **Replace the model only when it contains the make.** Keeps kit model names, such as a
  well-known kit design, for most cases. Rejected because a model that is a different name, or
  a partial one, passes unseen.
- **Keep the fields and rely on fixtures being clean.** No change to evidence. Rejected because
  the fixture screen only protects committed test data, not real cases processed by the running
  system.
- **Defer to S1.** S0 defines the evidence roles, and no evaluation has run yet, so changing
  them now costs least.
- **Anonymity.** This decision does not make anyone anonymous: the NTSB publishes these records,
  and the registration number, which is kept, leads to the registered owner through the public
  FAA registry. What it prevents is this project repeating the name.

Cost: the kit model name is lost for 3,109 cases (16% of the corpus).

## Status

Accepted, 2026-09-14.
