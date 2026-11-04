// Checks that a copied export is whole before the morning build reads it (S5 spec §18.1, §22).
// S4 uploads the case files, then index.json, then the finished mark, and overwrites the mark each
// night. If an upload fails partway, the mark keeps the previous night's `built_at`, so the build
// goes ahead only when the mark's `built_at` equals index.json's. Run by publish.sh in site mode
// with Node 24, which runs TypeScript directly: `node scripts/check-finished.ts <export folder>`.
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export class NotFinished extends Error {}

function readJson(path: string, what: string): Record<string, unknown> {
    let text: string;
    try {
        text = readFileSync(path, "utf8");
    } catch {
        throw new NotFinished(`${what} is missing: ${path}`);
    }
    let value: unknown;
    try {
        value = JSON.parse(text);
    } catch {
        throw new NotFinished(`${what} is not JSON: ${path}`);
    }
    if (value === null || typeof value !== "object" || Array.isArray(value)) {
        throw new NotFinished(`${what} is not a JSON object: ${path}`);
    }
    return value as Record<string, unknown>;
}

/** Throws NotFinished unless the export in `dir` carries a finished mark for this index. */
export function checkFinished(dir: string): void {
    const mark = readJson(join(dir, "_finished.json"), "the finished mark");
    if (mark["format"] !== "board-finished/1") {
        throw new NotFinished("the finished mark is not board-finished/1");
    }
    const index = readJson(join(dir, "index.json"), "index.json");
    const stamp = index["stamp"];
    const indexBuilt =
        stamp !== null && typeof stamp === "object" && !Array.isArray(stamp)
            ? (stamp as Record<string, unknown>)["built_at"]
            : undefined;
    const markBuilt = mark["built_at"];
    if (typeof markBuilt !== "string" || typeof indexBuilt !== "string") {
        throw new NotFinished("the finished mark or index.json has no built_at");
    }
    if (markBuilt !== indexBuilt) {
        throw new NotFinished(
            `the finished mark is for ${markBuilt}, index.json for ${indexBuilt}: ` +
                "the night's upload is not whole",
        );
    }
}

if (process.argv[1] !== undefined && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
    const dir = process.argv[2];
    if (dir === undefined) {
        console.error("usage: node scripts/check-finished.ts <export folder>");
        process.exit(2);
    }
    try {
        checkFinished(dir);
    } catch (err) {
        if (!(err instanceof NotFinished)) throw err;
        console.error(`check-finished: ${err.message}`);
        process.exit(1);
    }
    console.log("check-finished: the export is whole");
}
