"""Build the committed docket-title vocabulary (finding 6's replacement, decision 0046).

What this file is
    A generator for ``src/ntsb_probable_cause/docket/vocab/title_words.txt``: every
    capitalised word (``ntsb_probable_cause.docket.title_vocab.capitalised_words`` --
    ``[A-Z][a-z]{2,}``, three letters or more, ALL-CAPS acronyms excluded) that appears in
    five or more distinct dockets in the cached corpus. A word seen across many dockets is
    ordinary NTSB title vocabulary -- "Accident", "Aircraft", "Airframe", "Administration" --
    not a name specific to one case. ``scripts/check_fixtures_redacted.py`` flags a title's
    capitalised word only when it is in *neither* this file *nor* the system dictionary.

    The 2.4 GB docket cache this reads deliberately does not exist in CI or in a pre-commit
    hook (decision 0037 keeps it out of git), so the signal has to be generated once, here,
    on a machine that has the cache, and committed -- not recomputed at check time.

    Measured 2026-09-19 on 401 cached development-split dockets (3,790 document titles):
    235 words meet the five-docket threshold.

Regenerate
    Whenever the docket cache grows enough to be worth re-measuring::

        uv run python -m scripts.build_title_vocab

    (``NTSB_DOCKET_DIR`` from the environment or ``.env``, default ``data/docket`` --
    ``--docket-dir`` overrides it; ``--out`` overrides where the file is written, default
    ``src/ntsb_probable_cause/docket/vocab/title_words.txt``.) Commit the result. Because the
    file only ever *adds* words a bigger cache has now seen five times, a stale copy makes the
    check slightly stricter -- a common word one docket away from its fifth appearance gets a
    second look -- never looser: a word that already cleared the threshold stays in the file
    forever, regenerated or not.

Safety
    Titles are not personal data in general (decision 0037's own name check exists because a
    minority of them are), and this file holds only words that recur across five or more
    separate investigations -- by construction, not something specific to any one of them.
    Still, sanity-check the output before committing: skim it for anything that reads as a
    name rather than a term, and check the count is in the expected range.
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from ntsb_probable_cause.docket.listing import parse_listing
from ntsb_probable_cause.docket.title_vocab import MIN_DOCKETS, capitalised_words
from ntsb_probable_cause.errors import DocketError
from ntsb_probable_cause.settings import Settings

DEFAULT_OUT = Path("src/ntsb_probable_cause/docket/vocab/title_words.txt")


def build_vocabulary(docket_dir: Path, *, min_dockets: int = MIN_DOCKETS) -> list[str]:
    """Every capitalised word seen in ``min_dockets`` or more distinct cached dockets, sorted.

    Reads every ``<docket_dir>/<mkey>/listing.html`` -- the cached listing page decision 0037
    keeps out of git -- and counts, per lowercased word, the *distinct* docket folders it
    appeared in (a word used three times in one docket's titles counts once, not three).
    """
    dockets_by_word: dict[str, set[str]] = defaultdict(set)
    for listing_path in sorted(docket_dir.glob("*/listing.html")):
        mkey_dir = listing_path.parent.name
        try:
            mkey = int(mkey_dir)
        except ValueError:
            continue
        text = listing_path.read_text(encoding="utf-8", errors="replace")
        try:
            listing = parse_listing(text, mkey=mkey)
        except DocketError:
            continue
        for entry in listing.entries:
            for word in capitalised_words(entry.title):
                dockets_by_word[word.lower()].add(mkey_dir)
    return sorted(word for word, dockets in dockets_by_word.items() if len(dockets) >= min_dockets)


def main(argv: list[str]) -> int:
    """Generate the vocabulary file and print how many words it holds."""
    parser = argparse.ArgumentParser(prog="build_title_vocab")
    parser.add_argument("--docket-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--min-dockets", type=int, default=MIN_DOCKETS)
    args = parser.parse_args(argv)
    docket_dir = args.docket_dir or Settings().docket_dir
    if not docket_dir.is_dir():
        print(f"{docket_dir}: no docket cache here -- nothing to build from", file=sys.stderr)
        return 1
    words = build_vocabulary(docket_dir, min_dockets=args.min_dockets)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(word.capitalize() for word in words) + "\n")
    print(f"{len(words)} words (>= {args.min_dockets} dockets) written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
