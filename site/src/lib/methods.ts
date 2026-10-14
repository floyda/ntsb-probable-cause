// The Methods page's structure (S5 spec §9): which entries each group holds, an entry's anchor,
// and the value it shows. Every entry in the numbers file belongs to exactly one group, so a new
// entry cannot reach the site without a Methods row (tested).
import { count, countOf, entry, numbers, pointsOn, usd, withInterval } from "./numbers";

export interface Group {
    /** The anchor; a Path question's group uses that question's Path anchor. */
    id: string;
    title: string;
    /** Key prefixes the group holds, in the order its rows are shown. */
    prefixes: readonly string[];
}

export const GROUPS: readonly Group[] = [
    {
        id: "ladder",
        title: "The ladder",
        // The ladder's own order: no model, the case record only, the fixed pipeline, the loop.
        prefixes: ["ladder.baseline.", "ladder.no_docket.", "ladder.fixed.", "ladder.loop."],
    },
    { id: "docket", title: "3. Does reading the docket help?", prefixes: ["q3."] },
    {
        id: "scanned-pages",
        title: "4. Does reading words in scanned pages help?",
        prefixes: ["q4."],
    },
    { id: "coding", title: "5. Are the misses about evidence or about coding?", prefixes: ["q5."] },
    { id: "consistency", title: "6. How consistent is the answer key itself?", prefixes: ["q6."] },
    {
        id: "choosing",
        title: "7. Does choosing what to read beat reading everything?",
        // The order question 7 tells it in, then its figure's counts, checkpoint by checkpoint.
        prefixes: [
            "q7.loop_vs_fixed",
            "q7.no_docket_loss",
            "q7.read_all",
            "q7.loop_vs_answer",
            "q7.noise_band",
            "q7.path.cases",
            "q7.path.no_belief_after",
            "q7.path.before",
            "q7.path.reading.",
            "q7.path.after",
            "q7.path.coding.",
            "q7.path.answer",
            "q7.",
        ],
    },
    { id: "history", title: "History", prefixes: ["history."] },
    { id: "limits", title: "Limits", prefixes: ["limits."] },
];

/** The group holding `key`; throws when none does. */
export function groupOf(key: string): Group {
    const group = GROUPS.find((g) => g.prefixes.some((p) => key.startsWith(p)));
    if (group === undefined) throw new Error(`methods: no group holds ${key}`);
    return group;
}

/** The keys one group holds, in its prefixes' order, then the numbers file's. */
export function keysOf(id: string): string[] {
    const group = GROUPS.find((g) => g.id === id);
    if (group === undefined) throw new Error(`methods: no group ${id}`);
    const rank = (key: string): number => group.prefixes.findIndex((p) => key.startsWith(p));
    return Object.keys(numbers().entries)
        .filter((k) => groupOf(k).id === id)
        .sort((a, b) => rank(a) - rank(b));
}

/** The Methods page's own sections and the questions with no group (methods.astro). */
export const SECTIONS: readonly string[] = [
    "reading",
    "board",
    "grades",
    "questions",
    "answer-key",
    "case-record",
    "newly-closed",
    "predictions",
    "withheld",
    "glossary",
];

/** The link to a group or a section on the Methods page; throws for one that does not exist. */
export function methodsLink(id: string): string {
    if (!GROUPS.some((g) => g.id === id) && !SECTIONS.includes(id)) {
        throw new Error(`methods: no group or section ${id}`);
    }
    return `/methods/#${id}`;
}

/** The link to one entry's row on the Methods page (an unknown key fails, as `entry` does). */
export function entryLink(key: string): string {
    entry(key);
    return `/methods/#${anchorFor(key)}`;
}

/** An entry's anchor: "ladder.loop.top1" -> "n-ladder-loop-top1". */
export function anchorFor(key: string): string {
    return `n-${key.replaceAll(".", "-")}`;
}

/** An entry's value as the other pages show it, chosen by its unit. */
export function shown(key: string): string {
    const e = entry(key);
    switch (e.unit) {
        case "percent":
            return withInterval(key);
        case "points":
            return pointsOn(key);
        case "usd":
            return usd(key);
        case "count":
            return e.n === null ? count(key) : countOf(key);
    }
}
