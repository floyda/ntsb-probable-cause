// The Methods page's glossary (spec §9 item 8, §12 item 4): the NTSB terms the other pages show
// in small type, beside their plain labels, and the project's own terms. A test fails when a
// page shows a small-type term this list does not define.

export interface Term {
    term: string;
    means: string;
    /** The small-type words a page shows for this term, where they differ from `term`. */
    seenAs?: readonly string[];
}

export const GLOSSARY: readonly Term[] = [
    {
        term: "Abstain",
        means: "The agent judged the evidence too thin and gave no answer. An abstained case is counted, never left out.",
    },
    {
        term: "Arm",
        means: "One way of producing an answer in an evaluation. Arm A uses the start facts only, arm B is the fixed pipeline, and arm C is the loop.",
    },
    {
        term: "Billed cost",
        means: "What the model provider charged. It is lower than the list price when part of a request was cached.",
    },
    {
        term: "Code tables and past usage",
        means: "The NTSB's lists of occurrence and finding codes with their meanings, and how often each code was used on development cases. The agent chooses from the tables; it cannot write a code of its own.",
        seenAs: ["the code tables and past usage"],
    },
    {
        term: "Development cases",
        means: "Accidents up to 2019. The project tried its ideas on these.",
    },
    {
        term: "Docket",
        means: "The NTSB's public file of evidence for a case: the documents the investigators gathered, such as statements, maintenance records and weather reports.",
        seenAs: ["the docket"],
    },
    {
        term: "Evidence",
        means: "What the agent may read: the recorded facts of a case and its docket documents.",
    },
    {
        term: "Finding",
        means: "An NTSB code for why an accident happened: an aircraft part, a person's action or a condition, with a modifier such as “not attained/maintained”.",
        seenAs: ["NTSB findings"],
    },
    {
        term: "First code",
        means: "The first of the NTSB's occurrence codes for a case: its defining event.",
    },
    {
        term: "Fixed pipeline",
        means: "Arm B: it reads every docket document with readable text, answers, calls every coding tool in a fixed order, then runs the ordering check.",
    },
    {
        term: "Held-out cases",
        means: "Accidents from 2020 to 2023, kept aside and used rarely, to test what was built.",
    },
    {
        term: "heldout-400, dev-400",
        means: "Fixed samples of about 400 held-out and development cases. Every run on a sample uses the same cases, so two runs can be compared case by case.",
    },
    {
        term: "Live cases",
        means: "Cases the NTSB closes now. The agent codes each once, at closure.",
    },
    {
        term: "The loop",
        means: "Arm C, the agent's version 1: it chooses which docket documents to read and which coding tools to call.",
    },
    {
        term: "Occurrence code",
        means: "An NTSB code for one event in an accident, such as a loss of engine power. The NTSB lists them in the order they happened.",
        seenAs: ["NTSB occurrence codes", "NTSB occurrence codes, in order"],
    },
    {
        term: "Ordering check",
        means: "A second model call after the answer. It re-orders the answer's occurrence codes, using how often each is used and the agent's own account.",
    },
    {
        term: "Paired difference",
        means: "Two methods run on the same cases, compared case by case.",
    },
    {
        term: "Phase / event",
        means: "The two parts of an occurrence code's name: the phase of flight, such as Landing, and the event, such as Loss of control on ground.",
        seenAs: ["phase / event"],
    },
    {
        term: "Points",
        means: "The plain difference between two percentages.",
    },
    {
        term: "Probable cause",
        means: "The NTSB's one- or two-sentence statement of why an accident happened, published when it closes the case.",
    },
    {
        term: "Registration",
        means: "A file of rules and predictions committed before a measured run, so that none can be chosen after the result is seen.",
    },
    {
        term: "Synthesis",
        means: "The investigators' factual and analysis write-ups. They are written at the end of an investigation, toward the cause reached, so the agent never reads them.",
    },
    {
        term: "Top-1, top-3",
        means: "Whether the NTSB's first code is the agent's first code (top-1), or among its first three (top-3).",
    },
    {
        term: "Verdict",
        means: "The NTSB's probable cause and its occurrence and finding codes: the answer key, withheld until the agent has answered.",
    },
    {
        term: "95 percent interval",
        means: "The range the rate on all cases like these is likely to lie in. Fewer cases give a wider range.",
    },
];
