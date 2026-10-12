# S4 — Predictions and resolution: implementation plan

**Spec:** docs/specs/2026-10-10-s4-predictions-and-resolution-design.md

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tick a step in the same commit as its code (decision 0017). Log every departure from this plan in the **Deviations** section at the end. Tasks marked **Controller** are run by the controller session, not a subagent: they spend money, read the live store or bucket, run AWS commands, or need Andy.

**Goal:** Move the S3.3 live shadow off Andy's Mac into an unattended scheduled Fargate task with its own OpenRouter key and limit, its own private bucket as the store, alerts and a public ledger, and write each night an export in the fixed format `board/1` that S5 builds against (spec §1).

**Architecture:** The night is S3.3's morning (`live/morning.py`), changed in place for the full-cap money rule, counted fetch failures and closure record version 2, and wrapped by a new `live/night.py` that adds the same-day marker, later scores, the night record, alerts, the metric and the export. Cloud effects sit behind narrow protocols in `live/cloud.py` (a bucket mirror, the key's spend, alerts, the metric) whose boto3 and httpx clients are built only in `apps/live`; tests use in-memory fakes. The local run folder layout does not change: the container keeps a local mirror of the bucket's `runs/` and pushes changed files after every reply. `infra/live_stack.py` defines `NtsbLiveStack`; `.github/workflows/ledger.yml` appends manifest hashes to the `ledger` branch.

**Tech Stack:** Python 3.14, uv + hatchling, pydantic v2, pytest + pytest-socket, ruff, mypy --strict, import-linter, httpx (already a dependency), boto3 (the existing optional `aws` extra), aws-cdk-lib (existing dev dependency), GitHub Actions. No new dependency.

## Global Constraints

- **Branch.** `s4-predictions-and-resolution` in `.claude/worktrees/s4-predictions-and-resolution`. Never commit to `main`. The prefix `s4-` is what S4's spend line counts (decision 0170 item 6).
- **Ellery's text does not change** (decision 0156). The only change to `+t` in S4 is Task 1's widened invented inputs; from Task 1 on, `VERSION_1` must equal the label at every commit. Do not edit `scoring/prompt.py`, `scoring/hypothesis.py`, `scoring/codes.py`, or `agent/` `texts.py`, `steps.py`, `tools.py`, `schemas.py`, `later.py`, `loop.py`'s text, `armb.py`'s text. Adding fields to `AgentCall`, `ModelReply` or `ReplyRow` is not a text change.
- **Version 1's settings** (`live/morning.py:VERSION_1_SETTINGS`): `openai/gpt-6-luna`, reasoning `medium`, standard price, sync, reply budget 8,000, evidence v1, `load_stats("s3")`, guidance `r3-loc-stall` then `r6-aircraft-control`, temperature 0.0, $0.30 a case, exclusions `{prelim_narrative}`. Sample name `live`, arm C.
- **Money** (decision 0170): live key limit $10 a month on OpenRouter (Andy sets it); cases a night = floor((cap − `usage_monthly`) ÷ $0.30), cap = min($9, key limit − $1); refuse when the key endpoint fails or the key has no limit. No daily limit, no $0.04 projection, no $5 month on the live path. S4's development line: $10 on the development key, counted by commit on `s4-` branches.
- **Queue** (decisions 0157, 0175, 0179): closures on or after 2026-09-23, order (closure run, mkey), one run per case, seen = first model call sent. A failed fetch counts only on a night when another case fetched; alert at 3 counted failures; "not coded: unreachable" at 7, final. An outage night counts against no case.
- **Open split** (decision 0024): live cases are open-split. Nothing from a live run folder, the bucket, the export, the live docket cache or the store copy is committed or printed into a committed file. Committed: `docs/results/s4-names-dev.txt` (development cases), `docs/results/s33-fingerprint-continuity.txt`, `docs/results/s4-live.txt` (counts only), `docs/schemas/board-1.schema.json`, `tests/fixtures/board/` (invented cases only). Alert emails and the ledger hold kinds, counts, dates, run ids and hashes, never a case number. Tests use invented records and the existing redacted development fixtures. No subagent reads a live run folder or the bucket.
- **Names** (decisions 0049 item 2, 0180): no personal name in the export. No registration, no make or model, no non-expert explanation, no document text, no evidence fingerprint in the export.
- **Held-out and sealed.** Never read `heldout-400`, `dev-seal-400` or `dev-seal-s3-400`.
- **Numbers.** Every committed number comes from a committed script (CLAUDE.md rule 3). Clinical tone (rule 6).
- **Tests offline** (`pytest-socket`); coverage ≥ 90% branch; `make check` green at every commit. Google-style docstrings on public symbols; line length 100. Scripts carry a `Status` paragraph (decision 0059). Written-out `uv run` commands use `--locked`.
- **Worktree data.** Commands that read development data from this worktree need `export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data` (decision 0057).
- **AWS and IAM.** Andy runs every `cdk deploy` and every IAM create or delete; Andy writes the live OpenRouter key into Parameter Store from `pass` without printing it. Claude asks Andy before the first cloud night, stating cost and duration. Pushing an image to ECR and changing GitHub branch protection are asked first.
- **Paid development runs** (none planned) go only through `NTSB_PAID_BRANCH=s4-predictions-and-resolution scripts/paid_run.sh <target>`.
- **Subagents.** Implementers on `sonnet`; exploration on `haiku`; the final review (Task 17) on `opus`, split by dimension.
- Commit messages end with the attribution lines the session gives.

## Review Focus

1. **A night killed mid-run** (the 3-hour limit, or Fargate stopping the task): the next night must resume the run from the bucket without paying for answered calls again and without coding any case twice. Task 10 tests a kill after the first pushed reply.
2. **A bucket listing that holds a half-written folder** (a folder with `spec.json` and `replies.jsonl` but no `run.jsonl`): `unfinished_run` must find it and the night must resume it, not start a second run. Task 9 tests it on the mirror.
3. **The key endpoint answering with an unexpected shape** (no `data`, `usage_monthly` a string, `limit` null): the night refuses with `key-unreachable`, spends nothing and sends one alert. Task 9 tests each shape.
4. **A name in a title or an account that the rule cannot recognise**: the export must still pass its never-holds test for every invented name the rule is meant to catch, and the limit is printed. Task 5 tests titles, notes, cause statements and accounts with an owner name, an operator name and a title surname.
5. **Two tasks started the same day** (a manual run while the scheduled one runs): the second must stop before reading the store. Task 10 tests the conditional marker with a fake that rejects the second put.

---

## Order of work

**1** (built by a subagent; its continuity run and sweep by the Controller; stop if `+t` does not match on `fd6053f`), **2**, **3** (S5 can start once 3 is pushed), **4** (built by a subagent, run by the Controller, read by Andy), **5**, **6**, **7**, **8**, **9**, **10**, **11**, **12**, **13**, **14**, **15** (Controller with Andy: deploy, dry run, first cloud night), **16** (Controller: the backfill, a fresh closure, alerts, the Mac key, the report), **17** (Controller: final review and close-out).
Tasks 2, 3 and 4 are independent once 1 has landed; 5 needs 4's reading; 6 needs 2; 7 needs 6; 8 needs 7; 9 is independent of 6 to 8; 10 needs 7, 8, 9; 11 needs 3, 5, 6, 8; 12 needs 10; 13 needs 9; 14 needs 11.

## File map

- `agent/rendered.py`, `agent/version.py`, `tests/fixtures/rendered/not_model_text.toml`, `tests/test_agent_rendered.py`, `docs/results/s33-fingerprint-continuity.txt`, dated notes on 0161 and the S3.3 specification — Task 1.
- `live/morning.py` (the literal), `model/client.py` (`ModelReply.provider`), `agent/trail.py`, `agent/loop.py`, `agent/armb.py`, `agent/drive.py` (`ReplyRow.request_sha256`) — Task 2.
- `live/export.py`, `scripts/board_schema.py`, `docs/schemas/board-1.schema.json`, `tests/board_sample.py`, `tests/fixtures/board/`, `tests/test_live_export.py` — Task 3.
- `scripts/s4_names_probe.py`, `tests/test_s4_names_probe.py`, `docs/results/s4-names-dev.txt` — Task 4.
- `docket/vocab/words.txt` (moved), `docket/title_vocab.py`, `scripts/check_fixtures_redacted.py`, `live/names.py`, `tests/test_live_names.py` — Task 5.
- `scripts/s4_seen_pairs.py`, `scoring/tables/seen_pairs_dev.json`, `scoring/samples.py` (`load_seen_pairs`), `docket/client.py` (`cached_hashes`), `live/records.py` (`ClosureRecord` v2), `live/closure.py` — Task 6.
- `live/seams.py`, `live/local.py`, `live/queue.py`, `live/morning.py`, `live/state.py` — Task 7.
- `live/later.py` — Task 8.
- `live/cloud.py`, `settings.py` — Task 9.
- `live/night.py`, `agent/run.py` and `agent/drive.py` (`on_reply`), `apps/live/__main__.py` — Task 10.
- `live/board.py`, `apps/live/__main__.py` (`export`) — Task 11.
- `infra/live_stack.py`, `infra/app.py`, `scripts/build_live_image.sh`, `tests/test_live_stack.py` — Task 12.
- `live/ledger.py`, `scripts/ledger_append.py`, `.github/workflows/ledger.yml`, `apps/live/__main__.py` (`verify-ledger`), `tests/test_ledger_workflow.py` — Task 13.
- `scripts/s4_live_report.py`, `scripts/stage_spend.py` (`s4`), `scripts/live_env.sh`, `Makefile`, `docs/runbooks/live-cloud-nights.md` — Task 14.

---

## Task 1: The fingerprint covers several events (decision 0168)

**Files:** modify `src/ntsb_probable_cause/agent/rendered.py`, `src/ntsb_probable_cause/agent/version.py`, `tests/fixtures/rendered/not_model_text.toml`, `tests/test_agent_rendered.py`, `docs/decisions/0161-the-rendered-text-fingerprint-and-the-version-1-check.md` (a dated note at the end only), `docs/specs/2026-10-07-s3-3-live-shadow-design.md` (§7.2's phrase, with a dated note); the Controller rewrites `docs/results/s33-fingerprint-continuity.txt`.

**Background.** `fields.py:_phase_of_flight` picks the defining event, else the lowest `sequenceNumber`, and sends its `cicttPhaseSOEGroup` as the phase of flight. `_RAW` (`rendered.py:74`) has one event, so an edit to that choice never moves `+t`. In `not_model_text.toml`, `"fields.py:isDefiningEvent"` and `"fields.py:sequenceNumber"` are listed as source keys "not text the model receives"; with several events their edits must move `+t`, so they move to the `[selects]` table, which the sweep requires to move it.

**Interfaces:**
- Produces, in `agent/rendered.py`: `_RAW_EVENTS: Final[dict[str, object]]` (a copy of `_RAW` with `ntsbNumber` `"XXX00XX002"`, `mKey` `2`, and `aircrafts[0].events` = three events, in this list order: `{"isDefiningEvent": False, "sequenceNumber": 2, "cicttPhaseSOEGroup": "Maneuvering"}`, `{"isDefiningEvent": True, "sequenceNumber": 3, "cicttPhaseSOEGroup": "Approach"}`, `{"isDefiningEvent": False, "sequenceNumber": 1, "cicttPhaseSOEGroup": "Enroute"}`) and `_RAW_NO_DEFINING` (`"XXX00XX003"`, `mKey` `3`, two events, none defining: sequence 2 `"Landing"` listed first, sequence 1 `"Takeoff"` second). Two new scenarios at the end of `_scenarios()`.
- `VERSION_1` changes value; `SOURCE_LABEL_V1` does not.

- [x] **Step 1: Write the failing test** in `tests/test_agent_rendered.py`:

```python
def test_event_selection_reaches_the_text() -> None:
    sent = json.dumps(rendered.rendered_requests(), ensure_ascii=False)
    # The defining event is listed second and numbered 3: it is the one sent.
    assert "Approach" in sent
    # With no defining event, the lowest sequence number is sent, although listed last.
    assert "Takeoff" in sent
    assert "Maneuvering" not in sent and "Enroute" not in sent
```

- [x] **Step 2: Run it.** `uv run --locked pytest tests/test_agent_rendered.py::test_event_selection_reaches_the_text -v` — Expected: FAIL (`"Approach"` not in sent).
- [x] **Step 3: Add the two records and scenarios.** Build `_RAW_EVENTS` and `_RAW_NO_DEFINING` with `copy.deepcopy(_RAW)` and the changes above (a helper `_with_events(number, mkey, events)`). Append to `_scenarios()`:

```python
        _Scenario(
            "several events, one defining",
            _case(_view(_DOCKET_UNREADABLE, _RAW_EVENTS), _config(without=frozenset({"coding"}))),
            (_calling(_RECORD), _calling(_ANSWER), _saying(_REFINEMENT)),
        ),
        _Scenario(
            "several events, none defining",
            _case(
                _view(_DOCKET_UNREADABLE, _RAW_NO_DEFINING), _config(without=frozenset({"coding"}))
            ),
            (_calling(_RECORD), _calling(_ANSWER), _saying(_REFINEMENT)),
        ),
```

  If `_view` or `_case` does not take the raw record this way, read their signatures (`rendered.py:414`, `:418`) and pass the record the way the "coding ablation, nothing readable" scenario does. Each new scenario must end with the stop that scenario ends with (`expected_stop`).
- [x] **Step 4: Run it.** Same command — Expected: PASS. Then `uv run --locked pytest tests/test_agent_rendered.py -v` — every test passes except the version pin (next step).
- [x] **Step 5: Move the two keys to `[selects]`.** In `tests/fixtures/rendered/not_model_text.toml`, delete the lines `"fields.py:sequenceNumber" = …` and `"fields.py:isDefiningEvent" = …` from their table and add to `[selects]`:

```toml
"fields.py:isDefiningEvent" = "the key that marks the defining event, whose phase is sent: the phase is sent, the key is not, and the sweep shows an edit to it moves the fingerprint (decision 0168)"
"fields.py:sequenceNumber" = "the key that orders events when none is defining, and whose first phase is sent: the phase is sent, the key is not, and the sweep shows an edit to it moves the fingerprint (decision 0168)"
```

  `sequenceNumber` is also read by `_ordered_events` for `eventCode`, which is withheld; the `[selects]` entry covers both sites, and the sweep checks the edit moves `+t` at least through the phase.
- [x] **Step 6: Re-pin version 1.** Run `uv run --locked python -c "from ntsb_probable_cause.agent import version, run; print(version.prompt_version(run.GUIDANCE))"` and write the printed value into `VERSION_1`. Extend the comment above it: "Re-pinned in S4 Task 1 (2026-10-10, decision 0168), when the invented inputs gained several events, before any cloud night." Show the pin can fail: change `"Approach"` to `"Approach2"` in `_RAW_EVENTS`, run `uv run --locked pytest tests/test_s32_frozen.py -v`, see FAIL, revert; say so in the commit message.
- [x] **Step 7: The notes.** Append to 0161: "*Note, 2026-10-10 (decision 0168):* the invented inputs gained two records with several events, so `+t` now covers `fields.py`'s event selection; version 1 was re-pinned to `<new label>` with continuity on `fd6053f` shown again." In the S3.3 specification, replace "it cannot miss a text" with "it covers the cases its invented inputs exercise" and add "*(Amended 2026-10-10, decision 0168.)*" after the sentence.
- [x] **Step 8:** `make check`; commit: `S4 Task 1: the fingerprint covers several events; version 1 re-pinned (decision 0168)`.
- [x] **Step 9 (Controller):** `make s33-continuity`. The results file must say `match: yes`; add one line at its end by hand only if the script does not already date the run (it does: check the file). If `match: no`, or the script fails because `rendered.py` needs code `fd6053f` lacks, **stop and put it to Andy**. Then `make s33-mutation-sweep`: exit 0, and both keys reported as moving the fingerprint. Commit: `S4 Task 1: +t matches on fd6053f after the re-pin`.

## Task 2: The model pinned by name; replying model, provider and request hash recorded (decision 0169, 0176 item 1)

**Files:** modify `src/ntsb_probable_cause/live/morning.py:85-101`, `src/ntsb_probable_cause/model/client.py` (`ModelReply`, `_parse`-equivalent at `client.py:360-405`), `src/ntsb_probable_cause/agent/trail.py` (`AgentCall`), `agent/loop.py:356` and `agent/armb.py:379` (the two `AgentCall(...)` sites), `agent/drive.py` (`ReplyRow`, `drive_sync`, `drive_batch`); tests in `tests/test_live_morning.py`, `tests/test_model_client.py`, `tests/test_agent_loop.py`, `tests/test_agent_drive.py`.

**Interfaces:**
- `VERSION_1_SETTINGS["model"] == "openai/gpt-6-luna"` (a literal).
- `ModelReply.provider: str | None = None`, parsed from the completion body's top-level `"provider"` (present in `tests/fixtures/openrouter/s3/standard-armb.json`).
- `AgentCall.reply_model: str | None = None`, `AgentCall.reply_provider: str | None = None` (from the reply; `None` when the call failed).
- `ReplyRow.request_sha256: str | None = None` and, in `agent/drive.py`:

```python
def request_sha256(call: PendingCall) -> str:
    """SHA-256 (hex) of what the request sends the model (decision 0176).

    The request body cut to ``rendered.MODEL_FACING_KEYS``, dumped with sorted keys, as
    ``rendered_sha256`` hashes its requests, so the two agree on what "sent" means.
    """
```

- [x] **Step 1: Failing tests.**
  - `tests/test_live_morning.py`: `test_version_1_pins_the_model_by_name`: `assert VERSION_1_SETTINGS["model"] == "openai/gpt-6-luna"`, and with `monkeypatch.setattr(morning, "MODEL_ID", "openai/other")` (and `live_spec` reading it), `settings_differences() == ["model"]`.
  - `tests/test_model_client.py`: parsing `tests/fixtures/openrouter/s3/standard-armb.json` gives `reply.provider == "OpenAI"` and `reply.model == "openai/gpt-6-luna"`; a body with no `"provider"` gives `None`.
  - `tests/test_agent_loop.py`: a scripted reply with `model="openai/gpt-6-luna"`, `provider="OpenAI"` gives an `AgentCall` with those values; a failed call gives `None` for both.
  - `tests/test_agent_drive.py`: after `drive_sync` over a scripted client, every `ReplyRow` in `replies.jsonl` has a 64-hex `request_sha256`, two calls with different history have different hashes, and a row written before this change (no field) still reads.
- [x] **Step 2: Run them.** `uv run --locked pytest tests/test_live_morning.py tests/test_model_client.py tests/test_agent_loop.py tests/test_agent_drive.py -k "name or provider or request_sha" -v` — Expected: FAIL.
- [x] **Step 3: Implement.** In `VERSION_1_SETTINGS`, `"model": "openai/gpt-6-luna",` with the comment "A literal, so an edit of `LUNA_6` cannot pass this check by moving both sides (decision 0169)." Keep `MODEL_ID = LUNA_6.model_id` (the running side). In the reply parser, `provider=_text_or_none(body.get("provider"))` (a `str` kept, anything else `None`). At both `AgentCall(...)` sites, `reply_model=None if reply is None else reply.model or None`, `reply_provider=None if reply is None else reply.provider`. In `drive_sync`, compute `request_sha256(call)` before `client.complete` and pass it to `ReplyRow`; in `drive_batch`, compute it where each round's calls are collected and carry it to the row written for that call. Import `MODEL_FACING_KEYS` from `agent.rendered` and `request_body` from `model.openrouter` (`rendered.py` already imports both, so no contract changes).
- [x] **Step 4: Run** the same tests — PASS. `uv run --locked pytest tests/test_s32_frozen.py` — PASS (no text moved).
- [x] **Step 5:** `make check`; commit: `S4 Task 2: the model pinned by name; replies record model, provider and request hash (decisions 0169, 0176)`.

## Task 3: The `board/1` format, its JSON Schema and an invented sample (decision 0173)

**Files:** create `src/ntsb_probable_cause/live/export.py`, `scripts/board_schema.py`, `docs/schemas/board-1.schema.json`, `tests/board_sample.py`, `tests/fixtures/board/index.json`, `tests/fixtures/board/cases/*.json`, `tests/test_live_export.py`; modify `Makefile` (`board-schema`, `board-sample`, in `.PHONY`).

**Interfaces** — produces, in `live/export.py` (pydantic, every model `frozen=True, extra="forbid"`):

```python
BOARD_FORMAT: Final = "board/1"
Grade = Literal["same_first", "same_codes_other_order", "different", "abstained",
                "not_coded", "awaiting_ntsb"]
CodeMark = Literal["same_place", "other_place", "not_in_other"]

class Code(BaseModel):            # one occurrence or finding code and its label
    code: str
    label: str

class MarkedCode(Code):
    mark: CodeMark

class Aircraft(BaseModel):        # never make, model or registration
    category: str | None          # aircrafts[0].aircraftCategory, e.g. "Airplane"
    engines: int | None           # aircrafts[0].aircraftNumberOfEngines
    engine_type: str | None       # aircrafts[0].engines[0].engineType

class BuildStamp(BaseModel):
    built_at: datetime
    commit: str
    model: str
    training_cutoff: date
    training_cutoff_source: str

class Counts(BaseModel):
    open_watched: int
    open_with_docket: int
    closures_per_night: dict[date, int]
    coded: int
    not_coded: dict[str, int]     # failure kind -> cases
    awaiting_ntsb: int

class BoardRow(BaseModel):
    case_number: str
    closed_on: date
    took_days: int                # closed_on - event date
    aircraft: Aircraft
    agent_first: Code | None
    ntsb_first: Code | None
    grade: Grade

class BoardIndex(BaseModel):
    format: Literal["board/1"] = BOARD_FORMAT
    stamp: BuildStamp
    counts: Counts
    rows: tuple[BoardRow, ...]    # newest closure first, then case number

class Facts(BaseModel):
    state: str | None             # eventStateOrRegion
    kind_of_flight: str | None    # aircrafts[0].ownerOperators[0].flightOperationType
    injury_level: str | None      # highestInjuryLevel
    documents_read: int
    documents_listed: int

class Withheld(BaseModel):
    coded_at: datetime | None     # first call sent, UTC
    commit: str
    prompt_version: str
    model: str                    # asked for
    replied_models: tuple[str, ...]
    providers: tuple[str, ...]

class Answer(BaseModel):          # Ellery's answer
    occurrence: tuple[Code, ...]
    findings: tuple[Code, ...]
    cause: str
    confidence: float
    abstained: bool

class Verdict(BaseModel):         # the NTSB's
    occurrence: tuple[Code, ...]
    findings: tuple[Code, ...]
    cause: str | None

class Comparison(BaseModel):
    agent_occurrence: tuple[MarkedCode, ...]
    ntsb_occurrence: tuple[MarkedCode, ...]
    findings_both: tuple[Code, ...]
    findings_ntsb_only: tuple[Code, ...]
    findings_agent_only: tuple[Code, ...]
    finding_precision_10: float | None
    finding_recall_10: float | None

class Belief(BaseModel):
    kind: Literal["h0", "h1", "h2", "answer"]
    first: Code
    cause: str
    account: str                  # Ellery's evidence_narrative, after the names step
    confidence: float
    changed: bool                 # first code differs from the belief before
    cost_usd: float

class DocumentChoice(BaseModel):
    position: int
    title: str                    # after the names step
    decision: Literal["read", "skipped", "scan_only", "not_offered"]
    note: str | None              # the agent's expected_effect, after the names step

class ReadChoice(BaseModel):
    step: Literal["choice1", "choice2"]
    reason: str
    documents: tuple[DocumentChoice, ...]
    cost_usd: float

class Lookup(BaseModel):
    tool: str
    arguments: dict[str, object]
    cost_usd: float

class Trail(BaseModel):
    beliefs: tuple[Belief, ...]
    read_choices: tuple[ReadChoice, ...]
    lookups: tuple[Lookup, ...]
    total_usd: float

class NotCoded(BaseModel):
    kind: str
    sentence: str

class CaseFile(BaseModel):
    format: Literal["board/1"] = BOARD_FORMAT
    case_number: str
    closed_on: date
    took_days: int
    aircraft: Aircraft
    grade: Grade
    facts: Facts | None           # None when unreachable (no record)
    withheld: Withheld | None
    answer: Answer | None
    verdict: Verdict | None
    comparison: Comparison | None
    trail: Trail | None
    not_coded: NotCoded | None

NOT_CODED_SENTENCES: Final[Mapping[str, str]] = {...}   # below
def board_json_schema() -> dict[str, object]: ...         # {"index": ..., "case": ...}
```

`NOT_CODED_SENTENCES` (one fixed plain sentence per failure kind, spec §10.1; kinds from `live.records.FAILURE_KINDS` plus `"cap: context"`, `"other"`, `"unreachable"`):

```python
{
    "leak": "A document in the docket held the NTSB's probable cause, so the case could not be shown to the agent.",
    "schema": "The agent's reply failed a technical check twice.",
    "failed": "The agent's run stopped at a step that failed twice.",
    "model": "The model service did not return a usable reply.",
    "cap": "The case reached its cost limit before the agent answered.",
    "cap: context": "The case's documents were too long to send to the model.",
    "aborted": "The run was stopped before this case finished.",
    "missing result": "The run finished without a result for this case.",
    "unreachable": "The case's record or docket could not be read on seven nights.",
    "other": "The case could not be coded, for a reason the system does not name.",
}
```

- [x] **Step 1: Failing tests** (`tests/test_live_export.py`):

```python
def test_sample_index_validates() -> None:
    BoardIndex.model_validate_json((SAMPLE / "index.json").read_text())

def test_sample_cases_validate_and_cover_every_grade() -> None:
    files = sorted((SAMPLE / "cases").glob("*.json"))
    grades = {CaseFile.model_validate_json(f.read_text()).grade for f in files}
    assert grades == set(get_args(Grade))

def test_committed_schema_matches_the_models() -> None:
    committed = json.loads(SCHEMA.read_text())
    assert committed == board_json_schema()

def test_committed_sample_matches_its_builder() -> None:
    built = board_sample.build()            # {relative path: text}
    on_disk = {p.relative_to(SAMPLE).as_posix(): p.read_text()
               for p in SAMPLE.rglob("*.json")}
    assert built == on_disk

def test_every_failure_kind_has_a_sentence() -> None:
    assert set(NOT_CODED_SENTENCES) >= {*FAILURE_KINDS, "cap: context", "other", "unreachable"}

def test_the_sample_holds_no_forbidden_value() -> None:
    text = "\n".join(p.read_text() for p in SAMPLE.rglob("*.json"))
    for forbidden in board_sample.FORBIDDEN:   # the invented registration, make, model,
        assert forbidden not in text            # owner and lay explanation board_sample uses
```

  where `SAMPLE = Path("tests/fixtures/board")`, `SCHEMA = Path("docs/schemas/board-1.schema.json")`.
- [x] **Step 2: Run** `uv run --locked pytest tests/test_live_export.py -v` — FAIL (module missing).
- [x] **Step 3: Write `live/export.py`** with the models above and `board_json_schema()` returning `{"index": BoardIndex.model_json_schema(), "case": CaseFile.model_json_schema()}`. Module docstring: what `board/1` is, the version rule (adding an optional field keeps `board/1`; removing, renaming or changing a meaning makes `board/2`), and the never-holds list (spec §10.2).
- [x] **Step 4: Write `tests/board_sample.py`**: invented cases `XXX26XX001` … `XXX26XX006`, one per grade, built as `CaseFile` and `BoardRow` values; the `same_first` case has two read choices and a `scan_only` document; one case is amateur-built (its `Aircraft` carries category and engines only); `FORBIDDEN = ("N123XX", "Inventedmake", "INV-1", "Invented Owner", "lay explanation marker")` names the values its source record would hold and the sample must not. `build() -> dict[str, str]` returns `{"index.json": ..., "cases/XXX26XX001.json": ...}`, each `model.model_dump_json(indent=2) + "\n"`. Add `if __name__ == "__main__":` writing them under `tests/fixtures/board/`.
- [x] **Step 5: Write `scripts/board_schema.py`** (`Status`: "Live tooling (S4 Task 3). Free. Writes `docs/schemas/board-1.schema.json` from `live.export`."), `main(argv)` writing `json.dumps(board_json_schema(), indent=2, sort_keys=True) + "\n"`. `Makefile`: `board-schema:` → `uv run --locked python -m scripts.board_schema`; `board-sample:` → `uv run --locked python -m tests.board_sample`. Run both.
- [x] **Step 6: Run** the tests — PASS. `make check`.
- [ ] **Step 7:** commit: `S4 Task 3: the board/1 format, its JSON Schema and an invented sample (decision 0173)`. **Controller:** push the branch and tell Andy S5 can start from `docs/schemas/board-1.schema.json` and `tests/fixtures/board/`.

## Task 4: The names measurement on `dev-400` (decision 0180 item 4) — built by a subagent, run by the Controller

**Files:** create `scripts/s4_names_probe.py`, `tests/test_s4_names_probe.py`, `Makefile` target `s4-names-probe`; the Controller creates `docs/results/s4-names-dev.txt`.

**Background.** Development cases only: the two noise-floor runs `20261001T201506-fd6053f-dev-400-C` and `20261001T201648-fd6053f-dev-400-C` under `NTSB_RUNS_DIR`, their raw records from `data/processed/cases.parquet` (`scoring.samples.load_cases` or the S3 scripts' loader `scripts/_s3_runs.py`), and their docket listings from the development docket cache (`docket.client.DocketClient(settings.docket_dir)` reads the cached `listing.html`; `docket.listing.parse_listing`). Never a live run (the S3 loader refuses them).

**What it counts**, per text kind, over the cases the two runs share: `cause` (each checkpoint's and the answer's `probable_cause`), `account` (`evidence_narrative`), `note` (each read decision's `expected_effect`), `reason` (each read choice's `reason`), and `ntsb_cause` (the record's probable cause, `records.verdict`). Flagged words come from `docket.title_vocab`: a capitalised word (`capitalised_words`) not in `known_title_words()`. For each kind:
1. cases whose text holds a word flagged in that case's own titles;
2. cases whose text holds an owner or operator string (`docket.attach.owner_operator_values`);
3. cases whose text holds a flagged word **outside** the rule (not among the case's own flagged title words and not inside an owner or operator string);
4. the total of 3's words.

The rule fixed before it runs (spec §12.2): if (3) is 0 for every kind, the rule stands; if not, Andy chooses (the full title rule on Ellery's text, or a published limit; for accounts also an empty field).

**Interfaces:** `def count_names(cases: Sequence[NameCase], known: frozenset[str]) -> NameCounts` (pure; `NameCase` holds `titles: tuple[str, ...]`, `owner_operator: tuple[str, ...]`, `texts: Mapping[str, tuple[str, ...]]`); `def main(argv: Sequence[str] | None = None) -> int` (`--out PATH`). The output prints counts and the kinds only, never a word, a title or a case number.

- [x] **Step 1: Failing test** with invented `NameCase`s: a title `"Statement of Smithers"` and a note `"Smithers saw the approach"` counts in (1) not (3); a cause naming `"Quimby"` absent from titles and owners counts in (3) with 1 word; an owner `"Invented Aviation LLC"` in an account counts in (2) not (3); `main` with a fake loader writes a file holding no invented word.
- [x] **Step 2: Run** — FAIL. **Step 3: Implement** with a `Status` paragraph ("Run once in S4 (spec §12.2). Free; development cases only; counts only."). `Makefile`: `s4-names-probe:` → `uv run --locked python -m scripts.s4_names_probe --out docs/results/s4-names-dev.txt`. **Step 4: Run** — PASS; `make check`; commit `S4 Task 4: the names measurement script`.
- [x] **Step 5 (Controller):** with `NTSB_DATA_DIR` set, `make s4-names-probe`; read the file; commit it (`S4 Task 4: names counts on dev-400`). Put the counts to Andy in simplified English with the rule fixed above, and record his choice in the Deviations section with his words. Task 5 implements the rule he chooses.

## Task 5: The names step in the library (decision 0180)

**Files:** move `tests/fixtures/words.txt` → `src/ntsb_probable_cause/docket/vocab/words.txt` (`git mv`); modify `src/ntsb_probable_cause/docket/title_vocab.py`, `scripts/check_fixtures_redacted.py`, every importer of `VENDORED_DICTIONARY_PATH` (`grep -rn VENDORED_DICTIONARY_PATH src scripts tests`); create `src/ntsb_probable_cause/live/names.py`, `tests/test_live_names.py`; extend `tests/test_title_vocab.py`, `tests/test_check_fixtures_redacted.py`.

**Interfaces:**
- `docket/title_vocab.py`: `known_title_words()` reads the word list as package data (`resources.files(_VOCAB_PACKAGE).joinpath("vocab/words.txt")`) and always finds it; it keeps returning `(words, True)` so its callers do not change. `title_looks_like_a_name(title, known) -> bool` moves here from the script, which imports it.
- `live/names.py`:

```python
NAME_MARKER: Final = "[name]"

@dataclass(frozen=True)
class CaseNames:
    """What one case's names step replaces: its own flagged title words and owner strings."""
    title_words: frozenset[str]          # lowercased
    owner_operator: tuple[str, ...]

def case_names(titles: Sequence[str], raw: Mapping[str, object], known: frozenset[str]) -> CaseNames: ...
def board_title(title: str, known: frozenset[str]) -> str: ...      # redact_title with NAME_MARKER
def board_text(text: str, names: CaseNames) -> str: ...             # own title words + owners replaced
```

  `board_text` replaces whole words, case-insensitively, and owner strings with `docket.attach.redact_known_names`'s rule, then the case's flagged title words. If Andy chose the full rule in Task 4, `board_text` also takes `known` and replaces every flagged word; if he chose an empty account field, `live/board.py` (Task 11) leaves `Belief.account` as `""` and a constant `ACCOUNTS_SHOWN = False` says why.

- [x] **Step 1: Failing tests** (`tests/test_live_names.py`): `board_title("Statement of Smithers", known) == "Statement of [name]"`; `board_text("Smithers reported a gust", names)` gives `"[name] reported a gust"` when `"smithers"` is among the case's title words; an owner `"Invented Aviation LLC"` in a cause is replaced; `"Cessna"` (in the word list) is kept; the import works with no `tests/` folder on the path (run the check in a subprocess with `cwd=tmp_path`). In `tests/test_title_vocab.py`: `known_title_words()[1] is True` from any working directory.
- [x] **Step 2: Run** — FAIL. **Step 3: Implement.** Package data: confirm `docket/vocab/words.txt` ends up in the wheel (`uv build` then `unzip -l dist/*.whl | grep words.txt`; hatchling includes non-Python files under the package by default, as `title_words.txt` shows). **Step 4: Run** — PASS; `make check` (the redaction check's tests pass with the moved list).
- [x] **Step 5:** commit: `S4 Task 5: the names step in the library; the word list ships in the package (decision 0180)`.

## Task 6: Seen pairs as a table, document hashes, and closure record version 2 (decision 0176)

**Files:** create `scripts/s4_seen_pairs.py`, `src/ntsb_probable_cause/scoring/tables/seen_pairs_dev.json`, `tests/test_s4_seen_pairs.py`; modify `src/ntsb_probable_cause/scoring/samples.py`, `src/ntsb_probable_cause/docket/client.py`, `src/ntsb_probable_cause/live/records.py`, `src/ntsb_probable_cause/live/closure.py`, `src/ntsb_probable_cause/live/morning.py` (`seen_pairs` call, `build_records` call); tests in `tests/test_live_records.py`, `tests/test_docket_client.py`, `tests/test_samples.py`.

**Background.** `AgentRunner` takes `seen_pairs`; the morning computes it from `data/processed/cases.parquet` (`scoring/samples.py:171`), which the container does not hold. The set is the primary occurrence codes of the development split: codes only, no case. Commit it as a table.

**Interfaces:**
- `scoring/samples.py`: `def load_seen_pairs() -> frozenset[str]` reads `scoring/tables/seen_pairs_dev.json` (`{"format": "seen-pairs/1", "split": "dev", "codes": [...]}`).
- `docket/client.py`: `def cached_hashes(cache: Path, mkey: int) -> tuple[str | None, dict[int, str]]` — the listing's and each document index's SHA-256 from `<cache>/<mkey>/fetch.json`, as `DocketClient` recorded them.
- `live/records.py`: `CLOSURE_FORMAT = "live-closure/2"`; `DocumentLine` gains `sha256: str | None`; `ClosureRecord` gains `event_date: date`, `listing_sha256: str | None`, `request_sha256s: tuple[str, ...]` (call order, from `replies.jsonl`), `replied_models: tuple[str, ...]`, `providers: tuple[str, ...]` (distinct, sorted, from the trail); `format: Literal["live-closure/2"]`.
- `live/closure.py`: `build_records(folder, prepared, lock_sha, docket_cache: Path)`.

- [x] **Step 1: Failing tests.** `test_s4_seen_pairs`: the script over a tiny invented parquet (two dev rows, one held-out row) writes exactly the dev codes, sorted; `load_seen_pairs()` returns a non-empty frozenset of 6-digit strings. `test_docket_client`: after `DocketClient(tmp).document(1, 2, "h")` with a fake transport, `cached_hashes(tmp, 1)` returns the SHA-256 of the bytes at index 2. `test_live_records`: a record built from an invented run folder with a `replies.jsonl` of two rows carries both hashes in order, each document line's `sha256`, the `event_date`, and `format == "live-closure/2"`; a v1 line (old format) fails validation (only v2 is written to the bucket).
- [x] **Step 2: Run** — FAIL. **Step 3: Implement.** `scripts/s4_seen_pairs.py` (`Status`: "Run once in S4 (Task 6). Free; development split; codes only."), calling the existing `seen_pairs(processed)` and writing the table. The morning uses `load_seen_pairs()` everywhere it called `seen_pairs(settings.data_dir / "processed")`. `build_records` takes the hashes before `_cleanup` deletes the cache (the morning already calls it first; keep that order and say so in a comment).
- [x] **Step 4 (Controller, free):** with `NTSB_DATA_DIR` set, run `uv run --locked python -m scripts.s4_seen_pairs`; a test asserts the committed table equals `seen_pairs(...)` when the parquet is present and skips otherwise.
- [x] **Step 5: Run** — PASS; `make check`; commit: `S4 Task 6: seen pairs as a table; closure record version 2 with document and request hashes (decision 0176)`.

## Task 7: The queue and money in the morning (decisions 0170, 0175)

**Files:** create `src/ntsb_probable_cause/live/state.py`; modify `src/ntsb_probable_cause/live/seams.py`, `live/local.py`, `live/queue.py`, `live/morning.py`; tests in `tests/test_live_morning.py`, `tests/test_live_queue.py`, `tests/test_live_local.py`, new `tests/test_live_state.py`.

**Interfaces:**
- `live/seams.py`:

```python
@dataclass(frozen=True)
class MonthSpend:
    used_usd: float
    limit_usd: float

class SpendCounter(Protocol):
    def month(self, now: datetime) -> MonthSpend:
        """This calendar month's live spend and the limit it is held to.

        Raises:
            LiveRefusal: kind "key-unreachable" when the spend or limit cannot be read.
        """
```

  `ResultSink` loses `coded_on`; gains `night_state() -> NightState` and `write_night_state(state: NightState) -> None`.
- `live/state.py`:

```python
class NightState(BaseModel, frozen=True):
    """Carried from night to night: counted fetch failures and the cases settled unreachable."""
    format: Literal["live-state/1"] = "live-state/1"
    failures: dict[str, int] = {}          # case id -> counted failed nights
    unreachable: dict[str, Closed] = {}    # case id -> its closure facts

class Closed(BaseModel, frozen=True):
    mkey: int
    event_date: date
    closed_on: date

ALERT_AT: Final = 3        # decision 0175
FINAL_AT: Final = 7

def after_fetches(state: NightState, take: Sequence[QueuedCase], failed: Set[str],
                  fetched: int) -> tuple[NightState, list[str]]:
    """Count tonight's failures and settle cases at FINAL_AT; return the alerts' kinds.

    A failure counts only when ``fetched`` > 0 (another case fetched); otherwise the night is an
    outage: nothing counts and the kinds are ["outage"]. A case reaching ALERT_AT adds
    "unreachable-3"; reaching FINAL_AT moves it to ``unreachable`` and adds
    "unreachable-final". A case that fetched is removed from ``failures``.
    """
```

- In `live/morning.py`: `class LiveRefusal(ConfigurationError)` with `kind: str` (one of `"version-refused"`, `"recorder-not-finished"`, `"store-unsound"`, `"key-unreachable"`, `"money-held-back"`, `"docket-folders"`), raised wherever `_Refusals.add` is called today, carrying the kind; `ConfigurationError` raised by `Store.closures()` is re-raised as `LiveRefusal("store-unsound", ...)`.
- `live/morning.py`:

```python
LIVE_CAP_USD: Final = 0.30                 # decision 0144, a version 1 setting
LIVE_MONTH_CAP_USD: Final = 9.0            # decision 0170
LIVE_MARGIN_USD: Final = 1.0

def cases_tonight(spend: MonthSpend) -> tuple[int, float]:
    """(cases, room in dollars) by the full-cap rule: floor((cap - used) / $0.30), cap the lower
    of $9 and the limit less $1; never below 0."""
```

  `MorningSummary` gains `held_back: int` (cases queued past tonight's number). No case id leaves the morning: `run_morning` returns `NightOutcome(summary: MorningSummary, alerts: tuple[str, ...])`, the alerts being kinds only. `live_spec(budget_usd)` sets `expected_cost_per_case_usd=LIVE_CAP_USD` and the morning passes `room`. `EXPECTED_COST_PER_CASE_USD`, `MONTHLY_CAP_USD`, `DAILY_LIMIT`, `todays_take` and the `$40`-guard half of `_check_cap` are removed. `done` for the queue is `sink.done_case_ids() | state.unreachable.keys()`. `_fetch` returns `(fetched, failed_ids)`.
- `live/local.py`: `LocalSpend.month(now)` returns `MonthSpend(used_usd=<as before>, limit_usd=10.0)`; `LocalFolderSink.night_state()` reads `<runs_dir>/live-state.json` (default `NightState()`), `write_night_state` writes it.

- [x] **Step 1: Failing tests.**
  - `test_live_state.py`: (a) take 3, 1 failed, 2 fetched → failures `{id: 1}`, no alert; (b) the same case fails twice more on nights with fetches → `["unreachable-3"]` on the third; (c) on the seventh → `"unreachable-final"`, the case is in `unreachable` and out of `failures`; (d) every case failed (`fetched == 0`) → `["outage"]`, failures unchanged; (e) a case that fetched is dropped from `failures`.
  - `test_live_morning.py`: `cases_tonight(MonthSpend(0.71, 10.0)) == (27, 8.29)` (rounded to the cent in the assert); `cases_tonight(MonthSpend(0.0, 5.0)) == (13, 4.0)`; `cases_tonight(MonthSpend(9.5, 10.0)) == (0, 0.0)`; a morning with 40 queued and room for 27 codes 27 and reports `held_back == 13` and alert `"money-held-back"`; a spend counter that raises `LiveRefusal("key-unreachable")` stops the morning before the store is opened; the version check raises `LiveRefusal` with `kind == "version-refused"`; a store whose `closures()` raises `ConfigurationError` gives `kind == "store-unsound"`; a case settled unreachable is never queued again.
  - Update the S3.3 tests that used `DAILY_LIMIT`, `coded_on` or the $5 cap: delete what tests removed behaviour, and say so in the commit message.
- [x] **Step 2: Run** `uv run --locked pytest tests/test_live_state.py tests/test_live_morning.py tests/test_live_queue.py tests/test_live_local.py -v` — FAIL.
- [x] **Step 3: Implement** in the order: `state.py`, `seams.py`, `local.py`, `morning.py`. In `morning.py`, the order of a morning becomes: label and settings → docket folders → **spend (`deps.spend.month`)** → store → recorder's run → unrecorded runs → resume (refused with `money-held-back` when its unanswered cases × $0.30 exceed the room) → queue (`done | unreachable`) → backfill → fetch → `after_fetches` → run → records → cleanup → `sink.write_night_state`. Keep the S3.3 refusal log (`live-refusals.jsonl`) writing the kind.
- [x] **Step 4: Run** — PASS; `make check`; commit: `S4 Task 7: the full-cap rule, counted fetch failures and refusal kinds in the morning (decisions 0170, 0175)`.

## Task 8: Later scores (decision 0174)

**Files:** create `src/ntsb_probable_cause/live/later.py`, `tests/test_live_later.py`.

**Interfaces:**

```python
SCORES_FORMAT: Final = "live-score/1"
AWAIT_ALERT_NIGHTS: Final = 7

class LaterScore(BaseModel, frozen=True):
    format: Literal["live-score/1"] = SCORES_FORMAT
    case_id: str
    scored_on: date
    record_sha256: str                    # sha256 of json.dumps(raw, sort_keys=True)
    verdict_occurrence: tuple[str, ...]
    verdict_findings: tuple[str, ...]
    verdict_findings_in_cause: tuple[str, ...]
    ntsb_cause: str | None
    top1: bool
    top3: bool
    abstained: bool
    finding_precision_10: float | None
    finding_recall_10: float | None

@dataclass(frozen=True)
class Awaiting:
    case_id: str
    mkey: int
    event_date: date
    closed_on: date
    coded_on: date
    answer: Hypothesis                    # the case's final step's hypothesis

def awaiting(runs: Sequence[Path], scored: Set[str]) -> list[Awaiting]:
    """Coded cases whose closure record is unscored and that no later score covers."""

def score_later(raw: Mapping[str, object], case: Awaiting, today: date) -> LaterScore | None:
    """Score ``case`` against ``raw``'s verdict through ``split_record`` and ``score_case``
    (with ``load_seen_pairs()``); None while the record has no occurrence codes."""

def overdue(cases: Sequence[Awaiting], today: date) -> int:
    """How many have waited AWAIT_ALERT_NIGHTS nights or more since coding."""
```

- [x] **Step 1: Failing tests** with an invented run folder (closure record `scored=False`, `outcome="coded"`; `cases.jsonl` with a final step's hypothesis) and invented raw records: `awaiting` finds the case; a raw with no occurrence codes gives `None`; a raw with codes gives a `LaterScore` whose `top1` matches `score_case` on the same inputs and whose `record_sha256` changes when the raw changes; a case already in `scored` is not awaiting; `overdue` counts a case coded 7 nights before `today` and not one coded 6 nights before; a case `not coded` is never awaiting.
- [x] **Step 2: Run** — FAIL. **Step 3: Implement** (pure, no I/O but reading the folders passed in). **Step 4: Run** — PASS; `make check`; commit: `S4 Task 8: later scores when the NTSB's codes arrive (decision 0174)`.

## Task 9: The cloud seams (decisions 0170, 0172, 0177)

**Files:** create `src/ntsb_probable_cause/live/cloud.py`, `tests/test_live_cloud.py`; modify `src/ntsb_probable_cause/settings.py` (`live_bucket: str | None = None`, `live_alert_topic_arn: str | None = None`), `tests/test_sources_settings.py`.

**Interfaces** (no boto3 or httpx import in this module; clients come in through these protocols):

```python
class BucketLike(Protocol):
    def list_keys(self, bucket: str, prefix: str) -> list[tuple[str, int]]: ...   # (key, size)
    def download_file(self, bucket: str, key: str, filename: str) -> None: ...
    def upload_file(self, filename: str, bucket: str, key: str) -> None: ...
    def put_if_absent(self, bucket: str, key: str, body: bytes) -> bool: ...      # False if it exists

class BucketMirror:
    """The bucket's ``runs/``, ``scores/`` and ``nights/`` held in a local folder."""
    def __init__(self, bucket: str, local: Path, s3: BucketLike) -> None: ...
    def pull(self) -> None: ...                       # every object under the three prefixes
    def push(self, relative: Path) -> int: ...        # upload files changed since pull or last
                                                      # push (by SHA-256); return how many
    def mark_started(self, day: date) -> bool: ...    # put_if_absent("nights/<day>/started")
    def push_export(self, folder: Path) -> None: ...  # every file to export/board-1/

class HttpGet(Protocol):
    def __call__(self, url: str, *, headers: Mapping[str, str]) -> tuple[int, object]: ...

class OpenRouterKeySpend:
    """The live key's ``usage_monthly`` and ``limit`` from ``GET /api/v1/key``."""
    def __init__(self, key: str, base_url: str, get: HttpGet) -> None: ...
    def month(self, now: datetime) -> MonthSpend: ...

class Alerts(Protocol):
    def send(self, kinds: Sequence[str], counts: Mapping[str, int]) -> None: ...

class PrintAlerts: ...                               # prints one line; local and dry runs
class SnsLike(Protocol):
    def publish(self, *, TopicArn: str, Subject: str, Message: str) -> object: ...
class SnsAlerts:
    def __init__(self, topic_arn: str, sns: SnsLike) -> None: ...
class MetricLike(Protocol):
    def put_metric_data(self, *, Namespace: str, MetricData: list[dict[str, object]]) -> object: ...
METRIC_NAMESPACE: Final = "Ntsb/Live"
METRIC_NAME: Final = "NightFinished"
def publish_finished(metric: MetricLike) -> None: ...  # one data point, value 1

class MirrorSink:
    """``ResultSink`` over the mirror: ``LocalFolderSink`` on ``<local>/runs`` for reads, the
    night state at ``<local>/nights/state.json``, and ``write`` / ``write_night_state`` push
    what they wrote."""
```

  `OpenRouterKeySpend.month` raises `LiveRefusal("key-unreachable", ...)` when the status is not 200, the body has no `data` object, `usage_monthly` is not a number, or `limit` is null or not a number. `SnsAlerts.send` writes `Subject` "Ellery live night: <kinds joined>" (under 100 characters) and a `Message` of `kind: count` lines; a test checks no case-number pattern (`[A-Z]{3}\d{2}[A-Z]{2}\d{3}`) can be in it because only kinds and integers are formatted. The night state lives at `nights/state.json` in the bucket (one object, overwritten each night; versioning keeps every earlier one).

- [x] **Step 1: Failing tests** with in-memory fakes (`FakeBucket` holding a dict of key → bytes, `put_if_absent` honouring existence; `FakeHttp` returning scripted `(status, body)`; `FakeSns`, `FakeMetric` recording calls):
  - `pull` then `push` of an unchanged folder uploads 0 files; after one file changes, 1;
  - a pulled half-written folder (`spec.json` and `replies.jsonl`, no `run.jsonl`) is reported by `MirrorSink.unfinished_run()` (Review Focus 2);
  - `mark_started` is `True` once and `False` the second time on the same day (Review Focus 5);
  - `OpenRouterKeySpend.month` with `{"data": {"usage_monthly": 0.71, "limit": 10}}` → `MonthSpend(0.71, 10.0)`; with status 500, `{}`, `{"data": {"usage_monthly": "0.7", "limit": 10}}`, `{"data": {"usage_monthly": 0.7, "limit": None}}` → `LiveRefusal` with `kind == "key-unreachable"` (Review Focus 3); the request carries `Authorization: Bearer <key>` and the test never prints it;
  - `SnsAlerts.send(["outage"], {"cases": 3})` publishes once to the topic with both lines; `publish_finished` sends one data point named `NightFinished` in `Ntsb/Live`.
- [ ] **Step 2: Run** — FAIL (no RED run was made; tests and module were written together). **Step 3: Implement.** **Step 4: Run** — PASS; `make check`; commit: `S4 Task 9: the cloud seams: bucket mirror, key spend, alerts and metric (decisions 0170, 0172, 0177)`.

## Task 10: The night, the push after each reply, and `ntsb-live run` in the image (decisions 0171, 0175, 0177)

**Files:** create `src/ntsb_probable_cause/live/night.py`, `tests/test_live_night.py`; modify `src/ntsb_probable_cause/agent/drive.py` (`drive_sync(..., on_reply: Callable[[], None] | None = None)`), `src/ntsb_probable_cause/agent/run.py` (`AgentRunner(..., on_reply=...)`, passed to `drive_sync` only), `live/morning.py` (`MorningDeps.on_reply_factory`), `apps/live/__main__.py`, `tests/test_live_app.py`, `tests/test_agent_drive.py`.

**Interfaces:**

```python
# live/night.py
NIGHT_FORMAT: Final = "live-night/1"
NIGHT_MANIFEST_FORMAT: Final = "live-night-manifest/1"

@dataclass(frozen=True)
class NightDeps:
    morning: MorningDeps            # its sink is a MirrorSink, its spend an OpenRouterKeySpend
    mirror: BucketMirror
    alerts: Alerts
    metric: MetricLike | None       # None outside the image
    ntsb: Callable[[], NtsbClient]  # for later scores
    export: Callable[[Path], Path]  # builds the export from the mirror; returns its folder (Task 11)

@dataclass(frozen=True)
class NightReport:
    started: bool                   # False when today's marker already existed
    outcome: NightOutcome | None
    alerts: tuple[str, ...]
    later_scored: int

def run_night(deps: NightDeps) -> NightReport: ...
```

  `run_night`, in order: `mirror.mark_started(today)` (False → print "a night already started today", alert nothing, return); `mirror.pull()`; `run_morning(...)` with `on_reply` pushing the open run folder (first call: settle the pending inputs into the folder, then `mirror.push`); on `LiveRefusal` record its kind as the alert and continue to the end steps that need no store; later scores (`later.awaiting`, re-fetch each through `live.fetch.fetch_record`, `score_later`, append to `scores/<today>.jsonl`, `overdue` → `"awaiting-codes-7"`); write `nights/<today>/night.json` (`{"format", "date", "coded", "not_coded", "held_back", "later_scored", "alerts", "failures_counted"}`, counts only) and `nights/<today>/manifest.json` (the night's files with sizes and SHA-256, plus `"counts"`); push; `publish_finished` only when no refusal stopped the night; build and push the export; `alerts.send` once with every kind collected. Any other exception: send `["night-crashed"]` with no counts, then re-raise (the missed-night alarm also fires).

- `apps/live/__main__.py`: `run` without `--dry-run` refuses (exit 1, one line) unless `settings.commit_sha` is set **and** `settings.live_bucket` is set: "ntsb-live run: paid nights run only in the live image (decision 0171); use --dry-run here." In the image it builds `NightDeps` (boto3 S3 wrapped as `BucketLike`, `sns`, `cloudwatch` clients; `httpx.get` wrapped as `HttpGet`; the morning's `ResultSink` a `MirrorSink`) and calls `run_night`. `--dry-run` with `live_bucket` set pulls the mirror into a temporary folder and runs the morning's dry run on it, with `PrintAlerts`, writing nothing to the bucket. The `FetchError | DocketError` line ends "See the runbook, 'fetch-failed'." instead of "Tell Claude if it happens again." (decision 0175).

- [x] **Step 1: Failing tests.** `test_agent_drive.py`: `on_reply` is called once after each `replies.jsonl` row is written, and never when absent. `test_live_night.py`, with every seam faked (the fake NTSB client replays invented records; the fake model replays scripted replies from `agent/rendered.py`'s helpers or the S3.3 morning tests' fake):
  - a normal night: marker set, one run folder pushed with `closures.jsonl` and `manifest.json`, a night record and night manifest, the metric published once, the export callable called once, no alert;
  - **a kill after the first pushed reply** (the fake model raises `KeyboardInterrupt` on the second call): the bucket holds the folder with `inputs.jsonl` and one reply; a second `run_night` on the next day resumes it, sends only the unanswered calls (count the fake model's calls), and codes no case twice (Review Focus 1);
  - same-day second start: `run_night` returns `started=False` and the fake store was never opened (Review Focus 5);
  - an outage night: alert `["outage"]`, no failure counted; a key that fails: alert `["key-unreachable"]`, nothing spent, no metric; a recorder not finished: `["recorder-not-finished"]`;
  - a later score: a pulled run with an unscored case and a fake NTSB record that now has codes → one line in `scores/<today>.jsonl`;
  - `night.json` and the alert message hold no case-number pattern.
  `test_live_app.py`: `run` without `--dry-run` and without `NTSB_COMMIT_SHA` exits 1 with the refusal line and calls nothing; the `FetchError` line names the runbook row.
- [x] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS; `make check`; commit: `S4 Task 10: the cloud night, a push after each reply, and paid nights only in the image (decisions 0171, 0175, 0177)`.

## Task 11: The export builder and `ntsb-live export` (decisions 0173, 0180)

**Files:** create `src/ntsb_probable_cause/live/board.py`, `tests/test_live_board.py`; modify `apps/live/__main__.py` (`export --from DIR --out DIR`), `tests/test_live_app.py`.

**Interfaces:**

```python
def build_export(mirror: Path, out: Path, *, store: Store | None, today: date,
                 commit: str, now: datetime) -> Path:
    """Write ``index.json`` and ``cases/<case>.json`` under ``out`` from the mirror's runs and
    scores, and the store's counts (open watched, open with docket, closures per night); return
    ``out``. ``store=None`` writes zero counts (local development without a store)."""

def grade(record: ClosureRecord, later: LaterScore | None) -> Grade: ...
def occurrence_marks(agent: Sequence[str], ntsb: Sequence[str]) -> tuple[list[CodeMark], list[CodeMark]]: ...
```

  Sources, per case: the closure record (grade inputs, documents, titles, hashes, timing, commit), `inputs.jsonl` (facts from the raw paths in Task 3's `Facts` and `Aircraft` comments, the NTSB's verdict through `split_record`), `cases.jsonl` (the checkpoints' `StepRecord`s: beliefs, costs, final answer), `trail.jsonl` (read choices' `ChooseDocuments` arguments with `expected_effect` and `reason`, coding lookups' tool and arguments, costs), and any `LaterScore`. Grades: `not coded` → `not_coded`; abstained → `abstained`; unscored and no later score → `awaiting_ntsb`; `top1` → `same_first`; `top3` → `same_codes_other_order`; else `different`. Labels: occurrence `phases[code[:3]] + " / " + events[code[3:]]`; finding `items[code[:8]]` and the modifier label `modifiers[code[8:]]` joined by `" - "`. Every title passes `names.board_title`; every cause, account, note and reason passes `names.board_text` with that case's `CaseNames`. Unreachable cases come from `NightState.unreachable`, with `facts=None` and the `"unreachable"` sentence. A case not coded still gets its `verdict` filled from its record, because the board shows the NTSB's cause beside the failure (S5 §4).

- [x] **Step 1: Failing tests** (invented run folders made by a helper in the test module from Task 3's sample values; no development or live data):
  - the built export validates against `BoardIndex` and `CaseFile`; rows are newest closure first;
  - each grade comes out for the matching inputs; `occurrence_marks(["552230", "552090"], ["552090", "551230"])` → `(["not_in_other", "other_place"], ["other_place", "not_in_other"])`, and identical lists give all `"same_place"`;
  - **never-holds** (spec §10.2, Review Focus 4): an invented raw holding registration `"N123XX"`, make `"Inventedmake"`, model `"INV-1"`, owner `"Invented Owner"`, a lay explanation `"LAY-MARKER"`, a title `"Statement of Smithers"`, an account and a note naming `"Smithers"` and `"Invented Owner"`, and a docket text `"DOC-TEXT-MARKER"`: none of these strings is in any exported file, and `"[name]"` is;
  - a case with a later score is graded from it; an unreachable case has the unreachable sentence;
  - `ntsb-live export --from <mirror> --out <dir>` writes the files and prints counts only.
- [x] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS; `make check`; commit: `S4 Task 11: the board/1 export builder and ntsb-live export (decisions 0173, 0180)`.

## Task 12: `NtsbLiveStack` and the image script (decision 0171)

**Files:** create `infra/live_stack.py`, `scripts/build_live_image.sh`, `tests/test_live_stack.py`, `tests/test_build_live_image.py`; modify `infra/app.py` (instantiate `NtsbLiveStack` beside the recorder's, reading CDK context), `Dockerfile` only if a test shows it needs a change (it should not: the task overrides the command).

**What the stack holds** (spec §4.1; every resource named in the template test):
- `ec2.Vpc` "Vpc": two public subnets in `eu-west-2a`/`eu-west-2b`, `nat_gateways=0`; a security group with no inbound rule and all outbound.
- `ecr.Repository` "Repository": `repository_name="ntsb-live"`, `TagMutability.IMMUTABLE`, scan on push, lifecycle `max_image_count=5`, `RETAIN`.
- `s3.Bucket` "LiveBucket": private (`BlockPublicAccess.BLOCK_ALL`), versioned, `enforce_ssl=True`, S3-managed encryption, `RETAIN`, lifecycle: noncurrent versions under `export/` expire after 30 days.
- `ecs.Cluster` named `ntsb-live`; `logs.LogGroup` `/ecs/ntsb-live`, 30 days.
- `ecs.FargateTaskDefinition` family `ntsb-live`, `cpu=512`, `memory_limit_mib=1024`, x86; container from `ecs.ContainerImage.from_ecr_repository(repository, tag=f"@{digest}")` or the digest form CDK supports (context `live_image_digest`, required at synth unless the context `live_image_digest_placeholder=1` is set for tests); command `["timeout", "10800", "ntsb-live", "run"]` (3 hours, matching the recorder's `timeout` wrapper); environment `NTSB_LIVE_BUCKET`, `NTSB_LIVE_ALERT_TOPIC_ARN`, `NTSB_STORE=s3://<recorder bucket>/recorder.sqlite` (context `recorder_bucket`); secrets `NTSB_API_KEY` from `/ntsb/api-key` and `OPENROUTER_API_KEY` from `/ntsb/live/openrouter-key` (`ssm.StringParameter.from_secure_string_parameter_attributes` by name; the stack never creates either).
- Task role: `s3:GetObject` on `arn:aws:s3:::<recorder bucket>/recorder.sqlite`; on the live bucket `s3:ListBucket`, `s3:GetObject`, `s3:PutObject` only (no `s3:DeleteObject*`); `sns:Publish` on the topic; `cloudwatch:PutMetricData` with the condition `cloudwatch:namespace = Ntsb/Live`.
- `sns.Topic` "AlertTopic" with an email subscription to the context `alert_email` (Andy confirms it).
- `cloudwatch.Alarm` "MissedNight" on metric `Ntsb/Live` `NightFinished`, statistic Sum, period 6 hours, 5 evaluation periods, threshold `< 1`, `TreatMissingData.BREACHING`, action the topic. Before committing, confirm the period and evaluation limits on AWS's CloudWatch alarm documentation and record the page and date in a comment.
- `scheduler.CfnSchedule` "Nightly": `cron(0 6 * * ? *)`, UTC, `State` `DISABLED` unless context `live_schedule=enabled`; target the task on the cluster with the public subnets, `assignPublicIp` ENABLED, a role allowed `ecs:RunTask` on the task definition and `iam:PassRole` on its two roles; retry policy 0 retries (a second start the same day stops at the marker anyway).
- Ledger role "LedgerRole": `iam.Role` assumed via the GitHub OIDC provider (context `github_oidc_provider_arn`, the account's existing provider; the stack never creates one), trust `token.actions.githubusercontent.com:aud = sts.amazonaws.com` and `sub` in `repo:floyda/ntsb-probable-cause:ref:refs/heads/main` and `repo:floyda/ntsb-probable-cause:ref:refs/heads/s4-predictions-and-resolution` (context `ledger_branches`, default both); permissions `s3:ListBucket` on the live bucket with condition `s3:prefix` in `runs/`, `nights/` (and their `*` forms), and `s3:GetObject` on `<bucket>/runs/*/manifest.json` and `<bucket>/nights/*/manifest.json` only.
- Outputs: `LiveBucketName`, `RepositoryUri`, `AlertTopicArn`, `LedgerRoleArn`, `LogGroupName`.

`scripts/build_live_image.sh`: refuses a dirty tree (`git status --porcelain` non-empty → exit 1); `sha=$(git rev-parse --short HEAD)`; `docker buildx build --platform linux/amd64 --build-arg COMMIT_SHA="$sha" -t "$repo:live-$sha" --push .` with `repo` from the stack output `RepositoryUri` (read with `aws cloudformation describe-stacks --profile ntsb --stack-name NtsbLiveStack`); prints the pushed digest only. A `Status` comment block like `scripts/live_env.sh`'s.

- [x] **Step 1: Failing tests** (`tests/test_live_stack.py`, skipped without `node` as `test_infra_stack.py` is): every resource above exists with its properties; **no statement in the task role allows any `s3:Delete*`**; the ledger role's statements allow only `s3:ListBucket` and `s3:GetObject` on the two manifest patterns; the schedule is `DISABLED` by default and `ENABLED` with the context; the template holds no NAT gateway; the recorder's `tests/test_infra_stack.py` still passes unchanged. `tests/test_build_live_image.py`: with stub `git`, `docker` and `aws` on `PATH` (as `tests/test_paid_run.py` does), a dirty tree exits 1 before `docker`; a clean one calls `docker buildx build --platform linux/amd64` with `COMMIT_SHA=<sha>` and the tag `live-<sha>`, never `latest`.
- [x] **Step 2: Run** — FAIL. **Step 3: Implement.** `cd infra && uv run --locked cdk synth NtsbLiveStack -c live_image_digest_placeholder=1 -c recorder_bucket=example -c alert_email=example@example.com -c github_oidc_provider_arn=arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com` succeeds with no credentials. **Step 4: Run** — PASS; `make check`; commit: `S4 Task 12: NtsbLiveStack and the live image script (decision 0171)`.

## Task 13: The ledger (decision 0178)

**Files:** create `src/ntsb_probable_cause/live/ledger.py`, `scripts/ledger_append.py`, `.github/workflows/ledger.yml`, `tests/test_live_ledger.py`, `tests/test_ledger_workflow.py`; modify `apps/live/__main__.py` (`verify-ledger --ledger PATH`).

**Interfaces:**

```python
LEDGER_FORMAT: Final = "ledger/1"

class LedgerLine(BaseModel, frozen=True):
    format: Literal["ledger/1"] = LEDGER_FORMAT
    appended_at: datetime
    key: str                     # runs/<run id>/manifest.json or nights/<date>/manifest.json
    sha256: str
    size: int
    counts: dict[str, int] | None   # a night manifest's counts; None for a run manifest

def new_lines(ledger: Sequence[LedgerLine], manifests: Mapping[str, bytes],
              now: datetime) -> list[LedgerLine]:
    """One line per manifest whose key is not in the ledger, or whose SHA-256 differs from the
    key's latest line (a rewrite is appended, never hidden), sorted by key."""

def verify(ledger: Sequence[LedgerLine], mirror: Path) -> list[str]:
    """Problems, never contents: a manifest whose SHA-256 differs from its latest line, a
    manifest missing, a folder that fails ``records.verify_manifest``. Empty when sound."""
```

`scripts/ledger_append.py` (`Status`: "Live tooling, run by `.github/workflows/ledger.yml` only"): reads `ledger.jsonl` from `--ledger PATH`, lists `runs/` and `nights/` in `--bucket` with boto3, downloads only keys ending `/manifest.json`, appends `new_lines`, prints `appended: N` and nothing else.

`.github/workflows/ledger.yml`:

```yaml
name: ledger
on:
  schedule:
    - cron: "0 10 * * *"
  push:
    branches: [s4-predictions-and-resolution]
  workflow_dispatch:
permissions: {}
concurrency:
  group: ledger
  cancel-in-progress: false
jobs:
  append:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      id-token: write
    steps:
      - uses: actions/checkout@<sha pinned as in ci.yml>
        with:
          persist-credentials: false
      - uses: actions/checkout@<same sha>
        with:
          ref: ledger
          path: ledger
          persist-credentials: true
      - uses: astral-sh/setup-uv@<sha pinned as in ci.yml>
      - uses: aws-actions/configure-aws-credentials@<sha pinned as in ci.yml>
        with:
          role-to-assume: ${{ vars.LEDGER_ROLE_ARN }}
          aws-region: eu-west-2
      - name: Append new manifest hashes
        env:
          LIVE_BUCKET: ${{ vars.LIVE_BUCKET }}
        run: uv run --locked --extra aws python -m scripts.ledger_append --bucket "$LIVE_BUCKET" --ledger ledger/ledger.jsonl
      - name: Commit the ledger
        working-directory: ledger
        run: |
          git config user.name "ledger-bot"
          git config user.email "ledger-bot@users.noreply.github.com"
          git add ledger.jsonl
          git diff --cached --quiet || git commit -m "ledger: $(date -u +%Y-%m-%d)"
          git push origin HEAD:ledger
```

  Copy the exact pinned SHAs from `.github/workflows/ci.yml`; if `ci.yml` does not use `configure-aws-credentials`, pin its current release by commit SHA and note the version in a comment, as `ci.yml` does for `amazon-ecr-login`. `actionlint` and `zizmor` (pre-commit) must pass.

- [x] **Step 1: Failing tests.** `test_live_ledger.py`: `new_lines` over an empty ledger and two manifests gives two lines with their hashes; a second call with the same manifests gives none; a changed manifest gives one more line; a night manifest's `counts` are copied; `verify` reports a changed manifest and a folder whose file changed, and names keys only. `test_ledger_workflow.py` (as `tests/test_ci_workflow.py` reads `ci.yml`): top-level `permissions` is `{}`; the job's are exactly `contents: write`, `id-token: write`; triggers are schedule, push to the S4 branch, and dispatch, never `pull_request`; every `uses:` is pinned to a 40-hex SHA; no step runs `cat`, `head`, `tail` or `jq` on a downloaded file.
- [x] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS; `make check` (actionlint and zizmor through pre-commit); commit: `S4 Task 13: the ledger: append job, verify-ledger and the workflow (decision 0178)`.

## Task 14: The report, the spend line, the runbook and the Makefile

**Files:** create `scripts/s4_live_report.py`, `tests/test_s4_live_report.py`, `docs/runbooks/live-cloud-nights.md`; modify `scripts/stage_spend.py` (`s4`), `tests/test_stage_spend.py`, `scripts/live_env.sh` (default profile `ntsb`; also prints `NTSB_LIVE_BUCKET` from `NtsbLiveStack`'s `LiveBucketName` when the stack exists), `tests/test_live_env.py`, `Makefile` (remove `s33-morning`; add `s4-spend`, `s4-dry-run`, `s4-export`, `s4-verify-ledger`, `s4-report`, `s4-image`), `tests/test_makefile.py`, `tests/test_live_runbook.py` (point it at the new runbook too), `apps/live/__main__.py` (`report` runs the S4 report).

**The report** (`docs/results/s4-live.txt`; counts only; printed alone, decision 0021): nights (started, finished, refused by kind), alerts by kind, cases coded, not coded by kind, unreachable, awaiting codes, later scores; the six grades as counts with a 95% Wilson interval on "same first code" (`scoring.metrics.wilson`); finding recall@10 mean; replies by provider and replies whose model differs from the one asked for (decision 0169); names replaced, as a floor (decision 0180 item 5); money: the live key's spend in the first cloud nights apart from later nights (from each night's run records, decision 0170 item 6), and S4's development spend (`stage_spend --stage s4`); the backfill's count and SHA-256; closures per night since 2026-09-23; the closing rule's seven conditions with what the files show for each (decision 0181); a line that the open split enters only as counts. It reads a local copy of the bucket (`--mirror DIR`), the export built from it (`--export DIR`, where it counts `[name]` markers for the floor) and the ledger (`--ledger PATH`); it prints no case number (a test greps the output for the case-number pattern).

**`stage_spend`:** `"s4": Stage("S4", base="ebb16cb", first=<the commit of the S4 specification's first draft, 4f952cd>, line_usd=10.0, prefix="s4-", line_rule="decision 0170 item 6", count_rule="decisions 0128 item 2, 0135")`.

**Makefile targets** (each with a comment, each in `.PHONY`): `s4-spend EST=<usd>`; `s4-dry-run` (`eval "$(scripts/live_env.sh)"`, then `uv run --locked --extra aws ntsb-live run --dry-run`); `s4-export` (`aws s3 sync` of the bucket's `runs/`, `scores/`, `nights/` into `$NTSB_DATA_DIR/live-mirror` with the `ntsb` profile, then `ntsb-live export --from … --out $NTSB_DATA_DIR/live-export`); `s4-verify-ledger` (`git fetch origin ledger`, `git show origin/ledger:ledger.jsonl > …`, `ntsb-live verify-ledger`); `s4-report` (after `s4-export` and `s4-verify-ledger`'s fetch: `ntsb-live report --mirror … --export … --ledger … --out docs/results/s4-live.txt`); `s4-image` (`scripts/build_live_image.sh`).

**The runbook**, simplified technical English with a glossary: what a night does; one row per alert kind and per message `ntsb-live run` prints (meaning, what Andy does — usually nothing; `fetch-failed` and `store-unsound` among them, decision 0175); deploy steps (context values, `cdk deploy NtsbLiveStack --profile ntsb`, writing the live key: `pass show api/openrouter-live | aws ssm put-parameter --name /ntsb/live/openrouter-key --type SecureString --value file:///dev/stdin --overwrite --profile ntsb`, with a note that the value never appears on screen; confirming the SNS email); setting `vars.LEDGER_ROLE_ARN` and `vars.LIVE_BUCKET` on the repository; creating the `ledger` branch with an empty `ledger.jsonl` and its protection (no force push, no deletion); enabling the schedule; the alarm state test (`aws cloudwatch set-alarm-state --alarm-name <name> --state-value ALARM --state-reason "S4 test"`); removing the Mac's key (IAM user `ntsb-live-reader`, its access key, the inline policy `live-shadow-read-store`, `pass rm aws/ntsb-live-reader`, the `ntsb-live` profile from `~/.aws/config`); moving the task to a `main`-built image after the merge and removing the branch's ledger trust.

- [x] **Step 1: Failing tests** for the report (invented mirror and ledger: every section prints; no case number; the closing-rule lines read "met"/"not met" from the inputs), `stage_spend --stage s4`, `live_env.sh` defaults, the Makefile targets (`s33-morning` gone, the new ones present), the runbook rows (every alert kind in `live.night` and every `LiveRefusal` kind has a row: the test imports the kinds and greps the runbook).
- [x] **Step 2: Run** — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS; `make check`; commit: `S4 Task 14: the S4 report, spend line, runbook and Makefile targets`.

## Task 15 (Controller, with Andy): deploy, dry run and the first cloud night

- [ ] Ask Andy to create the live OpenRouter key on OpenRouter with a **$10 monthly limit**, store it in `pass` as `api/openrouter-live`, and write it to Parameter Store with the runbook's command. Confirm with `aws ssm describe-parameters --profile ntsb --parameter-filters Key=Name,Values=/ntsb/live/openrouter-key` (shows the name and type, never the value).
- [ ] Ask Andy before pushing the first image; then `make s4-image` and note the digest.
- [ ] Ask Andy to run `cdk deploy NtsbLiveStack --profile ntsb` with the context values from the runbook (schedule disabled). Andy confirms the SNS subscription email.
- [ ] Ask Andy before creating the `ledger` branch and its protection; then create it and set the two repository variables (or Andy does).
- [ ] `make s4-dry-run`: checks, store, queue, one fetch; record its printed counts (no case numbers) in the Deviations log.
- [ ] Send a test alert: `aws sns publish --profile ntsb --topic-arn <AlertTopicArn> --subject "Ellery test" --message "test"`; Andy confirms receipt (closing condition 5, first half).
- [ ] **Ask Andy for the first cloud night**, stating: about 30 cases, about $0.15 of live-key spend at the measured $0.005 a case (worst case $9, held by the full-cap rule), about 45 minutes, starting at the next 06:00 UTC once the schedule is enabled. On his yes, Andy redeploys with `-c live_schedule=enabled` (or Claude asks to). Record the go-ahead with his words.
- [ ] After the night: read its alert emails (if any), `make s4-export` and check it validates, `make s4-verify-ledger` after the 10:00 UTC job. Log counts and cost in Deviations.

## Task 16 (Controller): backfill, fresh closure, alarm, Mac key, report

- [ ] Each morning until the backfill drains: check the night's email (none means no failure), the ledger job's run, and the night's counts from the mirror. No manual run (closing condition 2).
- [ ] When a case closes after the backfill list was fixed and is coded and scored on the next 06:00 UTC night, note its night (no case number) (condition 3), and that the ledger holds that night's manifest hash (condition 4).
- [ ] The alarm state test from the runbook; Andy confirms the alarm email (condition 5, second half).
- [ ] After the first good cloud night: ask Andy to remove the Mac's key with the runbook's steps (condition 7).
- [ ] `make s4-export` (condition 6, first half); `make s4-report`, read it, commit `docs/results/s4-live.txt` (condition 6, second half).
- [ ] If no fresh closure within 14 days after the backfill drains, close on the rest and say so in the report and As-built (decision 0181).
- [ ] Check the first AWS bill for a CloudWatch charge; if any, the fallback of decision 0177 item 4 is a new task.

## Task 17 (Controller): final review and close-out

- [ ] Final review on `opus`, split by dimension (correctness of the night and resume; the open-split fence and names; IAM and the ledger's exposure; tests), each reviewer given the spec, this plan and the diff `ebb16cb..HEAD`; fix findings in review-fix commits.
- [ ] Run the `close-stage` skill: As-built record in the specification (Delivered; Done means, with evidence; Departures; Decisions taken during the stage; Implementation record with the cloud nights' dates, commits and image digests), delete this plan, roadmap note (spec §20), `CLAUDE.md` (S4 built; "SQLite predictions store" and "Scheduler and resolution watcher" lines; the new commands and targets), `pyproject.toml` version, the close-out commit removing the S4 branch from `ledger_branches`. Pull request titled `S4: Predictions and resolution`, merged with a merge commit (decisions 0018, 0033); Andy deploys the trust change and moves the task to a `main`-built image after the merge.

---

## Deviations

(Log every departure from this plan here, dated, with the reason.)

- 2026-10-10 (plan writing): the specification's §13 named `tests/s3_probe_fixtures.py` as the S3 fake; it holds S3.1 probe trails. Corrected in the specification with a dated note; the cloud seams take narrow protocols tested with in-memory fakes (Task 9).
- 2026-10-10 (plan writing): `seen_pairs` reads `data/processed/cases.parquet`, which the container does not hold. Task 6 commits the development split's primary occurrence codes as a table (codes only). Not in the specification; it changes no score.
- 2026-10-10 (plan writing): the specification says the run folder is copied "after each case". The plan pushes changed files after every reply (Task 10), which is finer and needs only a hook in `drive_sync`. A call sent but unanswered when the task dies is paid again on resume; before the first reply nothing is in the bucket, so a task killed between the first send and the first reply codes that case again the next night (cost cents; noted as a known limit in the runbook).
- 2026-10-11, Task 1: the brief's test asserted `"Maneuvering" not in sent`, but the code tables in the prompt name every phase, so it could not pass; the test reads only the `phase_of_flight` evidence line (a regex over the sent text) and asserts on a set of phases. It calls `rendered_requests()` directly, as the file already imports it. The two new scenarios are appended after "arm B tool post-pass".
- 2026-10-11, Task 1 fix round: `make s33-mutation-sweep` reported `isDefiningEvent` at `fields.py:166-167` MISFILED, because the sweep keys literals by module and value, so the one `[selects]` entry covered three sites and two of them (in `_ordered_events`, feeding only the withheld `eventCode`) cannot move `+t`. Added `fields._is_defining` holding the only literal, mirroring `_sequence`; behaviour is unchanged.

- 2026-10-11 (Task 2): `tests/test_sources_settings.py::test_no_module_but_sources_names_a_luna_model` forbade any `-luna` text outside `sources.py`, which the brief's literal in `live/morning.py` breaks. The test now allows `morning.py` and requires exactly one occurrence there. `request_sha256` mirrors `rendered_sha256`'s per-request cut and dump (rendered.py exposes no per-request helper); it reuses `MODEL_FACING_KEYS`.
- 2026-10-11 (Task 3): in the sample, an abstained case's `BoardRow.agent_first` is `None` (its `answer` still holds the codes); the brief did not say. `_belief` in `tests/board_sample.py` carries a `noqa` for argument count. Neither changes the format.
- 2026-10-11, Task 4: the loader (`load_dev_cases`) takes `main(argv, loader)`; the script defaults to the two noise-floor run ids so the Makefile target needs no variable. A `note` is every document decision's `expected_effect` in an accepted read choice (read or skipped); the brief's "read decision" was ambiguous. Count 4 counts each distinct flagged word once per case. Listings are read straight from `<docket_dir>/<mkey>/listing.html` (no client, so no network path exists); cases without one are counted and printed.
- 2026-10-11, Task 6: `DocketClient` already recorded each file's SHA-256 in `fetch.json`, so `cached_hashes` only reads it. Closure records: version 1 stays as a read-only `ClosureRecordV1` and `read_closure_records` reads either version, so `scripts/s33_live_report.py` still reads S3.3's runs; S3.3's tests that build records (`test_live_records.py`, through which `test_s33_live_report.py` builds its own) were moved to v2. `DocumentLine.sha256` defaults to None so version 1 document lines still parse.
- 2026-10-11 (Task 4, Step 5): count (3) was above 0 in seven kinds of text, so Andy chose. His words: "I'm tempted to just not attempt this I don't think like it will add much, more likely to make the text unreadable"; asked whether that meant no names step at all or the exact parts only, he chose "Exact parts only". Decision 0182 replaces 0180 item 2. Task 5 changes: `CaseNames` holds the owner and operator strings only (no `title_words`); `board_text` replaces owner and operator strings only; `board_title` keeps the title rule. Task 11 passes the coding lookups' free-text arguments (`reason`, `expected_effect`) through `board_text` too (found by the Task 4 review).
- 2026-10-11 (Task 5): interfaces follow decision 0182, not the brief's original `CaseNames` and `board_text`: `case_names(raw)` takes owner and operator strings only (no `titles`, `known`, `title_words`); `board_text(text, names)` replaces those strings only; no `ACCOUNTS_SHOWN`. To share one matching rule, `docket/attach.py` gained `replace_values(text, values, marker)`, which `redact_known_names` now calls (its output is unchanged). `VENDORED_DICTIONARY_PATH` is now `Path(__file__).parent / "vocab" / "words.txt"` (absolute, so any working directory finds it), and `known_title_words` keeps its signature.
- 2026-10-11 (Task 7): the morning passes `settings.monthly_budget_usd` to `live_spec`, not `room`. The runner refuses a resume whose spec differs from the run's first (`budget_usd` is compared), and the room falls as the month's spend grows, so a run resumed on a later night would be refused (found by the existing resume test). The room is enforced by `cases_tonight` before any fetch; the runner's guard stays a backstop that the cloud's empty runs folder never reaches. The refusal log's rows are `{"at", "kind"}` (the old `reason` key is replaced by `kind`, since the old reasons `daily-limit`, `monthly-cap` and `monthly-guard` are gone and the rest map one to one onto kinds). `run_morning` returns `NightOutcome`; `apps/live/__main__.py` prints its summary, a `held back by money` line and one `alert: <kind>` line each.
- 2026-10-11 (Task 8): `awaiting` skips version 1 closure records: they hold no `event_date`, which a later score's board row needs. `coded_on` is the UTC day of the record's last model reply (the closure day if none). `record_sha256` is plain `json.dumps(raw, sort_keys=True)` as the brief says (the recorder's own hash does the same; `data/build.py` alone adds `ensure_ascii=False`). `score_later` splits with the live exclusion `{prelim_narrative}`, as the morning does.
- 2026-10-11 (Task 9): `tests/test_live_fence.py::test_nothing_under_live_names_the_stores_upload` banned the word `push` under `live/`; `live/cloud.py` (`BucketMirror.push`) is the S4 bucket mirror, a different object from the recorder's pull-only store, so the test now exempts `cloud.py`. Also: `pyproject.toml` gained `include_external_packages = true` (needed for an external forbidden module), a contract keeping `live.cloud` from importing boto3, botocore or httpx directly (`allow_indirect_imports`, since `morning` and `local` reach them), and vulture `ignore_names` for protocol parameters named as boto3 names them.
- 2026-10-11 (Task 9, fix round 1): SNS body now starts with a `kinds:` line (AWS rejects an empty message); `SnsAlerts` and `PrintAlerts` refuse (ValueError) kinds or count names not matching `^[a-z][a-z0-9-]*$` and non-int or bool counts; `push` refuses paths outside runs/, scores/ and nights/; `pull` skips and counts keys leaving the folder (returns the count); the key refusal is raised outside the `except` so `__context__` is None. The fence test's word-ban is replaced fully by an AST check that no live file imports `push` from `store.sync` or takes `.push` on that module. Task 9 Step 2 (RED) was never run, so it is unticked.
- 2026-10-11 (Task 11, fix round 1): closure record version 1 is refused: the export raises `ConfigurationError`. The Mac's S3.3 folders are never uploaded and S3.3's cases are coded again in the cloud (decision 0179, spec 6.2), so the mirror never holds a v1 record; one there means the mirror is wrong.
- 2026-10-11 (Task 11): per decision 0182 the brief's "Smithers in an account and a note" check is split: "Smithers" in a document title becomes `[name]`; "Invented Owner" (the case's owner and operator strings) is replaced in every cause, account, note, reason and lookup argument. A surname that appears only in prose is not replaced, by 0182.
- 2026-10-11 (Task 11): `build_export` wraps `write_export`, which also returns an `ExportReport` of counts for the command. Counts of closures per night come from `Store.closures()` (every real closure the store holds, by closure night); open cases are the watched cases that are not closures.
- 2026-10-11 (Task 11 review): Ellery's prose quotes the make, model and registration that version 1's evidence holds, against spec §10.2. Andy chose "A: allow in prose" (decision 0183): fields hold none of them, prose may name make and model, and the case's own registration is replaced in prose and titles.
- 2026-10-11 (Task 10): `drive_sync`'s `on_reply` is also told once before the first request a call sends, not only after each reply row. The brief's hook alone left nothing in the bucket until the first reply, so a task killed during the first request lost the inputs and, on the launch night, the backfill (decision 0157: never recomputed); the controller required the inputs in the bucket before the first call. This closes the plan-writing note's known limit: such a task's run is now resumed, not started again (its first request is still paid twice). `MorningDeps.on_reply_factory` is `Callable[[Path], Callable[[], None]]`: given the run folder after its pending inputs and backfill have moved in, before the first request.
- 2026-10-11 (Task 10): the night's observer copies every file of the run folder except `reservation.json`. The reservation is the runner's local budget lock, settled at the run's end; the task role cannot delete, so a copied one would stay in the bucket and be counted against every later night's guard.
- 2026-10-11 (Task 10): the export is built and pushed before `night.json` is written (the brief put it after the push), so the night record's `alerts` holds `export-failed` too. `night.json` adds `later_errors` (kind -> count; carried ruling 5). The night manifest's `files` lists the night folder's own files as `records.write_manifest` does, so `records.verify_manifest` reads it; `night_files` lists tonight's run folder, scores file and `nights/state.json` by bucket path, with size and SHA-256; `counts` are flat integers (Task 13's `LedgerLine.counts`); `finished` is false when something stopped the night.
- 2026-10-11 (Task 10): one alert per kind, each with its own counts (carried ruling 10; decision 0177 item 1 says one email per condition). A `FetchError` or `DocketError` that escapes the morning (a resume's or a completion's fetch) stops the night as `fetch-failed`, like a refusal, rather than `night-crashed`. `run_night` takes an optional `limit` (passed from `ntsb-live run --limit`). `ALERT_KINDS` is defined once in `live/morning.py`, beside `LiveRefusal`, which refuses a kind not in it; `live/night.py` imports it. `budget-guard` is the kind chosen for the runner's own monthly guard (carried ruling 1). In the image, `ntsb-live run` exits 1 when something stopped the night and 0 otherwise (a second start included); the S3.3 morning lock is not taken there (the marker replaces it). `test_live_app.py`'s error-line tests now run `run --dry-run`, since `run` alone refuses outside the image. `test_live_morning.py`'s "state written after the records" test is replaced by "straight after the fetches" (carried ruling 3).
- 2026-10-11 (Task 10, fix round 1): every push uploads in an explicit order (`cloud.push_order`), not by name: `run.jsonl` last, as the point at which a run reads as finished, and `spec.json` just before it, as the point at which a folder reads as a live run. A task killed between two uploads now leaves either a folder no night takes for a live run (nothing yet sent) or a run the next night resumes, never a finished run with files missing. The mirror itself never pushes `reservation.json` (the night's observer no longer filters it).
- 2026-10-11 (Task 10, fix round 1): the pull comes before `mark_started` (the brief had it after): a pull only reads the bucket, so a failed pull leaves the day unclaimed. A second task the same day still stops before the store is opened. `mark_started` also writes the empty marker to the local folder and records it as seen, so the night manifest still lists `started` and no later push re-uploads it unconditionally.
- 2026-10-11 (Task 10, fix round 1): `NightDeps.export` is `Callable[[Path, date, datetime], Path]`, not the brief's `Callable[[Path], Path]`: the night passes its own day and clock reading (the night's start), so a night past midnight UTC dates its export as it dates its records. Any exception from the export or its push is `export-failed` (only its class is printed), and the night record, its push and the metric still follow.
- 2026-10-11 (Task 10, fix round 1): two new alert kinds in `ALERT_KINDS`: `resume-refused` (a `LiveRefusal` raised before the key, the store and any fetch, when an unfinished live run's `spec.json` names another commit or dirty flag than the running one; a run is never resumed across commits, decisions 0018, 0033) and `later-score-failed` (any later-score error; its counts are by error class, as `leakage-error`, `fetch-error`). `night.json`'s `later_errors` keeps its kinds. `S3Bucket.put_if_absent` retries an HTTP 409 `ConditionalRequestConflict` twice more (pauses 0.5 s and 1 s, injected) and returns False after a third, failing closed. The cloud dry run takes `live.lock` before it builds any client.

- 2026-10-11 (Task 12): the container's entry point is overridden, not only the command, because the `Dockerfile`'s `ENTRYPOINT` is `ntsb-record`: entry point `timeout 10800 ntsb-live`, command `run`, so argv is `timeout 10800 ntsb-live run`. The `Dockerfile` already bakes `NTSB_COMMIT_SHA` and `NTSB_DATA_DIR=/tmp/ntsb` and installs the `aws` extra, so the task sets neither and the `Dockerfile` is unchanged. Image pinned with `from_registry(<repo uri>@<digest>)` plus `repository.grant_pull` on the execution role. Lifecycle covers `runs/` and `export/` (two rules), by controller ruling. The live stack is built in `app.py` only when context `recorder_bucket` is given, so the recorder's `cdk synth` needs no live context. The build script reads the digest from `--metadata-file`.
- 2026-10-11 (Task 13): `cloud.push_order` puts a night folder's `manifest.json` last (it lists `night.json`), by controller ruling; a run folder's is unchanged. `verify` reports a night folder with no `night.json` as "unfinished night", and checks a night manifest's `night_files` (bucket paths) as well as its own files. `ntsb-live verify-ledger` takes `--ledger PATH` and an optional `--mirror DIR` (default `<data_dir>/live-mirror`); it prints problem lines and a count, exit 1 on any problem. The job carries `if: vars.LEDGER_ROLE_ARN != '' && vars.LIVE_BUCKET != ''` so it skips until Andy sets up the role, variables and `ledger` branch; the ledger checkout fails if the branch is missing and nothing creates it. zizmor needed no ignore comment (its default run reports no finding on the persisted-credentials checkout). `tests/test_live_cloud.py` and `tests/test_live_app.py` gained the push-order and `verify-ledger` tests.
- 2026-10-11 (Task 13, fix round 1): the plan's workflow had `persist-credentials: true` on the ledger checkout and `vars.LEDGER_ROLE_ARN` / `vars.LIVE_BUCKET`; by controller ruling neither checkout persists credentials (only the commit step holds `GH_TOKEN`, pushing by URL, nothing written to disk), `setup-uv` caching is off, the append step uses `--no-dev`, the role ARN and bucket are repository secrets (masked), and the job is guarded by `vars.LEDGER_ENABLED == 'true'`, which Andy sets last. `ledger_append` reads only `(runs|nights)/<one folder>/manifest.json`, counts deeper keys (stderr), and refuses (exit 1, writes nothing) a missing ledger file or one without a final newline. `verify` reports a ledgered night without `night.json` as `night.json: missing` (superseding the "unfinished night" kind above), keeps earlier problems when `night_files` is malformed, and `verify-ledger` fails in one line on a malformed ledger.
- 2026-10-11 (Task 11b): added at the S5 session's request, with no plan section; nothing ticked. Optional `board/1` fields (decision 0173 item 4): `mkey` on `BoardRow` and `CaseFile`; `BuildStamp.launched_on`; `BoardRow.backfilled`; `DocumentChoice.pages` (from a new optional `DocumentLine.pages`, closure record v2, safe because no v2 record is in the bucket yet); `DocumentChoice.not_offered_reason`. The schema is generated with defaults required, so these are listed as required and every file written carries them (null when unknown); the models still accept a file that lacks them.
- 2026-10-11 (Task 14): `ntsb-live run --dry-run` with a live bucket (the cloud dry run) now passes `check_resume=False` to `run_morning` and prints one information line, because the Mac's commit is not the image's (carried ruling 1); a paid night keeps the check (`check_resume` defaults to True). Both are tested.
- 2026-10-11 (Task 14): `ntsb-live report` now runs `scripts/s4_live_report.py` and takes `--mirror`, `--export`, `--ledger`, optional `--attest` and `--out`; it takes no lock (it reads local files only). S3.3's `scripts/s33_live_report.py` stays, and `make s33-report` runs it directly. `make s33-morning` and `make s33-dry-run` are removed: `s33-dry-run` would, with the live stack present, read the live key's limit with the development key and refuse, so `s4-dry-run` replaces it (it reads the NTSB key and the LIVE OpenRouter key from `pass` inside the recipe, so `paid_run.sh` is unchanged).
- 2026-10-11 (Task 14): closing conditions 5 (alert email received, alarm shown to fire) and 7 (the Mac's key removed) cannot be seen in the bucket, the export or the ledger. The report reads them from an optional attestation file (`--attest`, default `$NTSB_DATA_DIR/live-attest.json`, three dated keys), and reads "not met" without one. Condition 2's "no one intervening" is shown only as: every run holding a backfill case is listed in a scheduled night's manifest. Condition 3 counts a coded, scored case not on the backfill list with `waited_days <= 1`. Condition 6 is "the export passes the `board/1` models and holds a case"; the results file's commit is Andy's. Condition 1 reads `docs/results/s33-fingerprint-continuity.txt` (`match: yes` and `VERSION_1`'s `+t` hash) and that no closure record carries another prompt version.
- 2026-10-11 (Task 14): the report's "first cloud nights" are the run records started on or before the night the backfill drained (all of them while it has not drained); "later nights" follow. `s4-image` also refuses unless `CONFIRM=yes` is given, so it cannot push to ECR by accident. `scripts/live_env.sh` looks up the live stack optionally (no live line, no error, when the stack is absent) and its default profile is `ntsb`; its refusal text no longer names the `ntsb-live` profile. The plan's "repository variables" `LEDGER_ROLE_ARN` and `LIVE_BUCKET` are repository secrets and `LEDGER_ENABLED` is the variable set last (carried rulings 3 to 6, Task 13 fix round 1).
- 2026-10-11 (Task 14, fix round 1): `make s4-export` also copies the night's own `export/board-1/` to `$NTSB_DATA_DIR/live-night-export`, and `ntsb-live report` takes `--night-export`. The report reads that copy (built in the task with the store) for closures per night and for condition 6, and the Mac's local build (no store, so `closures_per_night` is empty) for cases, grades and the names floor. Without `--night-export` the per-night section says so and condition 6 is "not met". A backfill case counts as settled with any closure record (dated by `last_returned`, else `first_sent`, else its run's start), or when `nights/state.json` lists it unreachable (dated by the last night folder, an upper bound). Attestation values must parse with `date.fromisoformat`; the report prints the dates. `Settings` strips surrounding whitespace from the NTSB, OpenRouter and TypeSafe keys. `live_env.sh` exits 1 with one line when the live-stack lookup fails because the login expired. `scripts/s33_live_report.py` reports an AWS error as one line through `ntsb-live`'s own wording. The resume-refused message in `live/morning.py` now says to deploy the image the run began on (a deploy deregisters older task-definition revisions). The runbook's ledger steps before the merge use a push to the S4 branch, since `ledger.yml` is not on `main`.
- 2026-10-12 (final review, wave A, A1): a resume is refused for money only when its remaining exposure passes the room: over the run's unanswered cases, the sum of `max(0, $0.30 - the computed cost of that case's replies already in replies.jsonl)`, priced with `model.client.cost_usd` as the loop prices them. A full night killed mid-run therefore resumes the next night instead of waiting for the month to reset.
- 2026-10-12 (final review, wave A, A2): the preferred route (drop one case from the resume and close it `not coded: docket-changed`) cannot be built cleanly, because `AgentRunner`'s resume compares the whole recorded spec, case ids included (`scoring.runner.refuse_unresumable`). The fallback is built: a run writes `dockets.json` (format `live-dockets/1`: per case its id, key, listing SHA-256, each document index's SHA-256 from `fetch.json`, and the indices its first read choice offers, from `docket.filter.arm_b_documents`) beside the inputs, before its first request, and pushes it with them. `closure.build_records` takes its hashes from it, never from the cache. A resume, and the completion of a finished run with no records, fetch each docket again and compare; any difference refuses with `LiveRefusal("docket-changed")` before any call. A docket that fails to fetch on a resume stays a `fetch-failed` stop (retried next night, counted against no case), not `docket-changed`. A `ConfigurationError` or `ValueError` from the resume or the completion path becomes `LiveRefusal("resume-failed")` (its class only in the message), so later scores, the export and the night record still run. `docket-changed` and `resume-failed` are in `ALERT_KINDS`, with runbook rows; `docket-changed` is not a failure kind, since no case is closed by it.
- 2026-10-12 (final review, wave A, A3): `board._collect` and `later.awaiting` read only a run folder whose `run.jsonl` says finished (`closure.is_finished`), the run's commit point.
- 2026-10-12 (final review, wave A, A4): each night writes `nights/<date>/state.json`, a copy of the shared `nights/state.json` at the night's end, and its manifest's `night_files` lists that snapshot, never the shared file (the snapshot is also one of the night folder's own `files`).
- 2026-10-12 (final review, wave A, A5): the cloud dry run prints one more line, `live key: limit_reset: <value>` (`monthly`, `null`, `absent`, `not a plain word`, or `not read` when the key was never read), from `OpenRouterKeySpend.limit_reset_line()`. Nothing refuses on it, since no saved answer shows the field.
- 2026-10-12 (final review, wave A, A6, Andy's choice A of 2026-10-12; its decision record is wave B's): `CaseNames.registration` becomes `registrations`, every aircraft's, once each, any shorter than 3 characters left out; `board_title` replaces the case's owner and operator strings and registrations (any case, whole string) before the title rule. The published limit is `names.NAMES_LIMIT`, which the S4 report now prints.
- 2026-10-12 (final review, wave A, A7, A9, A10): `DocumentChoice.not_offered_reason` gains `already_read` and `over_size_limit` (unpublished field, so `board/1` stays); the `not_offered` description no longer says only "could not offer as text". The never-holds check compares lower-cased text and is planted with the owner in capitals in a title, a second aircraft's registration in an account and a kept `N1`. The night test validates its own export with the `board/1` models (no `jsonschema` dependency; the drift test keeps the committed schema equal to the models'). The builder refuses when the title rule's word list is missing.
- 2026-10-12 (final review, wave A, A8, A11): every `aws s3 sync` in the Makefile carries `--only-show-errors`. `BucketMirror.push_export` uploads the case files, then `index.json`, then `export/board-1/_finished.json` (`{"format": "board-finished/1", "built_at", "commit"}` from the index's stamp), last and only when every upload succeeded; an export whose `index.json` has no readable stamp uploads nothing (`export-failed`).
