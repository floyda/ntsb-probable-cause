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

/** Lines that read wrongly away from the first page, reworded for a card alone. */
const AWAY: Record<string, string> = {
    // "The board above" has nothing above it on a card.
    "newly-closed": "The live board answers this in public.",
};

function card(name: string, question: string, line: string): Card {
    return { name, question, line, alt: `Ellery. ${question} ${line}` };
}

/** The site card, then one card per Path question, in the Path's order. */
export function cardWords(): Card[] {
    return [
        card("site", SITE_QUESTION, SITE_LINE),
        ...ROUTE_QUESTIONS.map((q) =>
            card(`q-${q.anchor}`, q.question, AWAY[q.anchor] ?? q.answer),
        ),
    ];
}

/** A card by name; the site card when none is given. */
export function cardFor(name = "site"): Card {
    const found = cardWords().find((c) => c.name === name);
    if (found === undefined) throw new Error(`cards: no card named ${name}`);
    return found;
}
