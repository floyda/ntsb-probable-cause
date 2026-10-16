import { describe, expect, it } from "vitest";
import { AUTHOR_URL, checkPlaces, PAGES } from "./site";

describe("the top bar's pages (S5 step 6a, Task 2)", () => {
    it("names each page once, by an address ending in a slash", () => {
        const hrefs = PAGES.map((p) => p.href);
        expect(new Set(hrefs).size).toBe(hrefs.length);
        for (const href of hrefs) expect(href).toMatch(/^\/[a-z-]+\/$/);
    });
    it("does not link to a page not yet built", () => {
        expect(PAGES.map((p) => p.href)).not.toContain("/open/");
    });
    it("links the author's line to an https address", () => {
        expect(AUTHOR_URL).toMatch(/^https:\/\//);
    });
});

describe("a rail's places (S5 step 6a, Task 3)", () => {
    it("accepts a list of distinct, labelled places", () => {
        const places = [
            { id: "a", label: "First" },
            { id: "b", label: "Second" },
        ];
        expect(checkPlaces(places)).toBe(places);
    });
    it("refuses no places, an empty label, or an id named twice", () => {
        expect(() => checkPlaces([])).toThrow(/no places/);
        expect(() => checkPlaces([{ id: "a", label: " " }])).toThrow(/no label/);
        expect(() =>
            checkPlaces([
                { id: "a", label: "One" },
                { id: "a", label: "Two" },
            ]),
        ).toThrow(/twice/);
    });
});
