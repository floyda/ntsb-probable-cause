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
        // The board's own table: the first page also holds the ladder's hidden one (step 6b).
        await expect(page.locator(".board-frame table")).toBeVisible();
        // Stop 4's strip follows the chosen case (step 6b): its trail, or a line saying none.
        const strip = page.locator("#route-strip");
        await expect(strip).toHaveCount(1);
        const toTrail = strip.locator(`a[href="/case/${n}/trail/"]`);
        if ((await toTrail.count()) === 0) await expect(strip).toHaveText(/no trail to show/);
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

// Every place a rail names, reached by a link, shows its sign below the phone's strip, or on
// screen on a wide one (S5 step 6a, Task 3; plan Review Focus 1; review, 2026-10-19: one padded
// question could pass with no scroll margin at all, so every place is checked).
for (const address of ["/", "/path/", "/methods/"]) {
    test(`every place on ${address} lands clear of the rail`, async ({ page }) => {
        await page.goto(address);
        const ids = await page
            .locator("nav.rail a[data-place]")
            .evaluateAll((links) => links.map((a) => a.getAttribute("data-place") ?? ""));
        expect(ids.length).toBeGreaterThan(5);
        for (const id of ids) {
            await page.goto(`${address}#${id}`);
            await page.waitForTimeout(150);
            const { top, below } = await page.evaluate((place) => {
                const rail = document.querySelector("nav.rail");
                const strip =
                    rail !== null && getComputedStyle(rail).gridColumnStart !== "2"
                        ? rail.getBoundingClientRect().bottom
                        : 0;
                const target = document.getElementById(place);
                const section = target?.closest("section") ?? target;
                const sign = section?.querySelector(".sign") ?? target;
                return { top: sign?.getBoundingClientRect().top ?? -1, below: strip };
            }, id);
            expect(top, id).toBeGreaterThanOrEqual(below);
        }
    });
}

test.describe("with scripts off", () => {
    test.use({ javaScriptEnabled: false });
    test("the rail is a complete list of links, with nothing marked", async ({ page }) => {
        await page.goto("/path/");
        await expect(page.locator("nav.rail a")).toHaveCount(10);
        await expect(page.locator("nav.rail a[aria-current]")).toHaveCount(0);
    });
});

// The first page's arrival motion (spec §3.1; S5 step 6b, Task 3). Its four limits: the page is
// complete before anyone scrolls, reduced motion and no script show everything at once, and each
// arrival ends in under about a second.
test.describe("the first page's arrival", () => {
    const headings = async (page: import("@playwright/test").Page): Promise<number[]> =>
        page
            .locator("main > section h2")
            .evaluateAll((hs) => hs.map((h) => Number(getComputedStyle(h).opacity)));

    test("leaves every stop visible to anything that does not scroll", async ({ page }) => {
        await page.goto("/");
        await page.waitForTimeout(300);
        const seen = await headings(page);
        expect(seen.length).toBeGreaterThanOrEqual(5);
        expect(seen.every((o) => o === 1)).toBe(true);
        await expect(page.locator("[data-arrive]")).toHaveCount(0);
    });

    test("finishes each arrival within about a second", async ({ page }) => {
        await page.goto("/");
        await page.mouse.wheel(0, 200);
        await page.waitForTimeout(100);
        await page.locator("#loop").scrollIntoViewIfNeeded();
        await page.waitForTimeout(1200);
        const state = await page.evaluate(() => {
            const bars = [
                ...document.querySelectorAll<SVGRectElement>("#loop svg.drawing rect.bar"),
            ]
                .filter(
                    (r) =>
                        r.getBoundingClientRect().width > 0 ||
                        r.closest("svg")?.getBoundingClientRect().width,
                )
                .map((r) => getComputedStyle(r).transform);
            const h = document.querySelector("#loop h2");
            return {
                arrive: document.getElementById("loop")?.getAttribute("data-arrive") ?? null,
                opacity: h === null ? -1 : Number(getComputedStyle(h).opacity),
                bars,
            };
        });
        expect(state.arrive).toBe("arrived");
        expect(state.opacity).toBe(1);
        for (const t of state.bars) expect(["none", "matrix(1, 0, 0, 1, 0, 0)"]).toContain(t);
    });
});

test.describe("the first page with reduced motion", () => {
    test.use({ reducedMotion: "reduce" });
    test("shows everything at once and moves nothing", async ({ page }) => {
        await page.goto("/");
        await page.mouse.wheel(0, 400);
        await page.waitForTimeout(150);
        await page.locator("#path").scrollIntoViewIfNeeded();
        await expect(page.locator("[data-arrive]")).toHaveCount(0);
    });
});

test.describe("the first page with scripts off", () => {
    test.use({ javaScriptEnabled: false });
    test("hides nothing", async ({ page }) => {
        await page.goto("/");
        await page.locator("#path").scrollIntoViewIfNeeded();
        await expect(page.locator("[data-arrive]")).toHaveCount(0);
        const opacity = await page
            .locator("#path h2")
            .evaluate((h) => Number(getComputedStyle(h).opacity));
        expect(opacity).toBe(1);
    });
});

// The board is a fixed window onto its rows (Andy, 2026-10-21): older rows scroll inside it, and
// each ticks into place as it comes into the window, so no row in view is left blank.
test("the board is a window whose rows arrive as they scroll into it", async ({ page }, info) => {
    // A phone has no window: its rows sit in the page (Andy, 2026-10-22).
    test.skip(info.project.name === "phone", "no window on a phone");
    await page.goto("/");
    const frame = page.locator(".board-frame");
    const max = await frame.evaluate((f) => getComputedStyle(f).maxHeight);
    expect(max).not.toBe("none");
    await page.mouse.wheel(0, 50);
    await page.waitForTimeout(100);
    await frame.scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
    await frame.evaluate((f) => {
        f.scrollTop = f.scrollHeight;
    });
    await page.waitForTimeout(900);
    const states = await page.evaluate(() => {
        const f = document.querySelector(".board-frame");
        const box = f?.getBoundingClientRect();
        return [...document.querySelectorAll(".board tbody tr")]
            .filter((r) => {
                const b = r.getBoundingClientRect();
                return (
                    box !== undefined &&
                    b.bottom > box.top &&
                    b.top < box.bottom &&
                    b.top < innerHeight
                );
            })
            .map((r) => Number(getComputedStyle(r).opacity));
    });
    expect(states.length).toBeGreaterThan(0);
    expect(states.every((o) => o === 1)).toBe(true);
});

// A frame that forbids changing the address (a sandboxed preview) still opens the chosen case
// beneath the board, instead of leaving the page (Andy, 2026-10-21).
test("a chosen row still opens its case when the address cannot change", async ({ page }) => {
    await page.addInitScript(() => {
        history.pushState = () => {
            throw new DOMException("blocked", "SecurityError");
        };
    });
    await page.goto("/");
    const second = page.locator("a[data-case]").nth(1);
    const n = (await second.getAttribute("data-case")) ?? "";
    await second.click();
    await expect(page.locator(`article#opened[data-case="${n}"]`)).toBeVisible();
    // Still the first page: the board is here, and the address did not move.
    expect(new URL(page.url()).pathname).toBe("/");
    await expect(page.locator(".board-frame table")).toBeVisible();
});

// A tap anywhere on a row opens its case, not only on its date; the stop's sign stays in view
// above it (review, 2026-10-21).
test("a tap on a row's result opens its case, with the stop's sign in view", async ({ page }) => {
    await page.goto("/");
    const row = page.locator(".board tbody tr").nth(1);
    const n = (await row.locator("a[data-case]").getAttribute("data-case")) ?? "";
    await row.locator("td").last().click();
    await expect(page.locator(`article#opened[data-case="${n}"]`)).toBeFocused();
    const sign = page.locator("#case .sign");
    await expect(sign).toBeInViewport();
});

// On a phone each document of a trail is a stacked row, so no part of it is cut off at the
// screen's edge (review, 2026-10-21).
test("a trail's document rows fit the screen", async ({ page }) => {
    await page.goto("/");
    const trail = await page.locator('a[href$="/trail/"]').first().getAttribute("href");
    test.skip(trail === null, "no case with a trail");
    await page.goto(trail ?? "/");
    const clipped = await page
        .locator(".frame")
        .evaluateAll((frames) => frames.filter((f) => f.scrollWidth > f.clientWidth + 1).length);
    expect(clipped).toBe(0);
});

// The board first shows its newest rows, five on a phone with no window of their own; a button
// shows the rest and moves focus to the first row it showed (Andy, 2026-10-22). With scripts
// off every row shows and the button does not.
test("a phone shows the five newest rows, and the button shows the rest", async ({
    page,
}, info) => {
    test.skip(info.project.name !== "phone", "the phone's cap");
    await page.goto("/");
    const rows = page.locator(".board tbody tr");
    const more = page.locator(".board-more");
    test.skip((await more.count()) === 0, "too few rows to cap");
    const total = Number(/\d+/.exec((await more.textContent()) ?? "")?.[0]);
    await expect(rows).toHaveCount(5);
    const frame = page.locator(".board-frame");
    expect(await frame.evaluate((f) => getComputedStyle(f).maxHeight)).toBe("none");
    // Nothing to scroll inside the board: no space is kept for the rows not shown.
    expect(await frame.evaluate((f) => f.scrollHeight - f.clientHeight)).toBeLessThanOrEqual(1);
    await expect(
        page.getByRole("button", { name: `Show all ${String(total)} closed cases` }),
    ).toBeVisible();
    await more.click();
    await expect(rows).toHaveCount(total);
    expect(
        await rows.evaluateAll((all) => all.filter((r) => r.getClientRects().length === 0).length),
    ).toBe(0);
    await expect(rows.nth(5).locator("a[data-case]")).toBeFocused();
    await expect(more).toBeHidden();
});

test.describe("the capped board with scripts off", () => {
    test.use({ javaScriptEnabled: false });
    test("shows every row and no button", async ({ page }) => {
        await page.goto("/");
        const hidden = await page
            .locator(".board tbody tr")
            .evaluateAll((all) => all.filter((r) => r.getClientRects().length === 0).length);
        expect(hidden).toBe(0);
        await expect(page.locator(".board-more")).toBeHidden();
    });
});
