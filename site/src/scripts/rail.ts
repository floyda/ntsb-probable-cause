// Marks the place being read in the page's rail (spec §21 note, 2026-10-16). Without this script
// the rail is a plain list of links. It never moves the page: on a phone it scrolls only the
// strip, to keep the marked tab in view.
const rail = document.querySelector<HTMLElement>("nav.rail");

if (rail !== null) {
    const links = [...rail.querySelectorAll<HTMLAnchorElement>("a[data-place]")];
    const root = document.documentElement;

    // The strip's height, so a place reached by a link is not hidden beneath it (tokens.css).
    // Which layout is showing is the media query's, the same as Rail.astro's CSS; the height is
    // measured again whenever the rail changes size (text size, fonts, a narrower screen).
    const wide = window.matchMedia("(min-width: 1000px)");
    const measure = (): void => {
        const height = wide.matches ? 0 : rail.offsetHeight;
        root.style.setProperty("--strip-h", `${String(height)}px`);
    };
    measure();
    wide.addEventListener("change", measure);
    new ResizeObserver(measure).observe(rail);

    const mark = (id: string): void => {
        for (const link of links) {
            const on = link.dataset["place"] === id;
            link.classList.toggle("on", on);
            if (on) {
                link.setAttribute("aria-current", "location");
                const strip = link.closest("ol");
                if (strip !== null && strip.scrollWidth > strip.clientWidth) {
                    strip.scrollTo({
                        left: link.offsetLeft - strip.clientWidth / 2 + link.offsetWidth / 2,
                    });
                }
            } else link.removeAttribute("aria-current");
        }
    };

    const watch = new IntersectionObserver(
        (entries) => {
            for (const entry of entries) {
                const id = entry.target.getAttribute("data-place-of");
                if (entry.isIntersecting && id !== null) mark(id);
            }
        },
        { rootMargin: "-35% 0px -60% 0px" },
    );
    for (const link of links) {
        const id = link.dataset["place"] ?? "";
        const target = document.getElementById(id);
        // A place named by its heading is watched through the section that heading opens.
        if (target === null) continue;
        // A section already watched for another place keeps it; this place's own element is
        // watched instead, so no place is left unmarked (review, 2026-10-19).
        const section = target.closest("section");
        const area = section !== null && !section.hasAttribute("data-place-of") ? section : target;
        area.setAttribute("data-place-of", id);
        watch.observe(area);
    }
}
