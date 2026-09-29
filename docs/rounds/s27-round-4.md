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

## Result (scripts/round_result.py, decision 0098 item 4)

- run: 20260928T165443-1c9ecdf-dev-400-B-check-luna; reference: 20260928T144353-031e97e-dev-400-B-check-luna; noise pair: 20260926T082427-d19aafa-dev-400-B-check-luna, 20260927T111202-fbab38a-dev-400-B-check-luna
- occurrence top-1: -4.0% [-7.8%, -0.3%] on n=399
- noise floor (occurrence top-1, the two identical runs): 1.0%
- finding recall@10 (do no harm): -0.9% [-2.4%, +0.7%] on n=397
- first codes changed: 174; toward a more common option: 69, fixes 14, breaks 10 (decision 0101 item 4)
- outcome: dropped: the gain's interval includes zero

## Note (ad-hoc counts, 2026-09-28; not part of the reading)

The fall is not only in the cases the guidance speaks to. Checked top-1 hits among the 87 cases
whose NTSB defining event is a fuel or engine-power event: B-v1 23, the repeat 27, Round 2 33,
Round 3 35, Round 4 28; among the 117 whose defining event is loss of control or stall: 38, 36,
41, 47, 41. Runs with no fuel guidance already differ by up to 12 hits in the fuel group, so the
difference between two identical runs (1.0 point on one pair) understates how much a run moves.
Round 4 against the repeat is +0.8% [-3.3%, +5.0%]. The sealed sample (decision 0095) is where
the kept stack is tested on cases no round was read on.
