# S2.7 rounds

One file per guidance round, `s27-round-<N>.md` (decision 0098 item 3), committed **before** the
round's run; the runner refuses guidance whose registration is not committed. The result is
appended below the registration after the run, by `scripts/round_result.py`, and nothing above
it is edited. `s27-sealed.md` registers the final setup before the sealed sample is opened
(decision 0095).

## Template

    # S2.7 round <N>: <one-line change>

    - **Change:** adds `src/ntsb_probable_cause/scoring/guidance/r<N>-<slug>.md` (text quoted below).
    - **Stack:** the kept guidance before it, in order: <names or "none">.
    - **Source (decision 0098 item 2):** <the counts in docs/results/s27-coding-stats.txt it quotes,
      or the official definition it cites>.
    - **The miss group it should shrink:** <group>, from docs/results/s27-round0-dev.txt.
    - **Reading rule:** decision 0098 item 4, applied by scripts/round_result.py; with-check scores
      decide if Round 1 kept a check (<way or "no check">).
    - **Reference run:** <run id>; **noise pair:** <B-v1 run id> and <repeat run id>.
    - **Cost estimate:** <$, from the last run's cost per case>.
    - **Prediction:** <one line>.
    - **Local sentence check:** `scripts/check_guidance.py` passed on <date>.

    ## The guidance text

    <the file's text, verbatim>
