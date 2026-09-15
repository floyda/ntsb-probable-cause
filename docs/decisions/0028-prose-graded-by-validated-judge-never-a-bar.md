# 0028 — Prose outputs are graded by a validated judge, and are never a bar

## Context

The model writes three texts: its own evidence narrative (0013), a probable-cause sentence,
and a lay explanation the public page needs (0006). None can be scored by exact match. The
spike's one model judge was wrong in one direction, rejecting 14 of 23 answers a human had
accepted (`../ntsb-spike/scripts/ablation_phase.py`), which is why 0006 made the headline
code-constrained. The roadmap left the grading method to S1.

## Decision

1. A judge model from a different family than the answerer, Haiku 4.5, is given a fixed
   rubric and returns labels only: for the evidence narrative against the withheld factual
   narrative, `consistent` / `contradicts` / `adds unsupported facts`; for the
   probable-cause sentence against the NTSB's, `same cause` / `related` / `different`; for
   the lay explanation against the model's own codes, whether it explains them in plain
   language.
2. The judge is validated on `dev-400` before it touches a held-out run: its `same cause`
   label is compared with the code scores as a confusion table, and Andy hand-checks 30
   disagreements chosen at random with a seed. The sheet is committed without case IDs or
   verdict text.
3. The judge is used on held-out runs only if its agreement with the code layer is at least
   the spike's 62.5% and the hand-check shows no one-sided error. Otherwise the prose is
   published labelled "unchecked by a validated judge".
4. Judge labels are reported and are never a bar the agent must clear.
5. The judge's payload is the only payload that carries withheld text. It is built in
   `scoring/judge.py`, the tripwire is not run on it, and the boundary test asserts it never
   reaches the answering client.

## Why

1. **A judge is measured before it is trusted**, because the spike showed what an
   unmeasured one does.
2. **A different family** so that grader and answerer do not share blind spots.
3. **Labels, not scores**, so the judge cannot invent a scale.
4. **Never a bar**, so that the headline claim rests only on exact match.

## What this rules out

- **No grading at all.** Free text going public with no quality measure is the shortcut the
  project exists to avoid.
- **The answering model as its own judge.** Self-grading shares every bias.
- **A judge score in the headline.** Rejected in 0006 and again here.

## Status

Accepted.
