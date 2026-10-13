// Reads S4's nightly export, board/1 (S5 spec §17.3). Only the case files index.json lists are
// read: S4's task cannot delete, so a dropped case's file can stay in the folder (spec §22).
// Fields S4 added after the first sample are read as null when absent (S4, 2026-10-12).
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { Ajv2020 } from "ajv/dist/2020.js";
import addFormatsModule from "ajv-formats";
import type { CaseFile } from "./board-case-types";
import type { BoardIndex } from "./board-index-types";

export class ExportError extends Error {}

const REPO = resolve(import.meta.dirname, "../../..");
const SCHEMA_PATH = join(REPO, "docs/schemas/board-1.schema.json");

/** The export to build from: `BOARD_EXPORT_DIR`, else S4's invented sample. */
export function exportDir(): string {
    return resolve(process.env["BOARD_EXPORT_DIR"] ?? join(REPO, "tests/fixtures/board"));
}

type Json = Record<string, unknown>;

function nullIfAbsent(record: Json, keys: readonly string[]): void {
    for (const key of keys) if (!(key in record)) record[key] = null;
}

function normaliseIndex(index: Json): void {
    const stamp = index["stamp"];
    if (stamp !== null && typeof stamp === "object") nullIfAbsent(stamp as Json, ["launched_on"]);
    const rows = index["rows"];
    if (Array.isArray(rows))
        for (const row of rows as Json[]) nullIfAbsent(row, ["mkey", "backfilled"]);
}

function normaliseCase(file: Json): void {
    nullIfAbsent(file, ["mkey"]);
    const trail = file["trail"];
    if (trail === null || typeof trail !== "object") return;
    const choices = (trail as Json)["read_choices"];
    if (!Array.isArray(choices)) return;
    for (const choice of choices as Json[]) {
        const documents = choice["documents"];
        if (!Array.isArray(documents)) continue;
        for (const doc of documents as Json[]) nullIfAbsent(doc, ["pages", "not_offered_reason"]);
    }
}

function read(path: string): Json {
    if (!existsSync(path)) throw new ExportError(`${path}: listed in index.json but missing`);
    return JSON.parse(readFileSync(path, "utf8")) as Json;
}

// ajv-formats is published as CommonJS; its default export is the function under ESM.
const addFormats = addFormatsModule as unknown as (ajv: Ajv2020) => Ajv2020;

/** Reads, normalises and checks every file of an export; throws ExportError on any fault. */
export function loadExport(dir: string): { index: BoardIndex; cases: Map<string, CaseFile> } {
    const schema = JSON.parse(readFileSync(SCHEMA_PATH, "utf8")) as { index: object; case: object };
    const ajv = new Ajv2020({ strict: false });
    addFormats(ajv);
    const checkIndex = ajv.compile(schema.index);
    const checkCase = ajv.compile(schema.case);

    const indexPath = join(dir, "index.json");
    const indexJson = read(indexPath);
    normaliseIndex(indexJson);
    if (!checkIndex(indexJson)) {
        throw new ExportError(
            `${indexPath}: not board/1: ${JSON.stringify(checkIndex.errors?.[0])}`,
        );
    }
    const index = indexJson as unknown as BoardIndex;

    const cases = new Map<string, CaseFile>();
    for (const row of index.rows) {
        const path = join(dir, "cases", `${row.case_number}.json`);
        const file = read(path);
        normaliseCase(file);
        if (!checkCase(file)) {
            throw new ExportError(`${path}: not board/1: ${JSON.stringify(checkCase.errors?.[0])}`);
        }
        cases.set(row.case_number, file as unknown as CaseFile);
    }
    return { index, cases };
}
