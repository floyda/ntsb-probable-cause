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
