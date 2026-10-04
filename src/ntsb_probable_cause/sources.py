"""Facts about external services, each with the source it came from (decision 0012)."""

from dataclasses import dataclass
from typing import Final, Literal

# ../ntsb-spike/public.yaml, operation get-cases-by-date-range-v2; confirmed by saved responses.
NTSB_BASE_URL = "https://api.ntsb.gov/public"
CASES_BY_DATE_RANGE_V2 = "api/Common/v2/GetCasesByDateRange/"
# ../ntsb-spike/public.yaml, operation get-cases-by-modified-date-range.
CASES_BY_MODIFIED_DATE_RANGE_V1 = "api/Common/v1/GetCasesByModifiedDateRange/"
MODE_AVIATION = "aviation"
MAX_PAGE_SIZE = 1000
API_KEY_HEADER = "Ocp-Apim-Subscription-Key"

# The docket is not in the Enterprise API (../ntsb-spike/public.yaml has no docket path). It is
# a web page for people, scraped as the spike's probes did (../ntsb-spike/scripts/
# docket_shape_probe.py). The saved real page under tests/fixtures/docket/ is the source for
# its structure (rule 2, decision 0037).
DOCKET_BASE_URL = "https://data.ntsb.gov"
DOCKET_USER_AGENT = "ntsb-probable-cause (https://github.com/floyda/ntsb-probable-cause)"

# docketPage is null on every record (spike session 5); the URL is built from mKey.
_DOCKET_URL = DOCKET_BASE_URL + "/Docket?ProjectID={mkey}"


def docket_url(mkey: int) -> str:
    """Return the public docket URL for a case's internal key."""
    return _DOCKET_URL.format(mkey=mkey)


def docket_document_url(href: str) -> str:
    """The absolute URL of a document link, as the listing page gives it (``/Docket/Document``)."""
    return f"{DOCKET_BASE_URL}{href}"


@dataclass(frozen=True)
class ModelPrice:
    """Price per million tokens, in US dollars."""

    model_id: str
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    source: str


# https://openrouter.ai/api/v1/models, checked 2026-09-12 (decision 0009).
SONNET_5 = ModelPrice("anthropic/claude-sonnet-5", 2.0, 10.0, "OpenRouter models API, 2026-09-12")
SONNET_5_BATCH = ModelPrice(
    "anthropic/claude-sonnet-5:batch", 1.0, 5.0, "OpenRouter models API, 2026-09-12"
)

# https://openrouter.ai/api/v1/models, checked 2026-09-15 (decision 0031). Luna and Luna-pro
# are listed at the same price; the probe picks one and the plan records why.
LUNA = ModelPrice("openai/gpt-5.6-luna", 0.20, 1.20, "OpenRouter models API, 2026-09-15")
LUNA_BATCH = ModelPrice(
    "openai/gpt-5.6-luna:batch", 0.10, 0.60, "OpenRouter models API, 2026-09-15"
)

# https://openrouter.ai/api/v1/models, checked 2026-09-22 (decision 0073). The same line as
# GPT-5.6 Luna at about half the price; the default only moves to it after S2.4's gate.
LUNA_6 = ModelPrice("openai/gpt-6-luna", 0.10, 0.50, "OpenRouter models API, 2026-09-22")
LUNA_6_BATCH = ModelPrice(
    "openai/gpt-6-luna:batch", 0.05, 0.25, "OpenRouter models API, 2026-09-22"
)
# The provider's own refusal of an over-long request on 2026-10-04: "This endpoint's maximum
# context length is 1050000 tokens" (held-out arm B's answer batch, S3.2 Task 15a). One request
# over it fails its whole batch.
LUNA_6_CONTEXT_TOKENS: Final = 1_050_000
# The prompt-size ceiling in estimated tokens (characters / 4, the runner's and the loop's own
# estimate), decision 152. It bounds arm B's stage-1 answer prompt (payload and system text) and
# every loop and post-pass call. Arm B's later turns are not checked: the stage-2 refinement may
# exceed it by the stage-1 reply (at most the 8,000-token reply budget) plus the refinement
# message, less the stage-1 system text it replaces, and a retry by its rejection message. The
# margin under the context window absorbs that (tests/test_runner.py pins the overshoot). The
# estimate undercounts document text, which tokenizes at about two characters a token: over
# both dev-400 noise-floor trails, real prompt tokens were at most 2.4303 times the estimate
# (docs/results/s32-context-ratio-dev.txt). So the ceiling is
# floor(0.8 * 1,050,000 / 2.430343) = 345,630, rounded down to a thousand: a call at the ceiling
# is at most about 838,000 real tokens, 80% of the window.
PROMPT_TOKEN_CEILING: Final[int] = 345_000
HAIKU_45_BATCH = ModelPrice(
    "anthropic/claude-haiku-4.5:batch", 0.50, 2.50, "OpenRouter models API, 2026-09-15"
)
# The judge calls the chat-completions endpoint directly, which the provider does not serve
# for a ``:batch`` model id, so the judge needs the standard price too (checked 2026-09-16).
HAIKU_45 = ModelPrice("anthropic/claude-haiku-4.5", 1.00, 5.00, "OpenRouter models API, 2026-09-16")

# https://openrouter.ai/api/v1/models, checked 2026-09-16. S1's cross-model sanity check
# (0031 point 3, amended by 0034): a different model family, to tell "the task is hard" from
# "Luna is weak". Sonnet 5 batch prices a dev-400 run at $6.26 against this model's $0.87.
# Gemini 3.5 and newer reject our stage-2 shape (a request ending on the model's own turn);
# 3.1-flash-lite is the newest Gemini that accepts it (probed 2026-09-16, see 0034).
GEMINI_31_FLASH_LITE = ModelPrice(
    "google/gemini-3.1-flash-lite", 0.25, 1.50, "OpenRouter models API, 2026-09-16"
)
GEMINI_31_FLASH_LITE_BATCH = ModelPrice(
    "google/gemini-3.1-flash-lite:batch", 0.12, 0.75, "OpenRouter models API, 2026-09-16"
)

# https://openrouter.ai/api/v1/models, checked 2026-09-16. A second, independent family for
# the cross-model check (0034): three models agreeing costs $0.39 more than two. Probed on the
# same day for our stage-2 shape; the reasoning-tier models of every family (GLM-5, Kimi K2.5,
# DeepSeek Pro) spend the whole output budget thinking and return empty content, so only the
# non-reasoning "flash" tiers are usable here.
GLM_53_FLASH = ModelPrice("z-ai/glm-5.3-flash", 0.09, 0.30, "OpenRouter models API, 2026-09-16")
GLM_53_FLASH_BATCH = ModelPrice(
    "z-ai/glm-5.3-flash:batch", 0.07, 0.25, "OpenRouter models API, 2026-09-16"
)

# TypeSafe AI's launch post (typesafe.ai/blog/introducing-system-one-models-and-jev), read
# 2026-09-16: $0.042 per million input tokens, output unmetered. Self-reported and, in the
# vendor's words, not shown to be unsubsidised (decisions 0030, 0097). ``jev-latest`` is the
# SDK's default model name; every reply records the version it resolved to.
JEV = ModelPrice("jev-latest", 0.042, 0.0, "TypeSafe launch post, 2026-09-16, self-reported")

# https://openrouter.ai/api/v1/models, read 2026-09-24: the transcriber candidates of S2.6
# spec §7.2 that S1 had not priced. Standard prices only: an image cannot go through the batch
# service (https://openrouter.ai/docs/batch-quickstart, read 2026-09-24), and Qwen has no
# batch variant at all.
GEMINI_36_FLASH = ModelPrice(
    "google/gemini-3.6-flash", 0.75, 3.75, "OpenRouter models API, 2026-09-24"
)
QWEN_35_122B = ModelPrice("qwen/qwen3.5-122b-a10b", 0.26, 2.08, "OpenRouter models API, 2026-09-24")

# https://openrouter.ai/api/v1/models, read 2026-09-27 and saved as
# <data_dir>/s27/openrouter-models-2026-09-27.json (S2.7 track 2, Task 5): the transcriber
# shortlist of decision 0100 item 1, prices as listed per million tokens.
S27_LING_30_FLASH_VL = ModelPrice(
    "inclusionai/ling-3.0-flash-vl", 0.021, 0.0616, "OpenRouter models API, 2026-09-27"
)
S27_QWEN_37_FLASH = ModelPrice(
    "qwen/qwen3.7-flash", 0.03, 0.13, "OpenRouter models API, 2026-09-27"
)
S27_DEEPSEEK_V41_FLASH = ModelPrice(
    "deepseek/deepseek-v4.1-flash", 0.035, 0.29, "OpenRouter models API, 2026-09-27"
)
# z-ai/glm-5.3-flash is already priced above as GLM_53_FLASH, read 2026-09-16 at
# $0.09/$0.30. The 2026-09-27 listing prices it lower, at $0.045/$0.14; this entry is the
# current price and is listed after GLM_53_FLASH in _PRICES below so ``price_of`` returns it
# (last entry wins on a shared key) -- flagged in the Task 6 report for Andy, not decided here.
S27_GLM_53_FLASH = ModelPrice(
    "z-ai/glm-5.3-flash", 0.045, 0.14, "OpenRouter models API, 2026-09-27"
)
S27_TERNARY_BONSAI_2_27B = ModelPrice(
    "prism-ml/ternary-bonsai-2-27b", 0.075, 0.5, "OpenRouter models API, 2026-09-27"
)
S27_MUSE_SPARK_12_CONTRIBUTOR = ModelPrice(
    "meta/muse-spark-1.2-contributor", 0.1, 0.2, "OpenRouter models API, 2026-09-27"
)
S27_MUSE_SPARK_13_CONTRIBUTOR = ModelPrice(
    "meta/muse-spark-1.3-contributor", 0.1, 0.2, "OpenRouter models API, 2026-09-27"
)
S27_LUNA_6_PRO = ModelPrice("openai/gpt-6-luna-pro", 0.1, 0.5, "OpenRouter models API, 2026-09-27")
S27_MIMO_V26_FLASH = ModelPrice(
    "xiaomi/mimo-v2.6-flash", 0.14, 0.28, "OpenRouter models API, 2026-09-27"
)
S27_QWEN_38_FLASH = ModelPrice(
    "qwen/qwen3.8-flash", 0.15, 0.47, "OpenRouter models API, 2026-09-27"
)
S27_QWEN_38_OMNI_FLASH = ModelPrice(
    "qwen/qwen3.8-omni-flash", 0.15, 0.47, "OpenRouter models API, 2026-09-27"
)
# openai/gpt-5.6-luna is already priced above as LUNA, read 2026-09-15 at the same
# $0.2/$1.2 the 2026-09-27 listing gives -- no new entry needed; ``price_of`` already
# returns a matching price.
S27_LUNA_56_PRO = ModelPrice(
    "openai/gpt-5.6-luna-pro", 0.2, 1.2, "OpenRouter models API, 2026-09-27"
)
S27_DEEPSEEK_V4_FLASH_VISION_EXP = ModelPrice(
    "deepseek/deepseek-v4-flash-vision-exp", 0.2156, 0.6468, "OpenRouter models API, 2026-09-27"
)

_PRICES = {
    p.model_id: p
    for p in (
        SONNET_5,
        SONNET_5_BATCH,
        LUNA,
        LUNA_BATCH,
        LUNA_6,
        LUNA_6_BATCH,
        HAIKU_45_BATCH,
        HAIKU_45,
        GEMINI_31_FLASH_LITE,
        GEMINI_31_FLASH_LITE_BATCH,
        GLM_53_FLASH,
        GLM_53_FLASH_BATCH,
        JEV,
        GEMINI_36_FLASH,
        QWEN_35_122B,
        S27_LING_30_FLASH_VL,
        S27_QWEN_37_FLASH,
        S27_DEEPSEEK_V41_FLASH,
        S27_GLM_53_FLASH,
        S27_TERNARY_BONSAI_2_27B,
        S27_MUSE_SPARK_12_CONTRIBUTOR,
        S27_MUSE_SPARK_13_CONTRIBUTOR,
        S27_LUNA_6_PRO,
        S27_MIMO_V26_FLASH,
        S27_QWEN_38_FLASH,
        S27_QWEN_38_OMNI_FLASH,
        S27_LUNA_56_PRO,
        S27_DEEPSEEK_V4_FLASH_VISION_EXP,
    )
}


def price_of(model_id: str) -> ModelPrice:
    """The price entry for a model id; KeyError if the project has not recorded one."""
    return _PRICES[model_id]


# The reasoning levels OpenRouter's model list gives (``reasoning.supported_efforts``): both
# Luna models, read 2026-09-23; ``minimal`` added for the Gemini transcriber candidates, read
# 2026-09-24.
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]

# S2.6 spec §7.2: each transcriber candidate at its lowest reasoning level, recorded (the
# benchmark found more reasoning made Flash Lite *worse*). Read from the models list on
# 2026-09-24. Gemini 3.6 Flash cannot switch reasoning off (``mandatory``); Qwen lists no
# levels, so ``none`` is confirmed by S2.6 Task 13's one-page probe before it is used.
LOWEST_REASONING: dict[str, ReasoningEffort] = {
    "google/gemini-3.1-flash-lite": "minimal",
    "google/gemini-3.6-flash": "minimal",
    "openai/gpt-6-luna": "none",
    "qwen/qwen3.5-122b-a10b": "none",
    # docs/results/s27-transcriber-shortlist.txt, read 2026-09-27 (S2.7 track 2, Task 5/6):
    # each shortlisted model's lowest reasoning level, walkthrough W1's rule.
    "inclusionai/ling-3.0-flash-vl": "none",
    "qwen/qwen3.7-flash": "none",
    "deepseek/deepseek-v4.1-flash": "low",
    "z-ai/glm-5.3-flash": "low",
    "prism-ml/ternary-bonsai-2-27b": "medium",
    "meta/muse-spark-1.2-contributor": "minimal",
    "meta/muse-spark-1.3-contributor": "minimal",
    "openai/gpt-6-luna-pro": "none",
    "xiaomi/mimo-v2.6-flash": "none",
    "qwen/qwen3.8-flash": "none",
    "qwen/qwen3.8-omni-flash": "none",
    "openai/gpt-5.6-luna": "none",
    "openai/gpt-5.6-luna-pro": "none",
    "deepseek/deepseek-v4-flash-vision-exp": "low",
}

# The agent's default model and reasoning level, each named once (decision 0073). The level is
# stated on every agent request rather than left to the provider, whose default could change
# with nothing in a run's record to show it (S2.4 spec §4.1).
DEFAULT_MODEL = "openai/gpt-6-luna"
DEFAULT_REASONING_EFFORT: ReasoningEffort = "medium"


# https://openrouter.ai/docs (decision 0009) and https://openrouter.ai/docs/batch-quickstart,
# read 2026-09-15. Confirmed by the saved responses under tests/fixtures/openrouter/.
OPENROUTER_BASE_URL = "https://openrouter.ai"
CHAT_COMPLETIONS = "/api/v1/chat/completions"
BATCHES = "/api/beta/batches"

# https://api.typesafe.ai/openapi.json, as generated into ``typesafe-sdk`` 0.6.0 on PyPI (read
# 2026-09-17). The saved responses under tests/fixtures/typesafe/ confirm the shape (0097).
TYPESAFE_SYSTEM_ONE = "/v1/systemone"
TYPESAFE_MODELS = "/v1/models"
# The vendor's documented ceiling on labels in one Choice question.
TYPESAFE_MAX_CHOICE_LABELS = 255
