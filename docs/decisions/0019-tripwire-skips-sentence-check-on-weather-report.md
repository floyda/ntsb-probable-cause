# 0019 — In the weather report field, the tripwire skips sentences from the factual narrative

## Context

The tripwire (decision 0016, check 4) is the last check in `split_record`. After a record is
split, it looks inside every evidence value for text that also appears in the withheld parts — the
factual narrative, the analysis and the probable cause — and stops the case with `LeakageError` if
it finds any. It compares three things: whole withheld texts, individual withheld sentences, and
occurrence and finding codes. A sentence only counts if it is at least `MIN_SENTENCE_CHARS` long,
because short phrases such as "the pilot" appear everywhere. That length was to be measured, not
guessed: the smallest candidate (10, 20, 40, 80) with zero matches over every processed case.

The first scan over 19,641 cases (`scripts/corpus_scan.py`) found no candidate with zero matches.
All matches were sentence matches, from two causes. The scan's results file,
`docs/results/s0-corpus-scan.txt`, prints the matches by evidence field, withheld source and
length both with and without this decision's exemption, so the figures below can be checked there.

- **The weather report: 3 matches in 2 cases (1 development, 1 held-out), of 117, 55 and 223
  characters. All three sentences come from the factual narrative; none from the analysis or the
  probable cause.** Investigators quote the weather observation in the factual narrative, and the
  same observation is the `weather_metar` evidence field (`weatherConditions[0].metar`). For
  example, evidence `KABC 121453Z 27008KT 10SM CLR 24/08 A3002`, and a factual narrative that
  reads "... reported the following conditions. KABC 121453Z 27008KT 10SM CLR 24/08 A3002. The
  pilot then ...": the middle sentence is the whole observation, so it matches. The development
  match is of this kind. The held-out matches are in a plain-English weather value that the
  narrative repeats.
- **The weather field is not always a coded report.** Of 4,774 non-empty `weather_metar` values,
  4,739 contain a coded observation time (`DDHHMMZ`); 35 are plain English. For plain-English
  values, which text was copied from which cannot be told from the format.
- **A manufacturer name with full stops: 2 matches in 2 cases, each exactly 10 characters.** The
  sentence splitter cuts "S.C. Aerostar S.A." into short pieces that match the make field. They
  appear only at the 10-character candidate.

## Decision

1. For the `weather_metar` evidence role only, the tripwire does not compare **sentences taken from
   the factual narrative**. In that role it still compares sentences from the analysis and the
   probable cause, whole withheld texts, and codes — for coded and plain-English values alike.
   Every other evidence role keeps every comparison. The exemption is one named constant in
   `records/guard.py` pairing the role with the withheld source, citing this record.
2. There is no exemption for the manufacturer name. The measured minimum sentence length removes
   those matches.
3. The corpus scan is re-run with the exemption, and `MIN_SENTENCE_CHARS` is set from its result.

## Why

1. **It removes exactly the matches measured, and nothing that carries a conclusion.** Every
   weather match came from the factual narrative, which describes the weather observation among
   other facts. The answer itself lives in the analysis and the probable cause; sentences from
   those are still caught in the weather field, including in the 35 plain-English values, where
   the direction of copying cannot be known.
2. **The alternatives either weaken the guard everywhere or stop real cases.** No candidate up to
   80 clears, and the longest weather quote is 223 characters; a threshold above that would let
   any copied sentence shorter than 224 characters pass in every field, including the preliminary
   narrative now and docket text from S2. Exempting only coded weather values would keep the full
   check on plain English, but would stop the held-out case above with a false alarm, so it could
   not be evaluated.
3. **Exemptions are added only where the data forces them, and as narrowly as it allows.** The
   manufacturer-name matches disappear at the measured length, so exempting that field would
   lower the check for no measured benefit.
4. **Other checks still cover the field.** The path check (0016, check 2) and the boundary test's
   provenance check confirm the value is exactly what the raw record holds at
   `weatherConditions[0].metar`.

What the exemption cannot see: a factual-narrative sentence placed in a plain-English weather
value. The factual narrative is withheld because it is written toward the cause, so that would be
unwanted; it is judged acceptable because it is the least conclusive of the three withheld texts
and its sentences in the weather field are, in the cases measured, weather observations.

## What this rules out

- **Skipping every sentence comparison in the weather field.** Simpler. Rejected because an
  analysis or probable-cause sentence in one of the 35 plain-English values would pass unseen.
- **Skipping sentence comparisons only for coded weather values.** Keeps the full check on plain
  English. Rejected because the held-out case whose plain-English weather value the narrative
  repeats would stop with `LeakageError` and could not be evaluated.
- **One higher threshold for every field (about 250 characters).** No special case in the code.
  Rejected because it misses shorter copied sentences in every field to accommodate one.
- **Listing the two cases as exceptions.** Clears today's corpus exactly. Rejected because live
  cases will quote weather reports again and would then stop with false alarms.
- **Removing the weather report from evidence.** Removes the collision. Rejected because weather is
  often part of a probable cause, so it is evidence the agent needs.
- **Also exempting the manufacturer name.** Rejected for reason 3. The sentence splitter's handling
  of abbreviations is revisited when docket text becomes evidence in S2, where the re-run scan will
  show whether it matters.

## Status

Accepted, 2026-09-14.
