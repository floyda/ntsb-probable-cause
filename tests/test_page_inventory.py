"""scripts/page_inventory.py: the sample, the weights, the cut-off and the stop rule."""

from scripts import page_inventory as inv


def _frame() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for kind, count in (("image only", 200), ("text and image", 400), ("text only", 300)):
        for i in range(count):
            rows.append(
                {
                    "case_id": f"C{i % 40}",
                    "mkey": i,
                    "fatal": i % 2 == 0,
                    "document": 1,
                    "page": i,
                    "pages": 999,
                    "kind": kind,
                }
            )
    return rows


def test_the_sample_follows_the_allocation_and_the_seed() -> None:
    first = inv.draw_sample(_frame())
    again = inv.draw_sample(_frame())
    assert len(first) == 300
    assert [r["n"] for r in first] == list(range(1, 301))
    assert first == again
    assert sum(1 for r in first if r["stratum"] == "text only/fatal") == 15


def test_photo_only_pages_are_their_own_stratum() -> None:
    """Decision W2: a photograph page is never drawn as an ordinary scan."""
    photos = [
        {
            "case_id": f"P{i}",
            "mkey": i,
            "fatal": i % 2 == 0,
            "document": 9,
            "page": i,
            "pages": 99,
            "kind": "image only",
            "photo_only": True,
        }
        for i in range(40)
    ]
    sample = inv.draw_sample(_frame() + photos)
    assert sum(1 for r in sample if r["stratum"] == "photo-only/fatal") == 15
    assert not any(
        r.get("photo_only")
        for r in sample
        if r["stratum"] != "photo-only/fatal" and r["stratum"] != "photo-only/non-fatal"
    )


def test_weighted_share_weights_each_stratum_by_its_population() -> None:
    labels = {
        "image only/fatal": ["handwriting"] * 1 + ["photograph"] * 1,
        "text and image/fatal": ["typed text"] * 2,
    }
    population = {"image only/fatal": 100, "text and image/fatal": 300}
    assert inv.weighted_word_share(labels, population) == 0.125  # (100 x 1/2 + 0) / 400


def test_the_cut_off_is_the_largest_run_of_admissible_cuts() -> None:
    rows = [(0.01, "logo or letterhead only")] * 58 + [(0.01, "handwriting")]
    rows += [(0.07, "logo or letterhead only")] * 9 + [(0.07, "handwriting")] * 3
    rows += [(0.5, "photograph")] * 10
    assert inv.mixed_cut(rows) == 0.05


def test_no_admissible_cut_sends_every_page() -> None:
    assert inv.mixed_cut([(0.01, "handwriting")] * 5) == 0.0


def test_andys_correction_replaces_the_models_label() -> None:
    marks = {1: {"label": "wrong", "correct label": "handwriting"}, 2: {"label": "right"}}
    assert inv.final_labels({1: "typed text", 2: "blank"}, marks) == {
        1: "handwriting",
        2: "blank",
    }


def test_the_stop_rule() -> None:
    assert inv.stop_outcome(0.09).startswith("stop")
    assert inv.stop_outcome(0.10).startswith("go on")
