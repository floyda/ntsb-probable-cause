# S2.7 round 2: phase families, with the NTSB's past phase choices listed as counts

- **Change:** adds `src/ntsb_probable_cause/scoring/guidance/r2-phase-families.md` (text quoted
  below): one sentence on phase families, then, for the four largest phase-of-flight groups,
  the NTSB's past phase choices as counts, and a closing sentence that the evidence decides.
- **Stack:** the kept guidance before it, in order: none.
- **Source (decision 0098 item 2):** the "phase groups" section of
  `docs/results/s27-coding-stats.txt` (the Approach, Enroute, Landing and Maneuvering lines).
  No option is stated as a habit: none of the four groups has a phase at 60% of its cases or
  more (decision 0101), so the text lists the options with their counts and says the evidence
  decides. The Landing group's 92 cases under phase `553` are not quoted: the code tables the
  model receives have no entry for `553`, so it cannot choose it (reported separately).
- **The miss group it should shrink:** "right event, wrong phase" (61 of 399 on B-v1, and 62 and
  57 after the Luna check on B-v1 and the repeat), from `docs/results/s27-round0-dev.txt` and
  Round 1's derived folders; Andy's hand-read marked all 8 of its cards "wrong phase". Of the 61,
  50 were a general code against a specific sub-phase of the same family, in both directions
  (ad-hoc count, 2026-09-28).
- **Reading rule:** decision 0098 item 4, applied by `scripts/round_result.py`; with-check scores
  decide, because Round 1 kept a check (`luna`, confirmed by decision 0103's second Jev
  comparison).
- **Reference run:** `20260927T111202-fbab38a-dev-400-B-check-luna` (the repeat, checked);
  **noise pair:** `20260926T082427-d19aafa-dev-400-B-check-luna` and
  `20260927T111202-fbab38a-dev-400-B-check-luna` (their top-1 difference: +1.0% [-3.0%, +5.0%]).
- **Cost estimate:** about $1.16 for the arm B run (the repeat's cost), $0.12 for the Luna check,
  and $0.81 for the judge if the round is kept; about $2.10 in all.
- **Prediction:** a small gain, 1 to 3 points of checked top-1 over the reference, mostly in the
  "right event, wrong phase" group, with finding recall@10 unchanged; it may well be dropped as
  inside the noise.
- **Local sentence check:** `scripts/check_guidance.py` passed on 2026-09-28 (7 guidance
  sentences against 13560 development cases; 0 found).

## The guidance text

    Phase codes come in families: a general code, such as 400 Enroute or 550 Landing, and more specific sub-phase codes, such as 402 Enroute-Cruise or 552 Landing-Landing Roll. For the defining event, choose the phase code the evidence places the event in.

    When the phase-of-flight group recorded in the evidence is Enroute, the NTSB coded the defining event under Enroute-Cruise in 1105 of 1994 past cases, under the general Enroute code in 493, under Enroute-Climb to cruise in 202 and under Enroute-Descent in 178.

    When the group is Maneuvering, the NTSB used the general Maneuvering code in 621 of 1302 past cases, Maneuvering-Low-alt flying in 500, Maneuvering-Hover in 103 and Maneuvering-Aerobatics in 78.

    When the group is Landing, the NTSB used Landing-Landing Roll in 1663 of 4306 past cases, Landing-Flare/Touchdown in 1352 and the general Landing code in 1199.

    When the group is Approach, the NTSB used Approach-VFR Pattern Final in 466 of 1403 past cases, the general Approach code in 307, Approach-VFR Go-Around in 230, Approach-VFR Pattern Downwind in 142 and Approach-VFR Pattern Base in 130, with fewer under the other approach codes.

    None of these counts is a rule: code the part of the flight the evidence places the event in.

## Result (scripts/round_result.py, decision 0098 item 4)

- run: 20260928T110233-2402e72-dev-400-B-check-luna; reference: 20260927T111202-fbab38a-dev-400-B-check-luna; noise pair: 20260926T082427-d19aafa-dev-400-B-check-luna, 20260927T111202-fbab38a-dev-400-B-check-luna
- occurrence top-1: +2.5% [-1.8%, +6.8%] on n=399
- noise floor (occurrence top-1, the two identical runs): 1.0%
- finding recall@10 (do no harm): -1.4% [-3.2%, +0.3%] on n=397
- first codes changed: 197; toward a more common option: 98, fixes 30, breaks 9 (decision 0101 item 4)
- outcome: dropped: the gain's interval includes zero
