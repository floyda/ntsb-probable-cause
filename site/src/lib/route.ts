// The first page as a route (spec §3.1; S5 step 6b): the case it shows, that case's trail as a
// strip of beliefs, and the eight Path questions with their one-line answers (Andy, 2026-10-21).
// Read from the export and the numbers file alone; every claim an answer makes is a guard in
// claims.ts.
import type { CaseFile } from "./board-case-types";
import type { BoardIndex } from "./board-index-types";
import { oneIn } from "./numbers";
import { trailSteps } from "./trail";
import { eventOf } from "./words";

/** The newest closed case with a trail to show; none when no case has one. */
export function routeCase(
    index: BoardIndex,
    cases: ReadonlyMap<string, CaseFile>,
): CaseFile | undefined {
    for (const row of index.rows) {
        const k = cases.get(row.case_number);
        if (k?.trail != null && k.trail.beliefs.length > 0) return k;
    }
    return undefined;
}

export type StripItem =
    /** `matched`: the belief put the NTSB's first code first; null before the NTSB publishes. */
    | { kind: "belief"; name: string; event: string; matched: boolean | null }
    | { kind: "step"; text: string };

const SHORT: Record<string, string> = {
    h0: "Before reading",
    h1: "After reading",
    h2: "After reading again",
    answer: "The answer",
};

/** The strip: each belief the trail holds, with what was read or looked up between them. */
export function stripItems(c: CaseFile): StripItem[] {
    const ntsbFirst = c.verdict?.occurrence[0]?.code ?? null;
    return trailSteps(c).map((step): StripItem => {
        if (step.kind === "belief") {
            const b = step.belief;
            return {
                kind: "belief",
                name: SHORT[b.kind] ?? step.name,
                event: eventOf(b.first.label),
                matched: ntsbFirst === null ? null : b.first.code === ntsbFirst,
            };
        }
        if (step.kind === "read") {
            const docs = step.choice.documents;
            const offered = docs.filter((d) => d.decision === "read" || d.decision === "skipped");
            const read = offered.filter((d) => d.decision === "read").length;
            return offered.length === 0
                ? { kind: "step", text: "nothing on offer to read" }
                : {
                      kind: "step",
                      text: `read ${String(read)} of ${String(offered.length)} documents offered`,
                  };
        }
        const n = step.lookups.length;
        return {
            kind: "step",
            text: n === 1 ? "1 coding look-up" : `${String(n)} coding look-ups`,
        };
    });
}

export interface RouteQuestion {
    /** The question's stop on the Path page. */
    anchor: string;
    question: string;
    answer: string;
}

/** The eight questions and their one-line answers, as Andy approved them on 2026-10-21. */
export const ROUTE_QUESTIONS: readonly RouteQuestion[] = [
    {
        anchor: "answer-key",
        question: "Is there an answer key nobody had to write?",
        answer: "Yes. The NTSB codes every closed case.",
    },
    {
        anchor: "case-record",
        question: "Is the case record enough?",
        answer: "No. Alone, it did no better than guessing.",
    },
    {
        anchor: "docket",
        question: "Does reading the docket help?",
        answer: "Yes. It is the largest gain on the ladder.",
    },
    {
        anchor: "scanned-pages",
        question: "Does reading words in scanned pages help?",
        answer: "Not shown to help, and costly, so it is paused.",
    },
    {
        anchor: "coding",
        question: "Are the misses about evidence or about coding?",
        answer: "Mostly the NTSB's coding order.",
    },
    {
        anchor: "consistency",
        question: "How consistent is the answer key itself?",
        answer: `Not fully: cases with the same cause sentence share a first code in about ${oneIn("q6.twins")}.`,
    },
    {
        anchor: "choosing",
        question: "Does choosing what to read beat reading everything?",
        answer: "No. The loop was worse than the fixed pipeline, at about the same bill.",
    },
    {
        anchor: "newly-closed",
        question: "Does it hold on newly closed cases?",
        answer: "The board above answers this in public.",
    },
];
