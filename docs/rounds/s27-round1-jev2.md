# S2.7 Round 1, second Jev check (`jev2`): registration

Decision [0103](../decisions/0103-a-registered-second-jev-check.md). Committed before any code
for `jev2` is written and before any call is made. Nothing below is changed after the first
call; a different design is a new registration.

## What runs

- **Way:** `jev2`, through `ntsb-eval check RUN --way jev2`, a post-pass like the other ways
  (plan W2). Derived folders: `<run id>-check-jev2`.
- **Answer sets:** B-v1 `20260926T082427-d19aafa-dev-400-B` and its repeat
  `20260927T111202-fbab38a-dev-400-B` (Round 1's two).
- **Model:** `jev-1.13.0`, pinned by name, not the `jev-latest` alias.
- **Candidates:** the same list as Round 1 (`ordering.candidates`, decision 0096 item 3),
  plus one extra option, `none_of_these`.
- **Calls:** one request per case, one question in it.

## The state (an object, not text)

The state is a JSON object with four named fields:

- `phase_of_flight_group`: the phase group recorded as evidence, or `"not recorded"`.
- `analyst_guesses`: the model's occurrence guesses, in its order, each
  `{"code": "<six digits>", "meaning": "<phase words> / <event words>"}`.
- `candidates`: one entry per candidate code, in the candidate list's order, each
  `{"code", "meaning", "past_cases_when_it_appears", "past_cases_in_this_phase_group"}`, and,
  for every candidate except the first guess, `"past_cases_with_the_first_guess"`.
- `analyst_account`: the model's own account of the evidence (`evidence_narrative`), unchanged.

No count or share appears as a number. Each is written as words, by these rules only:

| field | the share | its base |
|---|---|---|
| `past_cases_when_it_appears` | past cases containing the code where it is the defining event | past cases containing the code |
| `past_cases_in_this_phase_group` | this group's past cases whose defining event is the code | this group's past cases |
| `past_cases_with_the_first_guess` | past cases containing both codes where this code is the defining event | past cases containing both codes |

Words, applied in this order:

1. base under 20: `"too few past cases to say"`;
2. share at least 3/5: `"usually the defining event (a clear habit)"` (decision 0101: 60% of
   at least 20);
3. share at least 1/4: `"often the defining event"` (decision 0096 item 3: 1/4 of at least 20);
4. share above 0: `"seldom the defining event"`;
5. share 0: `"never the defining event in past cases"`.

The counts are the committed pool's (`scoring/tables/coding_stats.json`, decision 0094).

## The question

One Choice question, named `defining`:

- `instructions`: an object,
  - `question`: "Which of these occurrence codes would the NTSB flag as the defining event of
    this accident?"
  - `focus`: "Judge from the analyst's account which event began the accident sequence. Past
    habits are a guide, not a rule: prefer the option the account supports."
    (The same guidance GPT-6 Luna's check receives in `ordering.CHECK_SYSTEM`.)
- `criteria`: one entry per candidate code, keyed by the six-digit code, each an object:
  - `what`: `"<phase words> / <event words>"`;
  - `not_for`: written by code from the other candidates only, joined with `"; "`:
    for another candidate with the same event under a different phase,
    `"the same event in the <phase words> phase (<code>)"`; for another candidate with the
    same phase and a different event, `"<event words>, which is listed separately (<code>)"`.
    The field is left out when no other candidate shares the phase or the event.
- plus one entry `none_of_these`:
  `{"what": "The defining event is none of the codes listed", "not_for": "any listed code"}`.

No examples: they would have to come from real cases.

## The answer

- Options are ranked by Jev's probabilities, highest first. **Ties** (Jev returns steps of
  0.01) are broken by the model's own order: the model's guesses first, in its order, then
  the other candidates in the candidate list's order.
- If `none_of_these` ranks first, the answer is left unchanged (the model's own guesses).
- Otherwise the new occurrence order is the top three ranked codes, `none_of_these` left out,
  scored exactly as the other ways (`ordering.reorder`, `metrics.rescore_occurrence`).
- **Recorded on every step**, in the step's `arguments` (no new record fields): the ranking,
  `toward_more_common` (decision 0101), Jev's `choice`, `confidence`, and every option's
  probability; the resolved model version is the step's `model`.
- **No confidence cut-off.** Confidence is recorded and reported, never used to decide.

## The win rule (fixed now)

`jev2` replaces GPT-6 Luna as the kept check only if, on **both** answer sets, its paired
top-1 difference has a lower 95% interval bound above zero:

1. against no check (the source run);
2. against the plain rule (`-check-rule`);
3. against GPT-6 Luna (`-check-luna`).

Otherwise GPT-6 Luna stays the check (`CHECK=luna`). If all three hold, the outcome line says
so and Andy records the replacement as a new decision before any guidance round uses it.

## The report

`docs/results/s27-round1-jev2-dev.txt`, counts only: for each answer set, `jev2` against no
check, the rule, Luna and Round 1's Jev (fixes and breaks for each); first codes changed and
how many moved toward a more common option; how often `none_of_these` ranked first; the
median confidence of fixed, broken and unchanged cases; and the outcome line. Its heading says
it is a second, registered comparison designed after Round 1 from the vendor's documentation.

## Cost

A fraction of a cent (Round 1's Jev cost $0.0195 and $0.0196; the structured state is somewhat
longer). Andy runs both checks with his TypeSafe key.
