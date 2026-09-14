# 0023 — Evidence arrives by source, and availability is masked from measured arrival

## Context

A live investigation does not have all its evidence at once. The spike's fresh-case profile
(`scripts/fresh_case_profile.py`) found pilot hours on 0% of cases in their first two weeks
and a METAR in the record on 17%. The preliminary narrative appears on about 40% of cases
after some weeks and is deleted at closure, and docket documents arrive over months. Closed
cases, which evaluation uses, have everything at once, less the preliminary narrative.

S0 built one route from a case record to the model: `split_record(raw, exclude=…)` builds
the only `Evidence` object and runs the tripwire, and `Payload.from_evidence` renders it
(0016). S0's evidence roles do not include event date or location (`fields.py`), and the
spike never sent them. Amateur-built make and model are a fixed label (0020). The preliminary
narrative is empty in all 19,641 processed cases, which are all closed
(`docs/results/s0-corpus-scan.txt`).

## Decision

1. The agent starts from **start facts** — the evidence roles a live case has on day 1:
   phase of flight, injury level, aircraft make and model, engine type, and the aircraft
   registration unless S1's ablation removes it. Everything else comes through tools grouped
   by source: pilot details, the record's weather fields, the preliminary narrative, the
   docket listing, and one docket document
   ([agency design §3.1](../specs/2026-09-14-agency-hypothesis-trail-design.md)).
2. A field goes behind a tool only when it is measured to arrive late or, for docket
   documents, measured to be large enough that choosing is a real decision. Day-1 fields are
   never put behind a tool.
3. A tool never reads the raw record. Its result is the payload of the same `split_record`
   with every evidence role outside the tool excluded, so there is one payload assembler and
   the tripwire runs on every tool call. Arm A and the masked condition are exclusion sets.
4. Two **availability conditions** are reported. **Full**: everything the closed case holds in
   evidence roles, and the docket at closure. **Masked**: only what a live case would have at
   day *N*, from the spike's structured-field profile until the recorder (S2.5) measures
   structured-field and docket arrival on ongoing cases.
5. The preliminary narrative is absent from every offline evaluation. The recorder stores it
   each time it sees it, so that masked evaluation can include it for captured cases.
6. Event date and location are not evidence and not start facts. The weather archive, after
   S3, may use them as bookkeeping that is never rendered, and archive values need their own
   provenance rule before they reach a model.

## Why

1. **It is where agency can be real.** When evidence is missing, deciding whether to answer,
   what to fetch next or to abstain is a genuine decision, measured against a genuine absence.
2. **A tool with no measured reason is a pipeline in costume.** Putting day-1 fields behind a
   tool manufactures a decision the agent would never face live.
3. **It adds no second route to the model.** Tools and masks reuse the guarded split, so the
   single rule the project's credibility rests on (0013, 0016) holds for every call.
4. **The mask is measured, not chosen.** A mask invented to make the agent look busy would
   describe a situation that does not exist.
5. **Date, location and registration are recall handles.** With the case number kept out of
   the payload (S0 specification §8), they are the remaining easy routes to a remembered
   report. The registration is already ablated in S1; date and location are simply not added.

## What this rules out

- **One payload with every evidence role.** Simplest, and the spike's shape. Rejected as the
  only shape because it has no decision in it; it remains arm B.
- **Aircraft details behind a tool.** The first draft's option. Rejected for reason 2.
- **A separate assembler per tool.** Tools could read the record directly. Rejected: a second
  assembler is what 0016 forbids.
- **A masked condition from judgement.** Available now. Rejected for reason 4.
- **The Iowa Mesonet archive in S3.** Recovers weather on live cases (spike A10). Rejected for
  S3 because an archive value has no raw path, so the path and provenance checks cannot vouch
  for it (0016, 0019).

## Status

Accepted on Andy's squash merge of the pull request that carries the agency design revision,
2026-09-14.
