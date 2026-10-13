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
afterEach(() => {
    if (work) rmSync(work, { recursive: true, force: true });
    work = undefined;
});

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
        for (const row of index.rows) {
            delete row.mkey;
            delete row.backfilled;
        }
        writeFileSync(join(dir, "index.json"), JSON.stringify(index));
        const one = JSON.parse(readFileSync(join(dir, "cases/XXX26XX002.json"), "utf8"));
        delete one.mkey;
        for (const choice of one.trail.read_choices)
            for (const d of choice.documents) {
                delete d.pages;
                delete d.not_offered_reason;
            }
        writeFileSync(join(dir, "cases/XXX26XX002.json"), JSON.stringify(one));
        const loaded = loadExport(dir);
        expect(loaded.index.stamp.launched_on).toBeNull();
        expect(loaded.index.rows[0]?.mkey).toBeNull();
        expect(loaded.cases.get("XXX26XX002")?.mkey).toBeNull();
    });
});
