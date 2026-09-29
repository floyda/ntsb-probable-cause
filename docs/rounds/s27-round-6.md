# S2.7 round 6 (finding round 1): Aircraft control / Pilot, with the parameter not held

- **Change:** adds `src/ntsb_probable_cause/scoring/guidance/r6-aircraft-control.md` (text
  quoted below): for the three defining events loss of control on ground, loss of control in
  flight and aerodynamic stall/spin, which findings the NTSB flagged in the probable cause, as
  counts, and one instruction. It is in the answering turn's system text only, like every
  earlier round; the item-choice turn does not see it (Andy, 2026-09-29: "keep it the same for
  now so A").
- **Stack:** the kept guidance before it, in order: `r3-loc-stall` (Rounds 4 and 5 were
  dropped). This run has decision 0105's table fix; the reference (Round 3) does not. It touched
  19 cases' sequences and gained no top-1 hit in Round 5.
- **Source (decision 0098 item 2):** the committed pool counts,
  `src/ntsb_probable_cause/scoring/tables/coding_stats.json`, read through
  `coding_stats.load_stats().findings_given_event(<event>)` (added 2026-09-29; also printed in
  `docs/results/s27-coding-stats.txt`, "flagged findings by defining event"). Loss of control on
  ground (230): 2055 cases; `0206304044` Aircraft control / Pilot 1420, `0106202020` Directional
  control / Not attained/maintained 1498, `0204101544` Incorrect action performance / Pilot 76.
  Aerodynamic stall/spin (241): 472; 335, `0106201020` Airspeed / Not attained/maintained 286,
  48. Loss of control in flight (240): 1784; 1094; `0106200020` 358, `0106201020` 301,
  `0106202020` 208; 95. Stated as a habit (decision 0101: at least 60% of at least 20): Aircraft
  control / Pilot in all three (69.1%, 71.0%, 61.3%), Directional control in 230 (72.9%) and
  Airspeed in 241 (60.6%); the parameters in 240 are counts only. The data dictionary's
  definitions for these items read "(under development)", so none is quoted. The counts are
  conditioned on the defining event, which the model chooses itself (the round 4 lesson in the
  plan's Deviations).
- **The miss group it should shrink:** finding misses with the category wrong (833 of 1,111
  flagged findings on Round 3's checked run, `scripts/occurrence_misses.py`). On that run the
  NTSB flags Aircraft control / Pilot in 138 of 399 cases and the model chose it once; the NTSB
  flags modifier 20 202 times and the model chose it once; in 96 cases the model's first event is
  230, 240 or 241 and the NTSB flags Aircraft control / Pilot (ad-hoc counts, 2026-09-29).
- **Reading rule:** decision 0098 item 4 the other way round, for a finding round
  (`make s27-round-result FINDING=1`): kept on finding recall@10 (lower bound above zero and the
  gain above the noise pair's finding recall difference, 1.7 points), not kept if occurrence
  top-1 falls wholly below zero. With-check scores decide (`luna`; the check reorders occurrence
  codes only).
- **Reference run:** `20260928T144353-031e97e-dev-400-B-check-luna` (Round 3, the last kept
  round, checked); **noise pair:** `20260926T082427-d19aafa-dev-400-B-check-luna` and
  `20260927T111202-fbab38a-dev-400-B-check-luna`.
- **Cost estimate:** about $1.20 for the arm B run (Round 5's cost), $0.11 for the Luna check,
  and $0.81 for the judge if the round is kept; about $2.15 in all.
- **Prediction:** a gain of 3 to 8 points of finding recall@10, most of it from Aircraft control /
  Pilot in the 96 cases above, with occurrence top-1 unchanged; probably kept. The item-choice
  turn may pick another item in category 020630 for some; the result's finding depth shows it.
- **Local sentence check:** `scripts/check_guidance.py` passed on 2026-09-29 (6 guidance
  sentences against 13560 development cases; 0 found).

## The guidance text

    When the defining event is a loss of control or a stall, the NTSB usually flags the pilot's control of the aircraft as a finding in the probable cause, together with the flight parameter that was not held.

    Where the defining event was Loss of control on ground, the NTSB flagged item 02063040 Aircraft control (category 020630) with modifier 44 Pilot in 1420 of 2055 past cases, and item 01062020 Directional control (category 010620) with modifier 20 Not attained/maintained in 1498. Where it was Aerodynamic stall/spin, it flagged Aircraft control with modifier Pilot in 335 of 472 such cases, and item 01062010 Airspeed with modifier Not attained/maintained in 286. Where it was Loss of control in flight, it flagged Aircraft control with modifier Pilot in 1094 of 1784 such cases; the parameter varied, with modifier Not attained/maintained: item 01062000, the general performance/control parameters item, in 358, Airspeed in 301 and Directional control in 208. In the same three groups it flagged item 02041015 Incorrect action performance with modifier Pilot in only 76, 48 and 95 cases.

    When your defining event is one of these three and the evidence shows the aircraft was not kept under control, include Aircraft control with modifier Pilot among your findings (modifier 46 Student pilot when a student pilot was flying), and the parameter the evidence shows was not held, with modifier Not attained/maintained.

## Result (scripts/round_result.py, decision 0098 item 4)

- run: 20260929T053953-674c92e-dev-400-B-check-luna; reference: 20260928T144353-031e97e-dev-400-B-check-luna; noise pair: 20260926T082427-d19aafa-dev-400-B-check-luna, 20260927T111202-fbab38a-dev-400-B-check-luna
- finding recall@10: +11.4% [+8.2%, +14.6%] on n=397
- noise floor (finding recall@10, the two identical runs): 1.7%
- occurrence top-1 (do no harm): -6.3% [-10.5%, -2.5%] on n=399
- first codes changed: 171; toward a more common option: 83, fixes 13, breaks 19 (decision 0101 item 4)
- outcome: dropped: harm to the other score (interval wholly below zero)

## Note (ad-hoc counts, 2026-09-29; not part of the reading)

- Checked scores across the runs: top-1 / finding recall@10 — B-v1 27.6% / 10.4%, the repeat
  26.6% / 12.1%, Round 3 31.3% / 11.2%, Round 4 27.3% / 10.3%, Round 5 27.8% / 9.9%, Round 6
  25.1% / 22.6%. Findings given per case rose from about 1.7 to 2.20.
- Round 6 against the other runs that carry Round 3's guidance: Round 4, top-1 -2.3% [-6.3%,
  +1.8%], recall +12.3% [+9.1%, +15.4%]; Round 5, top-1 -2.8% [-7.0%, +1.3%], recall +12.7%
  [+9.8%, +15.8%]. Against the repeat: top-1 -1.5% [-5.8%, +2.5%], recall +10.5% [+7.2%,
  +13.7%].
- First guesses on loss of control or stall events: 186, against 168-183 in the earlier runs.
- The outcome above stands as the rule gives it: dropped, on harm to top-1 against the reference.

## Override (decision 0106)

Kept by override of the do-no-harm rule, 2026-09-29 (Andy: "I think option B, its clearly
something to pursue at a later stage"). The outcome above is left as the rule gave it. Round 6's
guidance stacks after `r3-loc-stall`, and its checked run,
`20260929T053953-674c92e-dev-400-B-check-luna`, is the reference for any later round.

The numbers above ("Note", this section) are reproduced from committed code, free and local, by
`make s27-round-comparisons` (`scripts/round_comparisons.py`); `docs/results/s27-round-comparisons-dev.txt` holds the run, no figure differs (final review, I2/M2).

## Judge outcomes (plan Task 15 Step 8)

The earlier run is Round 3's checked folder (judged 2026-09-28). The misread count moved from 99 to 109, inside Round 0's label churn (123 of 399 cases change outcome between two identical runs), so it does not show the finding guidance changing how the evidence is read. The narrative label is unvalidated (decision 0099). Judge cost $0.8187.

judge outcomes (scripts/judge_outcomes.py; counts only, decision 0099)

## 20260928T144353-031e97e-dev-400-B-check-luna -- outcomes (unvalidated narrative label, decision 0099)
all (399 cases):
  right: 125 of 399; cause label: different 20, related 57, same_cause 48
  understood, miscoded: 139 of 399; cause label: related 78, same_cause 61
  thin evidence: 36 of 399; cause label: different 2, related 30, same_cause 4
  misread: 99 of 399; cause label: different 60, related 33, same_cause 6
fatal (198 cases):
  right: 67 of 198; cause label: different 11, related 28, same_cause 28
  understood, miscoded: 79 of 198; cause label: related 43, same_cause 36
  thin evidence: 14 of 198; cause label: different 1, related 12, same_cause 1
  misread: 38 of 198; cause label: different 22, related 15, same_cause 1
non-fatal (201 cases):
  right: 58 of 201; cause label: different 9, related 29, same_cause 20
  understood, miscoded: 60 of 201; cause label: related 35, same_cause 25
  thin evidence: 22 of 201; cause label: different 1, related 18, same_cause 3
  misread: 61 of 201; cause label: different 38, related 18, same_cause 5

## 20260929T053953-674c92e-dev-400-B-check-luna -- outcomes (unvalidated narrative label, decision 0099)
all (399 cases):
  right: 100 of 399; cause label: different 17, related 47, same_cause 36
  understood, miscoded: 151 of 399; cause label: related 83, same_cause 68
  thin evidence: 39 of 399; cause label: different 1, related 34, same_cause 4
  misread: 109 of 399; cause label: different 63, related 38, same_cause 8
fatal (198 cases):
  right: 48 of 198; cause label: different 9, related 23, same_cause 16
  understood, miscoded: 85 of 198; cause label: related 48, same_cause 37
  thin evidence: 19 of 198; cause label: related 17, same_cause 2
  misread: 46 of 198; cause label: different 27, related 16, same_cause 3
non-fatal (201 cases):
  right: 52 of 201; cause label: different 8, related 24, same_cause 20
  understood, miscoded: 66 of 201; cause label: related 35, same_cause 31
  thin evidence: 20 of 201; cause label: different 1, related 17, same_cause 2
  misread: 63 of 201; cause label: different 36, related 22, same_cause 5
