import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import { checkFinished, NotFinished } from "../scripts/check-finished";

const BUILT = "2026-10-20T06:01:28.272470Z";

const made: string[] = [];
afterAll(() => {
    for (const dir of made) rmSync(dir, { recursive: true, force: true });
});

function exportWith(mark: unknown, built: unknown = BUILT): string {
    const dir = mkdtempSync(join(tmpdir(), "finished-"));
    made.push(dir);
    if (mark !== undefined) writeFileSync(join(dir, "_finished.json"), JSON.stringify(mark));
    writeFileSync(join(dir, "index.json"), JSON.stringify({ stamp: { built_at: built } }));
    return dir;
}

const whole = { format: "board-finished/1", built_at: BUILT, commit: "9c5be5d" };

describe("the finished mark (S5 spec §22; publish mode, Task 1)", () => {
    it("lets a whole export through", () => {
        expect(() => {
            checkFinished(exportWith(whole));
        }).not.toThrow();
    });
    it("stops an export with no mark", () => {
        expect(() => {
            checkFinished(exportWith(undefined));
        }).toThrow(/finished mark is missing/);
    });
    it("stops a mark left from an earlier night", () => {
        const dir = exportWith({ ...whole, built_at: "2026-10-19T06:00:00Z" });
        expect(() => {
            checkFinished(dir);
        }).toThrow(/not whole/);
    });
    it("stops a mark of another format", () => {
        expect(() => {
            checkFinished(exportWith({ ...whole, format: "board-finished/2" }));
        }).toThrow(NotFinished);
    });
    it("stops a mark that is not JSON, or not an object", () => {
        const dir = exportWith(whole);
        writeFileSync(join(dir, "_finished.json"), "{half");
        expect(() => {
            checkFinished(dir);
        }).toThrow(/not JSON/);
        expect(() => {
            checkFinished(exportWith([whole]));
        }).toThrow(/not a JSON object/);
    });
    it("stops when either side has no built_at", () => {
        expect(() => {
            checkFinished(exportWith({ format: "board-finished/1" }));
        }).toThrow(/no built_at/);
        expect(() => {
            checkFinished(exportWith(whole, null));
        }).toThrow(/no built_at/);
    });
    it("exits 1 with the reason when run as a script, and 0 when whole", () => {
        const script = join(__dirname, "../scripts/check-finished.ts");
        expect(execFileSync("node", [script, exportWith(whole)], { encoding: "utf8" })).toContain(
            "whole",
        );
        let status = 0;
        try {
            execFileSync("node", [script, exportWith(undefined)], { stdio: "pipe" });
        } catch (err) {
            status = (err as { status: number }).status;
        }
        expect(status).toBe(1);
    });
});
