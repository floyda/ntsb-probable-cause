# 0046 — The owner and operator names the record already holds are replaced in document text

Andy's proposal, 2026-09-18, during the S2 build: "could we not search for the names that have
already been removed from the other data? we should know what we are looking for?" Extends 0020
and 0044, which replace only an amateur-built aircraft's make and model.

## Context

Decision 0015 named the record fields that hold personal data and strips them from every
committed fixture: `registeredOwner`, `ownerIndividual`, `ownerAddress`, `ownerZip`,
`operatorName`, `operatorIndividual`, `operatorDoingBusinessAs`, `operatorAddress`,
`operatorZip`, `operatorCertificateNumber`. The comment above that list states the reason: in
general aviation the owner or operator is often the pilot.

Decisions 0020 and 0044 replace an amateur-built aircraft's make and model wherever they appear,
because those fields usually hold the builder's name. Nothing else was replaced. But a docket's
documents are written by, and about, the people the record already names: the pilot/operator
accident report form is filled in by the operator, maintenance records name the operator, and
statements name whoever gave them.

So the project holds the exact strings it would want to find, and was not looking for them.

`scripts/name_coverage.py` measured the development split (`dev-400`, 401 cases):

- every case names an owner or operator — 401 of 401;
- 828 name strings in total, of which 635 (77%) carry no organisation token;
- the shortest is five characters, so none can match a fragment of an ordinary word;
- 506 of the 828 are two words, the shape of a person's name;
- of the 96 distinct person-looking surnames, 27 (28%) are also ordinary dictionary words.

The full output is `docs/results/s2-name-coverage.txt`.

## Decision

1. The attach step replaces every non-empty value of the fields in `REDACTED_FIELDS` wherever it
   appears in a docket document's text or in the rendered listing, by the same mechanism as the
   amateur-built replacement: the exact recorded string, case-insensitive, anchored at word
   boundaries. The replacement label says what kind of thing was removed, not who it was.
2. **The full recorded string only, never its parts.** A surname alone is not searched for,
   because 28% of the surnames in the development split are also ordinary words, and replacing
   those would corrupt the evidence the model reads and inflate the count with matches that were
   never names.
3. The count of replacements continues to be reported as a floor, for the same reason as 0044: a
   variant spelling passes through.
4. This does not change what may be committed. Decision 0037 still governs: document text enters
   git only for NTSB-authored born-digital documents, after the scripted pass and Andy's read.

## Why

1. **It is mechanical and it is complete for the people it covers.** The strings are known
   exactly, so this is a string replacement with no judgement and no model in the loop.
2. **It covers every case, not a minority.** The amateur-built rule fires on the small share of
   cases that are amateur-built; this fires on all of them.
3. **It costs nothing in evidence quality.** No recorded name is under five characters, so the
   over-replacement risk that motivates the length floor in 0044 does not arise here.
4. **The limit is stated rather than hidden.** It finds the people the record names. It cannot
   find a witness, a mechanic, an inspector or a passenger, because we hold no string for them.
   That is why 0037's human read remains the gate on anything committed, and why the replacement
   count is published as a floor.

## What this rules out

- **Searching for surnames alone.** Measured at a 28% collision rate with ordinary words on the
  development split: it would damage evidence and make the count meaningless.
- **A model-based name detector over document text.** It would put withheld-bearing text through
  a second model, needs its own error measurement, and is unnecessary for the names we already
  hold. Reconsider only for the names we do not.
- **Treating the replacement as sufficient for publication.** It is one layer; 0037 is the gate.

## Status

Accepted; extends 0020, 0044 (proposed by Andy, 2026-09-18).
