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
