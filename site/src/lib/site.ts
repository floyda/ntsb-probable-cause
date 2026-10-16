// The site's own navigation (spec §21 note, 2026-10-16): the top bar's pages and the footer's
// links. Every page draws them from here through the layout, so none can leave them out.

/** The top bar's pages, after ELLERY (the first page). Open cases joins in step 6c. */
export const PAGES = [
    { id: "path", label: "The path", href: "/path/" },
    { id: "methods", label: "Methods", href: "/methods/" },
] as const;

/** A page the top bar can mark as current; case and trail pages are none of these. */
export type PageId = "home" | (typeof PAGES)[number]["id"];

/** "Built by Andy Floyd" links here (Andy, 2026-10-16). */
export const AUTHOR_URL = "https://floyda.dev";
