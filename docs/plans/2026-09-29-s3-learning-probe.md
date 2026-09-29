# S3 learning probe: implementation plan

**Spec:** docs/specs/2026-09-14-agency-hypothesis-trail-design.md

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tick a step in the same commit as its code (decision 0017). Log every departure from this plan in the **Deviations** section at the end.

**Goal:** Build a throwaway probe that runs a rough version of the agreed S3 loop on 20 development cases, so the S3 specification can be written from measured numbers rather than guesses. The probe answers: how often the agent chooses to read each kind of docket document given its current hypothesis; whether skipped documents would have changed its answer; which codes it passes to coding tools and whether the checks improve or damage its coding; cost per call, context growth, and format failures. Its output is **not a result**: it sets no bar and tunes nothing. The design was agreed with Andy on 2026-09-29 in the S3 brainstorm (there is no S3 specification yet; the agency design above is the design this probe informs).

**Architecture:** One package, `scripts/s3_probe/` (linted and type-checked like every other script, not `scripts/exploratory/`, because it spends money and sends evidence to a model). It reuses the library and adds nothing to `src/`: the one payload route (`split_record` → `Payload.from_evidence`, decision 0016), the case context (`docket/attach.py`, 0041), the v2 docket read from the transcription cache (`CachedDocketReader` with a `ReadingLookup`, cache-only), the stage-1 hypothesis schema and parser, the stage-2 refinement, `score_case`, the code tables, and S2.7's pool statistics (`scoring/coding_stats.py`). Everything that is not evidence (measured document facts, tool results) travels in the system text, as S2.7's ordering check does (`scoring/checkpass.py`); the agent's own earlier replies travel as assistant turns.

**Tech Stack:** Python 3.14, uv + hatchling, pydantic v2, httpx, pytest + pytest-socket, ruff, mypy --strict. No new dependency.

## Global Constraints

- **Branch.** `s3-probe`, in `.claude/worktrees/s3-probe`, cut from `s27-guidance` at `1cd5011`. Never commit to `main`, `s27-guidance`, `s27-coding-guidance` or `s28-coding-lookup`. Do not modify any file under `src/` — the probe is a script; if a library change seems needed, stop and report it.
- **Cases: `dev-400` only.** Every case the probe touches must be in `samples.sample_ids("dev-400")`; the probe refuses any other ID with an error before any model call. `dev-400` cases are outside decision 0094's statistics pool, so no coding tool can return counts that include the case's own verdict. Never read `dev-seal-400` (sealed, 0095), any held-out sample, or any open-split case.
- **One payload route.** Every piece of case evidence reaches the model only as `Payload.from_evidence(split_record(context, exclude=...)[0])`, where `context` is the raw record or `Attachment.context_for(indices).context`. Never build a payload any other way, never put docket text, titles or record fields into system text. System text may carry: the existing prompt texts (`prompt.SYSTEM_ANSWER`, `prompt.tables_block(tables)`, `prompt.guidance_block(GUIDANCE)`, `prompt.SYSTEM_REFINE`, `prompt.refine_message`), the probe's own instructions, per-document **numbers** keyed by listing index (pages, readable pages, estimated tokens, kind, transcribed pages), and tool results (code labels from the code tables and counts from the pool).
- **Offline docket, cache-only transcriptions.** Dockets come from the docket cache through a `DocketClient` whose transport refuses every request (the `_offline()` pattern in `scripts/docket_leak_scan.py`), so a cache miss fails loudly and nothing is fetched. Transcriptions come only from `ReadingLookup(TranscriptionCache(settings.transcription_dir))` (default model, instruction, resolution and page rule); a page with no cached reading is simply absent. The probe never calls a transcriber.
- **Model settings.** `model=sources.DEFAULT_MODEL` (`openai/gpt-6-luna`), `price_variant="standard"` (never batch — Andy, 2026-09-29), `reasoning_effort=sources.DEFAULT_REASONING_EFFORT` (`medium`), `max_output_tokens=8000` (decision 0084), `temperature=0.0`, JSON-schema output on every call.
- **Prompt.** `PROMPT_VERSION` as on the branch (`s1-v6`) with `GUIDANCE = ("r3-loc-stall", "r6-aircraft-control")` — S2.7's kept rounds (round 3; round 6 kept by decision 0106). Recorded in the run's `probe.json`.
- **Cost limits, enforced in code before every call.** Per case `CASE_CAP_USD = 0.15`; per run `RUN_CAP_USD = 3.00`. Before each call, estimate its cost as `(len(system) + len(payload.text) + len(history text)) / 4` input tokens at the model's input price plus `max_output_tokens` at the output price (`sources` prices, standard variant); if `case_spent + estimate > CASE_CAP_USD` the case stops with `stop_reason="cap"`; if `run_spent + estimate > RUN_CAP_USD` the run stops taking new calls. Actual cost comes from `model.client.cost_usd(reply, settings)`. The monthly budget (0083, $40) is checked at start: refuse if `budget.month_spent(runs_dir) + open reservations + RUN_CAP_USD > 40`; reserve `RUN_CAP_USD` under `budget_lock`, and settle at the end.
- **Spend record.** At the end (and after every 5 cases) append a `budget.SpendRecord` to `runs_dir/<job_id>/spend.jsonl` with `job_id = "s3-probe-<UTC timestamp>-<short sha>"` and **`kind="inventory"`** — the closest existing kind; a new kind would make `month_spent` fail on every other branch reading the shared `data/runs` (the `Literal` has `extra="forbid"`). This is a known mislabel, logged in Deviations and reported to Andy. Do not change `SpendRecord`.
- **No case text in git.** Committed output is counts only: `docs/results/s3-probe-dev.txt`, with no case number, title, docket text or model prose. Trails (JSONL and readable Markdown) go to `<NTSB_DATA_DIR>/probes/s3-probe/<job_id>/` and are never committed.
- **Clinical tone** in every prompt and output (rule 6). No victim names anywhere.
- **Tests offline.** Every test uses `RecordingFakeClient` (or a small fake built the same way) and fixture dockets; no test touches the network (`pytest-socket`). Coverage stays at or above the repository's `--cov-fail-under=90`.
- `make check` = ruff format, ruff check, lint-imports, deptry, vulture, mypy --strict, pytest. Google-style docstrings on every public symbol; line length 100. Every module in `scripts/` carries a `Status` paragraph beneath its summary line (decision 0059): *"Status: one-shot learning probe for S3 (2026-09-29). Output is not a result; it sets no bar and tunes nothing."*
- Commit messages end with the attribution lines the session gives.

## The flow for one case (what Task 4 builds)

Terms: *structured evidence* = the raw record with no `docket` subtree, split with no exclusions (the one-shot ceiling's payload). *Attachable documents* = listing indices whose `DocumentRecord.status == "read"` in the v2 docket (born-digital text or cached transcription).

1. **H0.** Payload = structured evidence. System = `SYSTEM_ANSWER + tables_block + guidance_block`. Schema = `HYPOTHESIS_SCHEMA`; parse with `parse_hypothesis` (one retry on a parse error, the retry adding "Your previous reply was rejected: {error}" to the system text).
2. **Read choice 1.** Payload = `split_record(attachment.context_for([]).context)` — the structured evidence plus the docket listing (titles come only from here). System = the H0 system text + `READ_CHOICE_INSTRUCTIONS` + the menu: one line per attachable document, `"{index}: {pages} pages, {readable_pages} readable, about {estimated_tokens} tokens, {kind}{', transcribed pages: N' if any}"`, plus a line listing unattachable indices with their status. History = H0 as an assistant turn. Schema = `READ_CHOICE_SCHEMA`: `{"documents": [{"index": int, "read": bool, "expected_effect": str}], "reason": str}`. Every attachable index must appear exactly once; an unknown or missing index is a parse error (one retry).
3. **H1.** Payload = `context_for(chosen)` split. System = H0 system. History = H0, choice 1. Hypothesis as step 1. If nothing was chosen, H1 = H0 with no call, recorded as `skipped: nothing chosen`.
4. **Read choice 2.** Offered only the attachable documents not yet read (skip the step if none). Same schema over those indices. History = H0, choice 1, H1.
5. **H2.** If choice 2 chose anything: payload = `context_for(chosen1 + chosen2)`, history = H0, choice 1, H1, choice 2. Otherwise H2 = H1, no call.
6. **H_all (skip regret).** Payload = `context_for(all attachable)`, no history, H0 system — the read-everything answer on the same prompt and evidence version. Skipped (recorded `not run: cap`) if its estimate would pass the case cap after reserving `CODING_RESERVE_USD = 0.03` for steps 7–8; skipped as `not needed` if the agent read every attachable document.
7. **Coding checks.** Payload = the H2 payload. History = H0 … H2 (the turns that produced H2). System = H0 system + `CODING_INSTRUCTIONS` + the tool descriptions + "Tool results so far:" followed by every earlier tool result in order. Schema = `CODING_ACTION_SCHEMA`: `{"done": bool, "tool": enum|null, "kind": enum|null, "codes": [str], "reason": str, "expected_effect": str, "top3": [{"phase": "NNN", "event": "NNN", "probability": 0..1}] (1–3 items)}`. Each call's reply is appended to history as an assistant turn. Loop until `done`, or `MAX_CODING_CALLS = 6` tool calls, or the cap. Tool errors (unknown code, wrong digits) are returned as the tool result text and counted as argument errors, not retried.
8. **Final.** One call with `HYPOTHESIS_SCHEMA` (instruction: "Give your final hypothesis after the checks."), same payload, system and history. Then stage 2 exactly as the runner does it: if not abstaining and findings exist, `SYSTEM_REFINE + refine_message(final, tables)` with `REFINEMENT_SCHEMA`, history = the final reply as an assistant turn, `parse_refinement`. Score with `score_case(refined, verdict, tables, seen_pairs=...)`.

`CODING_INSTRUCTIONS` must say, in substance: "You have written your own coding (your last hypothesis). Now check it against how the NTSB has coded past accidents, using the tools. The counts describe what is usual across past cases; they are not evidence about this accident. Keep a less usual code when this case's evidence supports it. Check the occurrence (which event defines the accident, and its phase) before the findings. Say for each call why you make it and what you expect it to show. Set done when your coding is settled."

## The coding tools (what Task 2 builds)

All take a `kind` and a list of codes and return plain text. Codes are validated against `CodeTables`; an invalid code yields a line `"unknown {kind} code: X"` in the result.

- **`describe_codes(kind, codes)`**, `kind ∈ {"occurrence", "finding_category", "item"}`, 1–6 codes. Occurrence (6 digits): `"{code}: {phase label} / {event label}"`. Finding category (6 digits): its label and up to 20 items under it (`items_under`). Item (8 digits): its label.
- **`occurrence_usage(codes)`**, 1–3 six-digit occurrence codes. For each code: pool cases containing it (`present_n`), cases where it is the defining code (`defining_n`), share defining when present, and the phases under which its event (`code[3:]`) is the defining event, with counts (summed from `CodingStats.group_defining` over every group and half; top 5). For each pair of codes given: `pair(a, b)` → cases with both, and how often each was defining. Uses `event_pair` too when the two codes share no phase.
- **`past_findings(code)`**, one six-digit occurrence code: `findings_given_event(code[3:])` → the top 10 flagged findings, each `"{finding10}: {item label} — {modifier label}: {n} of {cases} cases ({share:.0%})"`. If `cases < 20`: prefix `"Fewer than 20 past cases with this defining event; the counts are unreliable."`

## Per-case trail record (what Task 4 writes, Task 6 reads)

A frozen pydantic `CaseTrail` per case, one JSON line in `trails.jsonl`: case ID, fatal flag, has-scan flag; per document: index, kind, pages, readable pages, estimated tokens, transcribed pages, attachable; each call as a `CallRecord` (phase name, prompt tokens, completion tokens, reasoning tokens, cost, seconds, finish reason, parse-retry flag); the two read choices (index → read, expected effect; reason); H0, H1, H2, H_all, final and refined hypotheses (as `Hypothesis`, or `None` with the reason); each coding step (tool, kind, codes, reason, expected effect, top3, result text length, argument errors); scores per stage (`occurrence_top1`, `occurrence_top3`, and for refined also `finding_recall_10`); the pool's top choice at the final step (for the follow-or-override count: for the agent's final top-1, is it the most common defining code among its top-3 per `defining_n`?); the true primary occurrence code and whether it appeared among any coding-tool arguments; stop reason (`done`, `max_calls`, `cap`, `run_cap`, `failed: …`); total cost.

---

## Task 1: Package skeleton and case selection

**Files:** create `scripts/s3_probe/__init__.py`, `scripts/s3_probe/cases.py`, `scripts/s3_probe/__main__.py` (subcommand `select` only), `tests/test_s3_probe_cases.py`.

- [x] `cases.py`: `DocketFacts` (frozen dataclass: index, kind, pages, readable_pages, estimated_tokens, transcribed_pages, status) and `facts(docket: Docket) -> tuple[DocketFacts, ...]` from `Docket.documents`. `has_scan(facts) -> bool`: any document whose kind is `"scan"` or `"partial"` and which has at least one transcribed page. `select(candidates: Sequence[CaseInfo], *, per_cell: int = 5, seed: int = 20260929) -> tuple[str, ...]` where `CaseInfo` = (case_id, fatal, has_scan); four cells (fatal × has_scan), each drawn with `random.Random(seed)` over the cell's IDs sorted; a cell with fewer than `per_cell` cases raises `ValueError` naming the cell (do not top up from another cell). Fatal comes from the record the same way the runner's `CaseResult.fatal` does (find and reuse that helper; do not re-derive injury logic).
- [x] `select` refuses any ID not in `sample_ids("dev-400")`.
- [x] `python -m scripts.s3_probe select` reads `dev-400`'s records (`load_cases(settings.processed_dir …)` — use the settings path the runner uses), reads each docket offline at v2, builds `CaseInfo`, selects, and writes `<data_dir>/probes/s3-probe/cases.json` (IDs and cell per ID) and prints the four cell counts before selection and the chosen count per cell. Cases whose docket is missing from the cache are counted and excluded, not fetched.
- [x] Tests: `select` is deterministic for a seed; cells are balanced; short cell raises; non-dev-400 ID refused; `has_scan` truth table over kinds and transcribed pages.
- [x] `make check` green; commit.

## Task 2: Coding tools

**Files:** create `scripts/s3_probe/tools.py`, `tests/test_s3_probe_tools.py`.

- [x] Implement the three tools exactly as in "The coding tools" above, as pure functions of `(tables: CodeTables, stats: CodingStats, kind, codes)` returning `ToolResult(text: str, argument_errors: int)`. `TOOL_NAMES = ("describe_codes", "occurrence_usage", "past_findings")` and `run_tool(name, kind, codes, *, tables, stats) -> ToolResult` dispatching by name (unknown name → error result, not an exception). Enforce the per-tool code-count limits (excess codes are dropped and counted as argument errors).
- [x] `TOOL_DESCRIPTIONS: str` — the text block listing each tool, its arguments and what it returns, for the system text.
- [x] Tests with a small hand-built `CodingStats` (construct it via `coding_stats.build` from a few `PoolCase`s, or directly) and `load_tables()`: each tool's output lines, the fewer-than-20 warning, invalid codes, the pair section, the phase counts summed across groups and halves.
- [x] `make check` green; commit.

## Task 3: Prompts, schemas and menu

**Files:** create `scripts/s3_probe/prompts.py`, `tests/test_s3_probe_prompts.py`.

- [x] `GUIDANCE`, `base_system(tables) -> str` (= `SYSTEM_ANSWER + "\n\n" + tables_block(tables) + guidance_block(GUIDANCE)`, matching `runner._system_text` with no case number).
- [x] `READ_CHOICE_INSTRUCTIONS`, `READ_CHOICE_SCHEMA` (strict JSON schema; build it from a pydantic model with `hypothesis.strict_schema`), `parse_read_choice(text, offered: Sequence[int]) -> ReadChoice` (every offered index exactly once; otherwise `SchemaError`).
- [x] `menu(facts: Sequence[DocketFacts], offered: Sequence[int]) -> str` in the format given in the flow, step 2 — numbers and kinds only, never a title.
- [x] `CODING_INSTRUCTIONS` (substance as in the flow, step 7), `CODING_ACTION_SCHEMA`, `parse_coding_action(text, tables) -> CodingAction` (validates phase/event digits; `done=False` requires a tool name).
- [x] `FINAL_INSTRUCTION`.
- [x] Tests: schemas are strict (every object `additionalProperties: false`, all properties required); parsers accept good replies and reject missing/duplicate/unknown indices, bad digits, `done=False` without a tool; the menu never contains a title (build a docket fixture with a distinctive title and assert it is absent).
- [x] `make check` green; commit.

## Task 4: The case loop and trail record

**Files:** create `scripts/s3_probe/trail.py`, `scripts/s3_probe/loop.py`, `tests/test_s3_probe_loop.py`.

- [x] `trail.py`: the pydantic models in "Per-case trail record" (`CallRecord`, `ReadChoiceRecord`, `CodingStep`, `CaseTrail`), frozen, `extra="forbid"`.
- [x] `loop.py`: `CaseBudget` (per-case spend, the run-wide spend behind a `threading.Lock`, both caps, `estimate(system, payload, history, settings) -> float`, `check(...)` raising a private stop signal), and `run_case(raw, docket, *, client: ModelClient, tables, stats, seen_pairs, budget) -> CaseTrail` implementing the eight steps of "The flow for one case" exactly. Use `split_record`, `Payload.from_evidence`, `prepare_attachment(raw, docket)`, `Attachment.context_for`, `parse_hypothesis`, `parse_refinement`, `score_case`, `cost_usd`. A parse failure after its one retry ends the case with `stop_reason="failed: <phase>"` and keeps everything recorded so far. A `LeakageError` from the split ends the case with `failed: leak` (it must never be swallowed silently).
- [x] Refuse (raise) if the case ID is not in `dev-400`.
- [x] Tests (all with `RecordingFakeClient` scripted replies and a fixture docket carrying at least one born-digital document and one document with a cached transcription — reuse `tests/fixtures/docket` and the fakes in `tests/test_attach.py` / `tests/test_docket_transcribe.py`): the happy path records every phase in order; the payloads the fake received contain no text outside evidence roles (assert via the fake's recorded payloads that each is a `Payload` produced by the split, and that docket titles appear only in payloads, never in `client.systems`); choosing nothing skips H1; reading everything skips H_all as `not needed`; a coding loop that never sets `done` stops at 6; an unknown tool code is recorded as an argument error; the case cap stops the case before the call that would pass it; the run cap stops a second case; a malformed reply is retried once then fails the case; the refinement stage runs only when findings exist and the answer does not abstain.
- [x] `make check` green; commit.

## Task 5: The run command

**Files:** modify `scripts/s3_probe/__main__.py` (add `run`), create `tests/test_s3_probe_run.py`.

- [x] `python -m scripts.s3_probe run [--limit N] [--workers 4]`: reads `cases.json` (refuses if absent), refuses any case outside `dev-400`, checks the monthly budget and reserves `RUN_CAP_USD` (Global Constraints), creates `<data_dir>/probes/s3-probe/<job_id>/` with `probe.json` (job ID, commit SHA and dirty flag via the repository's `gitinfo`, model, reasoning effort, price variant, max output tokens, prompt version, guidance, caps, seed, case count, started), runs cases on a thread pool of `--workers` with **one `OpenRouterClient` per worker** (the `transcribe_all` pattern), appends each `CaseTrail` to `trails.jsonl` as it finishes (so a crash keeps finished cases), writes a `SpendRecord` every 5 finished cases and at the end, settles the reservation in a `finally`, and prints one line per finished case (index, stop reason, cost — no case number).
- [x] The OpenRouter key comes from `Settings().require_openrouter_key()`; never printed.
- [x] `--dry-run` runs the whole path with a schema-valid canned-reply client, spending nothing and writing nothing to `runs_dir` (used by the controller before the paid run).
- [x] Tests: refusal without `cases.json`; refusal of a non-dev-400 ID; budget refusal when the month is nearly spent; reservation settled after an exception; spend rows written with `kind="inventory"` and the job ID; `--dry-run` produces a `trails.jsonl` and no spend.
- [x] `make check` green; commit.

## Task 6: The report and readable trails

**Files:** create `scripts/s3_probe/report.py`; modify `__main__.py` (add `report`); create `tests/test_s3_probe_report.py`.

- [x] `python -m scripts.s3_probe report JOB_ID [--out docs/results/s3-probe-dev.txt]` reads `trails.jsonl` and `probe.json` and prints (and writes with `--out`) a counts-only report. First line: `"Learning probe, not a result: n=<cases>; every figure below is a signal, not a finding."` Then the job's settings from `probe.json`; then:
  - **Documents:** offered, chosen at choice 1, chosen at choice 2, by kind (born-digital / scan / partial) and by size band (`< 2,000`, `2,000–10,000`, `> 10,000` estimated tokens), with the choice rate for each; how often a choice-2 read happened at all.
  - **Skip regret:** cases where H_all ran; of those, cases where H_all's top-1 differs from H2's; and where one is right and the other wrong (both directions, counted separately).
  - **Hypotheses:** occurrence top-1 and top-3 counts at H0, H1, H2, H_all, final and refined; finding recall@10 mean at refined.
  - **Coding checks:** tool calls per case (min / median / max) and by tool; stop reasons; argument errors; distinct codes passed; cases where the true primary occurrence was among the codes passed; cases where the final top-1 differs from H2's top-1, split into (right→wrong, wrong→right, wrong→wrong); follow-or-override of the pool's top choice, with how often each was right.
  - **Cost and reliability:** calls per case; cost per case (mean, max) and total; prompt tokens per call by phase (mean, max) and the growth from H0 to the last coding call; seconds per call (mean, max); parse retries and failures by phase; finish reasons.
  - Every count is shown with its denominator. Nothing names a case.
- [x] `python -m scripts.s3_probe trails JOB_ID` writes one Markdown file per case under the job folder (`trails/<n>.md`, numbered in run order, the case ID inside the file only): for each phase the hypothesis top-3 with probabilities, the read choices with expected effects, each coding step's reason, arguments, expected effect, top3 and the tool result, the final and refined answers, the true codes, and costs. These files are for Andy to read and are never committed.
- [x] Tests: the report from a two-case synthetic `trails.jsonl` (built from `CaseTrail` objects) has the first line, correct denominators, no case ID; the trails files contain the case ID and are written only under the job folder.
- [x] `make check` green; commit.

## Task 7: Wiring and documentation

**Files:** modify `README.md` (scripts table), this plan.

- [ ] Add a row to `README.md`'s scripts table: `| s3_probe | one-shot | s3-probe-dev.txt — the S3 learning probe; not a result |`.
- [ ] Controller-only (not a subagent): run `python -m scripts.s3_probe select`, then `run --dry-run`, then — only after the final review — the paid `run`, then `report --out docs/results/s3-probe-dev.txt` and `trails`. Record the job ID, spend and any surprises in Deviations.
- [ ] `make check` green; commit.

## Deviations

- **2026-09-29 — H0 reads the structured evidence, not the start facts alone.** The design agreed in conversation said "first hypothesis from the start facts alone". On a closed case the structured fields (pilot, weather) are present, and the read choice should rest on the best hypothesis available before any document; start facts alone would make every read choice look better-informed-by-reading than it is. Andy to confirm.
- **2026-09-29 — The comparison is the probe's own H_all, not an old arm B run.** H_all uses the same prompt, guidance and evidence version as the probe's other calls, so a difference is the reading, not the prompt.
- **2026-09-29 — Spend is recorded with `kind="inventory"`.** No existing kind fits and adding one would break `month_spent` on the branches sharing `data/runs`. The job ID (`s3-probe-…`) identifies it. Andy to decide whether a `probe` kind is added on `main` later and the row relabelled.
- **2026-09-29 (Task 2) — exact text layout chosen where the brief specifies content but not
  characters.** The brief pins the exact line for `past_findings` (`"{finding10}: {item
  label} — {modifier label}: {n} of {cases} cases ({share:.0%})"`) and for `describe_codes`'s
  occurrence case, but leaves `describe_codes`'s `finding_category` block, and
  `occurrence_usage`'s per-code and pair lines, as prose ("its label and up to 20 items under
  it"; "cases containing it … the phases … with counts"; "cases with both, and how often each
  was defining"). `tools.py` renders these as: `finding_category` → `"{code}: {label}"` then
  one indented `"  {item8}: {label}"` line per item (first 20, sorted by code, with a `"  ...
  and N more"` line if truncated); `occurrence_usage`'s per-code block → three lines (label,
  `"  present: N; defining: M (X% of present)"` or `"(no pool cases present)"`, `"  top
  phases for event EEE: ..."` joined `"; "` or `"none"`); its pair line →
  `"{a} & {b}: both in N; {a} defining in Na; {b} defining in Nb"`, with an indented `"  events
  ... across phases: ..."` line added only when `a[:3] != b[:3]` (read as "share no phase").
  These are internally consistent and covered by exact-text tests in
  `tests/test_s3_probe_tools.py`, but Task 4/6 code reading these strings, or a future reviewer
  comparing against the brief, should treat this layout as this implementation's choice, not a
  quoted requirement.
- **2026-09-29 (Task 1) — `Settings` has no `processed_dir`.** The brief's `load_cases(settings.processed_dir …)` names a field that does not exist; every caller in the library (`apps/eval/__main__.py`, `scripts/docket_leak_scan.py`) derives it as `settings.data_dir / "processed"`, which `scripts/s3_probe/__main__.py` does too. The docket cache directory is read as `settings.docket_dir` (which `model_post_init` already derives from `data_dir` when unset) rather than `docket_leak_scan.py`'s literal `settings.data_dir / "docket"`; both resolve to the same path by default.
- **2026-09-29 (Task 3) — `hypothesis.strict_schema` handles nullable enum fields natively.**
  The task-3 brief asked me to check whether `strict_schema` supports nullable fields
  (`str | None`) under OpenAI strict mode and, if not, build the coding schema by hand. It
  does: pydantic v2 renders `Literal[...] | None` as `{"anyOf": [{"enum": [...], "type":
  "string"}, {"type": "null"}]}`, which `_strict` already leaves untouched (it only touches
  `object` nodes), and the field is still listed in `required` because it has no default. So
  `CODING_ACTION_SCHEMA`'s `tool` (`Literal[*tools.TOOL_NAMES] | None`) and `kind`
  (`Literal["occurrence", "finding_category", "item"] | None`) fields are built the same way
  as every other schema in the library, via `strict_schema(CodingAction)`, with no hand-rolled
  schema needed.
- **2026-09-29 (Task 3) — `menu`'s "not available" line is computed from every document in
  `facts`, not only the offered ones.** The brief's line ("then, if any documents have
  `status != "read"`, a line…") does not say whether "documents" means every document in the
  case or only the ones offered at this step; since offered documents are by construction
  attachable (`status == "read"`), the two readings are equivalent in practice — an offered
  document can never appear in this line — so `menu` reads it over all of `facts`, which lets
  the model see the full menu of what exists but cannot be read, not only what changed since
  the previous step.
- **2026-09-29 (Task 4) — choices the flow leaves open, fixed in `loop.py`.**
  (1) *Choice 2's payload* is `context_for(chosen1)` -- the structured evidence, the listing and
  the documents already read -- because a second choice made without sight of what the first
  one read would not be a second look. (2) *The coding payload* is `context_for(everything
  read)`: equal to the H2 payload whenever H2 or H1 was a call; when nothing was read at all it
  is the listing payload (structured evidence plus listing), not the H0 payload, because the
  coding history then holds read-choice replies made against the listing. (3) *With no
  attachable document* both read choices are skipped (`"skipped: nothing to offer"` /
  `"skipped: nothing left to offer"`) and H_all is `"not needed"`. (4) *A skipped stage* (H1 or
  H2 with nothing chosen) carries the previous hypothesis and is scored again, with its note;
  the history then holds only the replies actually made. (5) *The refined stage*, when stage 2
  does not run (abstained, or no findings), carries the final hypothesis with a
  `"not run: …"` note, as the runner returns the stage-1 hypothesis. (6) *The run budget*
  reserves each call's estimate under the lock before the call and settles to the actual cost
  after, so parallel cases cannot together pass `RUN_CAP_USD`; `run_case` takes that shared
  `RunBudget` (which also holds the case cap) and makes the case's own `CaseBudget` itself, so
  a case budget can never be reused across cases. (7) *The trail* adds three fields to the
  design's list: `estimated_usd` per call (to see how far the estimate is from the cost),
  `failure` (the parser's last error on `failed: <phase>`) and `leak` (the guard's message on
  `failed: leak`, which names role, kind and source, never withheld text). (8) *A parse failure
  or leak in H_all ends the case*, as the design says of every phase, although H_all is only a
  comparison; a leak can arise there from a document the agent chose not to read.
  (9) *Test records*: no committed fixture record is a `dev-400` case, so the tests relabel
  `ANC09CA024` with a `dev-400` ID; the docket is built in memory as in `tests/test_attach.py`
  (a scanned document "read through a transcription" is a `DocumentRecord` with
  `status="read"`, `kind="scan"`, `transcribed_pages=2`). (10) `loop.py` was 597 lines, past
  the ~500 the brief set as the point to report rather than split (resolved by the fix round
  below).
- **2026-09-29 (Task 4, fix round 1, controller's decisions) — three changes to the flow's
  edges.** (1) *Module split*: the caps (`CASE_CAP_USD`, `RUN_CAP_USD`, `CODING_RESERVE_USD`,
  `MAX_OUTPUT_TOKENS`), `call_settings`, `RunBudget`, `CaseBudget` and the stop signal (now the
  public `CapReached`, since `loop.py` must catch it across the module boundary) live in
  `scripts/s3_probe/budget.py`; `loop.py` imports them and re-exports nothing; Task 5 imports
  from `budget.py`. `MAX_CODING_CALLS` stays in `loop.py`. `loop.py` is now 543 lines.
  (2) *H_all does not end the case*: it is a side comparison, not the agent's path, so a parse
  failure after its retry is recorded as `h_all.note = "failed: parse"` and a leak from its
  split as `"failed: leak"` (the guard's message in `leak`), and the case goes on to the coding
  checks. This supersedes point (8) above. A leak from a document the agent chose still ends
  the case, and always did so before H_all (at H1, choice 2 or H2). (3) *Room for the answer*:
  before each coding call the loop estimates that call plus the final call and the refinement
  (the refinement priced from H2's findings, with the last reply standing in for the final
  one); if together they would pass the case cap it stops the checks with the new trail field
  `coding_stop = "cap"` and goes to the final answer. `coding_stop` records how the checks
  ended (`done`, `max_calls`, `cap`, or `None` if not reached). The case's `stop_reason` is
  then `"coding_cap"`; `"cap"` stays reserved for a call on the answer's own path that the cap
  refused.
- **2026-09-29 (Task 4, fix round 2, controller's decisions) — four changes affecting the
  probe's measurements.** (1) *No H_all call ends the case on the case cap*: H_all's call and
  its parse retry are each checked against the case cap with `CODING_RESERVE_USD` held back; a
  refusal is recorded as `h_all.note = "not run: cap"` and the case goes on. A coding call and
  its parse retry are each checked with the answer reserve (the final call plus the
  refinement); a refusal stops the checks (`coding_stop = "cap"`). The run cap still ends the
  case wherever it binds. (2) *`true_in_arguments` is `None`* when the case ended before the
  coding checks (step 7) were reached; `False` means they were reached and no argument held the
  true code. (3) *Message order*: the transport sends the system text, then the payload, then
  the history, so the model reads the current evidence before replies it wrote with less of it.
  Every call with history now ends its system text with `prompts.HISTORY_NOTE` ("Your earlier
  replies follow the evidence in this conversation. Some of them were written before you had
  read every document now included in the evidence. Where they differ from the evidence, the
  evidence given here is current."); calls without history do not carry it. This includes the
  refinement, whose system text is therefore no longer byte-for-byte the runner's
  `SYSTEM_REFINE + refine_message(...)`: the same text with the note appended. The note's
  characters are counted in every estimate, including the answer reserve. (4) *Trail safety and
  diagnosis*: a test asserts no docket title or document text appears in a dumped trail; a new
  `Stage.detail` keeps H_all's failure detail (the parser's last error on `failed: parse`, the
  guard's message on `failed: leak`).

- **2026-09-29 (Task 5) — a purpose-built `DryRunClient`, not a `RecordingFakeClient`.** The
  brief's line for `--dry-run` names `RecordingFakeClient`, but that class replays a fixed,
  ordered list of scripted replies and repeats its last entry once exhausted; `run`'s cases have
  different document counts and read choices, so no single script's length or content is right
  for every case, and a shared instance across cases (one client per worker thread, reused for
  many cases) would run off the end of its script and start returning stale, wrong-shaped
  replies. `DryRunClient` instead builds a schema-valid reply from `settings.schema_name` on
  every call: a hypothesis with one valid occurrence guess and no findings (so the refinement
  step is always `"not run: no findings"`), a read choice that reads the first offered document
  and marks the rest unread (read straight from `prompts.menu`'s listing lines in the system
  text via a regular expression, never from state of its own), and a coding action that is
  always `done`. It is stateless and deterministic, so one instance safely answers any number of
  calls across any number of cases, and it is used as a context manager (`__enter__`/`__exit__`)
  so the same `Callable[[ExitStack], Callable[[], ModelClient]]` factory shape serves both the
  dry run and the paid run.
- **2026-09-29 (Task 5) — a `SpendRecord`'s `calls` counts model calls, not cases.** A chunk's
  row reports `sum(len(trail.calls) for trail in chunk)`, matching how `scoring/preparation.py`
  uses the same field (one call per page read), rather than the chunk's case count.
- **2026-09-29 (Task 5) — `cases.py` gained `docket_reader`, `offline_transport`, `MKEY_FIELD`
  and `SELECTION_SEED`.** Task 1's `select` command built its offline transport and
  `CachedDocketReader` inline in `__main__.py`; `run` needs the identical construction, so it
  was factored into `cases.py` (as the brief's "Reuse Task 1's offline docket reader
  construction ... factor it into a shared helper if needed" asks) and `select` was left
  behaviourally unchanged -- `MKEY_FIELD` and the seed default moved with it, as named
  constants rather than a duplicated literal `"mKey"` / `20260929`.
- **2026-09-29 (Task 5) — the monthly-budget refusal test uses a near-zero `monthly_budget_usd`,
  not pre-existing spend.** `reserve_within_budget`'s guard is `month_spent + open reservations +
  projected > budget`; setting `Settings(monthly_budget_usd=0.01)` exercises the same comparison
  deterministically, without needing to fabricate a prior run's spend rows to approach the real
  $40 (decision 0083) limit.
- **2026-09-29 (Task 5) — the "run cap reached -> cases not started" path has no dedicated
  test.** It is implemented (`_run_cases` cancels every future not yet started once a trail's
  `stop_reason` is `"run_cap"`, folding in any that finished anyway before the pool's shutdown
  completes, so a paid-for case is never left unreported), but the brief's required test list
  for Task 5 does not name it and it is not exercised directly. `RunBudget`'s own cap mechanics
  are already covered thoroughly by Task 4's tests (`test_s3_probe_loop.py`); what Task 5 adds
  on top is the pool-level bookkeeping, left as a self-review note rather than a ninth test.

- **2026-09-29 (Task 5, review fix round 1) — two Important findings on the shared monthly
  budget, both fixed.**
  1. *A failure between reserving and settling could leave an open reservation.* `cmd_run`
     used to reserve, then build the job folder, `probe.json` and the client factory (whose
     `require_openrouter_key()` is the likeliest way to raise) only afterward, inside a
     `finally` that started later than the reservation itself -- so a missing key, a malformed
     `cases.json` (`_cell_counts`'s unchecked `v["fatal"]` could raise `KeyError`), or a
     `job_dir.mkdir` failure would all leave `RUN_CAP_USD` reserved with nothing left in the
     function to settle it, the exact bug `scoring/preparation.py` fixed for its own jobs
     ("Built before the reservation", fix round 1, I2). Fixed by building the client factory
     (and so checking the key) and validating `cases.json` (`_validate_cells`, new) before the
     reservation, and moving the reservation's own `try`/`finally` to wrap everything from
     `job_dir.mkdir` onward, guarding the `finally`'s `accounting.flush_final()` with an
     `accounting is not None` check in case even `job_dir.mkdir` itself fails. New test:
     `test_refuses_before_reserving_when_the_key_is_missing`.
  2. *A case that raised after some paid calls left that money unrecorded, and a second
     raising future in the fold-in could abort the whole report.* `run_case` re-raises what it
     cannot recover from, so a case that failed after an earlier call inside it had already
     succeeded (and been billed to `RunBudget`) produced no trail, and no spend row ever
     summed that call in; and `_run_cases`'s fold-in loop called `future.result()` unguarded,
     so a second such failure aborted the loop and dropped every later trail from
     `trails.jsonl`. Fixed with two changes: (a) `_run_cases` now wraps every
     `future.result()` (both in the main wait loop and the fold-in) in one `take()` helper
     that catches the exception, counts it, and hands it to a new `on_failed` callback instead
     of letting it propagate -- a case's own failure no longer aborts the run, and `_run_cases`
     now returns `(not_started, failed)`; (b) spend accounting moved into a new `_Accounting`
     class whose `flush_final` writes the run's last `SpendRecord` as `run_budget.spent -
     sum(rows already written)`, not the sum of the trails still in its chunk, so every dollar
     `RunBudget` recorded lands in exactly one row whatever the path, including a call billed
     to a case that never produced a trail. `cmd_run` now prints `"N/total failed: exception
     <type>"` for a failed case (no case number), still settles and writes the final
     `probe.json` on the way out, and returns 1 instead of 0 when any case failed (rather than
     re-raising, so the summary and `probe.json` are never skipped). New tests:
     `test_a_failing_case_settles_the_reservation_and_does_not_abort_the_run`,
     `test_spend_reconciles_when_a_case_fails_after_some_paid_calls` (a shared, stateful fake
     client whose second call raises; asserts the spend rows' total exceeds the one surviving
     trail's own cost, proving the failed case's billed H0 call was folded in), and
     `test_spend_rows_chunk_at_five_and_sum_to_the_trails_total` (six cases, exactly two spend
     rows, summing to the trails' total). `test_reservation_settled_after_an_exception` was
     renamed `test_a_failing_case_settles_the_reservation_and_does_not_abort_the_run` and its
     assertion changed from `pytest.raises(RuntimeError)` to `result == 1`, matching the new
     behaviour.
  A consequence of (2)(b): the final spend row's `calls` field is still summed only from the
  trails actually on hand (a case that failed mid-flow has no trail to count calls from), so
  it can slightly undercount against the exactly-reconciled `cost_usd` on the rare run where a
  case fails after a paid call. This is a cosmetic gap in one integer field, not a money gap,
  and is left as-is.
- **2026-09-29 (Task 6) — `CaseTrail` gained a field: `true_findings`.** The "Per-case trail
  record" section above (what Task 4 built, reviewed and merged) names only the true primary
  occurrence code for scoring `true_in_arguments`; it does not carry the verdict's flagged
  finding codes anywhere. The top-level brief for Task 6's readable trails asks each file to
  show "the true primary occurrence and flagged findings with labels", which needs the truth
  to be in the trail record -- `report.py`/`trails_md.py` never touch a `Verdict` or
  `split_record` themselves (only `loop.py` does, inside the guarded flow). Rather than have
  Task 6 re-derive truth outside the leakage guard's own call site, `trail.py` gained one
  additive field, `true_findings: tuple[str, ...]` (the verdict's `finding_codes_in_cause`,
  composed ten-digit codes, empty when the verdict was never split), and `loop.py`'s
  `_Case.trail()` now sets it alongside `true_primary` in the one place both are already
  computed. No other Task 4/5 behaviour changed; `tests/test_s3_probe_loop.py` and
  `tests/test_s3_probe_run.py` still pass unmodified. Andy to confirm the field belongs on the
  trail record (rather than, say, being dropped from the readable trail's brief instead).
- **2026-09-29 (Task 6, corrected in fix round 1) — `tests/s3_probe_fixtures.py` holds the
  three synthetic `CaseTrail` cases, shared by both `test_s3_probe_report.py` and
  `test_s3_probe_trails.py`.** The first pass at this task tried a bare `from
  s3_probe_fixtures import ...` between the two test files, which `mypy --strict` refused
  (`Cannot find implementation or library stub for module named "s3_probe_fixtures"`), and
  concluded from that single failure that no test module in this repository could import
  another. That conclusion was wrong and, on review, contradicted by three files already in
  the repository: `tests/test_boundary.py:13`, `tests/test_checkpass.py:11` and
  `tests/test_contamination.py:5` all import shared helpers from sibling test modules
  successfully under `mypy --strict`, every one of them with the *package-qualified* form,
  e.g. `from tests.boundary import (...)`, not a bare `from boundary import (...)`. The actual
  cause of the first failure was the bare import, not cross-test-module imports as such:
  `mypy_path = ["src", "infra"]` doesn't need to list `tests/` for `tests.<module>` to resolve,
  because `tests/` itself is discoverable as a namespace package from the project root once
  any file under it is in `files` (`explicit_package_bases = true`) -- it only needs to list
  `tests/` for a *bare* (unqualified) import to resolve, which none of the repository's
  existing cross-test imports use. Fixed by creating `tests/s3_probe_fixtures.py` (not
  collected by pytest, since it isn't `test_*`) and importing it from both test files as
  `from tests.s3_probe_fixtures import ...`, matching the existing pattern exactly; verified
  with `uv run mypy` (whole-project) and `make check`, both clean, and the case builders no
  longer duplicated.
