import { existsSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Every built page, by its address: dist/methods/index.html -> /methods/.
function pages(root: string, prefix: string): string[] {
    if (!existsSync(root)) return [];
    const found: string[] = [];
    const walk = (dir: string): void => {
        for (const name of readdirSync(dir)) {
            const path = join(dir, name);
            if (statSync(path).isDirectory()) walk(path);
            else if (name.endsWith(".html")) {
                const rel = relative(root, path).split(sep).join("/");
                found.push(prefix + rel.replace(/(^|\/)index\.html$/, "$1"));
            }
        }
    };
    walk(root);
    return found.sort();
}

const addresses = [...pages("dist", "/"), ...pages("holding", "/_holding/")];

test("there is at least one page to check", () => {
    expect(addresses.length).toBeGreaterThan(0);
});

for (const address of addresses) {
    test(`WCAG 2.2 AA: ${address}`, async ({ page }, info) => {
        await page.goto(address);
        const results = await new AxeBuilder({ page })
            .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
            .analyze();
        expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
        if (info.project.name === "phone") {
            // Only the board's own frame may scroll sideways, never the page (plan Review Focus 4).
            const width = await page.evaluate(() => document.documentElement.scrollWidth);
            expect(width).toBeLessThanOrEqual(390);
            const name = address.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "") || "home";
            await page.screenshot({ path: `test-results/phone/${name}.png`, fullPage: true });
        }
    });
}

test.describe("with scripts off (plan Review Focus 5)", () => {
    test.use({ javaScriptEnabled: false });

    test("the first page still shows a case, and a row still opens its page", async ({ page }) => {
        await page.goto("/");
        await expect(page.locator("article#opened")).toBeVisible();
        const first = page.locator("a[data-case]").first();
        const n = await first.getAttribute("data-case");
        await first.click();
        await expect(page).toHaveURL(new RegExp(`/case/${n ?? ""}/$`));
        await expect(page.locator(`article#opened[data-case="${n ?? ""}"]`)).toBeVisible();
    });
});

test.describe("with scripts on: choosing a row (review, 2026-10-13)", () => {
    test("opens the case beneath the board, and an anchor change does not reload", async ({
        page,
    }) => {
        await page.goto("/");
        const second = page.locator("a[data-case]").nth(1);
        const n = (await second.getAttribute("data-case")) ?? "";
        await second.click();
        await expect(page).toHaveURL(new RegExp(`/case/${n}/$`));
        await expect(page.locator(`article#opened[data-case="${n}"]`)).toBeFocused();
        await expect(page.locator("table")).toBeVisible();
        await page.evaluate(() => {
            (window as unknown as { marker: number }).marker = 1;
            window.location.hash = "somewhere";
        });
        await page.goBack();
        const marker = await page.evaluate(() => (window as unknown as { marker?: number }).marker);
        expect(marker).toBe(1);
    });
});

// The ladder's labels are wrapped from an estimate of their width (lib/ladder.ts); this checks the
// rendered text, in the real font, in whichever drawing the screen shows (plan Task 3, Task 5).
test("the ladder's rendered labels stay inside the drawing and never overlap", async ({ page }) => {
    await page.goto("/path/");
    await page.evaluate(() => document.fonts.ready);
    const faults = await page.evaluate(() => {
        const found: string[] = [];
        let checked = 0;
        for (const svg of document.querySelectorAll<SVGSVGElement>("svg.drawing")) {
            if (svg.getBoundingClientRect().width === 0) continue; // the drawing not shown
            checked++;
            const width = svg.viewBox.baseVal.width;
            const boxes = [...svg.querySelectorAll<SVGTextElement>("text")].map((t) => ({
                text: t.textContent,
                box: t.getBBox(),
            }));
            for (const { text, box } of boxes) {
                if (box.x < 0 || box.x + box.width > width) found.push(`outside: ${text}`);
            }
            for (const [i, a] of boxes.entries()) {
                for (const b of boxes.slice(i + 1)) {
                    const apart =
                        a.box.x + a.box.width <= b.box.x ||
                        b.box.x + b.box.width <= a.box.x ||
                        a.box.y + a.box.height <= b.box.y ||
                        b.box.y + b.box.height <= a.box.y;
                    if (!apart) found.push(`overlap: ${a.text} | ${b.text}`);
                }
            }
        }
        // Three ladders on the page (top, question 2, question 3), one drawing shown of each.
        if (checked !== 3) found.push(`checked ${String(checked)} drawings, not 3`);
        return found;
    });
    expect(faults).toEqual([]);
});

// A keyboard user reaches the content first (S5 step 6a, Task 2; WCAG 2.4.1): the skip link is
// the first stop, shows when focused, and moves focus past the top bar into the page.
test("the skip link is the first stop and moves focus to the content", async ({ page }) => {
    await page.goto("/path/");
    await page.keyboard.press("Tab");
    const skip = page.locator("a.skip");
    await expect(skip).toBeFocused();
    await expect(skip).toBeInViewport();
    await page.keyboard.press("Enter");
    await expect(page.locator("main#content")).toBeFocused();
});

// The rail marks the place being read, and a link to a place keeps its heading in view on a
// phone (S5 step 6a, Task 3; plan Review Focus 1).
test("the rail marks the place being read", async ({ page }) => {
    await page.goto("/methods/");
    await page.locator("#history").scrollIntoViewIfNeeded();
    await page.evaluate(() => {
        const h = document.getElementById("history");
        if (h !== null) window.scrollTo(0, h.getBoundingClientRect().top + window.scrollY - 200);
    });
    await expect(page.locator('nav.rail a[data-place="history"]')).toHaveAttribute(
        "aria-current",
        "location",
    );
    await expect(page.locator('nav.rail a[aria-current="location"]')).toHaveCount(1);
});

test("a link to a place leaves its heading below the phone's strip", async ({ page }, info) => {
    test.skip(info.project.name !== "phone", "the strip is the phone's; wide screens use a column");
    await page.goto("/path/#choosing");
    await page.waitForTimeout(300);
    const { strip, heading } = await page.evaluate(() => ({
        strip: document.querySelector("nav.rail")?.getBoundingClientRect().bottom ?? 0,
        heading: document.querySelector("#choosing h2")?.getBoundingClientRect().top ?? -1,
    }));
    expect(heading).toBeGreaterThanOrEqual(strip);
});

test.describe("with scripts off", () => {
    test.use({ javaScriptEnabled: false });
    test("the rail is a complete list of links, with nothing marked", async ({ page }) => {
        await page.goto("/path/");
        await expect(page.locator("nav.rail a")).toHaveCount(9);
        await expect(page.locator("nav.rail a[aria-current]")).toHaveCount(0);
    });
});
