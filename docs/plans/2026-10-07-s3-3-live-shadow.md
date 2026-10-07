# S3.3 — Live shadow: implementation plan

**Spec:** docs/specs/2026-10-07-s3-3-live-shadow-design.md

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tick a step in the same commit as its code (decision 0017). Log every departure from this plan in the **Deviations** section at the end. Tasks marked **Controller** are run by the controller session, not a subagent: they write records from the design session, spend money, read the live store, or need Andy.

**Goal:** Rehearse on Andy's Mac exactly what S4 will run in the cloud (spec §1): code each closed case once with Ellery version 1, unchanged, through a queue at 10 a day; score it the same morning as counts only; record what S4 and the site need in run folders built to move; and measure failures, time and cost until the closing rule of spec §11 is met.

**Architecture:** A new library package, `ntsb_probable_cause.live`, holds the queue, the fetching, the morning and the closure records, behind three seams (where results go, where spend is counted, where the store copy comes from), each with only its local version built. The run itself is the existing `agent.run.AgentRunner`, unchanged, given fetched records. A new module, `agent/rendered.py`, renders every fixed text the loop and arm B's post-pass can send from invented inputs, and its hash (`+t`) replaces the source fingerprint (`+p`) in the prompt version; a live run refuses unless the label is version 1's. A new command, `ntsb-live`, is kept apart from `ntsb-eval` by import contracts and by refusals in the evaluation commands.

**Tech Stack:** Python 3.14, uv + hatchling, pydantic v2, pytest + pytest-socket, ruff, mypy --strict, import-linter, boto3 (the store's `s3://` pull, already an optional dependency). No new dependency.

## Global Constraints

- **Branch.** `s3-3-live-shadow` in `.claude/worktrees/s3-3-live-shadow`. Never commit to `main`. The prefix `s3-` is what S3's spend line counts (decision 0128).
- **Ellery's text does not change** (spec §1, decision 0156). Until Task 2 lands, do not edit `scoring/prompt.py`, `scoring/hypothesis.py`, `scoring/codes.py`, or `agent/` `texts.py`, `steps.py`, `tools.py`, `schemas.py`, `later.py`, `loop.py`, `armb.py` (the old `+p` test, `tests/test_s32_frozen.py`, holds them). From Task 2 on, the rendered fingerprint `+t` must equal Task 2's pinned value at every commit; an edit that moves it is a defect, not a new version. Do not merge a dependency update that moves `+t`.
- **Model and settings** (spec §2): `openai/gpt-6-luna`, reasoning `medium`, batch price, reply budget 8,000, evidence v1, S3's statistics (`load_stats("s3")`), guidance `r3-loc-stall` then `r6-aircraft-control`, temperature 0.0. Every live run: sample name `live`, arm C, `--cap-usd 0.30`, exclusions `{prelim_narrative}` (spec §5, §9).
- **The queue** (spec §3): a closure is a status event to `Completed` or `N/A` as `Store._closure_runs` defines it; declared start 2026-09-23; order (closure run, mkey); at most 10 cases per UTC day across live runs; one run per case; a case seen (first model call sent) is never tried again; a case that failed before it was seen returns to the queue.
- **Caps, each refused before any call** (spec §9): $0.30 a case; $5 a calendar month of live spend; S3.3 stops when S3's spend by commit reaches $21.46 (S3.3's own $10); the $40 monthly guard; S3's $50 line.
- **Open split** (decision 0024, spec §8.3): live cases are open-split. Nothing from a live run folder, the live document cache, the backfill list or the store copy is committed, printed into a committed file, or read by any development or evaluation code. Only `docs/results/s33-live-shadow.txt` and `docs/results/s33-fingerprint-continuity.txt` are committed, counts only. Tests use invented records and the existing redacted development fixtures only. No subagent reads a live run folder.
- **Held-out and sealed.** Never read `heldout-400` (closed, `docs/rounds/s3-2-used.md`), `dev-seal-400` (used once, 0095) or `dev-seal-s3-400` (sealed for v2, 0141).
- **Numbers.** Every committed number comes from a committed script (CLAUDE.md rule 3). Clinical tone (rule 6).
- **Tests offline** (`pytest-socket`); coverage ≥ 90% branch; `make check` green at every commit. Google-style docstrings on public symbols; line length 100. Scripts carry a `Status` paragraph (0059). `uv run` commands use `--locked` where a command line is written out.
- **Decision numbers.** Records 157 to 164 do not exist until Task 1. Before Task 1 is on the branch, cite them as "record 157" (no leading zero) so `scripts/check_docs.py` passes; once Task 1 has created them, with their leading zero, as every record is cited.
- **Worktree data.** Any command that reads data from this worktree needs `export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data` (decision 0057).
- **Paid runs** go only through `NTSB_PAID_BRANCH=s3-3-live-shadow scripts/paid_run.sh <target>`, after `aws login --profile ntsb`. Andy is asked before the first paid morning, with its cost and duration; after that each morning runs within the $5 cap and its cost and duration are reported (spec §9).
- **Subagents.** Implementers run on `sonnet`; exploration on `haiku`; the final review (Task 12) on `opus`, split by dimension.
- Commit messages end with the attribution lines the session gives.

## Order of work

**1** (Controller), **2**, **3** (built by a subagent, run by the Controller; stop here if `+t` does not match on `fd6053f`), then **4** to **10** (code, free), **11** (Controller: the dry run, the first paid morning with Andy's go-ahead, the mornings), **12** (Controller: report and close-out).
Tasks 4, 5 and 6 are independent of each other once Task 2 has landed; 7 needs 5 and 6; 8 needs 4 to 7; 9 needs 8; 10 needs 5.

## File map

- `docs/decisions/157-…164-*.md`, `docs/decisions/README.md`, dated notes on 0133, 0143, 0148, 0150, 0154 — Task 1.
- `src/ntsb_probable_cause/agent/rendered.py`, `src/ntsb_probable_cause/agent/version.py`, `agent/texts.py` (label code out), `agent/run.py`, `agent/armb.py`, `apps/eval/__main__.py` (imports), `tests/test_s32_frozen.py`, `tests/test_agent_rendered.py`, `tests/fixtures/rendered/not_model_text.toml` — Task 2.
- `scripts/s33_fingerprint_continuity.py`, `tests/test_s33_fingerprint_continuity.py`, `docs/results/s33-fingerprint-continuity.txt` — Task 3.
- `scripts/paid_run.sh`, `tests/test_paid_run.py` — Task 4.
- `src/ntsb_probable_cause/store/db.py`, `store/models.py`, `store/__init__.py`, `src/ntsb_probable_cause/settings.py`, `src/ntsb_probable_cause/sources.py`, `tests/test_store.py`, `tests/test_settings.py` — Task 5.
- `src/ntsb_probable_cause/live/__init__.py`, `live/queue.py`, `live/records.py`, `tests/test_live_queue.py`, `tests/test_live_records.py` — Task 6.
- `live/fetch.py`, `live/seams.py`, `live/local.py`, `tests/test_live_fetch.py`, `tests/test_live_local.py` — Task 7.
- `live/morning.py`, `tests/test_live_morning.py` — Task 8.
- `apps/live/__init__.py`, `apps/live/__main__.py`, `pyproject.toml` (script, contracts), `apps/eval/__main__.py` (the fence), `scripts/stage_spend.py` (`s33`), `Makefile`, `tests/test_live_app.py`, `tests/test_live_fence.py`, `tests/test_makefile.py`, `docs/runbooks/live-shadow-mornings.md` — Task 9.
- `scripts/s33_live_report.py`, `tests/test_s33_live_report.py` — Task 10.
- `docs/results/s33-live-shadow.txt`, the As-built record, `CLAUDE.md`, the roadmap note, `pyproject.toml` version — Tasks 11, 12.

---

## Task 1 (Controller): Decision records 157 to 164

**Files:** (each named with a leading zero, as every record is) create `docs/decisions/157-s33-codes-closures-through-a-queue.md`, `158-live-runs-on-the-mac-at-the-batch-price.md`, `159-closure-runs-are-scored-as-counts-only.md`, `160-the-live-package-its-run-folders-and-the-open-split-fence.md`, `161-the-rendered-text-fingerprint-and-the-version-1-check.md`, `162-the-preliminary-narrative-is-left-out-of-live-runs.md`, `163-the-live-shadows-caps.md`, `164-what-no-longer-arises-in-s33.md`; modify `docs/decisions/README.md` and append dated notes to `0133`, `0143`, `0148`, `0150`, `0154` (nothing above a note is edited).

- [x] Write each record in `docs/decisions/README.md`'s format (Context, Decision, Why, What this rules out, Status, Glossary where terms are new), in simplified technical English, from spec §15 and the section each item names. Status line on each: `Accepted, 2026-10-07 (Andy, S3.3 design session; specification approved 2026-10-07).` Quote Andy where the session recorded his words: "A but we might want an upper limit on cases in one night"; "Can we reduce it to 10 cases a night"; "given S4 was meant to be the online agent, it probably makes sense to get running on mac first and then move onto AWS in S4" (spelling corrected, as 0121 does); "They won't be watched live though, so it feels like batch processing is probably good enough"; "local run folders with S3 bucket in mind without designing it"; "we should make use of uv lock if we don't already"; "Yes that's much better, less work and confusion later" (the `live` name and seams); "I will also need to be careful on disk space". Content:
  - **157** — spec §3, §11. Closure runs and the backfill rehearsal under 0154 and 0155; the queue (order, 10 a UTC day, queue not skip, one run per case, the seen rule); the backfill list fixed on the first morning, committed only as count and SHA-256; the closing rule. Ruled out: a nightly pass over open cases (0154); skipping cases over the limit (selection, 0155); the backfill alone; four fixed weeks.
  - **158** — spec §4, §4.1. Runs on the Mac through `paid_run.sh` in S3.3; the cloud task is S4's. Batch price; amends the roadmap's §4 sentence "The live path does not" use batch, for closure runs, which have no speed requirement; S4 chooses its own service. Timing: after the recorder's night, warned after 09:00 UTC. Ruled out: a second Fargate task now (two pull requests, spend outside S3's line, a cloud spend count); a step in the recorder's task (a long shadow could cost a recorder night); the standard price (twice the cost, and not the service v1 was measured on).
  - **159** — spec §10. Same-morning scoring against the verdict in the record, the board's three grades, counts only, printed alone, never beside held-out (0021); a case without a verdict is unscored. Ruled out: arm B beside the loop (0156; version 2's comparison needs it); no scoring.
  - **160** — spec §8. The `live` package and `ntsb-live`; the three seams; run folders under `data/runs` with sample `live`, self-contained, versioned, secret-free, with a manifest; the live document cache; cleanup after a finished run; the fence in code. **Correction to 0154 item 5's premise:** no docket document is "classed as synthesis" since decision 0056; withheld text is caught by the guard (a refusal of the whole case, or a mark, 0077, 0078); the closure record carries the reader's five statuses and Ellery's read or skip. Ruled out: a copy to S3 now; the store as a home for live results (one writer; it holds no verdict-derived data).
  - **161** — spec §7. `+t` replaces `+p` everywhere `+p` is used (applies 0143, amends 0133); what it renders; the reach test and the mutation test; continuity on `fd6053f` (Task 3's results file); version 1's two labels side by side (filled in when Task 2 pins `+t`; until then the record names the source label only and says the rendered one follows from Task 2); a live run refuses unless its prompt version is version 1's; `uv sync --locked`, `UV_LOCKED=1`, the lockfile checksum on every live run. Ruled out: record and continue; relying on CI only.
  - **162** — spec §5. Left out through the split's exclusion set; presence recorded and counted; answers the S3 specification's §20 open question. Ruled out: leaving it to the API; reading it on purpose (a new version, 0156 item 4).
  - **163** — spec §9. $0.30 a case (as measured, 0144), $5 a calendar month of live spend, S3.3's $10 stop as a line of $21.46 on S3's spend, each in code. Ruled out: $2 a month; no shadow cap.
  - **164** — spec §15 item 8. The structured expected-change field (0148 item 4) moves to version 2 because it changes Ellery's text; `later.py` stays unused on live cases (one run per case); Ellery is not told more documents may arrive (the docket is complete at closure: 0 of 300 closure documents arrived later).
- [x] Add a row per record to `docs/decisions/README.md`, and update the status column of 0133 ("amended by 161"), 0143 ("applied by 161"), 0148 ("item 4 moved to version 2 by 164"), 0150 ("S3.3's share limited by 163"), 0154 ("item 5's premise corrected by 160").
- [x] Append the dated notes ("Amended 2026-10-07 by 161: …" and so on) to those five records.
- [x] Replace "Record 2 of §15" / "Record 4" / "Record 5" in the specification with the records themselves (records 158, 160 and 161, cited with their leading zero now that they exist), and number §15's list items the same way.
- [x] `uv run --locked python -m scripts.check_docs` passes; commit: `S3.3 Task 1: decision records 157-164`.

## Task 2: The rendered-text fingerprint `+t`

**Files:** create `src/ntsb_probable_cause/agent/rendered.py`, `src/ntsb_probable_cause/agent/version.py`, `tests/test_agent_rendered.py`, `tests/fixtures/rendered/not_model_text.toml`; modify `src/ntsb_probable_cause/agent/texts.py` (remove `prompt_version`, `text_mark`, `is_plain`, `agent_text_sha256`, `source_text`, `_TEXT_PART`; keep `TEXT_SOURCES` as the reach test's module list), `agent/run.py`, `agent/armb.py`, `apps/eval/__main__.py` and every other importer of the removed names (find them with `grep -rn "prompt_version\|text_mark\|is_plain\|agent_text_sha256" src apps scripts tests`), `tests/test_s32_frozen.py`, `pyproject.toml` (the agent texts contract names `agent.version`).

**Background.** `texts.agent_text_sha256` hashes the source of the ten `TEXT_SOURCES` files plus two schemas as sent (decision 0133), so a comment moves the label. Decision 0143: hash what the agent receives instead. `CaseLoop` (`agent/loop.py`) and arm B's `FixedToolsLoop` (`agent/armb.py:221`) are state machines: `next_call()` hands out a `PendingCall` (`payload`, `settings`, `system`, `history`), `accept(reply, sent_at=, returned_at=)` takes a `model.client.ModelReply`. `model.openrouter.request_body(payload, settings, system=, history=)` is the exact JSON sent. So the renderer drives both machines over invented inputs with scripted replies and hashes what `request_body` would send.

**Interfaces:**
- Produces, `agent/rendered.py`:
  ```python
  MODEL_FACING_KEYS: Final = ("messages", "tools", "tool_choice", "parallel_tool_calls",
                              "response_format")
  RENDER_GUIDANCE: Final[tuple[str, ...]] = ("r3-loc-stall", "r6-aircraft-control")

  def rendered_requests() -> list[dict[str, object]]:
      """Every request the scenarios send, each cut to MODEL_FACING_KEYS, in a fixed order."""

  @functools.cache
  def rendered_sha256() -> str:
      """SHA-256 (hex) of json.dumps(rendered_requests(), sort_keys=True, ensure_ascii=False)."""
  ```
- Produces, `agent/version.py` (moved from `texts.py`, same behaviour except the mark):
  ```python
  AGENT_PROMPT_VERSION: Final = "s3-v1"
  SOURCE_LABEL_V1: Final = "s3-v1+ge17fecdc66ec+p947fac1c86a4"   # what v1's runs recorded
  VERSION_1: Final = "s3-v1+ge17fecdc66ec+t<12 hex, pinned in this task>"

  def text_mark() -> str: ...            # "+t" + rendered_sha256()[:prompt.FINGERPRINT_CHARS]
  def prompt_version(guidance: Sequence[str], round_number: int | None = None) -> str: ...
  def is_plain(version: str, guidance: Sequence[str]) -> bool: ...   # accepts +p or +t
  ```
- Consumes: `agent.loop.CaseLoop`, `LoopConfig`; `agent.armb.FixedToolsLoop` (read its constructor at `armb.py:241`); `agent.documents.docket_view(raw, docket)`; `docket.manifest.Docket`, `DocumentRecord`; `docket.listing` types for an invented listing; `model.client.ModelReply`, `ToolCall`, `Usage`; `model.openrouter.request_body`; `scoring.codes.load_tables`; `scoring.coding_stats.load_stats`.

- [x] **Invented inputs.** In `rendered.py`, build module-level constants: one invented raw record (`_RAW`) holding every evidence role `fields.EVIDENCE_FIELDS` reads, with invented values (no real case; look at a fixture under `tests/fixtures/` for the shape only), `ntsbNumber` `"XXX00XX000"`, `mKey` `1`, an `eventDate`, and no synthesis or verdict field; and an invented `Docket` for `mkey=1` whose listing holds four entries: two readable documents (invented text), one `unreadable: scan`, one `skipped: photo-only`. Docstring: "Invented, never a real case (decision 0143)."
- [x] **Scenarios.** Each is (raw, view or `None`, `LoopConfig` changes, `trigger`/`prior`/`new_structured`, scripted replies). Cover at least: (1) the full path: H0, a read choice reading one document and skipping one, with extra decisions on an unknown index, a not-readable index and an already-read index on the second look; H1; the second look reading the other; H2; each coding tool once, one call with an unknown code, one call naming the wrong tool, one with arguments that are not JSON; the answer; the refinement; (2) no docket; (3) a docket whose listed documents none can be read; (4) a later trigger with `new_structured=False` and one with `True`, from a `trail.Prior`; (5) the coding ablation (`without={"coding"}`); (6) a cap low enough that the loop forces the answer; (7) arm B's `FixedToolsLoop` over an invented answer. Use `CaseLoop(raw, view, config, ...)`, then loop: `call = loop.next_call()`; stop on `None`; append `{k: body[k] for k in MODEL_FACING_KEYS if k in body}` where `body = request_body(call.payload, call.settings, system=call.system, history=call.history)`; `loop.accept(reply, sent_at=T, returned_at=T)` with a fixed `T`. The config uses `load_tables()`, `load_stats("s3")`, `RENDER_GUIDANCE`, `exclusions=frozenset()`, `cap_usd=0.30`, `price_variant="batch"`.
- [x] **Failing test first** (`tests/test_agent_rendered.py`): `test_rendered_sha256_is_stable` (two calls in one process and one in a subprocess give the same hex); `test_render_guidance_is_the_runs` (`RENDER_GUIDANCE == agent.run.GUIDANCE`); `test_every_scenario_ends` (each loop reaches `next_call() is None` with no `protocol_error` left unanswered). Run: FAIL (module missing).
- [x] **The reach test** (`test_every_model_text_literal_is_reached`): for each module in `texts.TEXT_SOURCES`, plus `agent/documents.py` and `model/client.py`'s `Payload` rendering, parse the source with `ast`, collect every `str` constant that is not a docstring (for an f-string, each literal part of 6 characters or more); assert each appears in `json.dumps(rendered_requests(), ensure_ascii=False)` or is listed in `tests/fixtures/rendered/not_model_text.toml` as `"<module>:<literal>" = "<reason>"` (an exception message, a log line, a dict key, a regex). A literal that is model text and unreached is fixed by a scenario, never by the list.
- [x] **The mutation test** (`test_a_changed_text_moves_the_fingerprint`): for one model-text literal in each of the ten `TEXT_SOURCES` modules (chosen from the reach test's reached set, named in the test), copy `src/` to `tmp_path`, change that literal (append `"·"`), run `[sys.executable, "-c", "from ntsb_probable_cause.agent.rendered import rendered_sha256; print(rendered_sha256())"]` with `PYTHONPATH=<tmp>/src`, and assert the printed hex differs from the unmutated one. Also mutate one comment in `agent/loop.py` and assert the hex is **unchanged**. Mark it `@pytest.mark.slow` if the suite defines that marker; else keep it under 60 seconds.
- [x] Implement `rendered.py` until the three tests and the reach test pass; add scenarios for every unreached literal.
- [x] **Move the label code** to `agent/version.py`; `text_mark()` returns `f"+t{rendered_sha256()[: prompt.FINGERPRINT_CHARS]}"`; `is_plain` accepts `\+[pt][0-9a-f]{12}` so `resolve_latest` still finds S3.1's and S3.2's `+p` runs. Update every importer. `agent/run.py` and `agent/armb.py` call `version.prompt_version` / `version.text_mark` once at a run's start, as now.
- [x] **Pin version 1.** Run `uv run --locked python -c "from ntsb_probable_cause.agent import version, run; print(version.prompt_version(run.GUIDANCE))"`; write the printed value into `VERSION_1`. Rewrite `tests/test_s32_frozen.py`'s label test: `assert version.prompt_version(run.GUIDANCE) == version.VERSION_1`, and `assert version.SOURCE_LABEL_V1 == "s3-v1+ge17fecdc66ec+p947fac1c86a4"`; keep its temperature and dead-round tests unchanged. Show the label test can fail: change one word of `texts.CHOOSE` locally, run it, see FAIL, revert; record that in the commit message.
- [x] Add `ntsb_probable_cause.agent.version` and `ntsb_probable_cause.agent.rendered` to the import-linter contract "The agent's tools and texts see no case record" **only if** they import no `records`, `docket` or `data` module; `rendered.py` builds a `Docket` and so imports `docket`: leave it out of that contract and say why in a comment beside the contract.
- [x] `make check`; commit: `S3.3 Task 2: the rendered-text fingerprint +t replaces +p (decision 0143)`.

## Task 3: Continuity on `fd6053f` (built by a subagent, run by the Controller)

**Files:** create `scripts/s33_fingerprint_continuity.py`, `tests/test_s33_fingerprint_continuity.py`; the Controller creates `docs/results/s33-fingerprint-continuity.txt`; `Makefile` target `s33-continuity`.

**Interfaces:**
- Consumes: `agent/rendered.py` (Task 2), git.
- Produces: `def main(argv: Sequence[str] | None = None) -> int`; prints and, with `--out`, writes the results file.

- [x] **Failing test first:** with a fake runner (inject a callable that returns a hex per tree), `main(["--out", tmp])` writes a file holding the commit `fd6053f`, `SOURCE_LABEL_V1`, the `+t` on `fd6053f`, the `+t` on HEAD, and `match: yes`; with two different hexes it writes `match: no` and returns 1.
- [x] Implement: `git worktree add --detach <tmp> fd6053f` (under `tempfile.mkdtemp()`), copy this tree's `src/ntsb_probable_cause/agent/rendered.py` into `<tmp>/src/ntsb_probable_cause/agent/`, run `[sys.executable, "-c", "from ntsb_probable_cause.agent.rendered import rendered_sha256; print(rendered_sha256())"]` with `cwd=<tmp>` and `PYTHONPATH=<tmp>/src`, then the same in this tree; always `git worktree remove --force <tmp>` in `finally`. A `Status` paragraph (0059): "Run once in S3.3 (spec §7.2); writes `docs/results/s33-fingerprint-continuity.txt`."
- [x] `Makefile`: `s33-continuity:` → `uv run --locked python -m scripts.s33_fingerprint_continuity --out docs/results/s33-fingerprint-continuity.txt` (free), with a comment, and the target in `.PHONY`.
- [x] `make check`; commit: `S3.3 Task 3: the fingerprint continuity script`.
- [x] **Controller:** run `make s33-continuity`. If `match: yes`, commit the results file (`S3.3 Task 3: +t matches on fd6053f`); decision 0161 already cites it for version 1's two labels. **If `match: no`, or the script fails because `rendered.py` needs code `fd6053f` lacks: stop and put it to Andy (spec §18); do not start Task 4.**

## Task 4: `paid_run.sh` installs locked, and is tested by behaviour

**Files:** modify `scripts/paid_run.sh`, `tests/test_paid_run.py`.

- [x] **Failing tests first**, in `tests/test_paid_run.py`, with stand-in commands: write executable stubs for `git`, `uv`, `pass` and `make` into `tmp_path/bin`, each appending its arguments (and, for `make`, the value of `UV_LOCKED`) to `tmp_path/calls.log`; stub `git` answers `rev-parse --verify` (branch exists), `rev-list --count` (`0`), `status --porcelain` (empty), `rev-parse --short HEAD` (`abc1234`), `diff --quiet` (exit 0); create `tmp_path/checkout/.git/`. Run `bash scripts/paid_run.sh s33-dry-run` with `PATH=<bin>:/usr/bin:/bin`, `NTSB_PAID_BRANCH=s3-3-live-shadow`, `NTSB_PAID_CHECKOUT=<checkout>`, `NTSB_DATA_DIR=<tmp>/data`. Assert: `uv sync --quiet --locked` was called (not `--frozen`); `make s33-dry-run` was called with `UV_LOCKED=1`; the key was read with `pass show api/openrouter` after the `uv sync` line. Then three refusals by behaviour: `NTSB_PAID_BRANCH=main` exits 1 before any `git` call; `status --porcelain` printing ` M x` exits 1 before `make`; `rev-list --count` printing `2` exits 1 before `checkout`. Run: the `--locked` and `UV_LOCKED` tests FAIL.
- [x] Change `uv sync --quiet --frozen` to `uv sync --quiet --locked`, and add `export UV_LOCKED=1` before `make "$target" "$@"`, with a comment citing decision 161. Update the header's Status paragraph: "used by S3.2's held-out runs and S3.3's live mornings".
- [x] `make check`; commit: `S3.3 Task 4: paid_run.sh installs --locked and is tested by behaviour (decision 161)`.

## Task 5: The store's closures, the live settings and the training cut-off

**Files:** modify `src/ntsb_probable_cause/store/models.py`, `store/db.py`, `store/__init__.py`, `src/ntsb_probable_cause/settings.py`, `src/ntsb_probable_cause/sources.py`; tests in `tests/test_store.py` (or the store test file that covers `_closure_runs`; find it with `grep -rln _closure_runs tests`), `tests/test_settings.py`.

**Interfaces:**
- Produces, `store/models.py`:
  ```python
  class Closure(BaseModel, frozen=True):
      mkey: int
      ntsb_number: str
      event_date: str          # as stored, ISO date
      closure_run: int         # the earliest real closure's present_run
      closed_on: str           # that run's started_at, as a UTC ISO date
  ```
- Produces, `store/db.py` (read-only queries; no write):
  ```python
  def closures(self) -> list[Closure]: ...            # every real closure, ordered (closure_run, mkey)
  def run_finished_on(self, day: date) -> bool: ...    # a run started on that UTC date has finished_at
  ```
- Produces, `settings.py`: `live_docket_dir: Path = Path("data/live-docket")`, derived from `data_dir` in `model_post_init` when unset, as `docket_dir` is (env `NTSB_LIVE_DOCKET_DIR`).
- Produces, `sources.py`:
  ```python
  @dataclass(frozen=True)
  class TrainingCutoff:
      day: date
      source: str      # the page that states it
      read_on: date

  TRAINING_CUTOFFS: Final[Mapping[str, TrainingCutoff]] = {
      "openai/gpt-6-luna": TrainingCutoff(
          date(2026, 5, 18),
          "https://developers.openai.com/api/docs/models/gpt-6-luna",
          date(2026, 10, 7),
      ),
  }
  ```

- [x] **Failing tests first:** a store built in `tmp_path` with the existing test helpers, holding three cases: one closed `Ongoing → Completed` at run 2, one `Ongoing → not returned → N/A` at run 4, one re-labelled `Completed → N/A` after closing at run 3 (counts once, at 3); assert `closures()` returns them ordered by (closure_run, mkey), `closed_on` the date of each run's `started_at`, and that a store opened with `Store(path, readonly=True)` answers both queries; `run_finished_on` is `True` for a day with a finished run, `False` for a day whose run has `finished_at` NULL or no run. Settings: `Settings(data_dir=tmp).live_docket_dir == tmp / "live-docket"`, and an explicit `NTSB_LIVE_DOCKET_DIR` wins. Sources: the GPT-6 Luna entry exists and `sources.DEFAULT_MODEL` is a key.
- [x] Implement `closures()` by joining `_closure_runs()` with `cases` (for `ntsb_number`, `event_date`) and `runs` (for `started_at`); `run_finished_on` with one `SELECT` on `runs`. Export `Closure` from `store/__init__.py`.
- [x] `make check`; commit: `S3.3 Task 5: the store's closures, the live document cache setting, the training cut-off`.

## Task 6: The queue and the closure records (pure)

**Files:** create `src/ntsb_probable_cause/live/__init__.py`, `live/queue.py`, `live/records.py`, `tests/test_live_queue.py`, `tests/test_live_records.py`.

**Interfaces:**
- Consumes: `store.Closure` (Task 5); `docket.manifest.Status`; `sources.TrainingCutoff`.
- Produces, `live/queue.py`:
  ```python
  DECLARED_START: Final = date(2026, 9, 23)     # decision 0155
  DAILY_LIMIT: Final = 10                       # decision 157

  @dataclass(frozen=True)
  class QueuedCase:
      mkey: int
      case_id: str          # the NTSB number
      event_date: date
      closed_on: date
      closure_run: int

  def build_queue(closures: Sequence[Closure], done: AbstractSet[str]) -> list[QueuedCase]: ...
  def todays_take(queue: Sequence[QueuedCase], coded_today: int,
                  limit: int = DAILY_LIMIT) -> list[QueuedCase]: ...
  def closures_per_night(closures: Sequence[Closure]) -> dict[date, int]: ...
  def backfill_digest(case_ids: Sequence[str]) -> str: ...   # sha256 of "\n".join(sorted(ids))
  def waited_days(case: QueuedCase, coded_on: date) -> int: ...
  ```
- Produces, `live/records.py`:
  ```python
  CLOSURE_FORMAT: Final = "live-closure/1"
  BACKFILL_FORMAT: Final = "live-backfill/1"
  MANIFEST_FORMAT: Final = "live-manifest/1"
  CLOSURES_FILE: Final = "closures.jsonl"
  BACKFILL_FILE: Final = "backfill.json"
  INPUTS_FILE: Final = "inputs.jsonl"
  MANIFEST_FILE: Final = "manifest.json"

  class DocumentLine(BaseModel, frozen=True):
      position: int
      title: str
      status: Status                                   # the docket reader's five
      ellery: Literal["read", "skipped"] | None        # None when not on offer

  class ClosureRecord(BaseModel, frozen=True):
      format: Literal["live-closure/1"] = CLOSURE_FORMAT
      case_id: str
      mkey: int
      closed_on: date
      closure_run: int
      waited_days: int
      first_sent: datetime | None
      last_returned: datetime | None
      commit_sha: str
      dirty: bool
      prompt_version: str
      price_variant: Literal["batch", "standard"]
      model: str
      reasoning_effort: str | None
      training_cutoff: date
      training_cutoff_source: str
      uv_lock_sha256: str
      documents: tuple[DocumentLine, ...]
      prelim_present: bool
      outcome: Literal["coded", "not coded"]
      failure: str | None
      marks: tuple[str, ...]
      scored: bool                  # False when the record held no verdict
      top1: bool | None
      top3: bool | None
      abstained: bool | None
      cost_usd: float

  class Backfill(BaseModel, frozen=True):
      format: Literal["live-backfill/1"] = BACKFILL_FORMAT
      fixed_on: date
      case_ids: tuple[str, ...]
      sha256: str

  def write_manifest(folder: Path) -> None: ...
  def verify_manifest(folder: Path) -> list[str]: ...     # problems; [] when sound
  def portability_problems(folder: Path) -> list[str]: ...
  ```

- [x] **Failing tests first** (queue): `build_queue` drops closures before `DECLARED_START` and case ids in `done`, orders by (closure_run, mkey) whatever the input order; `todays_take` returns `queue[: max(0, limit - coded_today)]`; `closures_per_night` counts by `closed_on`; `backfill_digest` is order-free and changes when one id changes; `waited_days` is `(coded_on - closed_on).days`. Example: 40 closures on one night, `coded_today=0` → the 10 lowest mkeys; then `coded_today=10` → none.
- [x] **Failing tests first** (records): a `ClosureRecord` round-trips through JSON; `write_manifest` lists every file in the folder except itself, as relative POSIX paths with size and SHA-256, sorted; `verify_manifest` reports a changed byte, a missing file and an extra file; `portability_problems` reports any JSON string value that is an absolute path (`Path(value).is_absolute()`), and any value matching `sk-or-`, `AKIA[0-9A-Z]{16}`, or a key named `aws_profile` or `api_key`; a folder copied with `shutil.copytree` to another `tmp_path` verifies cleanly.
- [x] Implement both modules; no I/O in `queue.py`.
- [x] `make check`; commit: `S3.3 Task 6: the live queue and the closure records`.

## Task 7: Fetching, the seams and their local versions

**Files:** create `src/ntsb_probable_cause/live/fetch.py`, `live/seams.py`, `live/local.py`, `tests/test_live_fetch.py`, `tests/test_live_local.py`.

**Interfaces:**
- Consumes: `data.api.NtsbClient.cases_by_date_range(start, end) -> Iterator[Page]` (`Page.records`); `docket.client.DocketClient`; `docket.manifest.read_docket(client, mkey) -> Docket`; `fields.EVIDENCE_FIELDS` (`EvidenceField.role`, `.extract`); `store.Store`, `store.sync.Location`, `store.sync.pull`; `scoring.budget.spent_usd`; `scoring.records.RunRecord`, `read_jsonl`; Task 6's types.
- Produces, `live/fetch.py`:
  ```python
  class FetchError(Exception):
      """A case could not be fetched before its first model call: it returns to the queue."""

  def fetch_record(client: NtsbClient, case: QueuedCase) -> dict[str, object]: ...
  def prefetch_docket(client: DocketClient, mkey: int) -> Docket: ...
  def prelim_present(raw: Mapping[str, object]) -> bool: ...
  ```
- Produces, `live/seams.py` (`typing.Protocol`s):
  ```python
  class StoreSource(Protocol):
      def open(self) -> Store: ...          # a read-only copy
      def discard(self) -> None: ...        # delete the working copy

  class SpendCounter(Protocol):
      def live_month_usd(self, now: datetime) -> float: ...

  class ResultSink(Protocol):
      def done_case_ids(self) -> frozenset[str]: ...      # coded or not coded, any live run
      def coded_on(self, day: date) -> int: ...           # cases in live runs started that UTC day
      def unfinished_run(self) -> str | None: ...         # a live run whose record is not finished
      def backfill(self) -> Backfill | None: ...
      def write(self, run_id: str, records: Sequence[ClosureRecord],
                backfill: Backfill | None) -> None: ...   # closures, backfill, then the manifest
  ```
- Produces, `live/local.py`: `S3StoreSource(location: Location, work_file: Path)`, `LocalSpend(runs_dir: Path)`, `LocalFolderSink(runs_dir: Path)`, and `LIVE_SAMPLE: Final = "live"`, `STORE_WORK_FILENAME: Final = "live-store.sqlite"`.

- [x] **Failing tests first** (fetch): with `httpx.MockTransport` behind `NtsbClient(..., transport=...)` serving two pages for the event date, `fetch_record` returns the record whose `mKey` equals the case's; an `ApiError` or a missing record raises `FetchError`; `prefetch_docket` returns a `Docket` with per-document `"fetch failed"` statuses when single documents fail (reuse the docket fixtures under `tests/fixtures/docket`); `prelim_present` is `True` for a record with `narratives[0].prelimNarrative` text and `False` without.
- [x] **"No docket" is not "site down"** (spec §6: a case with no docket is coded in docket state "none"; one whose site is down returns to the queue). Read how `recorder/dockets.py` tells a listing page that says there is no released docket from a failed request (its `DocketOutcome` reasons and `_is_docket_outage_reason` in `recorder/run.py`), and reuse that distinction: a listing that answers "no documents" gives an empty `Docket` (no entries), which `docket_view` turns into no view, so the case is coded from the record; only a request the site did not answer raises `FetchError`. Test both, with the recorder's own fixtures for each page kind.
- [x] **Failing tests first** (local): `S3StoreSource` with a fake `S3Like` (as `tests/test_store_sync.py` builds one) pulls to the work file, opens it `readonly=True`, and a write through its connection raises `sqlite3.OperationalError`; `discard` deletes the work file and its `-wal`/`-shm`; `LocalSpend.live_month_usd` sums `spent_usd` of `run.jsonl` records whose `sample == "live"` and whose `started` is in the month, ignoring other samples; `LocalFolderSink` reads `done_case_ids` from every live run's `cases.jsonl`, `coded_on` from live runs whose run id starts with the day's `%Y%m%d`, `unfinished_run` as a live run whose last `run.jsonl` record has `finished is None` (or which has no `run.jsonl`), `backfill` from the first live run holding `backfill.json`; `write` writes `closures.jsonl` (and `backfill.json` when given) into `runs_dir/run_id`, then `write_manifest`.
- [x] Implement. `local.py` never imports `store.sync.push` (Task 9's contract enforces it).
- [x] `make check`; commit: `S3.3 Task 7: fetching, the three seams and their local versions`.

## Task 8: The morning

**Files:** create `src/ntsb_probable_cause/live/morning.py`, `tests/test_live_morning.py`.

**Interfaces:**
- Consumes: Tasks 2, 5, 6, 7; `agent.run.AgentRunner`, `GUIDANCE`; `agent.version.prompt_version`, `VERSION_1`; `agent.loop.PASS_REASONING`; `scoring.runner.RunSpec`, `CachedDocketReader`; `scoring.codes.load_tables`; `scoring.coding_stats.load_stats`; `scoring.samples.seen_pairs`; `scoring.records.CaseResult`, `RunRecord`; `agent.trail.AgentCall`; `gitinfo.commit_state`; `fields.EvidenceRole`.
- Produces:
  ```python
  LIVE_CAP_USD: Final = 0.30                 # decision 163
  MONTHLY_CAP_USD: Final = 5.0               # decision 163
  EXPECTED_COST_PER_CASE_USD: Final = 0.015  # estimate, spec §9; the reservation's projection
  LATE_START_UTC: Final = time(9, 0)         # spec §4: warn after this

  @dataclass(frozen=True)
  class MorningDeps:
      settings: Settings
      now: Callable[[], datetime]
      store: StoreSource
      spend: SpendCounter
      sink: ResultSink
      ntsb: Callable[[], NtsbClient]
      docket: Callable[[], DocketClient]
      models: Callable[[], tuple[ModelClient, BatchRunner | None]]
      commit: Callable[[], tuple[str, bool]]
      uv_lock_sha256: Callable[[], str]
      label: Callable[[], str] = lambda: prompt_version(GUIDANCE)

  @dataclass(frozen=True)
  class MorningSummary:
      run_id: str | None
      coded: int
      not_coded: dict[str, int]       # reason -> count
      returned: int                   # failed before seen, back in the queue
      queued: int                     # left after this morning
      cost_usd: float
      billed_usd: float | None
      minutes: float
      freed_bytes: int
      warnings: tuple[str, ...]

  def run_morning(deps: MorningDeps, *, dry_run: bool = False,
                  limit: int | None = None) -> MorningSummary: ...
  ```

- [x] **Failing tests first**, each with fakes for every dependency (no network, no model): (a) a label other than `VERSION_1` raises `ConfigurationError` naming both labels, before the store is opened; (b) no finished recorder run today → `ConfigurationError`, nothing fetched; (c) an unfinished live run is resumed with the raw records read back from its `inputs.jsonl`, in order, and no new run starts that morning; (d) `coded_on(today) == 10` → nothing taken, summary says the day's limit is reached; (e) live spend $4.95 plus 10 × `EXPECTED_COST_PER_CASE_USD` passes $5 → refused before any fetch; (f) a case whose `fetch_record` raises `FetchError` is left out of the run and counted in `returned`; (g) the run's `RunSpec` is `sample="live"`, `arm="C"`, `cap_usd=0.30`, `exclusions={EvidenceRole.PRELIM_NARRATIVE}`, `guidance=GUIDANCE`, `price_variant="batch"`, `sync=False`, `evidence_version="v1"`, `expected_cost_per_case_usd=EXPECTED_COST_PER_CASE_USD`; (h) a closure record per case: statuses from the prefetched `Docket`, `ellery` from the trail's read choices (`AgentCall.step in {"choice1", "choice2"}`, `arguments` decisions), `scored=False` and score fields `None` when `CaseResult.verdict_occurrence` is empty, `outcome="not coded"` with `failure` when `CaseResult.failure` is set, `first_sent`/`last_returned` from the trail; (i) the first morning writes `backfill.json` with the whole queue as it stood, and later mornings never rewrite it; (j) after a finished run, the run's cases' folders under `live_docket_dir` and the store work copy are deleted and `freed_bytes` counts them; after an interrupted run (the runner raises) they are kept; (k) `dry_run=True` opens the store, builds the queue, fetches the first case and its docket, makes no model call, writes no run folder, and prints what a morning would do; (l) a start after `LATE_START_UTC` adds a warning; (m) `limit=1` takes one case; (n) on the folder a faked run produces, `portability_problems(folder) == []` and `verify_manifest(folder) == []` (so `spec.json` and every other file `AgentRunner` writes hold no absolute path); (o) every refusal before a run (label, recorder unfinished, daily limit, monthly cap) appends one row `{"at": <UTC ISO>, "reason": <kind>}` to `runs_dir / "live-refusals.jsonl"`, with no case id, for Task 10 to count.
- [x] Implement `run_morning` in that order: label check; `store.open()`; `run_finished_on(today)`; resume an unfinished run if any; daily limit; caps (`spend.live_month_usd(now) + n × EXPECTED_COST_PER_CASE_USD <= MONTHLY_CAP_USD`); `build_queue(store.closures(), sink.done_case_ids())`; backfill on the first morning; `todays_take` (and `limit`); per case `fetch_record` then `prefetch_docket` into `live_docket_dir` (`FetchError` → returned); **the inputs, for an exact resume:** `AgentRunner.run` creates its own folder (`mkdir(exist_ok=False)`), so before calling it write the raw records, in order, to `runs_dir / "live-pending-inputs.jsonl"`, and move that file to `<run folder>/inputs.jsonl` once the folder exists (after `run` returns, or in an `except` that re-raises); a morning that finds an unfinished live run first moves a pending file into it, then resumes with the records read from it (this covers a hard kill, where no `except` ran). `AgentRunner` is not changed. Build `AgentRunner` as `apps/eval/__main__.py:_cmd_run` does for arm C, with `docket=CachedDocketReader(docket_client, readings=None)` over `DocketClient(settings.live_docket_dir, seconds_per_request=settings.docket_seconds_per_request)`, `seen_pairs=samples.seen_pairs(settings.data_dir / "processed")`, `stats=load_stats("s3")`; `runner.run(spec, raws)`; build and `sink.write` the closure records; cleanup; `store.discard()`; return the summary.
- [x] `make check`; commit: `S3.3 Task 8: the morning`.

## Task 9: `ntsb-live`, the fence, the stage line, the targets and the runbook

**Files:** create `apps/live/__init__.py`, `apps/live/__main__.py`, `tests/test_live_app.py`, `tests/test_live_fence.py`, `docs/runbooks/live-shadow-mornings.md`; modify `pyproject.toml`, `apps/eval/__main__.py`, `scripts/stage_spend.py`, `Makefile`, `tests/test_makefile.py`, `tests/test_import_boundaries.py` (if it lists contracts).

**Interfaces:**
- Consumes: Task 8's `run_morning`, `MorningDeps`; Task 7's local seams; `model.openrouter.OpenRouterClient`, `model.batch.BatchClient`; `data.api.NtsbClient`; `gitinfo.commit_state`.
- Produces: `ntsb-live run [--dry-run] [--limit N]` and `ntsb-live report` (the report subcommand calls Task 10's script function; until Task 10, it is absent); `scripts.stage_spend` stage `s33`.

- [x] **Failing tests first** (app): `main(["run", "--dry-run"])` with every factory replaced builds `MorningDeps` from `Settings()` (store `Location(settings.store)`, work file `settings.data_dir / STORE_WORK_FILENAME`, `LocalSpend(settings.runs_dir)`, `LocalFolderSink(settings.runs_dir)`) and prints the summary; `--limit 0` is refused; `uv_lock_sha256` reads the repository's `uv.lock`.
- [x] **Failing tests first** (fence, `tests/test_live_fence.py`): build a finished live run folder in `tmp_path` (sample `live`, cases with `split="open"`); each of `ntsb-eval report <id>`, `report --latest C live`, `judge`, `check`, `tools` exits with a refusal naming decision 0024; `scripts/_s3_runs.load_runs` refuses it (it already refuses any non-dev case: assert it); `month_spent` **does** count its spend; `resolve_latest` never returns it.
- [x] Implement the fence in `apps/eval/__main__.py`: one helper, `_refuse_live(record: RunRecord)`, called by `answering_run_record` (so every command that reads a run's record refuses), and `resolve_latest` skipping `sample == "live"`; check `scoring/checkpass.py`'s own development-only refusal already covers `check` and `tools` (test it).
- [x] **Import contract** in `pyproject.toml`: "Nothing in the library or the other commands imports the live package" (`forbidden`; sources: every library package except `live`, that is `agent`, `data`, `docket`, `errors`, `fields`, `gitinfo`, `model`, `paths`, `recorder`, `records`, `scoring`, `settings`, `sources`, `splits`, `store`, plus `apps.eval`, `apps.recorder`, `apps.ingest`; forbidden: `ntsb_probable_cause.live`, `apps.live`).
- [x] **The store's upload, by test:** `pull` and `push` share the module `store/sync.py`, and import-linter forbids modules, not functions, so `tests/test_live_fence.py` asserts that no file under `src/ntsb_probable_cause/live/` or `apps/live/` contains the name `push`, beside Task 7's test that a write to the store copy fails.
- [x] `live` imports `agent` (it runs `AgentRunner`). It is a consumer, like `apps`, so it is **not** added to the sources of "Nothing in the library imports the agent"; add a comment beside that contract saying so.
- [x] `pyproject.toml`: `ntsb-live = "apps.live.__main__:main"` under `[project.scripts]`.
- [x] `scripts/stage_spend.py`: add `"s33": Stage("S3.3", base="4178ca1", first="777c2a5", line_usd=21.46, prefix="s3-", line_rule="decision 163", count_rule="decisions 0128 item 2, 0135")` with a comment: S3.3's own $10 is S3's line less S3.1's and S3.2's $11.46; test it in the script's test file.
- [x] `Makefile` (and `.PHONY`), each with a comment saying free or paid, time and what it writes:
  ```make
  s33-dry-run:
  	uv run --locked ntsb-live run --dry-run
  # S3.3 spec §12 item 5, free: checks, store, queue, one fetch; no model call.

  s33-morning:
  	uv run --locked python -m scripts.stage_spend --stage s3 --estimate 0.15
  	uv run --locked python -m scripts.stage_spend --stage s33 --estimate 0.15
  	caffeinate -i uv run --locked ntsb-live run $(if $(LIMIT),--limit $(LIMIT))
  # S3.3 spec §4, paid: one live morning, at most 10 cases, about 1 to 2 hours on batch.
  # Run through scripts/paid_run.sh after `aws login --profile ntsb`. LIMIT=1 on the first one.

  s33-report:
  	uv run --locked python -m scripts.s33_live_report --out docs/results/s33-live-shadow.txt
  # S3.3 spec §10, free: the counts-only results file.
  ```
  Extend `tests/test_makefile.py`: every `s33-*` target is phony; `s33-morning` runs both `stage_spend` lines before `ntsb-live run`.
- [x] **Runbook** `docs/runbooks/live-shadow-mornings.md`, in simplified technical English with a glossary (Andy has no AWS background): when to run (after about 03:45 UTC, before 09:00 UTC), the three commands (`aws login --profile ntsb`, then `NTSB_PAID_BRANCH=s3-3-live-shadow scripts/paid_run.sh s33-morning`), what the summary means, what to do on each refusal (fingerprint, recorder not finished, daily limit, cap, login expired), resuming an interrupted morning (run the same command again), keeping the lid open, and disk space.
- [x] `make check`; commit: `S3.3 Task 9: ntsb-live, the open-split fence, the S3.3 line and the morning targets`.

## Task 10: The counts-only report

**Files:** create `scripts/s33_live_report.py`, `tests/test_s33_live_report.py`; wire `ntsb-live report` to it.

**Interfaces:**
- Consumes: `LocalFolderSink`'s folders (`closures.jsonl`, `backfill.json`, `run.jsonl`), `store.Store.closures()` through `S3StoreSource` (for closures per night), `queue.closures_per_night`, `scoring.codes.load_tables` (codes the tables lack), the project's Wilson interval helper (find it with `grep -rn "def wilson" src`).
- Produces: `def report_text(folders: Sequence[Path], closures: Sequence[Closure], tables: CodeTables) -> str`, `def main(argv: Sequence[str] | None = None) -> int`.

- [x] **Failing tests first**, on invented closure records: the text holds, in this order: mornings (runs, cases per run, queue length at each, days waited p50 and max, minutes first round to last); money (computed and billed per case and per calendar month); outcomes (first code right, right code in another position, different, each a count, with a 95% Wilson interval on "first code right" over scored cases; abstained; not coded by reason); the new checks (prelim present; refusals by kind, from `runs_dir/live-refusals.jsonl`, Task 8 (o); cases returned to the queue; verdict codes missing from the tables; closures without a verdict; closures as N/A); the backfill's count and SHA-256; closures per recorder night since 2026-09-23; and **the closing rule's two inputs** (spec §11): whether the backfill has drained, fresh closures coded so far (closures whose `closed_on` is after the backfill's `fixed_on`), and days since the first live morning, ending with one line: `closing rule: met (fresh closure)`, `met (14 days)` or `not met`. A test asserts the text holds no `case_id`, no `mkey`, and no string matching the NTSB number pattern `[A-Z]{3}\d{2}[A-Z]{2}\d{3}`, and no held-out figure (no "heldout", no "23.5").
- [x] Implement; `Status` paragraph (0059): "Live tool (S3.3 spec §10). Counts only (decision 0024)."
- [x] `make check`; commit: `S3.3 Task 10: the counts-only live report`.

## Task 11 (Controller): The dry run, the first paid morning, the mornings

- [ ] Push the branch. Run `aws login --profile ntsb` if needed, then `NTSB_PAID_BRANCH=s3-3-live-shadow scripts/paid_run.sh s33-dry-run` (free). Read its summary (counts only). Fix anything it finds before any paid run.
- [ ] **Ask Andy** before the first paid morning, stating: one case (`LIMIT=1`), about $0.01 and 15 to 30 minutes, inside 01:00 to 12:00 UTC. It fixes the backfill list. On his go-ahead: `NTSB_PAID_BRANCH=s3-3-live-shadow scripts/paid_run.sh s33-morning LIMIT=1`. Report its cost and duration.
- [ ] If the backfill list holds more than 100 cases, stop and put it to Andy (spec §18).
- [ ] Each later morning (Andy's permission stands within the $5 cap): `scripts/paid_run.sh s33-morning`; report the summary's coded, not coded, queued, cost and minutes to Andy. Log each morning's date and cost in Deviations under "Mornings".
- [ ] Stop when the closing rule of spec §11 is met; note which limb met it.

## Task 12 (Controller): The report and the close-out

- [ ] `make s33-report`; read `docs/results/s33-live-shadow.txt` against spec §10 (counts only); commit it.
- [ ] Final review on `opus`, split by dimension, three reviewers in parallel: (1) the open-split fence and leakage (nothing from a live case reaches a committed file, a development command or Ellery's text; the preliminary narrative is excluded; the closure record holds no document text); (2) the fingerprint (`+t` covers every text; the reach and mutation tests can fail; continuity; the refusal); (3) the morning, money and the scripts (queue rules, the seen rule, resume, caps, cleanup, `paid_run.sh`). Fix every Critical and Important finding; log the rest.
- [ ] Run the `close-stage` skill: As-built record appended to the specification (what was delivered, Done means with evidence, departures, known issues carried to S4, decisions, implementation record with run ids and spend), the specification marked Implemented, the roadmap's S3 entry noted done with a dated line, `CLAUDE.md` updated (S3.3 built, the `ntsb-live` command and `s33-*` targets, the `NTSB_LIVE_DOCKET_DIR` setting, `+t`), this plan deleted, `version = "0.10.0"`.
- [ ] Pull request titled `S3.3: live shadow`, to be merged with a merge commit (0033); the merge and the release are Andy's.

---

## Deviations

*(Dated entries, task by task, as the work finds them.)*

- **2026-10-07, Task 1.** Decision 0161 cites `docs/results/s33-fingerprint-continuity.txt` and `agent/version.py` for version 1's rendered label, instead of having the label filled into the record after Task 3: records are append-only, and the label does not exist until Task 2 pins it. Task 3's Controller step is reworded to match. The decisions' README rows for 0133, 0143, 0148, 0150 and 0154 carry the amendments in their status column, and dated notes are appended to those five records.
- **2026-10-07, Task 2.** (1) `rendered.py` also exports `scenario_runs()` and `ScenarioRun` (name, requests, stop reason, expected stop, unused replies), which the "every scenario ends" and reach tests read; `rendered_requests()` and `rendered_sha256()` are as specified. (2) `rendered.py` imports `agent.armb` inside `_arm_b()`, not at the top: `armb.py` now imports `agent.version` (for `text_mark`), which imports `rendered`, so a top-level import would be a cycle. It still imports only modules and names that exist at `fd6053f`; the continuity check was run early on that tree and gave `c6497367ee94`, the pinned value. (3) The two import-linter names were not added to the contract "The agent's tools and texts see no case record": `rendered` builds a `Docket` and imports `scoring.runner`, and `version` imports `rendered`; a comment beside the contract says so. (4) `not_model_text.toml` has a second table, `[unreachable]`, for eight literals that read as model text but that no input can make a run send today (an earlier check refuses first, or S3's statistics hold no such case). They are listed apart so the file does not call them "not model text"; each is reported as a concern in the task report, and the stale-entry test fails the day a scenario reaches one. (5) `test_agent_texts.py`'s `TestPromptVersion` and `TestAgentTextFingerprint` moved: the label tests to `tests/test_agent_version.py`, the source-hash tests were deleted with the code they tested; the five tests elsewhere that patched `texts.source_text` to simulate an edit in flight now patch `agent.version.rendered_sha256`. (6) The mutation test edits the text of ten named literals (one per module) and one comment; it has no `slow` marker (the suite defines none) and runs in about 6 seconds.
- **2026-10-07, Task 2, fix round 1.** The frozen-label guard depended on test order: `rendered_sha256` and `scenario_runs` are cached per process and read live module globals, so a test that patched one (`armb.run_coding_tool` in `TestBoundary`) and then reached `text_mark()` first froze a wrong hash (`+tb0d68e99b1e1`) and `test_the_loops_prompt_version_is_the_frozen_one` failed. Fixed with a session-scoped autouse fixture in `tests/conftest.py` that fills the cache before any test runs, a docstring note in `rendered.py`, and a regression test (`TestLabelDoesNotDependOnTestOrder`). No model text and no label changed.
- **2026-10-07, Task 3, fix round 1.** (1) Every setup or run failure on either side (worktree add, the copy, the frozen run, the HEAD run) now returns 2 with its cause printed; 1 is only a real mismatch. (2) `frozen_checkout` takes an injectable runner for its commands; tests assert the add, remove --force, prune order on success, when the body raises and when the copy fails.
- **2026-10-07, Task 5.** `closures()` builds on `_closure_runs()` (one definition) and joins `cases` and `runs` in Python, not SQL; `closed_on` and `run_finished_on` use SQLite's `date(started_at)`, which converts an offset timestamp to UTC. The tests are in `tests/test_store.py` and `tests/test_sources_settings.py` (there is no `tests/test_settings.py`).
- **2026-10-07, Task 6.** (1) `tests/test_import_boundaries.py` excludes `ntsb_probable_cause.live` from the children the contract "Nothing in the library imports the agent" must name: `live` runs the agent (Task 7 onward, decision 0160), so naming it would make the contract fail the day it does. The contract in `pyproject.toml` is unchanged. (2) `portability_problems` also reports a `.json` or `.jsonl` line that is not valid JSON, and a secret-like value is reported as its kind, never its text. (3) vulture needed no whitelist: the project runs it at `min_confidence = 80`, which does not flag unused functions.
- **2026-10-07, Task 6, fix round 1.** The boundary test's `outside` check now goes through `_disallowed_agent_importers`, which allows `ntsb_probable_cause.live` (and its submodules, not names such as `liveness`) as an importer of `agent` and nothing else; a new test feeds it a made-up import list to prove other packages are still caught. `pyproject.toml` contracts unchanged (Task 9).
- **2026-10-07, Task 7.** (1) `prefetch_docket` fetches the listing page itself before `read_docket` (a cache hit when the client has a cache directory, as the live one does): `read_docket` turns a page with no "Docket Information" block into an empty docket, which would read a layout change as "no docket". "No docket" is the site's own not-released page or an HTTP 404; every other listing failure (retries exhausted, any other status, count mismatch, no info block) is a `FetchError`. The recorder's private `_is_docket_outage_reason` is not imported; `docket.client.outcome_for_error` is reused. (2) `S3StoreSource` takes an optional `s3` client (for tests) and, for a local location, copies the file to the work file so `discard` never deletes the original; a missing store raises `FileNotFoundError`. (3) `LocalSpend` counts `RunRecord`s only, not preparation `spend.jsonl` rows, as decision 2 of the brief says.
- **2026-10-07, Task 7, fix round 1.** (1) `prefetch_docket(client, mkey, *, known_documents: int)`: a "no docket" answer (404 or not-released page) gives an empty `Docket` only when `known_documents == 0`; otherwise it raises `FetchError` (the live run cannot look again, decision 0157's seen rule). Task 8 must pass `store.documents_recorded(mkey)`. (2) New read-only `Store.documents_recorded(mkey) -> int`, counting rows in `documents` for the case, present or gone.
- **2026-10-07, Task 8.** (1) New read-only `Store.path` property (the morning measures the work copy's bytes before the source deletes it). (2) The take is `todays_take(queue, coded_today)[:n]`, with `n = min(day's room, limit)`; the monthly projection uses that `n`, because the caps are checked before the queue is built. (3) Refusal kinds are `label`, `recorder-unfinished`, `daily-limit`, `monthly-cap`; the monthly cap raises `BudgetError`, the daily limit returns a summary with a warning, and a dry run writes no refusal row. (4) Inputs: a pending file is moved into the run's folder after `run` returns or raises; the folder is found by diffing the runs folder before and after the call (not through the sink). A resume re-reads each case's docket from the cache (`prefetch_docket`) for the closure records, and, when no backfill is held yet, recomputes it with the resumed cases counted as still queued. (5) `ellery` is `read` if an accepted read choice read the document, `skipped` if it was offered and never read, `None` if never offered; `position` is the listing index. (6) `RunSpec.budget_usd` is `settings.monthly_budget_usd`; `AgentRunner` gets `now=deps.now`. (7) `morning.py` is 511 lines, just past the 500 guide; not split. (8) Tests replace `fetch_record`, `prefetch_docket`, `CachedDocketReader`, `load_tables`, `load_stats`, `seen_pairs` and `AgentRunner` on the module; (n) runs the real `AgentRunner` on a scripted batch client.
- **2026-10-07, Task 8, fix round 1.** (1) Backfill is pinned to `runs_dir/live-pending-backfill.json` before any fetch or run and moved into the first live run's folder beside the inputs; it is never computed on a resume (an unfinished run with no backfill held anywhere is refused). (2) The lockfile checksum is read at the start of the morning; record building moved to a new pure module `live/closure.py` (`Prepared`, `build_records`, `document_lines`); at the start of every non-dry morning a finished live run lacking `closures.jsonl` or its manifest is completed (records, manifest, cleanup) from its `inputs.jsonl`. (3) **Ruling: the specification governs over this plan's order**: a resume is held to the $5 monthly cap before any model call (`BudgetError`, `monthly-cap` row), projecting the cases of the run without an answer; the daily limit does not apply to a resume. (4) `_spec()` pins model `openai/gpt-6-luna`, reasoning `medium` and 8,000 reply tokens as module constants. (5) After a failed run, pending files go only into a new folder whose `spec.json` sample is `live`; more than one such folder is refused, none leaves them pending. (6) `morning.py` is about 540 lines even after the split to `closure.py`; not split further.
- **2026-10-07, Task 9.** (1) **A lock was added** (not in the brief): `ntsb-live run`, dry run included, holds an exclusive non-blocking `fcntl.flock` on `<runs_dir>/live.lock` for the whole morning and exits 1 with "another morning is running" if it is held, because nothing else stopped two mornings sharing the store work file and the pending files (found in Task 8's review). The lock file is never deleted. (2) `answering_run_record` refuses a live run (`_refuse_live`, naming decision 0024), so `resolve_latest` reads each candidate's first record directly and skips `sample == "live"`; `resolve_latest(..., "live")` itself is refused up front with 0024, since "no completed run found" would hide the reason. `apps/eval` holds its own `LIVE_SAMPLE = "live"` (it may not import `live`); a test holds it equal to `live.local.LIVE_SAMPLE`. `_cmd_report` now reads the run record before `cases.jsonl`, so a live folder is refused before anything else is read. (3) `checkpass`'s own refusal also covers `check` and `tools`, but the fence is reached first, so all six commands name 0024. (4) `--limit` must be at least 1 (refused by the argument parser). (5) `ntsb-live run` maps `BudgetError`, `ConfigurationError` and `FileNotFoundError` to one stderr line and exit 1, and any `botocore`/`boto3` error to "run `aws login --profile ntsb`" (the classes are matched by module name; boto3 is an optional dependency). (6) `ntsb-live report` is absent until Task 10. (7) The stage `s33` counts the same commits as `s3` (same first commit and prefix), against $21.46. (8) The runbook states the order rule (finish an interrupted morning before pushing code), `LIMIT=1` first, the 03:45 to 09:00 UTC window and the lid. (9) `s33-report` and its script are Task 10's; the target fails until then.
- **2026-10-07, Task 9, fix round 1.** (1) The `s33-dry-run` and `s33-morning` recipes run `ntsb-live` through `scripts/live_env.sh` (new; behaviour-tested with a stub `aws`) and `uv run --locked --extra aws --with awscrt`: it sets `AWS_PROFILE` (default `ntsb`) and, when `NTSB_STORE` is unset, `s3://<BucketName of NtsbRecorderStack>/recorder.sqlite`, and refuses plainly if the lookup fails; the recipe stops on that refusal (`env_out=$(...) && eval`). `paid_run.sh` exports `NTSB_API_KEY` from `pass show api/ntsb` (override `NTSB_PASS_NTSB`) for `s33-` targets only, never printed; three new behaviour tests. (2) `ntsb-live` says "log in again" only for `TokenRetrievalError`, `UnauthorizedSSOTokenError`, `SSOTokenLoadError` and `ClientError` codes `ExpiredToken`, `ExpiredTokenException`, `RequestExpired`, `InvalidClientTokenId`; any other botocore/boto3 error is "AWS error (<Class>): <short message>"; a non-AWS error propagates. A `BatchCancelledError` is now caught (one line, exit 1, "ntsb-live has no --resume option: run the same command again"). The RED step for this item was not run separately (test and code were written together). (3) The runbook refusal table is rewritten: every row quotes a text the program prints and `tests/test_live_runbook.py` checks each quoted text appears in the source; rows say "tell Claude"; the fingerprint row quotes the real message; the unfinished-run check covers a live folder with no `run.jsonl`; no second paid command while one runs; a "Before the first morning" section covers the login, what the recipe resolves, and the first dry run. (4) `checkpass.preflight` and `armb.preflight` are tested directly on a live run (they already refuse). (5) `_cmd_threshold` and `report --against` refuse a live run before reading its cases (tests delete the live `cases.jsonl` to prove the order); `scripts/reply_budget.py` and `scripts/sealed_report.py` refuse a live run through the new `scripts/_live_fence.py` before any read; the fence test for the s3 scripts matches the refusal text.
- **2026-10-07, Task 9, fix round 2.** (1) The runbook's first dry run is `NTSB_PAID_BRANCH=s3-3-live-shadow scripts/paid_run.sh s33-dry-run` (make alone has no `NTSB_API_KEY`); section 3 says to run from this branch's worktree until S3.3 is merged, and from the main folder after. (2) `LoginRefreshRequired` and `LoginTokenLoadError` (botocore's `aws login` provider) are expiry errors. (3) `scripts/_live_fence.py` falls back to `spec.json` when `run.jsonl` is missing or unreadable, and refuses a folder named `-live-` when neither names a sample; its `LIVE_SAMPLE` is held equal to `live.local.LIVE_SAMPLE` by a test. (4) `live_env.sh` prints `aws`'s own stderr after its plain message and still prints no export on failure. (5) `awscrt` is in the `aws` extra (`pyproject.toml`, locked at 0.37.0 by `uv lock`; deptry `DEP002` ignore since botocore loads it), `--with awscrt` is gone from both `s33-*` recipes and the runbook; `docs/runbooks/recorder-deploy.md` still says `--with awscrt`, which stays correct (it works with or without the extra) so it is untouched. The rendered fingerprint is unchanged: `tests/test_s32_frozen.py` and `tests/test_agent_version.py` pass.
- **2026-10-07, Task 10.** (1) `report_text(folders, closures, tables, refusals, *, today)` takes the refusal rows and the UTC date as arguments (the text function does no I/O and the closing rule's clock is testable). (2) `live.local.live_run_folders(runs_dir)` is new: a public wrapper over the sink's own recognition of live runs, so the script has no second one. (3) "Queue length at each" is rebuilt from the store as it stands today (cases not yet in any run up to and including that one), because a morning's queue length is not kept in the run folder; the line says so. (4) "Cases returned to the queue" is not recorded anywhere in a run folder (only the morning's printed summary has it), so the report states that and does not invent a number. (5) "Closures as N/A" cannot be told from "closures without a verdict" in the records (both hold no verdict codes), so the line says so and repeats the count. (6) "Billed" counts only runs whose every record carries a reported total, and says how many runs that is; per case divides by those runs' cases. (7) A failure reason is cut at the first colon, semicolon or bracket and any NTSB number is removed, so a failure text that names a case cannot reach the file. (8) `ntsb-live report [--out PATH]` imports `scripts.s33_live_report` lazily and puts the repository root on `sys.path` (`scripts` is not in the installed package); it holds the morning lock because it replaces the same store work file. (9) The `s33-report` recipe now resolves the store as the morning recipes do (`live_env.sh`, `--extra aws`), and `tests/test_makefile.py` covers it.
