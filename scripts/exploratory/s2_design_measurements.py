"""Measurements behind the S2 design (docs/specs/2026-09-18-s2-docket-tool-design.md).

Exploratory and one-off, in the pattern of `s1_design_measurements.py`. Nothing here is a
result: S2 produces the results. Every number is arithmetic over two sourced inputs:

- model prices from `ntsb_probable_cause.sources` (OpenRouter models API, dated there);
- docket sizes from the spike's shape probe, `../ntsb-spike/scripts/docket_shape_probe.py`
  (register A13, report §10, 160 development dockets 2015-2019, weighted to the population).
  The figures copied below are the ones the spike report and the agency design §3 print.

No data is read, no network is touched, no case is named.

Usage (from the repository root):
    uv run python scripts/exploratory/s2_design_measurements.py
"""

from __future__ import annotations

from ntsb_probable_cause import sources

# Spike report §10 and agency design §3 (docket_shape_probe.py, weighted quantiles).
MEDIAN_DOCS = 4
P90_DOCS = 11
MEDIAN_TOKENS_BY_STRATUM = {"CA": 5_352, "LA_nonfatal": 4_415, "LA_fatal": 3_250, "FA": 11_752}
SHARE_UNDER_10K = 0.89
LARGEST_SUBMISSION_TOKENS = 23_000  # decision 0038: two of the twelve largest documents
S1_PROMPT_TOKENS = 8_500  # S1 spec §14: prompt without the docket, both turns
S1_OUTPUT_TOKENS = 700  # S1 spec §14
MAX_OUTPUT_TOKENS = 2_000  # ModelSettings.max_output_tokens
CAP_USD = 0.05  # RunSpec.cap_usd
POLITE_SECONDS_PER_REQUEST = 2.0
SAMPLE = 400


def section(title: str) -> None:
    print(f"\n== {title}")


def case_cost(price: sources.ModelPrice, prompt_tokens: float, output_tokens: float) -> float:
    return (prompt_tokens * price.input_usd_per_mtok + output_tokens * price.output_usd_per_mtok) / 1e6


def main() -> None:
    prices = [sources.LUNA_BATCH, sources.LUNA, sources.SONNET_5_BATCH, sources.SONNET_5]

    section("M1: the per-case cap in prompt tokens, after reserving the maximum output")
    print(f"cap ${CAP_USD}; output reserve {MAX_OUTPUT_TOKENS} tokens at the output price")
    for p in prices:
        reserve = MAX_OUTPUT_TOKENS * p.output_usd_per_mtok / 1e6
        room = (CAP_USD - reserve) / p.input_usd_per_mtok * 1e6
        print(f"{p.model_id:34s} output reserve ${reserve:.4f}; prompt room {room:,.0f} tokens")

    section("M2: arm B cost per case at the median docket by stratum (spike medians + S1 prompt)")
    for p in prices:
        parts = []
        for stratum, tokens in MEDIAN_TOKENS_BY_STRATUM.items():
            usd = case_cost(p, S1_PROMPT_TOKENS + tokens, S1_OUTPUT_TOKENS)
            parts.append(f"{stratum} ${usd:.4f}")
        print(f"{p.model_id:34s} " + "; ".join(parts))

    section("M3: does the cap bind? largest spike document plus the S1 prompt, by price")
    for p in prices:
        usd = case_cost(p, S1_PROMPT_TOKENS + LARGEST_SUBMISSION_TOKENS, MAX_OUTPUT_TOKENS)
        print(f"{p.model_id:34s} ${usd:.4f} {'OVER' if usd > CAP_USD else 'under'} the cap")

    section("M4: stage spend at the default price (Luna batch), whole-docket upper bound per case")
    p = sources.LUNA_BATCH
    upper = case_cost(p, S1_PROMPT_TOKENS + 10_000, S1_OUTPUT_TOKENS)
    print(f"a case with a 10,000-token docket (share under: {SHARE_UNDER_10K}): ${upper:.4f}")
    runs = {
        "dev-400 arm B, filtered": SAMPLE,
        "dev-400 arm B, unfiltered (0022: development only)": SAMPLE,
        "dev-400 arm B without submissions (0038 item 4)": SAMPLE,
        "dev-400 re-runs while the header and order settle": 2 * SAMPLE,
        "heldout-400 arm B, once": SAMPLE,
    }
    total = 0.0
    for name, cases in runs.items():
        usd = cases * upper
        total += usd
        print(f"{name:55s} {cases:5d} cases  ${usd:.2f}")
    print(f"{'total, upper bound':55s} {sum(runs.values()):5d} cases  ${total:.2f}")

    section("M5: fetch time at one request every two seconds")
    for name, docs in (("median docket", MEDIAN_DOCS), ("p90 docket", P90_DOCS)):
        requests = SAMPLE * (1 + docs)
        hours = requests * POLITE_SECONDS_PER_REQUEST / 3600
        print(f"{name}: {SAMPLE} listings + {SAMPLE * docs} documents = {requests} requests, {hours:.1f} h")
    open_split = 80 * (1 + P90_DOCS)
    print(f"0040 sample, 80 dockets at p90: {open_split} requests, {open_split * POLITE_SECONDS_PER_REQUEST / 3600:.1f} h")


if __name__ == "__main__":
    main()
