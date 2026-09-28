# S2.7 round 3: loss of control in flight against aerodynamic stall/spin

- **Change:** adds `src/ntsb_probable_cause/scoring/guidance/r3-loc-stall.md` (text quoted
  below): where both codes appear in one phase, which one the NTSB flagged as defining, as a
  habit in the three phases where it is clear and as counts where it is not.
- **Stack:** the kept guidance before it, in order: none (round 2 was dropped).
- **Source (decision 0098 item 2):** the committed pool counts,
  `src/ntsb_probable_cause/scoring/tables/coding_stats.json`, read through
  `coding_stats.load_stats().pair(<phase>240, <phase>241)`: Maneuvering (450) both 36, loss of
  control defining 23, stall 8; Takeoff (300) 49, 33, 13; VFR pattern final (508) 24, 16, 6;
  Initial Climb (350) 84, 45, 29; Maneuvering-Low-alt flying (452) 32, 19, 11. The Initial Climb
  pair is also printed in `docs/results/s27-coding-stats.txt` (its "pairs occurring together"
  section lists only the 40 commonest pairs, so the others are cited from the JSON). A habit is
  stated only where it is clear (decision 0101: at least 60% of at least 20 cases): 23 of 36,
  33 of 49 and 16 of 24 are; 45 of 84 and 19 of 32 are not, so those are given as counts.
  Phases with fewer than 20 such cases are not mentioned.
- **The miss group it should shrink:** the commonest single miss, the NTSB's "Loss of control in
  flight" first where the model put "Aerodynamic stall/spin" first (33 of 399 on B-v1 in
  `docs/results/s27-round0-dev.txt`; 17 on B-v1 and 18 on the repeat after the Luna check,
  ad-hoc count 2026-09-28); Andy's hand-read marked the groups it falls in ("in sequence, not
  defining" and "a later guess in sequence") mostly "coding convention".
- **Reading rule:** decision 0098 item 4, applied by `scripts/round_result.py`; with-check scores
  decide, because Round 1 kept a check (`luna`).
- **Reference run:** `20260927T111202-fbab38a-dev-400-B-check-luna` (the repeat, checked; no
  round has been kept); **noise pair:** `20260926T082427-d19aafa-dev-400-B-check-luna` and
  `20260927T111202-fbab38a-dev-400-B-check-luna`.
- **Cost estimate:** about $1.10 for the arm B run (round 2's cost), $0.12 for the Luna check,
  and $0.81 for the judge if the round is kept; about $2.05 in all.
- **Prediction:** a small gain, under 2 points of checked top-1, because the Luna check already
  fixes about half of this miss; it will very probably be dropped, and if it is, the occurrence
  rounds end (decision 0098 item 5).
- **Local sentence check:** `scripts/check_guidance.py` passed on 2026-09-28 (8 guidance
  sentences against 13560 development cases; 0 found).

## The guidance text

    When a loss of control in flight and an aerodynamic stall or spin both appear in the same phase of flight, the NTSB flags one of them as the defining event.

    In the general Maneuvering phase, the NTSB flagged the loss of control in flight as the defining event in 23 of 36 past cases where both appeared, and the stall or spin in 8. In the Takeoff phase, it flagged the loss of control in 33 of 49 such cases and the stall or spin in 13. On the VFR pattern final approach, it flagged the loss of control in 16 of 24 such cases and the stall or spin in 6. In these three phases, put Loss of control in flight first unless the evidence shows that the stall itself, not a loss of control, began the accident sequence, and keep the stall or spin among your guesses.

    In the other phases the choice was closer. In Initial Climb the loss of control was defining in 45 of 84 such cases and the stall or spin in 29; in Maneuvering-Low-alt flying, in 19 of 32 and in 11. There, code first whichever the evidence shows began the accident sequence.

## Result (scripts/round_result.py, decision 0098 item 4)

- run: 20260928T144353-031e97e-dev-400-B-check-luna; reference: 20260927T111202-fbab38a-dev-400-B-check-luna; noise pair: 20260926T082427-d19aafa-dev-400-B-check-luna, 20260927T111202-fbab38a-dev-400-B-check-luna
- occurrence top-1: +4.8% [+0.8%, +8.8%] on n=399
- noise floor (occurrence top-1, the two identical runs): 1.0%
- finding recall@10 (do no harm): -0.9% [-2.5%, +0.8%] on n=397
- first codes changed: 180; toward a more common option: 89, fixes 26, breaks 8 (decision 0101 item 4)
- outcome: kept
