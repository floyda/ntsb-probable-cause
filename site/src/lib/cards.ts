// The preview cards' words (spec §12 item 12; S5 step 6c). A card is the picture a social site
// shows for a shared link. The images are drawn once by scripts/make-cards.spec.ts and
// committed; cards.json beside them records the words drawn, and a test fails when those differ
// from the words here. Nothing here reads the export, so no case can reach a card (§11).
import { ROUTE_QUESTIONS } from "./route";
import { SITE_LINE, SITE_QUESTION } from "./site";

export interface Card {
    /** The image's name: `site`, or `q-<anchor>` for a Path question. */
    name: string;
    question: string;
    line: string;
    /** The image's text alternative: every word drawn on it. */
    alt: string;
}

/** Where the committed cards live, under the site's public files. */
export const CARD_DIR = "cards";

/**
 * Lines that read wrongly away from the first page, reworded for a card alone. Each names the
 * line it replaces, so a change to that answer stops the build until the card is reworded too
 * (review, 2026-11-01).
 */
export const AWAY: Record<string, { from: string; to: string }> = {
    // "The board above" has nothing above it on a card.
    "newly-closed": {
        from: "The board above answers this in public.",
        to: "The live board answers this in public.",
    },
};

function lineFor(anchor: string, answer: string): string {
    const away = AWAY[anchor];
    if (away === undefined) return answer;
    if (away.from !== answer) {
        throw new Error(`cards: question ${anchor}'s answer changed; reword its card`);
    }
    return away.to;
}

function card(name: string, question: string, line: string): Card {
    return { name, question, line, alt: `Ellery. ${question} ${line}` };
}

/** The site card, then one card per Path question, in the Path's order. */
export function cardWords(): Card[] {
    return [
        card("site", SITE_QUESTION, SITE_LINE),
        ...ROUTE_QUESTIONS.map((q) =>
            card(`q-${q.anchor}`, q.question, lineFor(q.anchor, q.answer)),
        ),
    ];
}

/** A short mark of a card's words, added to its image's address so that link-preview services,
 * which keep a picture for weeks, fetch a redrawn card afresh (review, 2026-11-01). */
export function cardVersion(c: Card): string {
    let h = 0x811c9dc5;
    for (const ch of `${c.question}\n${c.line}`) {
        h ^= ch.codePointAt(0) ?? 0;
        h = Math.imul(h, 0x01000193) >>> 0;
    }
    return h.toString(16).padStart(8, "0");
}

/** A card by name; the site card when none is given. */
export function cardFor(name = "site"): Card {
    const found = cardWords().find((c) => c.name === name);
    if (found === undefined) throw new Error(`cards: no card named ${name}`);
    return found;
}
