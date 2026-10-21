// The first page's arrival (spec §3.1; S5 step 6b). The page is complete before any script runs,
// so a link preview, a search engine or a printed copy sees all of it. Only once the reader
// scrolls are the stops still below the screen marked to wait; each arrives, once, as it reaches
// the screen. Under reduced motion nothing is marked. The script sets attributes and one CSS
// variable per item; styles/arrive.css does all the motion. It never moves the page.
const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");

if (!reduce.matches) {
    const stops = [...document.querySelectorAll<HTMLElement>("main > section")];

    // Each item's place among its siblings, for the one-after-another delays (capped at 10).
    for (const stop of stops) {
        for (const item of stop.querySelectorAll<HTMLElement | SVGElement>(
            ".items > li, .questions > li, .ladder g.step",
        )) {
            const siblings = item.parentElement === null ? [] : [...item.parentElement.children];
            const i = Math.min(siblings.indexOf(item), 10);
            item.style.setProperty("--i", String(i));
            // A ladder step's bar and whiskers read the step's place.
            for (const part of item.querySelectorAll<SVGElement>("rect.bar, .whisker")) {
                part.style.setProperty("--i", String(i));
            }
        }
    }

    const onArrive = (entries: IntersectionObserverEntry[]): void => {
        // Units arriving together are staggered in page order (used by the board's rows).
        const now = entries
            .filter((e) => e.isIntersecting)
            .map((e) => e.target as HTMLElement)
            .sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
        for (const [j, unit] of now.entries()) {
            unit.style.setProperty("--j", String(Math.min(j, 10)));
            unit.setAttribute("data-arrive", "arrived");
            arrive.unobserve(unit);
            rows.unobserve(unit);
        }
    };
    // A stop or figure arrives once it is well onto the screen.
    const arrive = new IntersectionObserver(onArrive, { rootMargin: "0px 0px -15% 0px" });
    // A board row arrives as soon as any of it shows, in the page or in the board's own window
    // (the observer sees the window's clipping), so no row in view is left blank.
    const rows = new IntersectionObserver(onArrive, { rootMargin: "0px" });

    // What arrives: each stop, and each figure within one, so a figure below the screen waits
    // even when its stop's heading is already in view.
    const units = [
        ...stops,
        ...document.querySelectorAll<HTMLElement>(
            "main > section :is(.board tbody tr, figure.ladder, ol.items, ol.questions)",
        ),
    ];
    const first = (): void => {
        window.removeEventListener("scroll", first);
        if (reduce.matches) return;
        for (const unit of units) {
            const row = unit.matches(".board tbody tr");
            const frame = row ? unit.closest(".board-frame") : null;
            const bottom = Math.min(
                window.innerHeight,
                frame?.getBoundingClientRect().bottom ?? window.innerHeight,
            );
            if (unit.getBoundingClientRect().top >= bottom) {
                unit.setAttribute("data-arrive", "wait");
                (row ? rows : arrive).observe(unit);
            }
        }
    };
    window.addEventListener("scroll", first, { passive: true });
}
