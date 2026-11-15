// The trail view's steps and words (S5 spec §6), from the export's `trail` alone. Beliefs are the
// spine; read choices and coding lookups sit between them; cost is the export's own figure.
import type {
    Belief,
    CaseFile,
    Code,
    DocumentChoice,
    Lookup,
    ReadChoice,
} from "./board-case-types";
import { eventOf } from "./words";

export type TrailStep =
    | { kind: "belief"; belief: Belief; name: string; changed: string | null }
    | { kind: "read"; choice: ReadChoice; name: string }
    | { kind: "lookups"; lookups: Lookup[]; cost_usd: number };

const BELIEF_NAMES: Record<Belief["kind"], string> = {
    h0: "Before reading",
    h1: "After the first read choice",
    h2: "After the second read choice",
    answer: "The answer",
};

const CHOICE_NAMES: Record<ReadChoice["step"], string> = {
    choice1: "First read choice",
    choice2: "Second read choice",
};

// The belief a read choice can lead to. The export has it only when the choice read something
// that moved the agent to a checkpoint; it is never invented (plan Review Focus 1).
const AFTER: Record<ReadChoice["step"], Belief["kind"]> = { choice1: "h1", choice2: "h2" };

function isAbstained(c: CaseFile): boolean {
    return c.grade === "abstained" || c.answer?.abstained === true;
}

export function beliefName(kind: Belief["kind"]): string {
    return BELIEF_NAMES[kind];
}

/** The steps in the order they happened: h0, each read choice and its belief, lookups, answer. */
export function trailSteps(c: CaseFile): TrailStep[] {
    const trail = c.trail;
    if (trail === null) return [];
    const byKind = new Map(trail.beliefs.map((b) => [b.kind, b]));
    const steps: TrailStep[] = [];
    const abstained = isAbstained(c);
    const pushBelief = (kind: Belief["kind"]): void => {
        const belief = byKind.get(kind);
        if (belief === undefined) return;
        const first = steps.every((s) => s.kind !== "belief");
        steps.push({
            kind: "belief",
            belief,
            // Said as plainly as the opened case says it (review, 2026-10-14).
            name:
                kind === "answer" && abstained
                    ? "The answer: the agent abstained"
                    : beliefName(kind),
            changed: first ? null : belief.changed ? "first code changed" : "first code unchanged",
        });
    };

    pushBelief("h0");
    const choices = [...trail.read_choices].sort((a, b) => a.step.localeCompare(b.step));
    for (const choice of choices) {
        steps.push({ kind: "read", choice, name: CHOICE_NAMES[choice.step] });
        pushBelief(AFTER[choice.step]);
    }
    if (trail.lookups.length > 0) {
        const cost = trail.lookups.reduce((sum, l) => sum + l.cost_usd, 0);
        steps.push({ kind: "lookups", lookups: trail.lookups, cost_usd: cost });
    }
    pushBelief("answer");
    return steps;
}

/** "confidence 0.45": plain, as fitted, with no claim drawn from it (spec §6). */
export function confidenceLabel(x: number): string {
    return `confidence ${x.toFixed(2)}`;
}

/** "$0.0038": the export's figure, to four decimals. */
export function costLabel(usd: number): string {
    return `$${usd.toFixed(4)}`;
}

const NOT_OFFERED: Record<
    NonNullable<DocumentChoice["not_offered_reason"]>,
    { decision: string; detail: string }
> = {
    already_read: { decision: "already read", detail: "at the first read choice" },
    photo_only: { decision: "not offered", detail: "photographs only" },
    not_pdf: { decision: "not offered", detail: "not a PDF" },
    fetch_failed: { decision: "not offered", detail: "could not be fetched" },
    over_size_limit: { decision: "not offered", detail: "over the size limit" },
};

/**
 * A document's title as the site shows it (decision 0187, amended 2026-10-21): the exact sequence
 * "A", U+FFFD, U+FFFD, where the NTSB's own docket page lost a character, becomes an apostrophe
 * inside a word ("SPECIALIST'S") and an en dash anywhere else. A guess at the lost character,
 * made in the site so S4's export stays an exact copy; nothing else is changed.
 */
export function titleShown(title: string): string {
    return title.replace(/(.?)A\uFFFD\uFFFD(?=(.?))/gu, (_m, before: string, after: string) =>
        /\p{L}/u.test(before) && /\p{L}/u.test(after) ? `${before}\u2019` : `${before}\u2013`,
    );
}

/** What happened to one docket document at a read choice, with its pages when known. */
export function documentLine(d: DocumentChoice): { decision: string; detail: string | null } {
    let decision: string;
    let why: string | null = null;
    if (d.decision === "read") decision = "read";
    else if (d.decision === "skipped") decision = "skipped";
    else if (d.decision === "scan_only") {
        decision = "scan only";
        why = "no text to read";
    } else if (d.not_offered_reason === null) decision = "not offered";
    else ({ decision, detail: why } = NOT_OFFERED[d.not_offered_reason]);
    const pages = d.pages === null ? null : d.pages === 1 ? "1 page" : `${String(d.pages)} pages`;
    const parts = [why, pages].filter((p): p is string => p !== null);
    return { decision, detail: parts.length === 0 ? null : parts.join(" · ") };
}

const TOOL_NAMES: Record<string, string> = {
    describe_codes: "Looked up what codes cover",
    occurrence_usage: "Looked up how often codes come first",
    past_findings: "Looked up findings in past cases",
    suggest_codes: "Asked for suggested codes",
};

/** A coding tool in plain words. */
export function lookupName(tool: string): string {
    return TOOL_NAMES[tool] ?? tool.replaceAll("_", " ");
}

/** Which belief came closest to the NTSB's first code; null without a verdict or a trail. */
export function closestLine(c: CaseFile): string | null {
    const ntsbFirst = c.verdict?.occurrence[0];
    if (ntsbFirst === undefined || c.trail === null) return null;
    const event = `“${eventOf(ntsbFirst.label)}”`;
    const abstained = isAbstained(c);
    for (const step of trailSteps(c)) {
        // An abstention is not an answer, so it is never credited as closest.
        if (step.kind !== "belief" || (abstained && step.belief.kind === "answer")) continue;
        if (step.belief.first.code === ntsbFirst.code) {
            return `Closest to the NTSB: ${step.name.toLowerCase()}, the first belief to put ${event} first.`;
        }
    }
    return `No belief put the NTSB's first code, ${event}, first.`;
}

/** Every label the case itself holds for a code, so a lookup can name codes in words. */
function labelsOf(c: CaseFile): Map<string, string> {
    const codes: Code[] = [
        ...(c.answer?.occurrence ?? []),
        ...(c.answer?.findings ?? []),
        ...(c.verdict?.occurrence ?? []),
        ...(c.verdict?.findings ?? []),
        ...(c.trail?.beliefs.map((b) => b.first) ?? []),
    ];
    return new Map(codes.map((code) => [code.code, code.label]));
}

function text(value: unknown): string | null {
    return typeof value === "string" && value.trim() !== "" ? value : null;
}

function codeList(value: unknown): string[] {
    if (typeof value === "string") return [value];
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

const KIND_WORDS: Record<string, [string, string]> = {
    occurrence: ["the occurrence code", "the occurrence codes"],
    finding: ["the finding", "the findings"],
    finding_category: ["the finding category", "the finding categories"],
};

/** A coding lookup in plain words (§12 item 4): what it asked about, why, and the agent's note. */
export function lookupDetails(
    lookup: Lookup,
    c: CaseFile,
): { asked: string | null; why: string | null; note: string | null } {
    const labels = labelsOf(c);
    const args = lookup.arguments;
    const named = (codes: string[]): string | null => {
        if (codes.length === 0) return null;
        const words = codes.map((code) => labels.get(code));
        if (words.every((w) => w === undefined)) {
            return codes.length === 1 ? `code ${codes[0] ?? ""}` : `codes ${codes.join(", ")}`;
        }
        return codes.map((code, i) => words[i] ?? `code ${code}`).join("; ");
    };
    const parts: string[] = [];
    const codes = named(codeList(args["codes"]));
    const kind = text(args["kind"]);
    if (codes !== null) {
        const words = kind === null ? undefined : KIND_WORDS[kind];
        const n = codeList(args["codes"]).length;
        parts.push(
            words === undefined
                ? `about ${codes}`
                : `about ${n === 1 ? words[0] : words[1]} ${codes}`,
        );
    } else if (kind !== null) {
        parts.push(`about ${KIND_WORDS[kind]?.[1] ?? kind.replaceAll("_", " ")}`);
    }
    const after = named(codeList(args["occurrence"]));
    if (after !== null) parts.push(`after ${after}`);
    const phase = text(args["phase_group"]);
    if (phase !== null) parts.push(`for the phase ${phase}`);
    return {
        asked: parts.length === 0 ? null : parts.join(", "),
        why: text(args["reason"]),
        note: text(args["expected_effect"]),
    };
}

/** What the verdict section shows: null while the NTSB has not published. */
export function verdictView(
    c: CaseFile,
): { first: Code | null; cause: string | null; closest: string | null } | null {
    if (c.verdict === null) return null;
    return {
        first: c.verdict.occurrence[0] ?? null,
        cause: c.verdict.cause,
        closest: closestLine(c),
    };
}
