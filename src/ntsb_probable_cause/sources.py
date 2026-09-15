"""Facts about external services, each with the source it came from (decision 0012)."""

from dataclasses import dataclass

# ../ntsb-spike/public.yaml, operation get-cases-by-date-range-v2; confirmed by saved responses.
NTSB_BASE_URL = "https://api.ntsb.gov/public"
CASES_BY_DATE_RANGE_V2 = "api/Common/v2/GetCasesByDateRange/"
MODE_AVIATION = "aviation"
MAX_PAGE_SIZE = 1000
API_KEY_HEADER = "Ocp-Apim-Subscription-Key"

# docketPage is null on every record (spike session 5); the URL is built from mKey.
_DOCKET_URL = "https://data.ntsb.gov/Docket?ProjectID={mkey}"


def docket_url(mkey: int) -> str:
    """Return the public docket URL for a case's internal key."""
    return _DOCKET_URL.format(mkey=mkey)


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

_PRICES = {p.model_id: p for p in (SONNET_5, SONNET_5_BATCH, LUNA, LUNA_BATCH, HAIKU_45_BATCH)}


def price_of(model_id: str) -> ModelPrice:
    """The price entry for a model id; KeyError if the project has not recorded one."""
    return _PRICES[model_id]


# https://openrouter.ai/docs (decision 0009) and https://openrouter.ai/docs/batch-quickstart,
# read 2026-09-15. Confirmed by the saved responses under tests/fixtures/openrouter/.
OPENROUTER_BASE_URL = "https://openrouter.ai"
CHAT_COMPLETIONS = "/api/v1/chat/completions"
BATCHES = "/api/beta/batches"
