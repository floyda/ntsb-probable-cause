// Question 1's case (S5 spec §7.4), read from site/data/example-case.json, which
// scripts/site_example_case.py writes from a committed, redacted development fixture.
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";

export interface ExampleCode {
    code: string;
    label: string;
}

export interface ExampleCase {
    format: "example-case/1";
    case_number: string;
    mkey: number | null;
    event_date: string;
    injury: "none" | "minor" | "serious";
    cause: string | null;
    occurrence: ExampleCode[];
    findings: (ExampleCode & { in_cause: boolean })[];
}

const PATH = join(resolve(process.cwd(), ".."), "site/data/example-case.json");

/** The example case, checked enough that a malformed file fails the build. */
export function exampleCase(): ExampleCase {
    const raw = JSON.parse(readFileSync(PATH, "utf8")) as Partial<ExampleCase>;
    if (raw.format !== "example-case/1" || typeof raw.case_number !== "string") {
        throw new Error("example-case.json: not an example-case/1 file");
    }
    if (!Array.isArray(raw.occurrence) || !Array.isArray(raw.findings)) {
        throw new Error("example-case.json: codes missing");
    }
    return raw as ExampleCase;
}

const INJURY: Record<ExampleCase["injury"], string> = {
    none: "No injuries",
    minor: "Minor injuries",
    serious: "Serious injuries",
};

/** "No injuries": the case's highest injury level in words. */
export function injuryWords(c: ExampleCase): string {
    return INJURY[c.injury];
}
