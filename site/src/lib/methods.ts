// The Methods page's structure (S5 spec §9): which entries each group holds, an entry's anchor,
// and the value it shows. Every entry in the numbers file belongs to exactly one group, so a new
// entry cannot reach the site without a Methods row (tested).
import { count, countOf, entry, numbers, pointsOn, usd, withInterval } from "./numbers";

export interface Group {
    /** The anchor; a Path question's group uses that question's Path anchor. */
    id: string;
    title: string;
    /** Key prefixes the group holds. */
    prefixes: readonly string[];
}

export const GROUPS: readonly Group[] = [
    { id: "ladder", title: "The ladder", prefixes: ["ladder."] },
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
        prefixes: ["q7."],
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

/** The keys one group holds, in the numbers file's order. */
export function keysOf(id: string): string[] {
    return Object.keys(numbers().entries).filter((k) => groupOf(k).id === id);
}

/** The link to a group on the Methods page; throws for a group that does not exist. */
export function methodsLink(id: string): string {
    if (!GROUPS.some((g) => g.id === id)) throw new Error(`methods: no group ${id}`);
    return `/methods/#${id}`;
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
