// The opened case's findings as rows (S5 step 6a, Andy, 2026-10-19). A finding's label is built
// from the code tables as "area — … — item - detail" (S4's live/board.py). The rows lead with
// the item and its detail, and set a finding only the NTSB named beside one only the agent
// named when they share an item or an area, so a near miss shows as one. Written from the
// labels alone; no model writes any of it.
import type { Code } from "./board-case-types";

export interface FindingParts {
    /** The levels above the item, broadest first; empty when the label has none. */
    area: string[];
    item: string;
    /** The modifier, such as "Incorrect use/operation"; null when the label has none. */
    detail: string | null;
}

/** "Personnel issues — Task performance — Fuel planning - Incorrect use/operation" in parts. */
export function findingParts(label: string): FindingParts {
    const cut = label.lastIndexOf(" - ");
    const path = cut === -1 ? label : label.slice(0, cut);
    const detail = cut === -1 ? null : label.slice(cut + 3);
    const levels = path.split(" — ");
    const item = levels.pop() ?? path;
    return { area: levels, item, detail };
}

export type Who = "both" | "ntsb" | "agent";

export type FindingRow =
    | { kind: "one"; who: Who; finding: Code }
    /** A near miss: the same item with another detail, or the same area with another item. */
    | { kind: "close"; how: "detail" | "item"; ntsb: Code; agent: Code };

const areaOf = (c: Code): string => findingParts(c.label).area.join(" — ");
const itemOf = (c: Code): string => `${areaOf(c)} — ${findingParts(c.label).item}`;

/** The rows: findings both named, then close pairs (same item first), then the rest. */
export function findingRows(
    both: readonly Code[],
    ntsbOnly: readonly Code[],
    agentOnly: readonly Code[],
): FindingRow[] {
    const ntsbLeft = [...ntsbOnly];
    const agentLeft = [...agentOnly];
    const close: FindingRow[] = [];
    for (const [how, key] of [
        ["detail", itemOf],
        ["item", areaOf],
    ] as const) {
        for (const ntsb of [...ntsbLeft]) {
            // A label with no area cannot be matched by area or item.
            if (findingParts(ntsb.label).area.length === 0) continue;
            const at = agentLeft.findIndex((a) => key(a) === key(ntsb));
            if (at === -1) continue;
            const [agent] = agentLeft.splice(at, 1);
            ntsbLeft.splice(ntsbLeft.indexOf(ntsb), 1);
            if (agent !== undefined) close.push({ kind: "close", how, ntsb, agent });
        }
    }
    return [
        ...both.map((finding): FindingRow => ({ kind: "one", who: "both", finding })),
        ...close,
        ...ntsbLeft.map((finding): FindingRow => ({ kind: "one", who: "ntsb", finding })),
        ...agentLeft.map((finding): FindingRow => ({ kind: "one", who: "agent", finding })),
    ];
}
