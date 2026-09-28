# S2.7 round 4: a fuel problem before the loss of engine power

- **Change:** adds `src/ntsb_probable_cause/scoring/guidance/r4-fuel-power.md` (text quoted
  below): where fuel starvation or fuel exhaustion and a loss of engine power both appear, which
  one the NTSB flagged as defining, as a habit for the three pairs where it is clear.
- **Stack:** the kept guidance before it, in order: `r3-loc-stall`.
- **Source (decision 0098 item 2):** the committed pool counts,
  `src/ntsb_probable_cause/scoring/tables/coding_stats.json`, read through
  `coding_stats.load_stats().event_pair(<event>, <event>)`, which sums `pair` over every phase
  (added with this round; it counts code pairs, so a case holding one event under two phases
  counts once per pair): fuel exhaustion (192) with total loss of engine power (341) both 240,
  fuel exhaustion defining 173, power loss 56; fuel starvation (191) with 341, 213, 136, 59;
  fuel starvation with partial loss of engine power (342), 30, 20, 5. Each is a clear habit
  (decision 0101: at least 60% of at least 20 cases). Not stated: "Fuel related" (190) with 341,
  21 of 40 (not clear); fuel contamination (193) with 341, 18 of 19, and fuel exhaustion with 342,
  4 of 4 (under 20 cases each). The data dictionary gives no definition for occurrence events, so
  none is quoted.
- **The miss group it should shrink:** "in sequence, not defining" and "a later guess in
  sequence" where the NTSB's defining event is a fuel event and the model's first guess is a loss
  of engine power. On Round 3's checked run, `scripts/occurrence_misses.py` lists "Fuel
  starvation -> Loss of engine power (total)" at 5; with fuel contamination and fuel exhaustion,
  8 cases (ad-hoc count, 2026-09-28).
- **Reading rule:** decision 0098 item 4, applied by `scripts/round_result.py`; with-check scores
  decide, because Round 1 kept a check (`luna`).
- **Reference run:** `20260928T144353-031e97e-dev-400-B-check-luna` (Round 3, kept, checked);
  **noise pair:** `20260926T082427-d19aafa-dev-400-B-check-luna` and
  `20260927T111202-fbab38a-dev-400-B-check-luna`.
- **Cost estimate:** about $1.18 for the arm B run (Round 3's cost), $0.11 for the Luna check,
  and $0.81 for the judge if the round is kept; about $2.10 in all.
- **Prediction:** a small gain, under 2 points of checked top-1, because the group it targets
  holds about 8 cases; it will very probably be dropped.
- **Local sentence check:** `scripts/check_guidance.py` passed on 2026-09-28 (5 guidance
  sentences against 13560 development cases; 0 found).

## The guidance text

    When fuel starvation or fuel exhaustion and a loss of engine power both appear in a case, the NTSB flags one of them as the defining event.

    Where fuel exhaustion and a total loss of engine power both appeared, the NTSB flagged the fuel exhaustion as the defining event in 173 of 240 past cases, and the loss of engine power in 56. Where fuel starvation and a total loss of engine power both appeared, it flagged the fuel starvation in 136 of 213 such cases, and the loss of engine power in 59. Where fuel starvation and a partial loss of engine power both appeared, it flagged the fuel starvation in 20 of 30 such cases, and the loss of engine power in 5.

    When the evidence shows that the engine lost power because of fuel starvation or fuel exhaustion, put that fuel event first, and keep the loss of engine power among your guesses.
