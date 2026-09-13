import string

from hypothesis import example, given
from hypothesis import strategies as st

from ntsb_probable_cause.fields import EvidenceRole, EvidenceValue
from ntsb_probable_cause.records.guard import MIN_SENTENCE_CHARS, Leak, find_leaks, normalise_text

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
