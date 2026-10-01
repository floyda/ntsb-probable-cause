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

# S3 rounds

One file per tuning round of the agent loop, `s3-round-<N>.md`, numbered from 1 (S3 spec §10.3,
decision 0130 item 4). It is committed **before** the round's run: `ntsb-eval run --arm C --round
<N>` (`make s3-round N=<N>`) refuses the round until `docs/rounds/s3-round-<N>.md` is committed,
and records the round in the run's `spec.json` and in its prompt version (`+r<N>`). The change
itself is committed on the branch before the run too, so the commit the run records holds it.
After the run, `make s3-round-result` appends the result below the registration, and nothing
above it is edited.

Nothing is bumped by hand for a change of text. The agent's prompt version is
`s3-v1+g<guidance>+p<text>`, then `+r<N>` for a round (decision 0133). `+p` is the first twelve
characters of `texts.agent_text_sha256()`, a fingerprint of the source of every module that
holds or composes the text the agent sends (`texts.TEXT_SOURCES`): `scoring/prompt.py`,
`scoring/hypothesis.py`, `scoring/codes.py`, and `agent/texts.py`, `steps.py`, `tools.py`,
`schemas.py`, `later.py`, `loop.py` and `armb.py`, with the tool definitions and the refinement
schema as sent. A round that changes the protocol, a step text, a tool's wording or a tool
description changes `+p`; so does any other edit to those files, a comment included (a false
change only separates runs). A plain run made after a kept round therefore never shares a version
with the noise-floor runs. `scripts/s3_noise_floor.py` refuses two runs whose versions differ,
and a resume across a change of text is refused. `resolve_latest` still takes any run with S3's
guidance and no `+r` as plain arm C, whatever its `+p`. Arm B's tool post-pass label carries the
same `+p` after `+tools-s3`. A change to the step limits shows in `spec.json`.

A round is read against the loop's own noise floor: the two (or three) identical arm C runs on
`dev-400` that `make s3-noise-report` reads into `docs/results/s3-noise-floor-dev.txt`. S2.7's
noise floor is for a single answer, not for the loop (decision 0130, Why 1).

## Template (S3)

    # S3 round <N>: <one-line change>

    - **Change:** <what changes, the files that change, and the commit>. A round changes only
      the prompt texts (the protocol in `agent/texts.py`, for example), the tool descriptions
      (`agent/schemas.py`) or the step limits (spec §10.3). Calibration waits for S3.2. One change
      per round, so that the score says which change moved it (decision 0098, Why 1).
    - **Why:** <the pattern in the trails it answers, as counts>.
    - **Cases read to design it:** <the group, and how many trails were read>. The cases are chosen
      by script, never by hand: `scripts/s3_case_groups.py` sorts `dev-400` into always right,
      always wrong and flipping, across the noise-floor runs and the existing arm B runs (plan
      Task 15). Cases are never picked from arm B's misses.
    - **Reading rule:** decision 0098 item 4, applied to arm C runs by `scripts/round_result.py`
      (`make s3-round-result`). Kept only if the occurrence top-1 gain's interval lies above zero
      and the gain is larger than the noise floor (the absolute top-1 difference between the two
      noise-floor runs named below). Dropped if finding recall@10's paired difference lies wholly
      below zero. **Failures count in "do no harm"** (spec §8.4, §10.3): a failed case leaves
      `n`, so a round that fails more cases can look better than it is. The run's failures by
      reason and its format-gate count (as `scripts/s3_noise_floor.py` defines them) are read
      beside the reference run's. <State here, before the run, the rise in failed cases that
      drops the round.>
    - **Reference run:** <run id: the last kept round, or noise-floor run a>; **noise pair:**
      <noise-floor run a> and <noise-floor run b>.
    - **Cost estimate:** <$, from the last arm C run's cost per case>.
    - **Prediction:** <the direction and rough size of the change, one line>.
    - **Leak check:** <how each new or changed sentence the model will see was checked, and the
      date>. The rule is S2.7's: no sentence of 30 characters or more may appear in any
      development case's factual narrative, analysis narrative or probable cause. A guidance file
      is checked by `make s27-check-guidance GUIDANCE=<names>`; the agent's own texts (the
      protocol and the fixed strings of `agent/texts.py` and `agent/steps.py`, and the tool
      definitions of `agent/schemas.py`) by `uv run python -m scripts.check_guidance
      --agent-texts`. Say how any other new text was checked.
    - **Stop rule:** <the rounds dropped in a row before this one; S3.1's spend so far, from
      `make s3-spend`>. Two dropped rounds in a row end the rounds, and so does S3.1's share of
      S3's spend line being spent ($20 of $50; spec §14, plan Task 15).

    ## The change

    <the new or changed text, verbatim; or the step limits, before and after>
