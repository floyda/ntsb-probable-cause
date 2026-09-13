import string

from hypothesis import given
from hypothesis import strategies as st

from ntsb_probable_cause.fields import EvidenceRole, EvidenceValue
from ntsb_probable_cause.records.guard import MIN_SENTENCE_CHARS, find_leaks, normalise_text

CAUSE = "The pilot's failure to remove the airplane's tow bar before takeoff."


def leaks(
    evidence: dict[str, EvidenceValue],
    text: dict[str, str | None] | None = None,
    codes: tuple[str, ...] = (),
) -> list[str]:
    found = find_leaks(evidence, text or {"probable_cause": CAUSE}, codes, min_sentence_chars=20)
    return [leak.kind for leak in found]


def test_normalise_collapses_whitespace_and_case() -> None:
    assert normalise_text("  The   Pilot\n\tSaid ") == "the pilot said"


def test_clean_evidence_has_no_leaks() -> None:
    assert leaks({"aircraft_make": "CESSNA", "weather_metar": "KABC 011200Z"}) == []


def test_whole_withheld_text_is_found() -> None:
    assert "text" in leaks({"prelim_narrative": f"Summary: {CAUSE.upper()} End"})


def test_single_sentence_is_found() -> None:
    text: dict[str, str | None] = {
        "analysis_narrative": "The engine was examined. No anomalies were found with the airframe."
    }
    assert leaks({"prelim_narrative": "no anomalies were found with the airframe."}, text) == [
        "sentence"
    ]


def test_sentence_shorter_than_minimum_is_ignored() -> None:
    text: dict[str, str | None] = {
        "analysis_narrative": "None. The engine was examined in detail by the manufacturer."
    }
    assert leaks({"prelim_narrative": "none."}, text) == []


def test_boilerplate_is_ignored() -> None:
    text: dict[str, str | None] = {
        "probable_cause": f"{CAUSE} **This report was modified on 4/21/2016."
    }
    assert leaks({"prelim_narrative": "**this report was modified on 4/21/2016."}, text) == []


def test_code_token_is_found_but_not_inside_a_longer_number() -> None:
    assert leaks({"prelim_narrative": "code 300230 noted"}, codes=("300230",)) == ["code"]
    assert leaks({"prelim_narrative": "serial 13002301"}, codes=("300230",)) == []


def test_tuples_and_numbers_are_checked_as_text() -> None:
    assert leaks({"pilot_certificates": ("Private", "300230")}, codes=("300230",)) == ["code"]
    assert leaks({"pilot_total_hours": 250.0}) == []


@given(
    role=st.sampled_from(list(EvidenceRole)),
    withheld=st.text(alphabet=string.ascii_letters + " ", min_size=MIN_SENTENCE_CHARS).filter(
        lambda s: len(normalise_text(s)) >= MIN_SENTENCE_CHARS
    ),
    prefix=st.text(alphabet=string.printable, max_size=30),
    suffix=st.text(alphabet=string.printable, max_size=30),
)
def test_any_withheld_text_inserted_into_any_role_is_found(
    role: EvidenceRole, withheld: str, prefix: str, suffix: str
) -> None:
    evidence = {role.value: f"{prefix} {withheld} {suffix}"}
    assert find_leaks(evidence, {"factual_narrative": withheld}, ())
