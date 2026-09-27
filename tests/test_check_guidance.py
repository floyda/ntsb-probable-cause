from scripts import check_guidance as cg


def test_sentences_and_matches() -> None:
    text = "Short one. When a loss of control and a stall both occur, code the first. Another."
    needles = cg.sentences(text)
    assert needles == ["when a loss of control and a stall both occur, code the first."]
    haystack = "... when a loss of control and a stall both occur, code the first. ..."
    assert cg.matches(needles, [haystack]) == needles
    assert cg.matches(needles, ["nothing here"]) == []
