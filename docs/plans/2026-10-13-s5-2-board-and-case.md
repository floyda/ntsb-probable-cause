# S5 step 2 — The board and the opened case: implementation plan

**Spec:** docs/specs/2026-10-04-s5-public-site-design.md

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (Andy's choice for S5: Claude runs the tasks in the session, one fresh review of the branch at the end). Steps use checkbox (`- [ ]`) syntax. Tick a step in the same commit as its code (decision 0017). Log every departure in **Deviations**. Tasks marked **Controller** need Andy or touch a site outside this repository.

**Goal:** Step 2 of the specification's order of work (§21): the board of closed cases (§4) and the opened case (§5), built by Astro from S4's `board/1` export (§17.3), checked by schema, by unit tests and by the accessibility check, and shown to Andy as a preview. Nothing new is published: `publish.sh` still sends the holding page only.

**Architecture:** S4's schema and invented sample are copied onto this branch unchanged (Andy, 2026-10-13), with a make target that re-copies them from S4's branch so drift shows in `git diff`. A loader in `site/src/lib/export.ts` reads `index.json` and the case files it lists from `BOARD_EXPORT_DIR` (default: the sample), fills the fields S4 added later with null when absent, and validates every file with Ajv against the schema, stopping the build on any mismatch. The site's TypeScript types are generated from the same schema. All wording and formatting is pure functions in `site/src/lib/` with Vitest tests; Astro components only lay them out. The first page holds the board and, beneath it, the newest case opened; each case also has its own page at `/case/<case number>/`. A small script makes a chosen row open its case beneath the board; without script each row is a link.

**Tech Stack:** Astro 7, TypeScript 6 (strictest), Vitest, Ajv (draft 2020-12), json-schema-to-typescript, `@fontsource/doto` (the dot-matrix board face) and `@fontsource/atkinson-hyperlegible-next` (plain signage type for reading), all OFL-1.1 and self-hosted by the build.

## Global Constraints

- **Branch** `s5-public-site`, worktree `.claude/worktrees/s5-public-site`. The step 1 constraints hold: pnpm safeguards, 7-day minimum age for every package and action, strict checks, `make check` green at each commit.
- **Launch is Andy's decision** (§20). `publish.sh` and its tests are not touched in this step.
- **Only S4's export and committed files** are inputs (§17.3). No case data is typed into a page. Every board and case value comes from the export through `site/src/lib/`.
- **Respect (§11):** the result words are "same" and "different", never right, wrong, score or win. No registration, no names, no make or model in any field the site writes (S4's prose may name a make or model, by S4's decision on its branch). Injury level appears on the opened case only, never on the board.
- **Plain labels first, the NTSB's term second in small type** (§12 item 4): "What happened · NTSB occurrence codes", "Why it happened · NTSB findings", "The case's evidence files · the docket".
- **No link to a page that does not exist yet.** Methods (step 5) and the trail view (step 3) are not linked in this step; their links are added by the step that builds them. The internal-link check enforces it.
- **Never guess an NTSB address** (rule 2). The docket address is the spike's verified `https://data.ntsb.gov/Docket?ProjectID={mkey}` (build brief; `sources.docket_url`). The case-page address is used only if Task 7 verifies it.
- **Content-Security-Policy is `default-src 'self'`** (step 1): no inline `<script>` or `<style>` in any built page; a test checks the built HTML.
- **Accessibility (§12 item 8):** the board is a real `<table>` with a caption and header cells; every result mark carries its word; the axe check covers every built page in light, dark and phone width.
- **Tests:** Vitest for `site/src/lib/` and the built pages; pytest is unchanged except the copied fixtures pass the existing fixture checks.

## Review Focus

1. **An export from before S4's last fields** (no `mkey`, `launched_on`, `backfilled`, `pages`, `not_offered_reason`): it must still build, with those read as null and the dependent text left out (no docket link without `mkey`). Pinned by Task 2's normalisation test.
2. **A case file in the folder that `index.json` does not list** (S4's task cannot delete): it must never get a page. Pinned by Task 2's loader test and Task 6's dist check.
3. **A case the NTSB has not coded yet, or one not coded, or abstained**: every part of the opened case must still read sensibly, with no "undefined", empty heading or empty list. Pinned by Task 3's sentence tests and Task 5's render test over all seven sample cases.
4. **A long code label on a phone**: the board must not scroll the page sideways; only the table's own frame may. Pinned by Task 6's phone-width overflow check.
5. **Scripts off**: every row is still a working link and the newest case is still shown. Pinned by Task 6's no-script check.

## File map

| file | responsibility |
|---|---|
| `docs/schemas/board-1.schema.json`, `tests/fixtures/board/**` | S4's schema and invented sample, copied unchanged (Task 1) |
| `Makefile` (`site-board-sync`) | re-copies them from S4's branch (Task 1) |
| `site/scripts/gen-types.mjs`, `site/src/lib/board-types.ts` | types generated from the schema, and the check that they are current (Task 2) |
| `site/src/lib/export.ts`, `site/src/lib/export.test.ts` | the loader: list, normalise, validate (Task 2) |
| `site/src/lib/words.ts`, `site/src/lib/words.test.ts` | dates, durations, aircraft, grades, stamp, totals, the difference sentence, NTSB links (Task 3) |
| `site/src/components/Mark.astro`, `site/src/components/Board.astro`, `site/src/styles/board.css` | the result marks and the board (Task 4) |
| `site/src/components/OpenedCase.astro`, `site/src/pages/case/[case].astro`, `site/src/pages/index.astro` | the opened case, its own page, and the first page (Task 5) |
| `site/src/scripts/open-row.ts` | a chosen row opens beneath the board (Task 5) |
| `site/tests/dist.test.ts`, `site/tests/a11y.spec.ts` | checks over the built pages (Task 6) |

---

## Task 1: Copy S4's schema and sample

**Files:** Create `docs/schemas/board-1.schema.json`, `tests/fixtures/board/index.json`, `tests/fixtures/board/cases/XXX26XX00{1..7}.json`. Modify `Makefile`.

- [x] **Step 1: Add the sync target**

```make
# S4's export format and invented sample, copied from S4's branch until S4 merges (S5 step 2,
# Andy 2026-10-13). Re-run after S4 changes them; `git diff` shows what moved.
S4_BRANCH ?= origin/s4-predictions-and-resolution
site-board-sync:
	git fetch origin
	mkdir -p docs/schemas tests/fixtures/board/cases
	git show $(S4_BRANCH):docs/schemas/board-1.schema.json > docs/schemas/board-1.schema.json
	for f in $$(git ls-tree -r --name-only $(S4_BRANCH) -- tests/fixtures/board); do \
	  git show $(S4_BRANCH):$$f > $$f; done
```

Add `site-board-sync` to `.PHONY`.

- [x] **Step 2: Run it and check the copies**

Run: `make site-board-sync && git status --short docs/schemas tests/fixtures/board`
Expected: the schema and eight sample files added. Then `SKIP=no-commit-to-branch uv run pre-commit run --files docs/schemas/board-1.schema.json tests/fixtures/board/**/*.json tests/fixtures/board/*.json`: `check-fixtures-redacted`, `check-json` and `typos` pass (they are S4's invented cases).

- [x] **Step 3: Commit** — `S5 step 2 Task 1: S4's board/1 schema and invented sample, copied from S4's branch`.

---

## Task 2: Types and the loader

**Files:** Create `site/scripts/gen-types.mjs`, `site/src/lib/board-types.ts`, `site/src/lib/export.ts`, `site/src/lib/export.test.ts`, `site/vitest.config.ts`. Modify `site/package.json`.

**Interfaces — Produces:**
- `board-types.ts`: `BoardIndex`, `BoardRow`, `CaseFile`, `Code`, `MarkedCode`, `Belief`, `DocumentChoice` (generated; names follow the schema's titles).
- `export.ts`: `exportDir(): string` (from `BOARD_EXPORT_DIR`, default `../tests/fixtures/board`, resolved from `site/`); `loadExport(dir: string): { index: BoardIndex; cases: Map<string, CaseFile> }`; throws `ExportError` (message names the file and the first schema error) on any invalid, missing or unlisted-but-required file.

- [x] **Step 1: Add the tools**

```bash
cd site
pnpm add -D vitest ajv json-schema-to-typescript
```

Scripts in `package.json`: `"test": "vitest run"`, `"types": "node scripts/gen-types.mjs"`, `"types:check": "node scripts/gen-types.mjs --check"`.

- [x] **Step 2: Generate the types**

`site/scripts/gen-types.mjs`:

```js
// Writes src/lib/board-types.ts from S4's JSON Schema (S5 spec §17.3: the site's types are
// generated from the schema the export is checked against). `--check` fails if the file is stale.
import { readFileSync, writeFileSync } from "node:fs";
import { compile } from "json-schema-to-typescript";

const schema = JSON.parse(readFileSync("../docs/schemas/board-1.schema.json", "utf8"));
const banner = "// Generated by scripts/gen-types.mjs from docs/schemas/board-1.schema.json. Do not edit.\n";
const parts = [];
for (const key of ["index", "case"]) {
  parts.push(await compile(schema[key], key, { bannerComment: "", additionalProperties: false, strictIndexSignatures: true }));
}
const out = banner + parts.join("\n");
const path = "src/lib/board-types.ts";
if (process.argv.includes("--check")) {
  if (readFileSync(path, "utf8") !== out) {
    console.error(`${path} is stale: run pnpm run types`);
    process.exit(1);
  }
} else {
  writeFileSync(path, out);
}
```

Run `pnpm run types`; then `pnpm run format` (Prettier may reformat the output; if so, have the script run Prettier's API on `out` before comparing, and log it in Deviations). Shared definitions such as `Code` and `Aircraft` appear in both parts; if the compiler emits a duplicate declaration, compile the `case` part with `declareExternallyReferenced: false` for definitions already emitted, and log it.

- [x] **Step 3: Write the failing loader tests**

`site/src/lib/export.test.ts`:

```ts
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { ExportError, loadExport } from "./export";

const SAMPLE = join(__dirname, "../../../tests/fixtures/board");
let work: string | undefined;
function copy(): string {
  work = mkdtempSync(join(tmpdir(), "board-"));
  cpSync(SAMPLE, work, { recursive: true });
  return work;
}
afterEach(() => { if (work) rmSync(work, { recursive: true, force: true }); work = undefined; });

describe("loadExport", () => {
  it("reads the sample: one case per listed row", () => {
    const { index, cases } = loadExport(SAMPLE);
    expect(index.rows.length).toBe(7);
    expect([...cases.keys()].sort()).toEqual(index.rows.map((r) => r.case_number).sort());
  });

  it("ignores a case file that index.json does not list", () => {
    const dir = copy();
    const extra = JSON.parse(readFileSync(join(dir, "cases/XXX26XX001.json"), "utf8"));
    extra.case_number = "XXX26XX999";
    writeFileSync(join(dir, "cases/XXX26XX999.json"), JSON.stringify(extra));
    expect(loadExport(dir).cases.has("XXX26XX999")).toBe(false);
  });

  it("refuses a listed case whose file is missing", () => {
    const dir = copy();
    rmSync(join(dir, "cases/XXX26XX003.json"));
    expect(() => loadExport(dir)).toThrow(ExportError);
  });

  it("refuses a file that breaks the schema, naming it", () => {
    const dir = copy();
    const bad = JSON.parse(readFileSync(join(dir, "cases/XXX26XX002.json"), "utf8"));
    bad.grade = "right";
    writeFileSync(join(dir, "cases/XXX26XX002.json"), JSON.stringify(bad));
    expect(() => loadExport(dir)).toThrow(/XXX26XX002\.json/);
  });

  it("reads S4's later fields as null when an older export lacks them", () => {
    // Review Focus 1. S4 (2026-10-12): "Please still read a missing key as null."
    const dir = copy();
    const index = JSON.parse(readFileSync(join(dir, "index.json"), "utf8"));
    delete index.stamp.launched_on;
    for (const row of index.rows) { delete row.mkey; delete row.backfilled; }
    writeFileSync(join(dir, "index.json"), JSON.stringify(index));
    const one = JSON.parse(readFileSync(join(dir, "cases/XXX26XX002.json"), "utf8"));
    delete one.mkey;
    for (const choice of one.trail.read_choices) for (const d of choice.documents) { delete d.pages; delete d.not_offered_reason; }
    writeFileSync(join(dir, "cases/XXX26XX002.json"), JSON.stringify(one));
    const loaded = loadExport(dir);
    expect(loaded.index.stamp.launched_on).toBeNull();
    expect(loaded.index.rows[0]?.mkey).toBeNull();
    expect(loaded.cases.get("XXX26XX002")?.mkey).toBeNull();
  });
});
```

`site/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";
export default defineConfig({ test: { include: ["src/**/*.test.ts", "tests/**/*.test.ts"] } });
```

Run: `pnpm run test` — Expected: FAIL (`./export` does not exist).

- [x] **Step 4: Write the loader**

`site/src/lib/export.ts`:

```ts
// Reads S4's nightly export, board/1 (S5 spec §17.3). Only the case files index.json lists are
// read: S4's task cannot delete, so a dropped case's file can stay in the folder (spec §22).
// Fields S4 added after the first sample are read as null when absent (S4, 2026-10-12).
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import Ajv2020 from "ajv/dist/2020";
import type { BoardIndex, CaseFile } from "./board-types";

export class ExportError extends Error {}

const SCHEMA_PATH = resolve(import.meta.dirname, "../../../docs/schemas/board-1.schema.json");

export function exportDir(): string {
  return resolve(process.env["BOARD_EXPORT_DIR"] ?? resolve(import.meta.dirname, "../../../tests/fixtures/board"));
}

type Json = Record<string, unknown>;

function nullIfAbsent(record: Json, keys: readonly string[]): void {
  for (const key of keys) if (!(key in record)) record[key] = null;
}

function normaliseIndex(index: Json): void {
  nullIfAbsent(index["stamp"] as Json, ["launched_on"]);
  for (const row of index["rows"] as Json[]) nullIfAbsent(row, ["mkey", "backfilled"]);
}

function normaliseCase(file: Json): void {
  nullIfAbsent(file, ["mkey"]);
  const trail = file["trail"] as Json | null;
  for (const choice of (trail?.["read_choices"] as Json[] | undefined) ?? []) {
    for (const doc of choice["documents"] as Json[]) nullIfAbsent(doc, ["pages", "not_offered_reason"]);
  }
}

function read(path: string): Json {
  if (!existsSync(path)) throw new ExportError(`${path}: listed in index.json but missing`);
  return JSON.parse(readFileSync(path, "utf8")) as Json;
}

export function loadExport(dir: string): { index: BoardIndex; cases: Map<string, CaseFile> } {
  const schema = JSON.parse(readFileSync(SCHEMA_PATH, "utf8")) as { index: object; case: object };
  const ajv = new Ajv2020({ allErrors: false, strict: false });
  const checkIndex = ajv.compile(schema.index);
  const checkCase = ajv.compile(schema.case);
  const fail = (path: string, errors: unknown): never => {
    throw new ExportError(`${path}: does not match board/1: ${JSON.stringify(errors)}`);
  };

  const indexPath = join(dir, "index.json");
  const index = read(indexPath);
  normaliseIndex(index);
  if (!checkIndex(index)) fail(indexPath, checkIndex.errors?.[0]);

  const cases = new Map<string, CaseFile>();
  for (const row of (index as unknown as BoardIndex).rows) {
    const path = join(dir, "cases", `${row.case_number}.json`);
    const file = read(path);
    normaliseCase(file);
    if (!checkCase(file)) fail(path, checkCase.errors?.[0]);
    cases.set(row.case_number, file as unknown as CaseFile);
  }
  return { index: index as unknown as BoardIndex, cases };
}
```

(Ajv needs `ajv-formats` for `format: date`; without it formats are not checked. Add `ajv-formats` and `addFormats(ajv)` so dates are checked; log in Deviations if its import shape differs.)

- [x] **Step 5: Run the tests**

Run: `pnpm run test && pnpm run types:check && pnpm run check && pnpm run lint`
Expected: 5 passed; types current; zero errors and warnings.

- [x] **Step 6: Commit** — `S5 step 2 Task 2: types generated from board/1 and the export loader`.

---

## Task 3: The words

**Files:** Create `site/src/lib/words.ts`, `site/src/lib/words.test.ts`.

**Interfaces — Produces** (all pure, no I/O):
- `eventOf(label: string): string` — the part after the last `" / "`, else the label.
- `closedLabel(isoDate: string): string` — `"9 Oct"`; `closedLong(isoDate)` — `"9 Oct 2026"`.
- `tookLabel(days: number): string` — under 60 days `"47 days"`, else whole months `"3 mo"` (days ÷ 30.44, rounded down).
- `aircraftLabel(a: Aircraft): string` — `"Aeroplane, 1 piston"`, `"Helicopter, 1 turboshaft"`, `"Not recorded"` when all three are null.
- `GRADES: Record<Grade, { word: string; mark: MarkShape }>`; `MarkShape = "filled" | "half" | "open" | "dashed" | "square" | "diamond"`.
- `stampLine(index: BoardIndex): string` — `"Updated 06:00 UTC, 10 Oct · last closures 9 Oct"`.
- `totalsLine(rows: BoardRow[]): string` — `"Since launch: 1 same first code, 1 same codes in another order, 1 different, 1 agent abstained, 2 not coded, 1 awaiting the NTSB's codes."` (zero counts left out; counts only, no percentage, §12 item 10).
- `differenceSentence(c: CaseFile): string`.
- `factsLine(c: CaseFile): string[]` — the facts as separate items, for the line of §5 part 1.
- `withheldLine(c: CaseFile): string | null` — null when not coded.
- `docketUrl(mkey: number | null): string | null`.

- [x] **Step 1: Write the failing tests**

`site/src/lib/words.test.ts` (the sample's seven cases are the fixtures; every expected string is written out):

```ts
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { BoardIndex, CaseFile } from "./board-types";
import { aircraftLabel, closedLabel, differenceSentence, docketUrl, eventOf, factsLine, stampLine, tookLabel, totalsLine, withheldLine } from "./words";

const SAMPLE = join(__dirname, "../../../tests/fixtures/board");
const index = JSON.parse(readFileSync(join(SAMPLE, "index.json"), "utf8")) as BoardIndex;
const kase = (n: number): CaseFile => JSON.parse(readFileSync(join(SAMPLE, `cases/XXX26XX00${n}.json`), "utf8")) as CaseFile;

describe("small labels", () => {
  it("takes the event from a phase / event label", () => {
    expect(eventOf("Maneuvering-Low-alt flying / Aerodynamic stall/spin")).toBe("Aerodynamic stall/spin");
    expect(eventOf("Takeoff")).toBe("Takeoff");
  });
  it("writes dates and durations", () => {
    expect(closedLabel("2026-10-09")).toBe("9 Oct");
    expect(tookLabel(47)).toBe("47 days");
    expect(tookLabel(61)).toBe("2 mo");
    expect(tookLabel(427)).toBe("14 mo");
  });
  it("writes the aircraft as category and engines", () => {
    expect(aircraftLabel({ category: "Airplane", engines: 1, engine_type: "Reciprocating" })).toBe("Aeroplane, 1 piston");
    expect(aircraftLabel({ category: "Helicopter", engines: 1, engine_type: "Turbo shaft" })).toBe("Helicopter, 1 turboshaft");
    expect(aircraftLabel({ category: "Airplane", engines: 1, engine_type: null })).toBe("Aeroplane, 1 engine");
    expect(aircraftLabel({ category: null, engines: null, engine_type: null })).toBe("Not recorded");
  });
});

describe("board lines", () => {
  it("states the export's own build time and the last closures", () => {
    expect(stampLine(index)).toBe("Updated 06:00 UTC, 10 Oct · last closures 9 Oct");
  });
  it("counts each grade, leaving out zeros", () => {
    expect(totalsLine(index.rows)).toBe(
      "Since launch: 1 same first code, 1 same codes in another order, 1 different, 1 agent abstained, 2 not coded, 1 awaiting the NTSB's codes.",
    );
  });
});

describe("the difference sentence (spec §5 part 2; code writes it, never a model)", () => {
  it("same first code", () => {
    expect(differenceSentence(kase(1))).toBe("Both put “Aerodynamic stall/spin” first, and their sequences match.");
  });
  it("same codes, other order", () => {
    expect(differenceSentence(kase(2))).toBe("Both name “Hard landing”. The NTSB put it first; the agent put “Loss of control on ground” first.");
  });
  it("different", () => {
    expect(differenceSentence(kase(3))).toBe("The NTSB put “Fuel exhaustion” first. The agent put “Landing area undershoot” first and did not name the NTSB's first code.");
  });
  it("abstained", () => {
    expect(differenceSentence(kase(4))).toBe("The agent abstained: it judged the evidence too thin to code. The NTSB put “Loss of engine power (total)” first.");
  });
  it("not coded uses S4's fixed sentence", () => {
    expect(differenceSentence(kase(5))).toBe("A document in the docket held the NTSB's probable cause, so the case could not be shown to the agent.");
  });
  it("awaiting the NTSB's codes", () => {
    expect(differenceSentence(kase(6))).toBe("The NTSB has not published its codes yet. The agent put “Loss of engine power (partial)” first.");
  });
});

describe("the opened case's lines", () => {
  it("lists the facts, documents read as 'N of M'", () => {
    expect(factsLine(kase(1))).toEqual(["XXX26XX001", "closed 9 Oct 2026", "took 47 days", "Aeroplane, 1 piston", "TX", "Personal", "Fatal", "3 of 5 documents read"]);
  });
  it("says when the case was coded and that the verdict was withheld", () => {
    expect(withheldLine(kase(1))).toBe("Coded 9 Oct 2026, 03:14 UTC, from the docket as published at closure. The NTSB's cause and codes were withheld from the agent. Code version a1b2c3d.");
    expect(withheldLine(kase(5))).toBeNull();
  });
  it("builds the docket address from the NTSB's case key, or none", () => {
    expect(docketUrl(900101)).toBe("https://data.ntsb.gov/Docket?ProjectID=900101");
    expect(docketUrl(null)).toBeNull();
  });
  it("never writes undefined or an empty item for any sample case", () => {
    for (const n of [1, 2, 3, 4, 5, 6, 7]) {
      const c = kase(n);
      for (const text of [differenceSentence(c), ...factsLine(c)]) {
        expect(text).not.toMatch(/undefined|null|NaN/);
        expect(text.trim()).not.toBe("");
      }
    }
  });
});
```

Run: `pnpm run test` — Expected: FAIL (`./words` does not exist).

- [x] **Step 2: Write `words.ts`**

Implement each function to the tests. Rules not visible in the tests:
- Months and weekdays in English; dates are calendar dates, never shifted by time zone (parse `YYYY-MM-DD` by its parts, not `new Date(string)`).
- `stampLine` reads `stamp.built_at` (UTC) and the latest `closed_on` among rows; with no rows, `"Updated … · no closures yet"`.
- Aircraft: category `Airplane` → `Aeroplane`, other categories as given; engine types `Reciprocating` → `piston`, `Turbo prop` → `turboprop`, `Turbo shaft` → `turboshaft`, `Turbo fan` → `turbofan`, `Turbo jet` → `turbojet`, `Electric` → `electric`, any other lower-cased; a missing engine type writes `engine`/`engines`.
- Difference sentence: by grade, from `comparison` and the code lists. `same_first` adds "and their sequences match" when every mark is `same_place` on both sides, else "and their later codes differ". `different` says "named it, but not in its first three" when the NTSB's first code is fourth or later in the agent's list. `not_coded` returns `not_coded.sentence` unchanged. Curly quotes around NTSB labels.
- Facts: case number, closed (long), took, aircraft, then state, kind of flight, injury level and "N of M documents read" only when `facts` is not null and each value is not null.
- Withheld: `coded_at` in UTC as `9 Oct 2026, 03:14 UTC`, `commit` as given.

- [x] **Step 3: Run the tests** — `pnpm run test && pnpm run check && pnpm run lint` — Expected: all pass.

- [x] **Step 4: Commit** — `S5 step 2 Task 3: the board's and the opened case's words, from the export`.

---

## Task 4: The marks and the board

**Files:** Create `site/src/components/Mark.astro`, `site/src/components/Board.astro`, `site/src/styles/board.css`. Modify `site/src/styles/tokens.css`, `site/package.json` (fonts).

- [ ] **Step 1: Fonts**

`pnpm add @fontsource/doto @fontsource/atkinson-hyperlegible-next` (runtime dependencies: the build copies their files into `_astro/`). In `tokens.css`: `@import "@fontsource/atkinson-hyperlegible-next/400.css"; @import "@fontsource/atkinson-hyperlegible-next/700.css"; @import "@fontsource/doto/700.css";`, `--read: "Atkinson Hyperlegible Next", system-ui, sans-serif;`, `--board: "Doto", ui-monospace, monospace;`, and `html { font-family: var(--read); }`. Board tokens, the same in both themes because the board is a dark panel in both (§4): `--board-ground: #0d1117; --board-ink: #f2c94c; --board-dim: #b8c0cc; --board-rule: #2a3240;` (contrast checked by axe; if `--board-dim` fails AA on the ground, lighten it and log).

- [ ] **Step 2: `Mark.astro`**

Props `grade: Grade`. Renders `<span class="mark"><svg aria-hidden="true" …>` + `<span>{GRADES[grade].word}</span></span>`: the word is always present (shape is never the only signal, §12 item 8). Shapes, 14 × 14, `currentColor`: filled circle; half-filled circle (left half); open circle; dashed circle; open square; open diamond. No colour encodes the grade (§11: nothing reads as good or bad).

- [ ] **Step 3: `Board.astro`**

Props `index: BoardIndex`. A `<figure class="board">` with: a `<table>` whose `<caption>` is "Recently closed cases", header cells Closed, Took, Aircraft, Agent coded, NTSB coded, Result (`scope="col"`), and one row per `index.rows` entry in their order:
- Closed: `closedLabel`, and when `row.backfilled` a `<span class="from-start" aria-label="coded after launch, from the declared start">◦</span>`.
- Agent coded: `eventOf(agent_first.label)`; abstained → "No answer"; not coded → "—" with `aria-label="not coded"`.
- NTSB coded: `eventOf(ntsb_first.label)`; awaiting → "Not yet published".
- Result: `<Mark>`.
- The board lists every row the export holds; how many show at once on a phone (§4: about eight) is set with the scrolling route in step 6. The case number cell is not a column; the whole row's first cell holds `<a href={`/case/${n}/`} data-case={n}>`, so each row is a link (Review Focus 5).
Under the table: `stampLine`, `totalsLine`, the backfill note when any row is backfilled ("◦ closed before launch on {launched_on} and coded after it, from the declared start, 23 Sep 2026."), and the consistency line of §4: "The NTSB's own coding is not fully consistent, so 'different' does not simply mean wrong." (its link to Path comes in step 4).
The table sits in `<div class="board-frame">` with `overflow-x: auto` (Review Focus 4). At widths under 640 px, Took, Agent coded and NTSB coded are hidden with a class on their cells (§4: the phone keeps Closed, Aircraft and Result).

`board.css`: the panel on `--board-ground`, cells in `--board` at 1.1rem, header cells in `--board-dim`, rows separated by `--board-rule`, a visible focus ring on the row link.

- [ ] **Step 4: Build and look**

`pnpm run build`; put `<Board index={index} />` on `index.astro` temporarily if Task 5 is not done. Check no error; commit.

- [ ] **Step 5: Commit** — `S5 step 2 Task 4: the result marks and the board`.

---

## Task 5: The opened case and the first page

**Files:** Create `site/src/components/OpenedCase.astro`, `site/src/pages/case/[case].astro`, `site/src/scripts/open-row.ts`. Modify `site/src/pages/index.astro`, `site/astro.config.mjs`.

- [ ] **Step 1: `OpenedCase.astro`**

Props `kase: CaseFile`. An `<article class="opened" id="opened" data-case={case_number}>` with, in order (§5):
1. Facts: `factsLine` as a `<ul class="facts">`.
2. `<p class="difference">{differenceSentence}</p>`.
3. Two columns, "The agent's cause" and "The NTSB's cause": `answer.cause` (abstained: "No answer"; not coded: S4's sentence) and `verdict.cause` (null: "Not yet published").
4. "What happened · NTSB occurrence codes": two ordered lists, the agent's and the NTSB's, each item the label and its mark word (same place / other place / not in the other list) from `comparison`; when a side has no codes, one line saying why ("No answer", "Not coded", "Not yet published").
5. "Why it happened · NTSB findings": three lists — both named, only the NTSB, only the agent — each left out with a sentence when empty ("None."), never an empty list (Review Focus 3).
Then the withheld line (when not null) and the sources line: "Sources: the case's docket" linking `docketUrl(mkey)` when not null, plus the NTSB's case page if Task 7 verified it. No Methods or trail link yet.

- [ ] **Step 2: The case page**

`site/src/pages/case/[case].astro`: `getStaticPaths()` returns one path per row of `loadExport(exportDir())`, with the case file as a prop; renders `Base` with title `"{case_number} · Ellery"` and the `<OpenedCase>`; a back link to `/`.

- [ ] **Step 3: The first page**

`index.astro`: the caveat of §3.1 (Andy's wording, verbatim), the `<Board>`, then the newest row's `<OpenedCase>` under the heading "One case". (The scrolling route, the rail and the motion come in step 6.)

- [ ] **Step 4: A chosen row opens beneath the board**

`site/src/scripts/open-row.ts`, loaded by `index.astro` as `<script src="../scripts/open-row.ts"></script>` (Astro bundles it into a file, so the CSP's `'self'` allows it): on a click on a row link, fetch `/case/<n>/`, take its `article#opened`, replace the page's, move focus to it, and `history.pushState` to `/case/<n>/`; on `popstate` reload. If the fetch fails, follow the link. Without script, links navigate (Review Focus 5). In `astro.config.mjs` set `vite: { build: { assetsInlineLimit: 0 } }` so no script or style is inlined.

- [ ] **Step 5: A render test**

In `site/tests/dist.test.ts` (Task 6's file; start it here): after a build, for each of the seven sample cases, `dist/case/<n>/index.html` exists and contains its difference sentence and no `undefined`, `null` or `NaN` in visible text.

- [ ] **Step 6: Run** — `pnpm run build && pnpm run test && pnpm run test:a11y && pnpm run lint && pnpm run check` — Expected: all pass (axe now covers 9 pages in three projects).

- [ ] **Step 7: Commit** — `S5 step 2 Task 5: the opened case, its own page, and the first page`.

---

## Task 6: Checks over the built pages

**Files:** Modify `site/tests/dist.test.ts`, `site/tests/a11y.spec.ts`, `Makefile` (`site-check`), `.github/workflows/ci.yml` (`site` job).

- [ ] **Step 1: The dist checks** (Vitest, reading `dist/` after a build; skipped with a stated reason if `dist/` is absent):
- every `dist/case/*/index.html` belongs to a row of the export the build read (Review Focus 2);
- no built HTML holds an inline `<script>` without `src` or a `<style>` element (the CSP);
- every `href` starting with `/` resolves to a built file (internal links);
- no built text matches a US registration (`\bN[1-9][0-9A-HJ-NP-Z]{2,5}\b` with at least two digits).
- [ ] **Step 2: Playwright additions** in `a11y.spec.ts`: at 390 px, `document.documentElement.scrollWidth <= 390` on every page (Review Focus 4); with JavaScript disabled (`test.use({ javaScriptEnabled: false })` in a `noscript` describe), `/` shows the opened case and the first row's link goes to its case page (Review Focus 5).
- [ ] **Step 3: Wire them in:** `site-check` and the CI `site` job run `pnpm run types:check` and `pnpm run test` after `build`.
- [ ] **Step 4: Run** — `make check` — Expected: green.
- [ ] **Step 5: Commit** — `S5 step 2 Task 6: checks over the built pages`.

---

## Task 7: The NTSB's case page (Controller)

- [ ] **Step 1:** Take one development-split case's `mkey` from `tests/fixtures/records/` (event year 2019 or earlier). Request, once, with the project's user agent and nothing cached: `https://data.ntsb.gov/carol-repgen/api/Aviation/ReportMain/GenerateNewestReport/<mkey>/pdf` (the address CAROL's own report links use, to be confirmed here, not assumed). Record the date, status and content type in Deviations.
- [ ] **Step 2:** If it returns a PDF report for that case, add `caseReportUrl(mkey)` to `words.ts` with a test, and the "the NTSB's case page" link to the sources line. If not, leave the docket as the only NTSB link and record why.
- [ ] **Step 3: Commit** with the outcome.

---

## Task 8: Preview (Controller)

- [ ] **Step 1:** Build against the sample. Screenshot the first page and two case pages (same first code; not coded) at 390 × 844 and 1280 × 900, light and dark, with Playwright as in step 1; look at each.
- [ ] **Step 2:** Send them to Andy with the wording choices that need his eye: the six result words and marks, the difference sentences, the facts line, the dot font on the board, and the backfill note.
- [ ] **Step 3:** Record his answers as rulings or follow-up edits, and push the branch.

---

## Deviations

- **2026-10-13, Task 1:** copied from `origin/s4-predictions-and-resolution` at `b577bf3`. The
  hooks pass on the copies, and the Python suite passes with them in place (4,399 tests).
- **2026-10-13, Task 2: two generated type files, not one.** `board-index-types.ts` and
  `board-case-types.ts`, because both schemas define `Code` and `Aircraft` and one file would
  declare them twice. The generator also drops every property's own `title` before compiling
  (keeping the titles of the named definitions), or each property became a type alias of its own
  (`TookDays`, `CaseNumber` and about forty more). It formats through Prettier's API with the
  repository's `.editorconfig`, as Prettier's command line does, so `types:check` and
  `format:check` agree. Imports change accordingly (`board-index-types`, `board-case-types`).
- **2026-10-13, Task 2: lint skips the two generated files** (checked by `types:check` and the
  compiler), and test files may use untyped JSON (`no-unsafe-assignment`,
  `no-unsafe-member-access` off for `*.test.ts`), since the tests edit raw export JSON on purpose.
- **2026-10-13, Task 2:** Ajv is imported as `{ Ajv2020 } from "ajv/dist/2020.js"`, and
  `ajv-formats` (CommonJS) through a typed cast, so `format: date` and `date-time` are checked.
- **2026-10-13, Task 3:** `words.ts` also exports `closedLong` (used by the facts and withheld
  lines); one day is written "1 day". Every expected sentence in the plan passed unchanged.
