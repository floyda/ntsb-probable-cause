import string

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from ntsb_probable_cause.fields import EvidenceRole, EvidenceValue
from ntsb_probable_cause.records.guard import (
    MIN_SENTENCE_CHARS,
    SENTENCE_CHECK_EXEMPTIONS,
    Leak,
    find_leaks,
    normalise_text,
)

CAUSE = "The pilot's failure to remove the airplane's tow bar before takeoff."
# Invented clinical text, not from any real record; used only to test the guard's matching.
ANALYSIS = "The engine was examined thoroughly.No anomalies were found with the airframe."


def leaks(
    evidence: dict[str, EvidenceValue],
    text: dict[str, str | None] | None = None,
    codes: tuple[str, ...] = (),
) -> list[str]:
    found = find_leaks(evidence, text or {"probable_cause": CAUSE}, codes, min_sentence_chars=20)
    return [leak.kind for leak in found]


def test_normalise_collapses_whitespace_and_case() -> None:
    assert normalise_text("  The   Pilot\n\tSaid ") == "the pilot said"


def test_normalise_folds_curly_quotes_and_nfkc() -> None:
    curly = "The pilot’s “failure”"  # noqa: RUF001 - curly apostrophe and quotes, deliberate
    assert normalise_text(curly) == 'the pilot\'s "failure"'


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


def test_code_matched_as_whole_token() -> None:
    assert leaks({"prelim_narrative": "occurrence 300230."}, codes=("300230",)) == ["code"]


def test_code_not_matched_inside_a_longer_number() -> None:
    assert leaks({"prelim_narrative": "serial 13002301"}, codes=("300230",)) == []


def test_code_not_matched_inside_a_metar_time_group() -> None:
    # KICT 250200Z is an observation time, not a match for occurrence code 250200.
    assert leaks({"weather_metar": "KICT 250200Z 18005KT"}, codes=("250200",)) == []


def test_code_not_matched_inside_a_trailing_letter_suffix() -> None:
    assert leaks({"prelim_narrative": "part A300230B installed"}, codes=("300230",)) == []


def test_blank_and_whitespace_codes_are_skipped() -> None:
    assert leaks({"prelim_narrative": "anything at all here"}, codes=("", "   ")) == []


def test_tuples_and_numbers_are_checked_as_text() -> None:
    assert leaks({"pilot_certificates": ("Private", "300230")}, codes=("300230",)) == ["code"]
    assert leaks({"pilot_total_hours": 250.0}) == []


def test_leak_str_does_not_render_the_fragment_text() -> None:
    leak = Leak("prelim_narrative", "sentence", "analysis_narrative", CAUSE)
    rendered = str(leak)
    assert CAUSE not in rendered
    assert "prelim_narrative" in rendered
    assert "sentence" in rendered
    assert "analysis_narrative" in rendered
    assert str(len(CAUSE)) in rendered


def test_leak_repr_does_not_render_the_fragment_text() -> None:
    leak = Leak("prelim_narrative", "sentence", "analysis_narrative", CAUSE)
    assert CAUSE not in repr(leak)


# --- Boilerplate: exempts only the exact isolated boilerplate sentence, never the whole text ---


def test_bare_boilerplate_sentence_alone_is_not_flagged() -> None:
    text: dict[str, str | None] = {
        "probable_cause": f"{CAUSE} **This report was modified on 4/21/2016."
    }
    assert leaks({"prelim_narrative": "**this report was modified on 4/21/2016."}, text) == []


def test_probable_cause_prefixed_before_boilerplate_is_still_caught() -> None:
    text: dict[str, str | None] = {
        "probable_cause": f"{CAUSE} **This report was modified on 4/21/2016."
    }
    found = leaks({"prelim_narrative": f"See also: {CAUSE}"}, text)
    assert found


# --- Trivial edits that must not defeat the tripwire ---


def test_probable_cause_without_trailing_period_is_found() -> None:
    dropped = CAUSE.rstrip(".")
    assert "text" in leaks({"prelim_narrative": f"Summary: {dropped}"})


def test_probable_cause_followed_by_more_words_is_found() -> None:
    assert "text" in leaks({"prelim_narrative": f"{CAUSE} additional detail follows"})


def test_last_sentence_copied_without_its_period_is_found() -> None:
    text: dict[str, str | None] = {"analysis_narrative": ANALYSIS}
    assert "sentence" in leaks(
        {"prelim_narrative": "no anomalies were found with the airframe"}, text
    )


def test_smart_apostrophe_in_evidence_is_still_found() -> None:
    smart = CAUSE.replace("'", "’")  # noqa: RUF001 - curly apostrophe, deliberate
    assert "text" in leaks({"prelim_narrative": f"Summary: {smart}"})


def test_no_space_after_period_still_splits_into_sentences() -> None:
    text: dict[str, str | None] = {"analysis_narrative": ANALYSIS}
    assert "sentence" in leaks({"prelim_narrative": "the engine was examined thoroughly"}, text)
    assert "sentence" in leaks(
        {"prelim_narrative": "no anomalies were found with the airframe"}, text
    )


def test_semicolon_delimited_clause_is_found() -> None:
    text: dict[str, str | None] = {
        "analysis_narrative": "The left wing spar was fractured; the right wing was undamaged."
    }
    assert "sentence" in leaks({"prelim_narrative": "the right wing was undamaged."}, text)


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


@given(
    role=st.sampled_from(list(EvidenceRole)),
    withheld=st.text(alphabet=string.ascii_letters + " ", min_size=MIN_SENTENCE_CHARS).filter(
        lambda s: len(normalise_text(s)) >= MIN_SENTENCE_CHARS
    ),
    final_punct=st.sampled_from(list(".!?;:\"')]}")),
    prefix=st.text(alphabet=string.printable, max_size=30),
    suffix=st.text(alphabet=string.printable, max_size=30),
)
# Regression for fix round 2: a withheld needle ending "<letters> ." (space then punctuation)
# used to strip only the punctuation, leaving a trailing space that never matched the evidence
# copy (which has neither the space nor the punctuation).
@example(
    role=EvidenceRole.PRELIM_NARRATIVE,
    withheld="AAAAAAAAAAAAAAAAAAAA ",
    final_punct=".",
    prefix="",
    suffix="",
)
def test_any_withheld_text_without_its_final_punctuation_is_still_found(
    role: EvidenceRole, withheld: str, final_punct: str, prefix: str, suffix: str
) -> None:
    # The withheld text carries its usual final punctuation; the evidence copy has been
    # trivially edited to drop it. The tripwire must still catch the copy.
    punctuated = withheld + final_punct
    evidence = {role.value: f"{prefix} {withheld} {suffix}"}
    assert find_leaks(evidence, {"factual_narrative": punctuated}, ())


# --- Task 13, step 0 (controller-directed): leading open quote/bracket, trailing comma ---


def test_parenthesised_withheld_text_is_found_when_evidence_drops_the_parens() -> None:
    withheld = "(the engine lost power during the climb.)"
    evidence: dict[str, EvidenceValue] = {
        "prelim_narrative": "the engine lost power during the climb"
    }
    assert "text" in leaks(evidence, {"factual_narrative": withheld})


def test_quoted_withheld_text_is_found_when_evidence_drops_the_quotes() -> None:
    withheld = '"the engine lost power during the climb."'
    evidence: dict[str, EvidenceValue] = {
        "prelim_narrative": "the engine lost power during the climb"
    }
    assert "text" in leaks(evidence, {"factual_narrative": withheld})


def test_withheld_text_ending_in_a_comma_is_found_when_evidence_drops_the_comma() -> None:
    withheld = "the pilot continued the approach despite deteriorating weather, "
    evidence: dict[str, EvidenceValue] = {
        "prelim_narrative": "the pilot continued the approach despite deteriorating weather"
    }
    assert "text" in leaks(evidence, {"factual_narrative": withheld})


# --- Decision 0019 (review fix round 1): weather_metar is exempt from the sentence
# comparison only for sentences sourced from the factual narrative ---

_WEATHER_WITHHELD = (
    "The weather was clear at the time of the accident. "
    "The engine lost power during the initial climb after takeoff."
)
_WEATHER_SENTENCE = "the engine lost power during the initial climb after takeoff"

# Roles not exempted for a factual-narrative sentence: every role except the two pairs in
# SENTENCE_CHECK_EXEMPTIONS (weather_metar, 0019; docket_documents, 0050).
_NON_EXEMPT_ROLES = [
    role
    for role in EvidenceRole
    if role not in (EvidenceRole.WEATHER_METAR, EvidenceRole.DOCKET_DOCUMENTS)
]


def test_factual_narrative_sentence_in_weather_metar_gives_no_leak() -> None:
    text: dict[str, str | None] = {"factual_narrative": _WEATHER_WITHHELD}
    assert leaks({"weather_metar": _WEATHER_SENTENCE}, text) == []


def test_analysis_sentence_in_weather_metar_is_still_caught() -> None:
    text: dict[str, str | None] = {"analysis_narrative": _WEATHER_WITHHELD}
    assert leaks({"weather_metar": _WEATHER_SENTENCE}, text) == ["sentence"]


def test_probable_cause_sentence_embedded_in_weather_metar_is_caught() -> None:
    narrative = "The airplane departed controlled flight during the approach. " + CAUSE
    evidence: dict[str, EvidenceValue] = {
        "weather_metar": f"KABC 121453Z 27008KT 10SM CLR 24/08 A3002 {CAUSE} RMK AO2"
    }
    assert "sentence" in leaks(evidence, {"probable_cause": narrative})


@pytest.mark.parametrize("role", _NON_EXEMPT_ROLES, ids=lambda role: role.value)
def test_factual_narrative_sentence_is_caught_in_every_other_role(role: EvidenceRole) -> None:
    text: dict[str, str | None] = {"factual_narrative": _WEATHER_WITHHELD}
    assert "sentence" in leaks({role.value: _WEATHER_SENTENCE}, text)


def test_sentence_check_exemptions_is_exactly_the_two_measured_pairs() -> None:
    assert (
        frozenset(
            {
                ("weather_metar", "factual_narrative"),
                ("docket_documents", "factual_narrative"),
            }
        )
        == SENTENCE_CHECK_EXEMPTIONS
    )


def test_whole_probable_cause_in_weather_metar_is_still_caught() -> None:
    assert leaks({"weather_metar": CAUSE}) == ["text"]


def test_code_in_weather_metar_is_still_caught() -> None:
    assert leaks({"weather_metar": "occurrence 300230."}, codes=("300230",)) == ["code"]


# --- Decision 0050: docket_documents is exempt from the sentence comparison only for
# sentences sourced from the factual narrative; docket_listing is deliberately not exempted ---

# Invented clinical text, not from any real record; used only to test the guard's matching.
_DOCKET_WITHHELD = (
    "The pilot completed a preflight inspection before the accident flight. "
    "The postaccident examination found contamination in the fuel supplied to the left tank."
)
_DOCKET_SENTENCE = (
    "the postaccident examination found contamination in the fuel supplied to the left tank"
)


def test_factual_narrative_sentence_in_docket_documents_gives_no_leak() -> None:
    text: dict[str, str | None] = {"factual_narrative": _DOCKET_WITHHELD}
    assert leaks({"docket_documents": _DOCKET_SENTENCE}, text) == []


def test_analysis_sentence_in_docket_documents_is_still_caught() -> None:
    text: dict[str, str | None] = {"analysis_narrative": _DOCKET_WITHHELD}
    assert leaks({"docket_documents": _DOCKET_SENTENCE}, text) == ["sentence"]


def test_probable_cause_sentence_in_docket_documents_is_still_caught() -> None:
    narrative = "The airplane departed controlled flight during the approach. " + CAUSE
    evidence: dict[str, EvidenceValue] = {
        "docket_documents": f"Exhibit 3, investigator's note: {CAUSE} See attachment."
    }
    assert "sentence" in leaks(evidence, {"probable_cause": narrative})


def test_code_in_docket_documents_is_still_caught() -> None:
    assert leaks({"docket_documents": "occurrence 300230."}, codes=("300230",)) == ["code"]


def test_whole_factual_narrative_in_docket_documents_is_still_caught() -> None:
    # The sentence exemption applies only to split-out sentences, never to the whole-text
    # needle -- so a document that quotes the entire factual narrative still stops the case.
    text: dict[str, str | None] = {"factual_narrative": _DOCKET_WITHHELD}
    assert leaks({"docket_documents": _DOCKET_WITHHELD}, text) == ["text"]


def test_factual_narrative_sentence_in_docket_listing_is_still_caught() -> None:
    # 0050 item 3: docket_listing is deliberately not in SENTENCE_CHECK_EXEMPTIONS.
    text: dict[str, str | None] = {"factual_narrative": _DOCKET_WITHHELD}
    assert leaks({"docket_listing": _DOCKET_SENTENCE}, text) == ["sentence"]


def test_factual_narrative_sentence_in_another_role_is_still_caught() -> None:
    text: dict[str, str | None] = {"factual_narrative": _DOCKET_WITHHELD}
    assert leaks({"prelim_narrative": _DOCKET_SENTENCE}, text) == ["sentence"]


# --- Minor: opening marks, as a property rather than fixed examples ---

_OPENING_CLOSING = {'"': '"', "'": "'", "(": ")", "[": "]", "{": "}"}


@given(
    opening=st.sampled_from(sorted(_OPENING_CLOSING)),
    final_punct=st.sampled_from(list(".!?")),
    withheld=st.text(alphabet=string.ascii_letters + " ", min_size=MIN_SENTENCE_CHARS).filter(
        lambda s: len(normalise_text(s)) >= MIN_SENTENCE_CHARS
    ),
)
def test_withheld_text_wrapped_in_an_opening_mark_is_found_when_evidence_drops_the_marks(
    opening: str, final_punct: str, withheld: str
) -> None:
    closing = _OPENING_CLOSING[opening]
    wrapped = f"{opening}{withheld}{final_punct}{closing}"
    evidence: dict[str, EvidenceValue] = {"prelim_narrative": withheld}
    assert find_leaks(
        evidence, {"analysis_narrative": wrapped}, (), min_sentence_chars=MIN_SENTENCE_CHARS
    )
