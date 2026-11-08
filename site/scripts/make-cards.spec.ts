// Draws each preview card (spec §12 item 12; S5 step 6c) at 1200 by 630 into public/cards/, and
// records the words drawn in cards.json, which src/lib/cards.test.ts compares with the site's.
// The site's own fonts are embedded from node_modules, so a card looks like the site.
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { cardWords, CARD_DIR, type Card } from "../src/lib/cards";

const OUT = join(process.cwd(), "public", CARD_DIR);

function font(pkg: string, file: string): string {
    const path = join(process.cwd(), "node_modules/@fontsource", pkg, "files", file);
    return `data:font/woff2;base64,${readFileSync(path).toString("base64")}`;
}

const FONTS = `
@font-face { font-family: Doto; font-weight: 700;
    src: url(${font("doto", "doto-latin-700-normal.woff2")}) format("woff2"); }
@font-face { font-family: Atkinson; font-weight: 400;
    src: url(${font("atkinson-hyperlegible-next", "atkinson-hyperlegible-next-latin-400-normal.woff2")}) format("woff2"); }
@font-face { font-family: Atkinson; font-weight: 700;
    src: url(${font("atkinson-hyperlegible-next", "atkinson-hyperlegible-next-latin-700-normal.woff2")}) format("woff2"); }`;

function escape(s: string): string {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// The board's dark panel (tokens.css), with ELLERY in the dot face as in the top bar. The site
// card's question is long, so it is set in the reading face; a question card's is shorter and
// larger, with its answer beneath (Andy, 2026-11-01).
function html(c: Card): string {
    const site = c.name === "site";
    return `<!doctype html><html><head><meta charset="utf-8"><style>${FONTS}
html, body { margin: 0; width: 1200px; height: 630px; background: #0d1117; }
body { box-sizing: border-box; padding: 64px 80px; display: flex; flex-direction: column;
    border: 2px solid #2a3240; font-family: Atkinson, sans-serif; color: #eef1f5; }
.mark { font-family: Doto, monospace; font-weight: 700; font-size: 64px; letter-spacing: 0.06em;
    color: #f2c94c; line-height: 1; }
.rule { height: 2px; background: #2a3240; margin: 36px 0 40px; }
.q { font-weight: 700; font-size: ${site ? "46px" : "58px"}; line-height: 1.2; margin: 0; }
.line { font-size: ${site ? "30px" : "40px"}; line-height: 1.3; margin: 28px 0 0;
    color: ${site ? "#b8c0cc" : "#eef1f5"}; }
.foot { margin-top: auto; font-size: 24px; color: #b8c0cc; }
</style></head><body>
<div class="mark">ELLERY</div><div class="rule"></div>
<p class="q">${escape(c.question)}</p><p class="line">${escape(c.line)}</p>
<div class="foot">ellery.demo.floyda.dev${site ? "" : " · The path"}</div>
</body></html>`;
}

test("draw every card", async ({ page }) => {
    const cards = cardWords();
    for (const c of cards) {
        await page.setContent(html(c));
        await page.evaluate(() => document.fonts.ready);
        // A card whose words run off its foot is never saved.
        const height = await page.evaluate(() => document.body.scrollHeight);
        expect(height, c.name).toBeLessThanOrEqual(630);
        await page.screenshot({ path: join(OUT, `${c.name}.png`) });
    }
    writeFileSync(join(OUT, "cards.json"), `${JSON.stringify(cards, null, 2)}\n`);
});
