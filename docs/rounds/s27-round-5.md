# S2.7 round 5: the sub-phase over the general phase code, in three families

- **Change:** adds `src/ntsb_probable_cause/scoring/guidance/r5-sub-phases.md` (text quoted
  below): in the Approach, Enroute and Landing families, the NTSB's habit of coding the defining
  event under a sub-phase rather than the general code, as counts and one instruction.
- **Also in this run, not part of the guidance:** decision 0105's table fix (phases 553 and 601,
  events 281, 282, 284 and 850; prompt version `s1-v6`). The reference run does not have it. It
  is not read under decision 0098 item 4 and stays whatever this round's outcome; the result is
  read with `SUPPLEMENT=1`, which adds the line for the cases an added code touches.
- **Stack:** the kept guidance before it, in order: `r3-loc-stall` (Round 4 was dropped).
- **Source (decision 0098 item 2):** the committed pool counts,
  `src/ntsb_probable_cause/scoring/tables/coding_stats.json`, read through
  `coding_stats.load_stats().group_phases(<group>)` and `group_n(<group>)`: Approach 1403 cases,
  general code 500 in 307, a sub-phase in 1096; Enroute 1994, 400 in 493, a sub-phase in 1501;
  Landing 4306, 550 in 1199, a sub-phase in 3107, of which 553 in 92. Each group's defining codes
  all lie in its own family. Each is a clear habit (decision 0101: at least 60% of at least 20
  cases): 78.1%, 75.3% and 72.2%. Not stated: Maneuvering (a sub-phase in 681 of 1302, 52.3%, not
  clear) and Takeoff (the general code in 1341 of 1489, the other way round). Round 2 (dropped)
  listed each sub-phase's own count and stated no habit, because no single sub-phase reached 60%;
  this round states the family-level habit those counts add up to.
- **The miss group it should shrink:** "right event, wrong phase": 50 of 399 on Round 3's checked
  run (`scripts/occurrence_misses.py`). Of those, 26 are a general code where the NTSB used a
  sub-phase of the same family, 16 of them in these three families; 10 of Round 3's top-1 hits
  in these families use the general code and could be broken (ad-hoc counts, 2026-09-28).
- **Reading rule:** decision 0098 item 4, applied by `scripts/round_result.py`; with-check scores
  decide, because Round 1 kept a check (`luna`).
- **Reference run:** `20260928T144353-031e97e-dev-400-B-check-luna` (Round 3, the last kept
  round, checked); **noise pair:** `20260926T082427-d19aafa-dev-400-B-check-luna` and
  `20260927T111202-fbab38a-dev-400-B-check-luna`.
- **Cost estimate:** about $1.25 for the arm B run (Round 4's cost), $0.11 for the Luna check,
  and $0.81 for the judge if the round is kept; about $2.20 in all.
- **Prediction:** a gain of 1 to 2 points of checked top-1 at most, with some of the 10 hits at
  risk broken; it will very probably be dropped, and if it is, the occurrence rounds end
  (decision 0098 item 5, two dropped rounds in a row). Round 4's note applies: runs move more
  than the noise floor says, so the reference (Round 3, the highest run so far) is hard to beat.
- **Local sentence check:** `scripts/check_guidance.py` passed on 2026-09-28 (3 guidance
  sentences against 13560 development cases; 0 found).

## The guidance text

    Phase codes come in families: a general code, such as 500 Approach, 400 Enroute or 550 Landing, and more specific sub-phase codes within it, such as 508 Approach-VFR Pattern Final, 402 Enroute-Cruise or 552 Landing-Landing Roll.

    When the phase-of-flight group recorded in the evidence is Approach, Enroute or Landing, the NTSB coded the defining event under a sub-phase, not the general code, in most past cases: in 1096 of 1403 Approach cases, in 1501 of 1994 Enroute cases, and in 3107 of 4306 Landing cases, 92 of them under 553 Landing-aborted after touchdown.

    In these three families, code the defining event under the sub-phase the evidence places it in, and use the general code only when the evidence does not show which part of the approach, the en route flight or the landing the event happened in.
