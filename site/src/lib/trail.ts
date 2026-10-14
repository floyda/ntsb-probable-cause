// The trail view's steps and words (S5 spec §6), from the export's `trail` alone. Beliefs are the
// spine; read choices and coding lookups sit between them; cost is the export's own figure.
import type { Belief, CaseFile, DocumentChoice, Lookup, ReadChoice } from "./board-case-types";
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

export function beliefName(kind: Belief["kind"]): string {
    return BELIEF_NAMES[kind];
}

/** The steps in the order they happened: h0, each read choice and its belief, lookups, answer. */
export function trailSteps(c: CaseFile): TrailStep[] {
    const trail = c.trail;
    if (trail === null) return [];
    const byKind = new Map(trail.beliefs.map((b) => [b.kind, b]));
    const steps: TrailStep[] = [];
    const pushBelief = (kind: Belief["kind"]): void => {
        const belief = byKind.get(kind);
        if (belief === undefined) return;
        const first = steps.every((s) => s.kind !== "belief");
        steps.push({
            kind: "belief",
            belief,
            name: beliefName(kind),
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
    for (const step of trailSteps(c)) {
        if (step.kind === "belief" && step.belief.first.code === ntsbFirst.code) {
            return `Closest to the NTSB: ${step.name.toLowerCase()}, the first belief to put ${event} first.`;
        }
    }
    return `No belief put the NTSB's first code, ${event}, first.`;
}
