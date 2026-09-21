"""Facts about external services, each with the source it came from (decision 0012)."""

from dataclasses import dataclass

# ../ntsb-spike/public.yaml, operation get-cases-by-date-range-v2; confirmed by saved responses.
NTSB_BASE_URL = "https://api.ntsb.gov/public"
CASES_BY_DATE_RANGE_V2 = "api/Common/v2/GetCasesByDateRange/"
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
# vendor's words, not shown to be unsubsidised; a real usage block from the probe replaces
# the estimate (decisions 0030, 0060). ``jev-latest`` is the SDK's default model name.
JEV = ModelPrice("jev-latest", 0.042, 0.0, "TypeSafe launch post, 2026-09-16, self-reported")

_PRICES = {
    p.model_id: p
    for p in (
        JEV,
        SONNET_5,
        SONNET_5_BATCH,
        LUNA,
        LUNA_BATCH,
        HAIKU_45_BATCH,
        HAIKU_45,
        GEMINI_31_FLASH_LITE,
        GEMINI_31_FLASH_LITE_BATCH,
        GLM_53_FLASH,
        GLM_53_FLASH_BATCH,
    )
}


def price_of(model_id: str) -> ModelPrice:
    """The price entry for a model id; KeyError if the project has not recorded one."""
    return _PRICES[model_id]


# https://openrouter.ai/docs (decision 0009) and https://openrouter.ai/docs/batch-quickstart,
# read 2026-09-15. Confirmed by the saved responses under tests/fixtures/openrouter/.
OPENROUTER_BASE_URL = "https://openrouter.ai"
CHAT_COMPLETIONS = "/api/v1/chat/completions"
BATCHES = "/api/beta/batches"

# https://api.typesafe.ai/openapi.json, as generated into ``typesafe-sdk`` 0.6.0 on PyPI (read
# 2026-09-17, decision 0060): one POST for every question, one GET for the model list. The
# saved responses under tests/fixtures/typesafe/ (probe of 2026-09-17) confirm the shape.
TYPESAFE_SYSTEM_ONE = "/v1/systemone"
TYPESAFE_MODELS = "/v1/models"
# The vendor's documented ceiling on labels in one Choice question.
TYPESAFE_MAX_CHOICE_LABELS = 255
