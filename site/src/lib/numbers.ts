// The site's numbers (S5 spec §17.3), read by key from site/data/numbers.json, which
// scripts/site_numbers.py writes from the committed results files. Pages never type a number:
// every figure is one of these entries, formatted here, and an unknown key fails the build.
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";

export class NumbersError extends Error {}

export type Unit = "percent" | "points" | "usd" | "count";

export interface Entry {
    value: number;
    low: number | null;
    high: number | null;
    n: number | null;
    unit: Unit;
    sample: string;
    model: string;
    run: string | null;
    results_file: string;
    script: string;
    label: string;
}

export interface Numbers {
    format: "site-numbers/1";
    entries: Record<string, Entry>;
    lists: Record<string, Record<string, string | number>[]>;
}

// As in export.ts: Astro and Vitest run from site/, and the build bundles this module elsewhere.
const PATH = join(resolve(process.cwd(), ".."), "site/data/numbers.json");
const UNITS: readonly string[] = ["percent", "points", "usd", "count"];

const isNumberOrNull = (x: unknown): boolean => x === null || typeof x === "number";
const isStringOrNull = (x: unknown): boolean => x === null || typeof x === "string";

function checkEntry(key: string, raw: unknown): Entry {
    const e = raw as Record<string, unknown> | null;
    const ok =
        e !== null &&
        typeof e === "object" &&
        typeof e["value"] === "number" &&
        isNumberOrNull(e["low"]) &&
        isNumberOrNull(e["high"]) &&
        isNumberOrNull(e["n"]) &&
        typeof e["unit"] === "string" &&
        UNITS.includes(e["unit"]) &&
        ["sample", "model", "results_file", "script", "label"].every(
            (f) => typeof e[f] === "string",
        ) &&
        isStringOrNull(e["run"]);
    if (!ok) throw new NumbersError(`numbers.json: entry ${key} is malformed`);
    return raw as Entry;
}

/** Checks a parsed numbers file; throws NumbersError on another format or a malformed entry. */
export function parseNumbers(raw: unknown): Numbers {
    const file = raw as Record<string, unknown> | null;
    if (file === null || typeof file !== "object" || file["format"] !== "site-numbers/1") {
        throw new NumbersError("numbers.json: not a site-numbers/1 file");
    }
    const entries = file["entries"];
    const lists = file["lists"];
    if (
        entries === null ||
        typeof entries !== "object" ||
        lists === null ||
        typeof lists !== "object"
    ) {
        throw new NumbersError("numbers.json: entries or lists missing");
    }
    for (const [key, value] of Object.entries(entries)) checkEntry(key, value);
    return file as unknown as Numbers;
}

let cached: Numbers | undefined;

/** The committed numbers file, read and checked once. */
export function numbers(): Numbers {
    cached ??= parseNumbers(JSON.parse(readFileSync(PATH, "utf8")));
    return cached;
}

/** One entry by key; an unknown key throws, so a typo fails the build. */
export function entry(key: string): Entry {
    const found = numbers().entries[key];
    if (found === undefined) throw new NumbersError(`numbers.json has no entry ${key}`);
    return found;
}

/** One short list by key (question 5's commonest miss pairs). */
export function list(key: string): Record<string, string | number>[] {
    const found = numbers().lists[key];
    if (found === undefined) throw new NumbersError(`numbers.json has no list ${key}`);
    return found;
}

function ofUnit(key: string, unit: Unit): Entry {
    const e = entry(key);
    if (e.unit !== unit) throw new NumbersError(`${key} is ${e.unit}, not ${unit}`);
    return e;
}

function interval(e: Entry, key: string): [number, number] {
    if (e.low === null || e.high === null) throw new NumbersError(`${key} has no interval`);
    return [e.low, e.high];
}

const MINUS = "−";
const one = (x: number): string => x.toFixed(1);
// A plus for a gain (and for zero, as the results files print it), a true minus for a loss.
const signed = (x: number): string => (x < 0 ? `${MINUS}${one(-x)}` : `+${one(x)}`);
const grouped = (x: number): string => x.toLocaleString("en-GB");

/** "23.5%" */
export function pct(key: string): string {
    return `${one(ofUnit(key, "percent").value)}%`;
}

/** "23.5% [19.2%, 27.5%], 400 cases" */
export function withInterval(key: string): string {
    const e = ofUnit(key, "percent");
    const [low, high] = interval(e, key);
    const cases = e.n === null ? "" : `, ${grouped(e.n)} cases`;
    return `${one(e.value)}% [${one(low)}%, ${one(high)}%]${cases}`;
}

/** "−9.5 points [−14.0, −5.2]" */
export function points(key: string): string {
    const e = ofUnit(key, "points");
    const [low, high] = interval(e, key);
    return `${signed(e.value)} points [${signed(low)}, ${signed(high)}]`;
}

/** "$2.06" */
export function usd(key: string): string {
    return `$${ofUnit(key, "usd").value.toFixed(2)}`;
}

/** "16,790" */
export function count(key: string): string {
    return grouped(ofUnit(key, "count").value);
}

/** "88 of 399" */
export function countOf(key: string): string {
    const e = ofUnit(key, "count");
    if (e.n === null) throw new NumbersError(`${key} has no total`);
    return `${grouped(e.value)} of ${grouped(e.n)}`;
}

/** The count behind an entry: "400". */
export function caseCount(key: string): string {
    const n = entry(key).n;
    if (n === null) throw new NumbersError(`${key} has no count`);
    return grouped(n);
}

const WORDS = ["", "", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
// How far a rate may sit from "one in N" and still be called "about" it: a fifth of 1/N.
const NEAR = 0.2;

/** "one case in four": the nearest of one in two to one in ten, refused when none is near. */
export function oneInWords(percent: number): string {
    let best = 2;
    for (let k = 3; k <= 10; k++) {
        if (Math.abs(100 / k - percent) < Math.abs(100 / best - percent)) best = k;
    }
    const target = 100 / best;
    if (Math.abs(target - percent) > NEAR * target) {
        throw new NumbersError(`${one(percent)}% is not about one case in ${String(best)}`);
    }
    return `one case in ${WORDS[best] ?? String(best)}`;
}

/** The caveat's words for a rate entry. */
export function oneIn(key: string): string {
    return oneInWords(ofUnit(key, "percent").value);
}

/** Whether one entry's interval contains another entry's value (question 2's claim). */
export function containsValue(rangeKey: string, valueKey: string): boolean {
    const [low, high] = interval(entry(rangeKey), rangeKey);
    const v = entry(valueKey).value;
    return low <= v && v <= high;
}
