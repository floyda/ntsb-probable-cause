# S2.6 — The widened docket: implementation plan

**Spec:** docs/specs/2026-09-23-s26-widened-docket-design.md

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tick a step in the same commit as its code (decision 0017). Log every departure from the specification in the **Deviations** section at the end. A step marked **STOP** is Andy's: stop the stage there, report, and wait.

**Goal:** Measure what the image-bearing docket pages hold, choose a transcriber by a rule fixed in advance, add transcribed words to the docket tool as evidence version v2 (and pictures as a v3 probe), replace two refusals with case marks, and re-measure arm B on `dev-400` and once each (v1, v2) on `heldout-400`, so that S3's loop is compared with arm B on equal evidence.

**Architecture:** Page facts (`docket/pages.py`) and the renderer (`docket/render.py`) are pure functions over PDF bytes. Marks (`records/marks.py`) are computed inside `split_record` — the one split — and ride out on `Evidence` as bookkeeping fields that `Payload` never renders; v3's `unguarded_images` is added where pictures are chosen. The model seam gains an image input (`model/client.py:PageImage`); transcription (`docket/transcribe.py`) is evidence preparation, run by its own command, cached per page under `NTSB_DATA_DIR`, and read — never called — by an evaluation run. `RunSpec`, `RunRecord`, the report and the ledger gain the evidence version (0076). Every paid step is a `make` target Andy runs.

**Tech Stack:** Python 3.14, uv + hatchling, pydantic v2, pypdf, **pypdfium2 5.13.0 and Pillow (new, Task 3)**, httpx + respx, pytest + pytest-socket + hypothesis, ruff, mypy --strict, import-linter.

## Global Constraints

- **Branch and base.** Work on `s26-widened-docket` in `.claude/worktrees/s26-widened-docket`. It sits on `s25-recorder` (the spec cites 0071). Never touch `.claude/worktrees/s24-model-switch`. Tasks 1–5 need nothing from S2.4; Task 6 merges `main` once S2.4 has landed there; every later task is written against S2.4's code (`s24-model-switch` at `36bcd22`) and re-checked against `main` after the merge.
- **Files S2.4 changes wait for Task 6:** `scoring/runner.py`, `scoring/records.py`, `scoring/report.py`, `model/client.py`, `model/openrouter.py`, `sources.py`, `apps/eval/__main__.py`, `Makefile`, and their tests. No task before Task 6 edits them.
- **The split is the only split** (CLAUDE.md rule 1). The text marks (`analysis_sentence`, `narrative_coverage`) are computed inside `records/split.py:split_record` and nowhere else; `unguarded_images` is added in `scoring/runner.py:prepare_case`, the one place v3 pictures are chosen, because pictures never pass through the split. A mark never enters text or images a model receives (spec §4.4).
- **Held-out text is never read by a person.** Hand-check, inventory and answer-key material comes from `dev-400` only. Every script that reads the docket cache selects dockets by sample id (`scoring.samples.sample_ids`), never by globbing the cache, which also holds held-out dockets. Held-out and open-split pages are never rendered to a file a person opens.
- **Private material lives under `data/`** (git-ignored) and is never committed: hand-check sheets, page frames, page images, answer keys, transcriptions. Only counts go to `docs/results/`.
- **Every model call goes through `ModelClient` or `BatchRunner`** (0009). Tests never reach the network (`--disable-socket`); replies are recorded fixtures or `RecordingFakeClient`.
- **Images never go through the batch service** (OpenRouter batch documentation, <https://openrouter.ai/docs/batch-quickstart>, read 2026-09-24: "Image parts must be public `http(s)` URLs. Base64 and `data:` URI images are rejected on every provider", and Google's providers accept no image URL in a batch at all). Every call carrying an image uses the standard price variant, synchronously (decision W1, Andy, 2026-09-24).
- **Budget.** $40 a month during development (0083); the code default is $25 until Task 7 changes it. Transcription and inventory spend counts against the month (0081) through the spend records of Task 7. The stage pause point (0083 item 2) is Task 13 Step 12.
- **Paid and held-out commands handed to Andy** always state: `export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data`, the expected cost and duration, and what the tree looks like afterwards. They are run from a shell script that exports `OPENROUTER_API_KEY="$(pass show api/openrouter)"` and never prints it. **One held-out run per `make` recipe**: each held-out run appends its ledger row, which dirties the tree, and the held-out guard (0026) then refuses the next run; the row is committed between runs.
- **Numbers reported anywhere come from a script.** Numbers S2.6 needs from S2.4 (held-out failures by reason, the GPT-6 Luna bars) are cited from `docs/results/s24-bars.txt` on `main`, never copied from memory.
- `make check` = ruff format, ruff check, lint-imports, deptry, vulture, mypy --strict, pytest; coverage gate `--cov-fail-under=90`, branch coverage. Google-style docstrings on every public symbol; line length 100. Scripts carry a `Status` paragraph in their module docstring (house style since S2).
- Commit messages end with the attribution lines the session gives. Never commit to `main`. The stage pull request is titled `S2.6: the widened docket` and merged with a merge commit, never squashed (0033).

---

## Decisions for Andy before any code (the walkthrough)

The spec is approved; these are the places where writing the plan found something the spec did not settle, or where the spec's assumption turned out false. Each is marked in the task that depends on it. The walkthrough took them one per message on 2026-09-24; each outcome is written beside it below and in the Deviations section. All seven are decided.

- **W1. Images cannot use the batch service.** Found while planning (quoted in Global Constraints). The spec priced transcription, the inventory and the v3 probe at batch prices; the standard price is exactly twice the batch price for every candidate (OpenRouter models list, read 2026-09-24: Flash Lite $0.25/$1.50 per million tokens in/out against $0.125/$0.75; Gemini 3.6 Flash $0.75/$3.75; GPT-6 Luna $0.10/$0.50; Qwen3.5 122B $0.26/$2.08, which has no batch variant). Re-estimate (arithmetic, replaced at close-out): inventory $0.20, transcriber test $4–8, `dev-400` transcription $6–12, `heldout-400` transcription $6–12, v3 probe $4–6; the text-only arm B runs are unchanged. Stage total about **$26–46**, against the spec's $17–27. *Planned as:* every image call on the standard path, the stage spread across the September and October budgets, the pause point unchanged. **Decided 2026-09-24 (Andy): as planned ("A, go with the standard price").** Rejected: public image links so batch works (helps GPT-6 Luna only, puts fatal-accident pages at web addresses); cutting pages before the inventory measures them.
- **W2. Photo-only docket entries are never fetched.** `docket/manifest.py:read_docket` skips an entry whose listing says every page is a photo (the spike's rule), so the development cache holds none of them. Neither the inventory nor the v3 probe can see those photographs. Task 1 counts them from the listing metadata. An ad-hoc count of `dev-400`'s cached listings (2026-09-24, counts only): 146 photo-only PDFs holding 831 pages, in 113 of 401 cases (717 pages in fatal cases), against 170 photograph pages declared inside the documents S2 reads. **Decided 2026-09-24 (Andy): download them and include them** — Task 1 fetches them politely and frames them as their own stratum; the inventory samples 15 + 15 of them; v2 transcribes them and v3 shows them, guarded like any other page; v1 keeps S2's rule. Rejected: pictures for v3 only (every one would be unguarded, 0082 item 2); leaving them out (v3 would test about one photograph in six).
- **W3. Which mixed pages are sent to the transcriber.** The spec says "a page whose images are logos only is not" sent, and that the inventory decides — but a program has to decide *before* sending. *Planned as:* each page's image-area share (the fraction of the page its images cover, from the renderer) is recorded in the inventory, and the cut-off is chosen by a rule fixed before the inventory runs (Task 12 Step 2). An ad-hoc count of how the 8,399 mixed pages spread (2026-09-24, dev-400, counts only): 9.2% have images covering under 2% of the page, 11.4% under 5%, 14.3% under 10%, 16.8% under 20%; 58.7% are 70% or more image. **Decided 2026-09-24 (Andy): the rule as planned.** Rejected: sending every mixed page (against 0079 item 3, about $0.50–1.00 a sample on logos); a fixed cut with no measured error.
- **W4. The renderer's test pages are built in code, not committed real pages.** Spec §12 says "a committed development fixture page of each awkward shape". No real PDF is committed anywhere in the repository today (the extract tests build theirs with pypdf), and a real page would need Andy's read for names (0037). *Planned as:* rotated, tiled and fax-encoded pages built in the tests with Pillow and pypdf (verified to work while planning). **Decided 2026-09-24 (Andy): as planned.** Rejected: committing real development pages (Andy's read of each, fatal-accident pages in the repository); a local-only check on real pages besides (Task 1 and every transcription job already render real pages and record failures).
- **W5. The v3 probe's partner run.** v3 carries images, so it must run on the standard path (W1); B-v2 from Task 15 runs on batch. *Planned as:* a second B-v2 run on the standard path, paired with B-v3, so the pictures are the only difference (about $3–4 more, estimate). **Decided 2026-09-24 (Andy): as planned.** The same run, paired with Task 15's batch B-v2 (same evidence, same model), also measures the noise floor: how far two runs on identical evidence differ by chance and transport. It is published in Task 17's results file. Rejected: pairing v3 with the batch B-v2 (two changes at once); running every S2.6 run on the standard path (twice the cost of the text runs, and held-out would differ in transport from S2.4's bar).
- **W6. The inventory's stop rule needs a number.** Spec §6.4 stops transcription "if the inventory shows the image-bearing pages rarely hold words", without saying how rarely. A rule fixed after seeing the counts could be fitted to them. *Planned as:* stop if, weighted over all image-bearing `dev-400` pages, **under 10%** have words in their images (Task 12). **Decided 2026-09-24 (Andy): as planned.** Rejected: a 5% bar (full price for a sliver of words); no stop rule (the pause point sees money, not value).
- **W7. Most mixed pages are full-page scans that already carry a machine-read text layer.** An ad-hoc count (2026-09-24, dev-400, 3,517 PDFs, pypdfium2's text and image boxes) put 4,932 of 8,399 text-and-image pages at 70% or more image cover. For those the mixed-page instruction ("copy only words not already in the text layer") does most of the work, and the transcriber test's three keys never measure it. A crude check of those layers (400 pages, share of words found in the vendored word list) gave a median of 74%, against 77% on typed pages: usually not garbage. **Decided 2026-09-24 (Andy): keep the mixed-page instruction, and add a 25-page check of it to the transcriber test** (Task 13), gated like the photographs (at most 1 in 20 pages with invented added words). Rejected: not sending these scans (loses handwritten answers on scanned forms); transcribing them in full in place of the layer (against 0079; v2 would replace v1 text, not only add to it).

---

## File structure

| path | task | responsibility |
|---|---|---|
| `src/ntsb_probable_cause/docket/pages.py` | 1 | per-page facts from pypdf: characters, images, rotation, encodings; the page kind |
| `scripts/page_kinds.py` | 1 | `dev-400` page kinds, counts only; the private page frame |
| `tests/pdf_builder.py` | 1 | builds test PDFs from pypdf objects (text, images by encoding, rotation, forms) |
| `scripts/analysis_handcheck.py` | 2 | the private analysis-sentence marking page, and its scorer |
| `src/ntsb_probable_cause/docket/render.py` | 3 | page to JPEG with pypdfium2 at a fixed resolution; image-area share |
| `src/ntsb_probable_cause/records/marks.py` | 4 | `CaseMark`, `MarkKind` |
| `src/ntsb_probable_cause/records/guard.py` | 4, 5 | `sentence_needles`, `narrative_share`, `screen`, `MARKED_SENTENCES` |
| `src/ntsb_probable_cause/records/evidence.py`, `records/split.py` | 4, 5 | marks and the narrative share on `Evidence`, computed in the split |
| `src/ntsb_probable_cause/settings.py`, `scoring/budget.py` | 7 | the $40 default; spend records for preparation jobs |
| `scoring/runner.py`, `scoring/records.py`, `scoring/report.py`, `scoring/ledger.py`, `apps/eval/__main__.py` | 8, 9 | the evidence version; marks in results; the report printed twice |
| `src/ntsb_probable_cause/model/client.py`, `model/openrouter.py`, `sources.py` | 10 | `PageImage`; image parts in the request; candidate prices and reasoning levels |
| `src/ntsb_probable_cause/docket/transcribe.py` | 11 | the instruction, the request, the reply, the per-page cache, the worker pool |
| `scripts/page_inventory.py` | 12 | the inventory sample, labels, Andy's 60-label page, the counts |
| `scripts/transcriber_test.py` | 13 | the three answer keys, the four candidates, Andy's pages, the choice rule |
| `docket/extract.py`, `docket/manifest.py`, `docket/attach.py`, `apps/eval` `transcribe` | 14 | v2 in the docket tool |
| `model/client.py`, `scoring/runner.py` | 16 | v3: pictures alongside text, `unguarded_images` |
| `docs/results/s26-*.txt` | throughout | the stage's results, counts only |

Task numbers in this table are final; the tasks below use them.

---

## Part 1 — before S2.4 lands

### Task 1: Page facts and the page-kind counts (spec §1, §5.2, §6.2 step 1; no model, no cost)

**Files:**
- Create: `src/ntsb_probable_cause/docket/pages.py`
- Create: `scripts/page_kinds.py`
- Create: `tests/pdf_builder.py`, `tests/test_docket_pages.py`, `tests/test_page_kinds.py`
- Output: `docs/results/s26-page-kinds.txt` (committed); `data/s26/pages-dev-400.jsonl` (private)
- Not touched: the `Makefile` (S2.4 changes it). Its `page-kinds` target is added in Task 6; until then the command is run directly.

**Interfaces:**
- Produces: `docket.pages.PageKind = Literal["text only", "image only", "text and image", "blank"]`; `docket.pages.PageFacts` (frozen pydantic: `chars: int`, `images: int`, `rotation: int`, `encodings: tuple[str, ...]`, `failed: bool = False`, property `kind -> PageKind`); `docket.pages.page_facts(page: pypdf.PageObject) -> PageFacts`; `docket.pages.document_facts(data: bytes) -> tuple[PageFacts, ...]` (raises `DocketError("not a PDF: ...")`); `docket.pages.TILED_MIN_IMAGES = 5`.
- Produces (private frame, one JSON object per page): `{"case_id": str, "mkey": int, "fatal": bool, "document": int, "page": int, "pages": int, "kind": PageKind, "chars": int, "images": int, "rotation": int, "encodings": [str]}`. Tasks 12 and 13 sample from it.
- Produces (tests): `tests/pdf_builder.py: PageSpec(text: str = "", images: tuple[str, ...] = (), rotation: int = 0, in_form: bool = False)` and `build_pdf(pages: Sequence[PageSpec]) -> bytes`. Task 3 reuses it.

**Why the facts come from pypdf, not the renderer.** Counting images and reading rotation from a page's own dictionaries decodes nothing, so all ~16,800 `dev-400` pages are classified without any image codec. The text count is pypdf's `extract_text`, exactly as the docket tool reads it (0047), so "under 50 characters" means here what it means in `classify.py`.

- [x] **Step 1: Write the test PDF builder**

`tests/pdf_builder.py` (a helper module, not a test file). Checked while planning with pypdf 6.19: text extracts, rotation reads back, images inside a form are found, and PDFium draws the one-byte images without error.

```python
"""Build small PDFs from pypdf objects, for tests that must not commit a real docket page.

Each image is a one-pixel XObject whose ``/Filter`` names the encoding under test. Its data
is not a valid stream of that encoding: page facts read only the image's dictionary, and
PDFium draws such an image as blank rather than failing. Tests that need real pixels (the
renderer's, Task 3) build their images with Pillow instead.
"""

import io
from collections.abc import Sequence
from dataclasses import dataclass

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NumberObject,
    StreamObject,
)


@dataclass(frozen=True)
class PageSpec:
    """One test page: its text, one encoding name per image, its rotation."""

    text: str = ""
    images: tuple[str, ...] = ()
    rotation: int = 0
    in_form: bool = False


def _image(writer: PdfWriter, filter_name: str) -> IndirectObject:
    image = StreamObject()
    image.set_data(b"\x00")
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(1),
            NameObject("/Height"): NumberObject(1),
            NameObject("/ColorSpace"): NameObject("/DeviceGray"),
            NameObject("/BitsPerComponent"): NumberObject(8),
            NameObject("/Filter"): NameObject(filter_name),
        }
    )
    return writer._add_object(image)


def _form(writer: PdfWriter, draws: str, xobjects: DictionaryObject) -> IndirectObject:
    form = StreamObject()
    form.set_data(draws.encode())
    form.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): ArrayObject(
                [NumberObject(0), NumberObject(0), NumberObject(612), NumberObject(792)]
            ),
            NameObject("/Resources"): DictionaryObject({NameObject("/XObject"): xobjects}),
        }
    )
    return writer._add_object(form)


def build_pdf(pages: Sequence[PageSpec]) -> bytes:
    """A letter-size PDF with one page per spec, Helvetica text, images drawn in a column."""
    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    for spec in pages:
        page = writer.add_blank_page(width=612, height=792)
        xobjects = DictionaryObject(
            {NameObject(f"/Im{i}"): _image(writer, name) for i, name in enumerate(spec.images)}
        )
        draws = "".join(
            f"q 100 0 0 100 0 {i * 100} cm /Im{i} Do Q\n" for i in range(len(spec.images))
        )
        if spec.in_form and spec.images:
            xobjects = DictionaryObject({NameObject("/Fm0"): _form(writer, draws, xobjects)})
            draws = "q /Fm0 Do Q\n"
        text = f"BT /F1 12 Tf 72 700 Td ({spec.text}) Tj ET\n" if spec.text else ""
        content = StreamObject()
        content.set_data((draws + text).encode())
        page[NameObject("/Contents")] = writer._add_object(content)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
                NameObject("/XObject"): xobjects,
            }
        )
        if spec.rotation:
            page.rotate(spec.rotation)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
```

- [x] **Step 2: Write the failing tests for page facts**

`tests/test_docket_pages.py`:

```python
"""Page facts: characters, images, rotation and encodings, read without decoding (S2.6 §1)."""

import pytest

from ntsb_probable_cause.docket.pages import TILED_MIN_IMAGES, PageFacts, document_facts
from ntsb_probable_cause.errors import DocketError
from tests.pdf_builder import PageSpec, build_pdf

# Invented clinical text, over the 50-character line (classify.SCAN_PAGE_MAX_CHARS).
TYPED = "Examination of the left magneto found the points worn beyond limits."


def test_the_four_page_kinds() -> None:
    facts = document_facts(
        build_pdf(
            [
                PageSpec(text=TYPED),
                PageSpec(images=("/CCITTFaxDecode",)),
                PageSpec(text=TYPED, images=("/DCTDecode",)),
                PageSpec(),
            ]
        )
    )
    assert [f.kind for f in facts] == ["text only", "image only", "text and image", "blank"]


def test_a_short_caption_does_not_make_an_image_page_a_text_page() -> None:
    (facts,) = document_facts(build_pdf([PageSpec(text="Photo 3", images=("/DCTDecode",))]))
    assert facts.chars < 50
    assert facts.kind == "image only"


def test_rotation_and_encodings_are_read_from_the_page() -> None:
    (facts,) = document_facts(
        build_pdf([PageSpec(images=("/JBIG2Decode", "/JPXDecode"), rotation=90)])
    )
    assert facts.rotation == 90
    assert facts.encodings == ("JBIG2", "JPEG 2000")
    assert facts.images == 2


def test_images_inside_a_form_are_counted() -> None:
    specs = [PageSpec(images=("/DCTDecode",) * TILED_MIN_IMAGES, in_form=True)]
    (facts,) = document_facts(build_pdf(specs))
    assert facts.images == TILED_MIN_IMAGES
    assert facts.encodings == ("JPEG",)


def test_an_unknown_encoding_is_named_other() -> None:
    (facts,) = document_facts(build_pdf([PageSpec(images=("/RunLengthDecode",))]))
    assert facts.encodings == ("other",)


def test_not_a_pdf_raises() -> None:
    with pytest.raises(DocketError, match="not a PDF"):
        document_facts(b"<html>not a pdf</html>")


def test_a_failed_page_is_blank_and_flagged() -> None:
    facts = PageFacts(chars=0, images=0, rotation=0, encodings=(), failed=True)
    assert facts.kind == "blank"
```

- [x] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/test_docket_pages.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ntsb_probable_cause.docket.pages'`.

- [x] **Step 4: Implement `docket/pages.py`**

```python
"""What a PDF page holds: text characters, images, rotation and image encodings (S2.6 §1).

Read from the page's own dictionaries with pypdf and never decoded, so a page is classified
without any image codec (0047's rule against system tools). Text is pypdf's
``extract_text``, exactly as ``extract.py`` reads it, so "under 50 characters" means here
what it means to the docket tool.
"""

import io
from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pypdf import PageObject, PdfReader
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, PdfObject

from ntsb_probable_cause.docket.classify import SCAN_PAGE_MAX_CHARS
from ntsb_probable_cause.errors import DocketError

PageKind = Literal["text only", "image only", "text and image", "blank"]

# A page drawn from this many image pieces or more comes out of image extraction as strips
# rather than a page (spec §5.2).
TILED_MIN_IMAGES = 5

# The encodings spec §5.2 names, by the PDF filter that declares them. Anything else is
# "other"; an image with no filter is "none".
_ENCODINGS = {
    "/CCITTFaxDecode": "fax (CCITT)",
    "/JPXDecode": "JPEG 2000",
    "/JBIG2Decode": "JBIG2",
    "/DCTDecode": "JPEG",
    "/FlateDecode": "Flate",
}


class PageFacts(BaseModel):
    """One page's counts. Never its text."""

    model_config = ConfigDict(frozen=True)
    chars: int
    images: int
    rotation: int
    encodings: tuple[str, ...]
    failed: bool = False

    @property
    def kind(self) -> PageKind:
        """Text only, image only, text and image, or blank, by the 50-character line."""
        has_text = self.chars >= SCAN_PAGE_MAX_CHARS
        if self.images:
            return "text and image" if has_text else "image only"
        return "text only" if has_text else "blank"


def _resolve(value: object) -> object:
    """An indirect reference's target; any other value unchanged."""
    return value.get_object() if isinstance(value, PdfObject) else value


def _encoding(filters: object) -> str:
    """The encoding an image is stored in: the last filter applied, by name."""
    resolved = _resolve(filters)
    if isinstance(resolved, ArrayObject):
        resolved = _resolve(resolved[-1]) if resolved else None
    if resolved is None:
        return "none"
    return _ENCODINGS.get(str(resolved), "other")


def _images(resources: object, seen: set[int]) -> Iterator[str]:
    """One encoding per image the resources draw, following forms; each object counted once.

    ``DictionaryObject.get`` and ``.values()`` return references unresolved (checked on
    pypdf 6.19), so every value is resolved here explicitly.
    """
    resolved = _resolve(resources)
    if not isinstance(resolved, DictionaryObject):
        return
    xobjects = _resolve(resolved.get("/XObject"))
    if not isinstance(xobjects, DictionaryObject):
        return
    for value in xobjects.values():
        if isinstance(value, IndirectObject):
            if value.idnum in seen:
                continue
            seen.add(value.idnum)
        target = _resolve(value)
        if not isinstance(target, DictionaryObject):
            continue
        subtype = target.get("/Subtype")
        if subtype == "/Image":
            yield _encoding(target.get("/Filter"))
        elif subtype == "/Form":
            yield from _images(target.get("/Resources"), seen)


def page_facts(page: PageObject) -> PageFacts:
    """Characters of extractable text, images drawn, rotation and the encodings present."""
    try:
        chars = len((page.extract_text() or "").strip())
        encodings = list(_images(page.get("/Resources"), set()))
        rotation = page.rotation % 360
    except Exception:  # a broken page is counted, flagged and never fatal to the document
        return PageFacts(chars=0, images=0, rotation=0, encodings=(), failed=True)
    return PageFacts(
        chars=chars,
        images=len(encodings),
        rotation=rotation,
        encodings=tuple(sorted(set(encodings))),
    )


def document_facts(data: bytes) -> tuple[PageFacts, ...]:
    """Every page's facts; a file pypdf cannot open raises ``DocketError``, as in extract."""
    try:
        pages = list(PdfReader(io.BytesIO(data)).pages)
    except Exception as error:  # the same boundary as extract.extract_pdf
        raise DocketError(f"not a PDF: {error}") from error
    return tuple(page_facts(page) for page in pages)
```

- [x] **Step 5: Run the tests to see them pass**

Run: `uv run pytest tests/test_docket_pages.py -v`
Expected: PASS, 7 tests.

- [x] **Step 6: Write the failing tests for the script**

`tests/test_page_kinds.py`:

```python
"""scripts/page_kinds.py: counts only, development only, never a fetch (S2.6 §6.2 step 1)."""

import json
import re
from pathlib import Path

import pytest

from ntsb_probable_cause.docket.pages import PageFacts, document_facts
from scripts import page_kinds
from tests.pdf_builder import PageSpec, build_pdf


def _facts(chars: int, images: int = 0, rotation: int = 0, *encodings: str) -> PageFacts:
    return PageFacts(chars=chars, images=images, rotation=rotation, encodings=encodings)


def test_tally_counts_kinds_by_stratum_and_image_only_details() -> None:
    tally = page_kinds.Tally()
    tally.add_document(
        "fatal",
        (
            _facts(400),
            _facts(0, 1, 90, "fax (CCITT)"),
            _facts(0, 6, 0, "JPEG"),
            _facts(400, 1, 0, "JPEG"),
        ),
    )
    tally.add_document("non-fatal", (_facts(0), _facts(400)))
    assert tally.pages[("fatal", "image only")] == 2
    assert tally.pages[("non-fatal", "blank")] == 1
    assert tally.rotated["fatal"] == 1
    assert tally.tiled["fatal"] == 1
    assert tally.encodings["fax (CCITT)"] == 1
    assert tally.mixed_documents == 1  # the fatal document mixes three non-blank kinds
    assert tally.pdfs == 2


def test_report_holds_counts_and_no_case_number() -> None:
    tally = page_kinds.Tally()
    tally.cases.update({"fatal": 1})
    tally.add_document("fatal", (_facts(0, 1, 0, "JPEG"),))
    text = page_kinds.report(tally, "dev-400")
    assert "image only" in text
    assert "## limits" in text
    assert not re.search(r"\b[A-Z]{3}\d{2}[A-Z]{2}\d{3}[A-Z]?\b", text)  # no case number


def test_held_out_samples_are_refused() -> None:
    with pytest.raises(SystemExit, match="development"):
        page_kinds.main(["--sample", "heldout-400"])


def test_frame_rows_carry_the_page_and_its_kind(tmp_path: Path) -> None:
    rows = page_kinds.frame_rows(
        case_id="X1", mkey=7, fatal=True, document=2, facts=(_facts(0, 1, 0, "JPEG"),)
    )
    assert rows == [
        {
            "case_id": "X1",
            "mkey": 7,
            "fatal": True,
            "document": 2,
            "page": 1,
            "pages": 1,
            "kind": "image only",
            "chars": 0,
            "images": 1,
            "rotation": 0,
            "encodings": ["JPEG"],
            "photo_only": False,
        }
    ]
    out = tmp_path / "frame.jsonl"
    page_kinds.write_frame(out, rows)
    assert json.loads(out.read_text().splitlines()[0])["kind"] == "image only"


def test_document_facts_of_a_built_pdf_feed_the_tally() -> None:
    tally = page_kinds.Tally()
    tally.add_document("fatal", document_facts(build_pdf([PageSpec(images=("/JPXDecode",))])))
    assert tally.encodings["JPEG 2000"] == 1


def test_photo_only_documents_are_counted_apart_and_framed_as_such() -> None:
    """Decision W2: fetched photo-only documents never change S2's page-kind counts."""
    tally = page_kinds.Tally()
    tally.add_photo_document("fatal", (_facts(0, 1, 0, "JPEG"), _facts(0, 1, 0, "JPEG")))
    assert tally.photo_pages[("fatal", "image only")] == 2
    assert tally.pages == Counter()
    assert tally.photo_pdfs == 1
    (row,) = page_kinds.frame_rows(
        case_id="X1", mkey=7, fatal=True, document=5, facts=(_facts(0, 1),), photo_only=True
    )
    assert row["photo_only"] is True
```

(add `from collections import Counter` to the imports.)

- [x] **Step 7: Run them to see them fail**

Run: `uv run pytest tests/test_page_kinds.py -v`
Expected: FAIL — `ImportError: cannot import name 'page_kinds' from 'scripts'`.

- [x] **Step 8: Implement `scripts/page_kinds.py`**

```python
"""The kinds of page in a development sample's cached dockets: counts only (S2.6 §1, §5.2).

Status
    Live tool (S2.6, spec §6.2 step 1). ``make page-kinds`` (added in Task 6; until then run
    the command below) writes ``docs/results/s26-page-kinds.txt`` from the ``dev-400``
    docket cache, and the page frame the inventory and the transcriber test sample from,
    ``data/s26/pages-dev-400.jsonl``. The frame names cases, so it lives under ``data/``
    and is never committed. Every page-kind number in the S2.6 As-built record cites the
    results file; the design session's figures (spec §1, §5.2) were ad hoc, and where the
    two differ this one stands.

Reads the cache only -- a transport that refuses every request makes a cache miss loud and
free -- with one exception: ``--include-photo-only`` fetches the photo-only documents S2
never downloaded (decision W2, Andy, 2026-09-24), politely (the 2-second floor) into the
same cache, and counts and frames their pages apart from S2's, so the S2 figures above them
are unchanged. Development samples only: the frame would otherwise list held-out pages, and
no held-out page is inspected (spec §17).

Run: ``uv run python -m scripts.page_kinds [--sample dev-400] [--include-photo-only]
[--out PATH] [--frame PATH]``.
"""

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.listing import parse_listing
from ntsb_probable_cause.docket.pages import (
    TILED_MIN_IMAGES,
    PageFacts,
    PageKind,
    document_facts,
)
from ntsb_probable_cause.errors import DocketError
from ntsb_probable_cause.scoring.samples import load_cases, sample_ids
from ntsb_probable_cause.settings import Settings

KINDS: tuple[PageKind, ...] = ("text only", "image only", "text and image", "blank")
STRATA = ("fatal", "non-fatal")
ENCODING_ORDER = ("fax (CCITT)", "JPEG 2000", "JBIG2", "JPEG", "Flate", "other", "none")


def _offline() -> httpx.BaseTransport:
    """A transport refusing every request, so a cache miss is loud and costs no fetch."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline: this measurement reads the cache only")

    return httpx.MockTransport(refuse)


@dataclass
class Tally:
    """Page and document counts, accumulated over the sample."""

    cases: Counter[str] = field(default_factory=Counter)
    pdfs: int = 0
    mixed_documents: int = 0
    pages: Counter[tuple[str, PageKind]] = field(default_factory=Counter)
    rotated: Counter[str] = field(default_factory=Counter)
    tiled: Counter[str] = field(default_factory=Counter)
    encodings: Counter[str] = field(default_factory=Counter)
    failed_pages: int = 0
    photo_only_entries: Counter[str] = field(default_factory=Counter)
    photo_only_pages: Counter[str] = field(default_factory=Counter)
    photo_pdfs: int = 0
    photo_pages: Counter[tuple[str, PageKind]] = field(default_factory=Counter)
    not_cached: int = 0
    fetch_failed: int = 0
    not_pdf: int = 0

    def add_photo_document(self, stratum: str, facts: Sequence[PageFacts]) -> None:
        """Count a fetched photo-only document's pages apart from S2's documents (W2)."""
        self.photo_pdfs += 1
        for page in facts:
            self.photo_pages[(stratum, page.kind)] += 1

    def add_document(self, stratum: str, facts: Sequence[PageFacts]) -> None:
        """Count one PDF's pages; image-only pages also by rotation, pieces and encoding."""
        self.pdfs += 1
        if len({f.kind for f in facts if f.kind != "blank"}) > 1:
            self.mixed_documents += 1
        for page in facts:
            self.pages[(stratum, page.kind)] += 1
            self.failed_pages += page.failed
            if page.kind != "image only":
                continue
            self.rotated[stratum] += page.rotation != 0
            self.tiled[stratum] += page.images >= TILED_MIN_IMAGES
            self.encodings.update(page.encodings)


def frame_rows(  # noqa: PLR0913 -- one keyword per fact a frame row records.
    *,
    case_id: str,
    mkey: int,
    fatal: bool,
    document: int,
    facts: Sequence[PageFacts],
    photo_only: bool = False,
) -> list[dict[str, object]]:
    """One private frame row per page: where it is, and its counts. Never its text."""
    return [
        {
            "case_id": case_id,
            "mkey": mkey,
            "fatal": fatal,
            "document": document,
            "page": n,
            "pages": len(facts),
            "kind": page.kind,
            "chars": page.chars,
            "images": page.images,
            "rotation": page.rotation,
            "encodings": list(page.encodings),
            "photo_only": photo_only,
        }
        for n, page in enumerate(facts, start=1)
    ]


def write_frame(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    """Write the frame as JSON lines, replacing any earlier one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def sweep(
    records: Sequence[Mapping[str, object]],
    client: DocketClient,
    *,
    fetch_photo_only: DocketClient | None = None,
) -> tuple[Tally, list[dict[str, object]]]:
    """Every cached PDF of every case: counted, and listed page by page in the frame.

    With ``fetch_photo_only`` (a client allowed to fetch, politely), photo-only PDF entries
    are fetched too, and counted and framed apart (decision W2).
    """
    tally = Tally()
    rows: list[dict[str, object]] = []
    for raw in records:
        mkey = raw.get("mKey")
        fatal = raw.get("highestInjuryLevel") == "Fatal"
        stratum = STRATA[0] if fatal else STRATA[1]
        tally.cases[stratum] += 1
        if not isinstance(mkey, int):
            tally.not_cached += 1
            continue
        try:
            listing = parse_listing(client.listing_html(mkey), mkey=mkey)
        except DocketError:
            tally.not_cached += 1
            continue
        for entry in listing.entries:
            photo_only = entry.is_photo_only()
            if photo_only:
                tally.photo_only_entries[stratum] += 1
                tally.photo_only_pages[stratum] += entry.pages
                if fetch_photo_only is None:
                    continue
            if not entry.is_pdf():
                continue
            source = fetch_photo_only if photo_only and fetch_photo_only else client
            try:
                data = source.document(mkey, entry.index, entry.href)
            except DocketError:
                tally.fetch_failed += 1
                continue
            try:
                facts = document_facts(data)
            except DocketError:
                tally.not_pdf += 1
                continue
            if photo_only:
                tally.add_photo_document(stratum, facts)
            else:
                tally.add_document(stratum, facts)
            rows.extend(
                frame_rows(
                    case_id=str(raw["ntsbNumber"]),
                    mkey=mkey,
                    fatal=fatal,
                    document=entry.index,
                    facts=facts,
                    photo_only=photo_only,
                )
            )
    return tally, rows


def _row(label: str, counts: Mapping[str, int]) -> str:
    total = sum(counts.get(s, 0) for s in STRATA)
    fatal, non_fatal = counts.get("fatal", 0), counts.get("non-fatal", 0)
    return f"  {label:<16} {total:7d} {fatal:9d} {non_fatal:11d}"


def report(tally: Tally, sample: str) -> str:
    """The measurement, as docs/results/s26-page-kinds.txt holds it."""
    by_kind = {kind: {s: tally.pages[(s, kind)] for s in STRATA} for kind in KINDS}
    totals = {s: sum(by_kind[k][s] for k in KINDS) for s in STRATA}
    image_bearing = sum(sum(by_kind[k].values()) for k in ("image only", "text and image"))
    cases = sum(tally.cases.values())
    lines = [
        "# page kinds in the development dockets (S2.6 spec §1, §5.2) -- counts only",
        f"sample {sample}: {cases} cases (fatal {tally.cases['fatal']}, "
        f"non-fatal {tally.cases['non-fatal']}); PDFs read from the cache: {tally.pdfs}",
        f"no cached listing: {tally.not_cached}; document fetch failed: {tally.fetch_failed}; "
        f"not a PDF: {tally.not_pdf}; pages that failed to parse (counted blank): "
        f"{tally.failed_pages}",
        "a page with fewer than 50 characters of extractable text has no usable text layer",
        "(classify.SCAN_PAGE_MAX_CHARS); an image is any image the page's resources draw",
        "",
        "## pages by kind",
        f"  {'kind':<16} {'all':>7} {'fatal':>9} {'non-fatal':>11}",
        *(_row(kind, by_kind[kind]) for kind in KINDS),
        _row("total", totals),
        f"image-bearing pages (image only + text and image): {image_bearing}"
        f" (mean per case: {image_bearing / cases if cases else 0:.1f})",
        "",
        "## documents",
        f"  PDFs mixing more than one kind of non-blank page: {tally.mixed_documents}"
        f" of {tally.pdfs}",
        "",
        "## image-only pages: why pulling the image out would fail (spec §5.2)",
        _row("rotated", tally.rotated) + "   (90, 180 or 270 degrees)",
        _row(f"{TILED_MIN_IMAGES}+ images", tally.tiled),
        "  by encoding (a page counts once for each encoding it holds): "
        + ", ".join(f"{name} {tally.encodings[name]}" for name in ENCODING_ORDER),
        "",
        "## photo-only listing entries (S2's read_docket skips them; fetched for S2.6, W2)",
        _row("entries", tally.photo_only_entries),
        _row("declared pages", tally.photo_only_pages),
        f"  fetched and read: {tally.photo_pdfs} PDFs; their pages by kind:",
        *(
            _row(kind, {s: tally.photo_pages[(s, kind)] for s in STRATA})
            for kind in KINDS
        ),
        "",
        "## limits",
        "- an inline image (drawn in the content stream rather than as a resource) is not",
        "  counted, so a page built only from inline images reads as text only or blank;",
        "- text is pypdf's extract_text, as the docket tool reads it (decision 0047);",
        "- the counts above the photo-only section are S2's documents only, so they compare",
        "  with the design session's; photo-only pages are counted in their own section.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Count page kinds over a development sample's cached dockets."""
    parser = argparse.ArgumentParser(prog="page_kinds")
    parser.add_argument("--sample", default="dev-400")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--frame", type=Path)
    parser.add_argument("--include-photo-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.sample.startswith("dev"):
        raise SystemExit(f"{args.sample}: page kinds are counted on development samples only")
    settings = Settings()
    client = DocketClient(settings.docket_dir, transport=_offline())
    polite = (
        DocketClient(
            settings.docket_dir, seconds_per_request=settings.docket_seconds_per_request
        )
        if args.include_photo_only
        else None
    )
    records = load_cases(settings.data_dir / "processed", sample_ids(args.sample))
    tally, rows = sweep(records, client, fetch_photo_only=polite)
    text = report(tally, args.sample)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    frame = args.frame or settings.data_dir / "s26" / f"pages-{args.sample}.jsonl"
    write_frame(frame, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 9: Run the tests, then the whole check**

Run: `uv run pytest tests/test_docket_pages.py tests/test_page_kinds.py -v`, then `make check`
Expected: PASS; `make check` green. If `sweep` is below the coverage gate, add a test that writes a one-case cache into `tmp_path` in `DocketClient`'s layout (`<mkey>/listing.html`, `<mkey>/<index>.bin`, `<mkey>/fetch.json` with each file's `sha256` and `href`; copy the shape from `tests/fixtures/docket/ERA17LA217/`) and runs `sweep` with the offline transport. Fix any vulture or deptry finding at its cause; never whitelist.

- [x] **Step 10: Run the script on `dev-400`** (free; reads the local cache and politely fetches the 146 photo-only PDFs, about 5 minutes of it at the 2-second floor; about 15–25 minutes in all)

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
uv run python -m scripts.page_kinds --sample dev-400 --include-photo-only --out docs/results/s26-page-kinds.txt
```

Expected: `no cached listing: 0` (the S2 docket scan cached all 401), no `offline:` error, and `fetched and read:` close to the ad-hoc 146 photo-only PDFs (any fetch failure is counted on the `document fetch failed` line). Afterwards the tree holds one new file, `docs/results/s26-page-kinds.txt`; the frame is under `data/`, outside git. Compare the four kind totals with spec §1's ad-hoc figures (5,006 / 3,281 / 8,403 / 109) and the image-only details with §5.2's (527 rotated, 200 tiled, 929 fax, 250 JPEG 2000, 54 JBIG2); log every difference in Deviations. The scripted numbers stand.

- [x] **Step 11: Commit**

```bash
git add src/ntsb_probable_cause/docket/pages.py scripts/page_kinds.py tests/pdf_builder.py tests/test_docket_pages.py tests/test_page_kinds.py docs/results/s26-page-kinds.txt docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: page facts and the dev-400 page-kind counts (spec §6.2 step 1)"
```

- [ ] **Step 12: STOP — report the page kinds and the photo-only pages to Andy**

In plain words, with a glossary: the four kind totals against the design session's, and what the fetched photo-only documents hold (W2 is decided: they are in).

---

### Task 2: The analysis-sentence hand-check (spec §4.2, decision 0077 item 4; no model, no cost)

**Files:**
- Create: `scripts/marking_page.py` (the private, offline marking page every S2.6 hand-check uses: this one, Andy's 60 inventory labels, the handwriting key and the invented-words review)
- Create: `scripts/analysis_handcheck.py`
- Create: `tests/test_marking_page.py`, `tests/test_analysis_handcheck.py`
- Output: `data/handcheck/s26-analysis/index.html` and `data/handcheck/s26-analysis/sheet.csv` (private, never committed); `docs/results/s26-analysis-handcheck.txt` (committed, counts only)
- Modify (after Andy marks): `docs/decisions/0077-analysis-sentences-in-docket-documents-mark-the-case.md` (an appended, dated result note), `docs/decisions/README.md` (0077's status cell)

**Interfaces:**
- Consumes: `records.split.split_record`, `records.guard.find_leaks`, `records.guard.normalise_text`, `docket.attach.prepare_attachment`, `scoring.runner.CachedDocketReader`, `scoring.metrics.wilson`.
- Produces: `scripts.marking_page.Choice(name: str, options: tuple[str, ...], required: bool = True)`, `scripts.marking_page.Card(row: int, body_html: str, choices: tuple[Choice, ...] = (), text_fields: tuple[tuple[str, str], ...] = ())` (a text field is `(name, prefilled value)`), `scripts.marking_page.render(*, title: str, intro_html: str, cards: Sequence[Card], storage_key: str, csv_name: str) -> str`, `scripts.marking_page.read_marks(path: Path) -> dict[int, dict[str, str]]`. The downloaded CSV has a `row` column and one column per field name, in first-seen order. Tasks 12 and 13 reuse all four.
- Produces: `scripts.analysis_handcheck.SheetRow` (frozen dataclass: `case_id: str`, `document: int`, `title: str`, `category: str`, `sentence: str`, `before: str`, `after: str`, `cause_in_case: bool`); `sheet_rows(raw, docket) -> list[SheetRow]`; `score(rows: Sequence[Mapping[str, str]], marks: Mapping[int, str]) -> str`; `MAX_CONCLUSIONS = 5`; `EXPECTED_ROWS = 36`. Task 5 reads the results file's `outcome:` line.

**What Andy sees, and why.** Each card is one matched sentence, shown inside about 300 characters of the document text on each side, with the document's listing title and category. The text is shown as the tripwire compares it — lower case, whitespace collapsed — because that is the form in which it matched. The one question: *does this sentence quote evidence, or is it a conclusion sitting in the docket?* An example of "quotes evidence": a wreckage examination that reads "…examination of the engine revealed no mechanical anomalies that would have precluded normal operation…". An example of "conclusion in the docket": a party's letter that reads "…the loss of power was the result of the pilot's mismanagement of the fuel system…". The sentence is withheld text, so the page and the sheet stay under `data/`. Andy marks by clicking, never in a spreadsheet (marking 60 rows in a spreadsheet was reported unworkable twice in S2; `scripts/handcheck_page.py`).

- [ ] **Step 1: Write the failing tests for the marking page**

`tests/test_marking_page.py`:

```python
"""scripts/marking_page.py: an offline page, fields by name, a CSV Andy downloads."""

from pathlib import Path

from scripts import marking_page
from scripts.marking_page import Card, Choice


def test_the_page_carries_every_card_choice_and_prefilled_text() -> None:
    cards = [
        Card(row=1, body_html="<p>one</p>", choices=(Choice("mark", ("right", "wrong")),)),
        Card(row=2, body_html="<p>two</p>", text_fields=(("key", "line one\nline two"),)),
    ]
    page = marking_page.render(
        title="A check", intro_html="<p>intro</p>", cards=cards, storage_key="k1", csv_name="m.csv"
    )
    assert '<div class="card" data-row="1"' in page
    assert 'value="right"' in page and 'value="wrong"' in page
    assert "line one\nline two</textarea>" in page
    assert '"k1"' in page and '"m.csv"' in page
    assert '["mark", "key"]' in page


def test_an_optional_choice_does_not_hold_a_card_back() -> None:
    card = Card(
        row=1,
        body_html="",
        choices=(Choice("label", ("right", "wrong")), Choice("correct", ("a", "b"), required=False)),
    )
    page = marking_page.render(
        title="t", intro_html="", cards=[card], storage_key="k", csv_name="c.csv"
    )
    assert 'data-required="[&quot;label&quot;]"' in page


def test_prefilled_text_is_escaped() -> None:
    card = Card(row=1, body_html="", text_fields=(("key", "</textarea><script>x</script>"),))
    page = marking_page.render(
        title="t", intro_html="", cards=[card], storage_key="k", csv_name="c.csv"
    )
    assert "<script>x</script>" not in page


def test_read_marks_by_row(tmp_path: Path) -> None:
    path = tmp_path / "marks.csv"
    path.write_text('row,mark,notes\n1,"right",""\n2,"","later"\n')
    assert marking_page.read_marks(path) == {
        1: {"mark": "right", "notes": ""},
        2: {"mark": "", "notes": "later"},
    }
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_marking_page.py -v`
Expected: FAIL — `ImportError: cannot import name 'marking_page' from 'scripts'`.

- [ ] **Step 3: Implement `scripts/marking_page.py`**

```python
"""A private, offline marking page: cards, choices, text fields, and a CSV of the marks.

Status
    Live helper (S2.6). Every S2.6 hand-check renders through this: the analysis sentences
    (Task 2), the 60 inventory labels (Task 12), the handwriting answer key and the
    invented-words review (Task 13). The pages hold private material and are written under
    ``data/`` only, never committed.

Andy marks by clicking, never in a spreadsheet (reported unworkable twice in S2; see
``scripts/handcheck_page.py``). The page is one self-contained file opened with
``file://``: no server, no network. Marks are kept in the browser as they are made, so a
reload loses nothing; the CSV is built from the page itself when Andy downloads it, so a
prefilled text field he never touched still exports its prefilled value.

The caller escapes every piece of text it puts into ``body_html``; this module escapes the
values it places itself (choices, prefilled text).
"""

import csv
import html
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from string import Template


@dataclass(frozen=True)
class Choice:
    """One question answered by picking one option (radio buttons).

    A card counts as marked when every ``required`` choice is answered; an optional one
    (for example "the right label, if the shown one is wrong") may stay empty.
    """

    name: str
    options: tuple[str, ...]
    required: bool = True


@dataclass(frozen=True)
class Card:
    """One item to mark: its body, its choices and its text fields ``(name, prefilled)``."""

    row: int
    body_html: str
    choices: tuple[Choice, ...] = ()
    text_fields: tuple[tuple[str, str], ...] = ()


_PAGE = Template(
    """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>$title</title>
<style>
body{font-family:system-ui,sans-serif;max-width:72rem;margin:2rem auto;padding:0 1rem;
line-height:1.5}
.card{border:1px solid #bbb;border-radius:6px;padding:1rem;margin:1rem 0}
mark{background:#fde68a}.meta{color:#555;font-size:.9rem}
img{max-width:100%;border:1px solid #ddd}
textarea{width:100%;min-height:3rem;font-family:ui-monospace,monospace}
pre{white-space:pre-wrap;background:#f6f6f6;padding:.5rem}
</style></head><body>
<h1>$title</h1>
$intro
<p id="progress"></p>
$cards
<button type="button" id="download">Download marks as CSV</button>
<script>
var KEY = $key;
var FIELDS = $fields;
var CSV_NAME = $csv;
$script
</script>
</body></html>
"""
)

_SCRIPT = """
function load() {
  try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { return {}; }
}
function save(m) { try { localStorage.setItem(KEY, JSON.stringify(m)); } catch (e) {} }
var marks = load();
var cards = document.querySelectorAll(".card");
function set(row, name, value) {
  marks[row] = marks[row] || {}; marks[row][name] = value; save(marks); progress();
}
function done(card) {
  var names = JSON.parse(card.dataset.required);
  return names.every(function (n) {
    return card.querySelector('input[data-field="' + n + '"]:checked') !== null;
  });
}
function progress() {
  var n = 0;
  cards.forEach(function (c) { if (done(c)) { n++; } });
  document.getElementById("progress").textContent = n + " of " + cards.length + " marked";
}
cards.forEach(function (card) {
  var row = card.dataset.row;
  card.querySelectorAll("[data-field]").forEach(function (el) {
    var name = el.dataset.field;
    var saved = (marks[row] || {})[name];
    if (el.type === "radio") {
      if (saved === el.value) { el.checked = true; }
      el.addEventListener("change", function () { set(row, name, el.value); });
    } else {
      if (saved !== undefined) { el.value = saved; }
      el.addEventListener("input", function () { set(row, name, el.value); });
    }
  });
});
progress();
function quote(s) { return '"' + String(s || "").replace(/"/g, '""') + '"'; }
function value(card, name) {
  var checked = card.querySelector('input[data-field="' + name + '"]:checked');
  if (checked) { return checked.value; }
  var text = card.querySelector('textarea[data-field="' + name + '"]');
  return text ? text.value : "";
}
document.getElementById("download").addEventListener("click", function () {
  var lines = [["row"].concat(FIELDS).join(",")];
  cards.forEach(function (c) {
    var cells = [c.dataset.row].concat(FIELDS.map(function (f) { return quote(value(c, f)); }));
    lines.push(cells.join(","));
  });
  var blob = new Blob([lines.join("\\n") + "\\n"], { type: "text/csv" });
  var a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = CSV_NAME;
  a.click();
});
"""


def _card(card: Card) -> str:
    esc = html.escape
    fieldsets = "".join(
        f"<fieldset><legend>{esc(choice.name)}</legend>"
        + " ".join(
            f'<label><input type="radio" name="r{card.row}-{esc(choice.name)}" '
            f'data-field="{esc(choice.name)}" value="{esc(option)}"> {esc(option)}</label>'
            for option in choice.options
        )
        + "</fieldset>"
        for choice in card.choices
    )
    areas = "".join(
        f'<label>{esc(name)}<textarea data-field="{esc(name)}">{esc(value)}</textarea></label>'
        for name, value in card.text_fields
    )
    required = esc(json.dumps([choice.name for choice in card.choices if choice.required]))
    return (
        f'<div class="card" data-row="{card.row}" data-required="{required}">'
        f"{card.body_html}{fieldsets}{areas}</div>"
    )


def render(
    *, title: str, intro_html: str, cards: Sequence[Card], storage_key: str, csv_name: str
) -> str:
    """The self-contained page. Field names become CSV columns in first-seen order."""
    names: list[str] = []
    for card in cards:
        for name in [c.name for c in card.choices] + [n for n, _ in card.text_fields]:
            if name not in names:
                names.append(name)
    return _PAGE.substitute(
        title=html.escape(title),
        intro=intro_html,
        cards="\n".join(_card(card) for card in cards),
        key=json.dumps(storage_key),
        fields=json.dumps(names),
        csv=json.dumps(csv_name),
        script=_SCRIPT,
    )


def read_marks(path: Path) -> dict[int, dict[str, str]]:
    """A downloaded CSV, by row number: every field's value, empty where unmarked."""
    with path.open(newline="") as handle:
        return {
            int(row["row"]): {k: v for k, v in row.items() if k != "row"}
            for row in csv.DictReader(handle)
        }
```

- [ ] **Step 4: Run them to see them pass**

Run: `uv run pytest tests/test_marking_page.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Write the failing tests for the hand-check**

`tests/test_analysis_handcheck.py` (the docket is built from the manifest's own models, so no network and no real case is involved; the narrative is invented):

```python
"""scripts/analysis_handcheck.py: a private marking page, and counts-only scoring (0077)."""

import copy

import pytest

from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord
from scripts import analysis_handcheck

QUOTED = (
    "Examination of the engine revealed no mechanical anomalies"
    " that would have precluded normal operation."
)
ANALYSIS = QUOTED + " The pilot did not use the checklist before the flight."
CONCLUDED = "conclusion in the docket"


def _docket(text: str) -> Docket:
    entry = ListingEntry(
        index=1,
        title="Engine Examination Summary",
        pages=1,
        photos=0,
        doc_type="PDF",
        extension="pdf",
        href="x",
    )
    record = DocumentRecord(
        entry=entry,
        category="exam_site",
        status="read",
        pages=1,
        readable_pages=1,
        estimated_tokens=10,
        kind="born-digital",
    )
    return Docket(
        mkey=7,
        listing=Listing(mkey=7, declared_items=1, entries=(entry,)),
        documents=(record,),
        texts={1: text},
    )


def _raw(record_fixtures: list[dict[str, object]]) -> dict[str, object]:
    raw = copy.deepcopy(record_fixtures[0])
    narratives = raw["narratives"]
    assert isinstance(narratives, list)
    narratives[0]["analysisNarrative"] = ANALYSIS
    return raw


def test_a_shared_analysis_sentence_becomes_one_row_with_context(
    record_fixtures: list[dict[str, object]],
) -> None:
    text = f"[page 1 of 1]\nThe inspector noted fuel in both tanks. {QUOTED} The magneto held."
    rows = analysis_handcheck.sheet_rows(_raw(record_fixtures), _docket(text))
    assert len(rows) == 1
    (row,) = rows
    assert row.sentence.startswith("examination of the engine revealed")
    assert "fuel in both tanks" in row.before
    assert "magneto held" in row.after
    assert row.title == "Engine Examination Summary"
    assert row.category == "exam_site"


def test_a_document_without_a_shared_sentence_gives_no_row(
    record_fixtures: list[dict[str, object]],
) -> None:
    rows = analysis_handcheck.sheet_rows(_raw(record_fixtures), _docket("[page 1 of 1]\nNothing."))
    assert rows == []


def test_the_page_escapes_text_and_offers_the_two_marks() -> None:
    row = analysis_handcheck.SheetRow(
        case_id="X1",
        document=1,
        title="<b>Title</b>",
        category="other",
        sentence="a <script>sentence</script>",
        before="",
        after="",
        cause_in_case=False,
    )
    page = analysis_handcheck.render_page([row])
    assert "<script>sentence" not in page
    assert "&lt;script&gt;" in page
    assert 'value="quotes evidence"' in page and f'value="{CONCLUDED}"' in page


def _sheet(n: int) -> list[dict[str, str]]:
    return [
        {"row": str(i), "category": "exam_site", "case_id": f"C{i % 17}"}
        for i in range(1, n + 1)
    ]


def _marks(conclusions: int) -> dict[int, str]:
    marks = {i: "quotes evidence" for i in range(1, 37)}
    return marks | {i: CONCLUDED for i in range(1, conclusions + 1)}


def test_score_adopts_the_rule_at_five_conclusions() -> None:
    text = analysis_handcheck.score(_sheet(36), _marks(5))
    assert f"{CONCLUDED:<28} {5:3d}" in text
    assert "outcome: adopted" in text


def test_score_does_not_adopt_at_six_conclusions() -> None:
    text = analysis_handcheck.score(_sheet(36), _marks(6))
    assert "outcome: not adopted" in text


def test_score_refuses_the_rule_when_the_sheet_is_not_the_36() -> None:
    marks = {i: "quotes evidence" for i in range(1, 36)}
    text = analysis_handcheck.score(_sheet(35), marks)
    assert "outcome: not applied" in text


def test_score_refuses_an_unmarked_row() -> None:
    with pytest.raises(SystemExit, match="unmarked"):
        analysis_handcheck.score(_sheet(36), {i: "quotes evidence" for i in range(1, 36)})
```

- [ ] **Step 6: Run them to see them fail**

Run: `uv run pytest tests/test_analysis_handcheck.py -v`
Expected: FAIL — `ImportError: cannot import name 'analysis_handcheck' from 'scripts'`.

- [ ] **Step 7: Implement `scripts/analysis_handcheck.py`**

```python
"""The analysis-sentence hand-check: Andy's marking page, and its scorer (S2.6 §4.2, 0077).

Status
    One-shot (S2.6). ``sheet`` writes a private marking page and sheet under
    ``data/handcheck/s26-analysis/`` for the ``dev-400`` docket sentences the tripwire
    matches to the analysis narrative (36 in 17 cases, ``docs/results/s2-docket-leak.txt``).
    ``score`` reads the marks Andy downloads from that page and writes
    ``docs/results/s26-analysis-handcheck.txt``, counts only. Decision 0077 takes effect only
    if 5 or fewer of the 36 are conclusions.

The sheet holds withheld text -- the matched analysis sentences -- so it lives under
``data/`` and is never committed (spec §4.2). Each sentence is shown inside the document
text around it, as the tripwire compares it (lower case, whitespace collapsed), with the
document's listing title, and one question: does this sentence quote evidence, or is it a
conclusion sitting in the docket?

Run:
    uv run python -m scripts.analysis_handcheck sheet [--sample dev-400]
    uv run python -m scripts.analysis_handcheck score <marks.csv> [--out PATH]
"""

import argparse
import csv
import html
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from ntsb_probable_cause.docket.attach import prepare_attachment
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.manifest import Docket
from ntsb_probable_cause.errors import DocketError, LeakageError
from ntsb_probable_cause.fields import EvidenceRole, SynthesisRole, VerdictRole
from ntsb_probable_cause.records.guard import find_leaks, normalise_text
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring.metrics import wilson
from ntsb_probable_cause.scoring.runner import CachedDocketReader
from ntsb_probable_cause.scoring.samples import load_cases, sample_ids
from ntsb_probable_cause.settings import Settings
from scripts import marking_page
from scripts.marking_page import Card, Choice

ANALYSIS = SynthesisRole.ANALYSIS_NARRATIVE.value
CAUSE = VerdictRole.PROBABLE_CAUSE.value
DOCUMENTS = EvidenceRole.DOCKET_DOCUMENTS.value
CONTEXT_CHARS = 300
NO_SENTENCES = 10**9
# Spec §4.2 and decision 0077 item 4: "If 5 or fewer of the 36 are conclusions".
MAX_CONCLUSIONS = 5
EXPECTED_ROWS = 36
QUOTES, CONCLUSION = "quotes evidence", "conclusion in the docket"
MARKS = (QUOTES, CONCLUSION)
FOLDER = Path("handcheck") / "s26-analysis"
INTRO = (
    "<p>Each card shows one sentence (highlighted) that a docket document shares with the "
    "investigators' analysis narrative, inside the document text around it. The text is lower "
    "case because that is how the guard compares it. Mark each one: does the sentence "
    "<b>quote evidence</b> (a record of what was seen, measured or said), or is it a "
    "<b>conclusion in the docket</b> (a judgement about why the accident happened)? Marks save "
    "in this browser as you go. Download the CSV when you are done.</p>"
)


@dataclass(frozen=True)
class SheetRow:
    """One matched sentence, where it sits, and the text around it. Private."""

    case_id: str
    document: int
    title: str
    category: str
    sentence: str
    before: str
    after: str
    cause_in_case: bool


def _offline() -> httpx.BaseTransport:
    """A transport refusing every request, so a cache miss is loud and costs no fetch."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline: this hand-check reads the cache only")

    return httpx.MockTransport(refuse)


def sheet_rows(raw: Mapping[str, object], docket: Docket) -> list[SheetRow]:
    """Every analysis sentence one of the case's readable documents shares, once per case.

    Mirrors ``scripts/docket_leak_scan.py``: every readable document is attached, the split
    runs with sentence checks off so the case is not refused, and each document is compared
    alone so the row can name it. A sentence found in two documents is one row, under the
    first, because the 36 of ``s2-docket-leak.txt`` count sentences, not places.
    """
    readable = [r.entry.index for r in docket.documents if r.status == "read"]
    attachment = prepare_attachment(raw, docket)
    _, synthesis, verdict = split_record(
        attachment.context_for(readable).context, min_sentence_chars=NO_SENTENCES
    )
    analysis = synthesis.analysis_narrative
    if not analysis:
        return []
    joined = "\n".join(attachment.document_texts[i] for i in readable)
    cause_in_case = bool(
        verdict.probable_cause
        and find_leaks(
            {DOCUMENTS: joined}, {CAUSE: verdict.probable_cause}, (), exemptions=frozenset()
        )
    )
    seen: set[str] = set()
    rows: list[SheetRow] = []
    for index in readable:
        text = attachment.document_texts[index]
        haystack = normalise_text(text)
        leaks = find_leaks({DOCUMENTS: text}, {ANALYSIS: analysis}, (), exemptions=frozenset())
        for leak in leaks:
            if leak.kind != "sentence" or leak.fragment in seen:
                continue
            seen.add(leak.fragment)
            start = haystack.find(leak.fragment)
            end = start + len(leak.fragment)
            record = docket.record(index)
            rows.append(
                SheetRow(
                    case_id=str(raw["ntsbNumber"]),
                    document=index,
                    title=record.entry.title,
                    category=record.category,
                    sentence=leak.fragment,
                    before=haystack[max(0, start - CONTEXT_CHARS) : start],
                    after=haystack[end : end + CONTEXT_CHARS],
                    cause_in_case=cause_in_case,
                )
            )
    return rows


def _body(number: int, row: SheetRow) -> str:
    esc = html.escape
    cause = " · this case also holds a probable-cause sentence" if row.cause_in_case else ""
    return (
        f'<p class="meta">Row {number} · case {esc(row.case_id)} · docket item {row.document}: '
        f"{esc(row.title)} ({esc(row.category)}){cause}</p>"
        f"<p>…{esc(row.before)}<mark>{esc(row.sentence)}</mark>{esc(row.after)}…</p>"
    )


def render_page(rows: Sequence[SheetRow]) -> str:
    """The marking page: one card per sentence, the two marks, optional notes."""
    cards = [
        Card(
            row=number,
            body_html=_body(number, row),
            choices=(Choice("mark", MARKS),),
            text_fields=(("notes", ""),),
        )
        for number, row in enumerate(rows, start=1)
    ]
    return marking_page.render(
        title="Analysis-sentence hand-check (decision 0077)",
        intro_html=INTRO,
        cards=cards,
        storage_key="s26-analysis-handcheck",
        csv_name="analysis-handcheck-marks.csv",
    )


def write_sheet(folder: Path, rows: Sequence[SheetRow]) -> None:
    """The page and the full private sheet (row numbers match the page's)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text(render_page(rows))
    names = ["row", *(field for field in SheetRow.__dataclass_fields__)]
    with (folder / "sheet.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for number, row in enumerate(rows, start=1):
            writer.writerow({"row": number, **asdict(row)})


def score(rows: Sequence[Mapping[str, str]], marks: Mapping[int, str]) -> str:
    """Counts by mark and by document category, and the rule of 0077 item 4. No text."""
    numbers = [int(r["row"]) for r in rows]
    unmarked = [n for n in numbers if marks.get(n) not in MARKS]
    if unmarked:
        raise SystemExit(f"{len(unmarked)} rows are unmarked (e.g. row {unmarked[0]})")
    by_mark = Counter(marks[n] for n in numbers)
    by_category: Counter[tuple[str, str]] = Counter(
        (r["category"], marks[int(r["row"])]) for r in rows
    )
    conclusions = by_mark[CONCLUSION]
    total = len(numbers)
    low, high = wilson(conclusions, total)
    if total != EXPECTED_ROWS:
        outcome = (
            f"outcome: not applied -- the rule was written for {EXPECTED_ROWS} sentences and "
            f"this sheet holds {total}; returned to Andy"
        )
    elif conclusions <= MAX_CONCLUSIONS:
        outcome = "outcome: adopted -- decision 0077 takes effect"
    else:
        outcome = "outcome: not adopted -- returned to Andy, neutral-marker fallback (spec §4.2)"
    categories = sorted({c for c, _ in by_category})
    cases = len({r["case_id"] for r in rows})
    return "\n".join(
        [
            "# analysis-sentence hand-check (S2.6 spec §4.2, decision 0077 item 4) -- counts only",
            f"sample dev-400: {total} matched sentences in {cases} cases, each marked by Andy "
            "beside its document title",
            "the sentences themselves are withheld text and are not in this file",
            "",
            f"  {QUOTES:<28} {by_mark[QUOTES]:3d}",
            f"  {CONCLUSION:<28} {conclusions:3d}",
            "",
            "by document category (quotes evidence / conclusion in the docket):",
            *(
                f"  {c:<24} {by_category[(c, QUOTES)]:3d} / {by_category[(c, CONCLUSION)]:3d}"
                for c in categories
            ),
            "",
            f"the rule's measured error: {conclusions} of {total} sentences are conclusions "
            f"({conclusions / total:.1%} [{low:.1%}, {high:.1%}], Wilson 95%)",
            f"rule: adopt 0077 if {MAX_CONCLUSIONS} or fewer of {EXPECTED_ROWS} are conclusions",
            outcome,
        ]
    )


def main(argv: list[str] | None = None) -> int:
    """``sheet`` writes the private page; ``score`` writes the counts."""
    parser = argparse.ArgumentParser(prog="analysis_handcheck")
    commands = parser.add_subparsers(dest="command", required=True)
    sheet_p = commands.add_parser("sheet")
    sheet_p.add_argument("--sample", default="dev-400")
    score_p = commands.add_parser("score")
    score_p.add_argument("marks", type=Path)
    score_p.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    settings = Settings()
    folder = settings.data_dir / FOLDER
    if args.command == "sheet":
        if not args.sample.startswith("dev"):
            raise SystemExit("the hand-check reads development cases only")
        reader = CachedDocketReader(DocketClient(settings.docket_dir, transport=_offline()))
        rows: list[SheetRow] = []
        skipped = 0
        for raw in load_cases(settings.data_dir / "processed", sample_ids(args.sample)):
            mkey = raw.get("mKey")
            try:
                if not isinstance(mkey, int):
                    raise DocketError("no mKey")
                rows.extend(sheet_rows(raw, reader.read(mkey)))
            except (DocketError, LeakageError):
                skipped += 1
        write_sheet(folder, rows)
        cases = len({r.case_id for r in rows})
        print(f"{len(rows)} sentences in {cases} cases; {skipped} cases skipped; page at {folder}")
        return 0
    with (folder / "sheet.csv").open(newline="") as handle:
        sheet = list(csv.DictReader(handle))
    marks = {row: fields.get("mark", "") for row, fields in marking_page.read_marks(args.marks).items()}
    text = score(sheet, marks)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 8: Run the tests to see them pass, then the whole check**

Run: `uv run pytest tests/test_marking_page.py tests/test_analysis_handcheck.py -v`, then `make check`
Expected: PASS; green. If `main` pulls coverage under 90%, test `main(["sheet", "--sample", "heldout-400"])` raising `SystemExit`, and `main(["score", ...])` over a `tmp_path` sheet with `NTSB_DATA_DIR` monkeypatched.

- [ ] **Step 9: Commit the tools**

```bash
git add scripts/marking_page.py scripts/analysis_handcheck.py tests/test_marking_page.py tests/test_analysis_handcheck.py docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: an offline marking page, and the analysis-sentence hand-check (spec §4.2)"
```

- [ ] **Step 10: Write the sheet** (free; reads the local cache; a few minutes)

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
uv run python -m scripts.analysis_handcheck sheet --sample dev-400
```

Expected: `36 sentences in 17 cases; 0 cases skipped`. A different count is logged in Deviations and reported to Andy before he marks, because the score step will not apply the rule to it. Nothing in git changes.

- [ ] **Step 11: STOP — Andy marks the 36 sentences** (about 30–45 minutes)

Andy opens `/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/handcheck/s26-analysis/index.html` in a browser (it works offline), marks every card, and clicks **Download marks as CSV**. Tasks 3 and 4 do not depend on this and continue meanwhile.

- [ ] **Step 12: Score and publish the counts**

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
uv run python -m scripts.analysis_handcheck score ~/Downloads/analysis-handcheck-marks.csv --out docs/results/s26-analysis-handcheck.txt
```

Then append to `docs/decisions/0077-analysis-sentences-in-docket-documents-mark-the-case.md`:

```markdown

**Hand-check result, <date> (appended; nothing above is edited).** Andy marked the <n>
matched sentences: <quotes> quote evidence and <conclusions> are conclusions in the docket
(`docs/results/s26-analysis-handcheck.txt`). <Adopted: this record takes effect, and
<conclusions> of <n> is its measured error. | Not adopted: returned to Andy with the
neutral-marker fallback.>
```

and set 0077's status cell in `docs/decisions/README.md` to `Accepted; adopted after the hand-check <date>; extends 0050` (or `Accepted, conditional; hand-check failed <date>, returned to Andy`). Copy the counts from the file, never from memory.

```bash
git add docs/results/s26-analysis-handcheck.txt docs/decisions/0077-analysis-sentences-in-docket-documents-mark-the-case.md docs/decisions/README.md docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: the analysis-sentence hand-check, scored (decision 0077 item 4)"
```

- [ ] **Step 13: STOP if not adopted.** If the outcome line reads `not adopted` or `not applied`, report to Andy in plain words and wait: Task 5 does not start until he decides. Tasks 3, 4 and 6 onwards do not depend on it.

---

### Task 3: The renderer (spec §5, decision 0075; no model, no cost)

*Decision W4 (Andy, 2026-09-24): the test pages are built in code.*

**Files:**
- Modify: `pyproject.toml` (two dependencies; one mypy override), `uv.lock` (by `uv add`)
- Create: `src/ntsb_probable_cause/docket/render.py`
- Create: `tests/test_docket_render.py`

**Interfaces:**
- Consumes: `tests/pdf_builder.py` (Task 1).
- Produces: `docket.render.Resolution = Literal[150, 200]`; `docket.render.RESOLUTION: Resolution = 150` (Task 13 may set it to 200 by the rule of spec §7.5); `docket.render.MEDIA_TYPE = "image/jpeg"`; `docket.render.RenderedPage` (frozen pydantic: `page: int` (1-based), `dpi: int`, `width: int`, `height: int`, `image_area_share: float`, `data: bytes`, property `sha256: str`); `docket.render.render_pages(data: bytes, pages: Sequence[int] | None = None, *, dpi: Resolution = RESOLUTION) -> list[RenderedPage]` (raises `DocketError` for a non-PDF or a page out of range).

**Why JPEG.** Every request carries its page image. Measured ad hoc while planning over 121 `dev-400` pages: a 150-dpi image-only page is about 1.2 MB as PNG and 385 KB as JPEG at quality 90 (medians); a typed page is about 200 KB either way. The typed-text answer key (spec §7.3) measures reading from these images exactly as rendered, so any loss from compression is inside the measurement, not hidden from it.

**Why `image_area_share`.** Decision W3: the share of the page its images cover is what tells a logo on a letterhead (a few per cent) from a photograph with a caption (most of the page), before any model is asked.

- [ ] **Step 1: Add the dependencies**

```bash
uv add "pypdfium2>=5.13.0" "pillow>=12.3.0"
```

Then in `pyproject.toml`, add to the `dependencies` list comment block, above the two new lines:

```toml
    # Decision 0075: pages are drawn with PDFium (the engine in Chrome), installed from the lock
    # file as a ready-built package -- not a system program, so 0047's reproducibility test holds.
    # Pillow writes the drawn page as JPEG.
```

and after the `pyarrow.*` mypy override:

```toml
[[tool.mypy.overrides]]
# pypdfium2 ships no `py.typed` marker (checked on 5.13.0, 2026-09-24). Its values enter this
# project only in docket/render.py, where each is converted to a plain int or float.
module = ["pypdfium2", "pypdfium2.*"]
ignore_missing_imports = true
```

- [ ] **Step 2: Write the failing tests**

`tests/test_docket_render.py`. The pages are made with Pillow and pypdf in the test, so no real docket page is committed (W4). Checked while planning: a page rotated 90° renders landscape with its top-left corner moved to the top right, as a viewer shows it; Pillow writes a 1-bit image into a PDF as CCITT fax; five strips merged onto one page render as one whole page.

```python
"""The renderer: upright, whole, every encoding; a fixed resolution (S2.6 §5, 0075)."""

import io

import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter, Transformation

from ntsb_probable_cause.docket.render import RESOLUTION, render_pages
from ntsb_probable_cause.errors import DocketError
from tests.pdf_builder import PageSpec, build_pdf

DARK = 128


def _image_pdf(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PDF", resolution=72)
    return out.getvalue()


def _marked_portrait(mode: str = "L") -> Image.Image:
    """200 x 300 points, white, with a black square in the top-left corner."""
    image = Image.new("L", (200, 300), 255)
    ImageDraw.Draw(image).rectangle((0, 0, 60, 60), fill=0)
    return image.convert(mode)


def _pixel_dark(data: bytes, x_frac: float, y_frac: float) -> bool:
    image = Image.open(io.BytesIO(data)).convert("L")
    x = min(image.width - 1, int(x_frac * image.width))
    y = min(image.height - 1, int(y_frac * image.height))
    return int(image.getpixel((x, y))) < DARK  # type: ignore[arg-type]


def test_an_upright_page_keeps_its_corner() -> None:
    (page,) = render_pages(_image_pdf(_marked_portrait()))
    assert page.height > page.width
    assert _pixel_dark(page.data, 0.02, 0.02)


def test_a_rotated_page_is_drawn_upright() -> None:
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(_image_pdf(_marked_portrait()))))
    writer.pages[0].rotate(90)
    out = io.BytesIO()
    writer.write(out)
    (page,) = render_pages(out.getvalue())
    assert page.width > page.height
    assert _pixel_dark(page.data, 0.98, 0.02)  # the corner a viewer shows at the top right
    assert not _pixel_dark(page.data, 0.02, 0.02)


def test_a_fax_encoded_page_renders() -> None:
    data = _image_pdf(_marked_portrait(mode="1"))
    xobjects = PdfReader(io.BytesIO(data)).pages[0]["/Resources"]["/XObject"]
    filters = [str(x.get_object()["/Filter"]) for x in xobjects.values()]
    assert any("CCITTFaxDecode" in f for f in filters)
    (page,) = render_pages(data)
    assert _pixel_dark(page.data, 0.02, 0.02)


def test_a_page_built_from_five_strips_renders_whole() -> None:
    writer = PdfWriter()
    base = writer.add_blank_page(width=200, height=300)
    for i in range(5):
        strip = Image.new("L", (200, 60), 0 if i % 2 == 0 else 255)
        base.merge_transformed_page(
            PdfReader(io.BytesIO(_image_pdf(strip))).pages[0],
            Transformation().translate(0, i * 60),
        )
    out = io.BytesIO()
    writer.write(out)
    (page,) = render_pages(out.getvalue())
    assert _pixel_dark(page.data, 0.5, 0.99)  # strip 0, at the bottom
    assert not _pixel_dark(page.data, 0.5, 0.7)  # strip 1
    assert _pixel_dark(page.data, 0.5, 0.02)  # strip 4, at the top
    assert page.image_area_share == pytest.approx(1.0)


def test_image_area_share_tells_a_logo_from_a_photograph() -> None:
    data = build_pdf(
        [PageSpec(text="A typed report with a logo.", images=("/DCTDecode",)), PageSpec(text="x")]
    )
    logo, typed = render_pages(data)
    assert logo.image_area_share == pytest.approx(100 * 100 / (612 * 792))
    assert typed.image_area_share == 0.0


def test_resolution_sets_the_size_and_the_default_is_150() -> None:
    data = _image_pdf(_marked_portrait())
    (low,) = render_pages(data)
    (high,) = render_pages(data, dpi=200)
    assert RESOLUTION == 150
    assert (low.width, low.height) == (417, 625)
    assert high.width > low.width
    assert low.dpi == 150


def test_rendering_is_repeatable() -> None:
    data = _image_pdf(_marked_portrait())
    assert render_pages(data)[0].sha256 == render_pages(data)[0].sha256


def test_only_the_asked_pages_are_drawn() -> None:
    data = build_pdf([PageSpec(text="one"), PageSpec(text="two"), PageSpec(text="three")])
    assert [p.page for p in render_pages(data, [3, 1])] == [3, 1]


def test_not_a_pdf_and_a_missing_page_raise() -> None:
    with pytest.raises(DocketError, match="not a PDF"):
        render_pages(b"<html>not a pdf</html>")
    with pytest.raises(DocketError, match="no page 2"):
        render_pages(build_pdf([PageSpec(text="one")]), [2])
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/test_docket_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ntsb_probable_cause.docket.render'`.

- [ ] **Step 4: Implement `docket/render.py`**

```python
"""A PDF page drawn as a viewer shows it: upright, whole, every encoding (decision 0075).

pypdfium2 bundles PDFium, the PDF engine inside Chrome, as a ready-built package installed
from the lock file, so nothing is installed on the machine itself and 0047's reproducibility
test holds. PDFium honours a page's rotation, so a page stored sideways comes out upright
with no correction here; tiled and fax, JPEG 2000 or JBIG2 pages are drawn like any other.
"""

import hashlib
import io
from collections.abc import Sequence
from typing import Literal

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image
from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.errors import DocketError

Resolution = Literal[150, 200]
# Spec §5.4 and §7.5: the transcriber test chooses 150 or 200 dots per inch; 150 until then.
# Part of every transcription's cache key (Task 11).
RESOLUTION: Resolution = 150
POINTS_PER_INCH = 72
# Measured ad hoc while planning (121 dev-400 pages): a 150-dpi image-only page is about
# 1.2 MB as PNG and 385 KB as JPEG at quality 90. Every request carries its image.
JPEG_QUALITY = 90
MEDIA_TYPE = "image/jpeg"


class RenderedPage(BaseModel):
    """One drawn page: its number, size, how much of it is image, and the JPEG bytes."""

    model_config = ConfigDict(frozen=True)
    page: int
    dpi: int
    width: int
    height: int
    image_area_share: float
    data: bytes

    @property
    def sha256(self) -> str:
        """The image's hash: what identifies this drawing of the page."""
        return hashlib.sha256(self.data).hexdigest()


def _image_area_share(page: pdfium.PdfPage) -> float:
    """The share of the page its images cover, from their boxes, clipped to the page.

    Overlapping images are summed, so the share is capped at 1. A logo on a letterhead is a
    few per cent; a photograph with a caption is most of the page (decision W3).
    """
    width, height = (float(v) for v in page.get_size())
    if width <= 0 or height <= 0:
        return 0.0
    covered = 0.0
    for image in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]):
        left, bottom, right, top = (float(v) for v in image.get_bounds())
        covered += max(0.0, min(right, width) - max(left, 0.0)) * max(
            0.0, min(top, height) - max(bottom, 0.0)
        )
    return min(1.0, covered / (width * height))


def _jpeg(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


def render_pages(
    data: bytes, pages: Sequence[int] | None = None, *, dpi: Resolution = RESOLUTION
) -> list[RenderedPage]:
    """Draw the asked pages (1-based, in the order asked; every page if ``None``)."""
    try:
        document = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as error:
        raise DocketError(f"not a PDF: {error}") from error
    try:
        total = len(document)
        drawn: list[RenderedPage] = []
        for number in pages if pages is not None else range(1, total + 1):
            if not 1 <= number <= total:
                raise DocketError(f"no page {number} of {total}")
            # A real dev-400 page fails to load in PDFium (found while planning): it becomes a
            # DocketError, which a transcription records as a failed reading, never a crash.
            try:
                page = document[number - 1]
            except pdfium.PdfiumError as error:
                raise DocketError(f"page {number} did not load: {error}") from error
            try:
                image: Image.Image = page.render(scale=dpi / POINTS_PER_INCH).to_pil()
                share = _image_area_share(page)
            except pdfium.PdfiumError as error:
                raise DocketError(f"page {number} did not render: {error}") from error
            finally:
                page.close()
            rgb = image.convert("RGB")
            drawn.append(
                RenderedPage(
                    page=number,
                    dpi=dpi,
                    width=rgb.width,
                    height=rgb.height,
                    image_area_share=share,
                    data=_jpeg(rgb),
                )
            )
        return drawn
    finally:
        document.close()
```

- [ ] **Step 5: Run the tests to see them pass, then the whole check**

Run: `uv run pytest tests/test_docket_render.py -v`, then `make check`
Expected: PASS, 9 tests; green. If deptry reports `pillow` unused, the cause is a missing import, not the rule. If mypy reports a pypdfium2 value as `Any` anywhere else, convert it where it enters (`int(...)`, `float(...)`), never `# type: ignore` in `src/`.

- [ ] **Step 6: Check the container build still resolves** (the recorder's image installs the same lock)

Run: `uv lock --check` and `uv sync --frozen`. Expected: no error. The recorder never imports the renderer; the new wheels ship for Linux on x86 and ARM (spec §5.1), so the image build is unaffected.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/ntsb_probable_cause/docket/render.py tests/test_docket_render.py docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: the renderer -- pypdfium2 pages, upright and whole, as JPEG (decision 0075)"
```

---

### Task 4: Marks in the split, and the narrative-coverage mark (spec §4.3, §4.4; decision 0078; no model, no cost)

**Files:**
- Create: `src/ntsb_probable_cause/records/marks.py`
- Modify: `src/ntsb_probable_cause/records/guard.py` (`_needles` factored out of `find_leaks`; + `sentence_needles`, `narrative_shares`, `NARRATIVE_COVERAGE_MARK`, `Screen`, `screen`, `MARKED_SENTENCES` — empty until Task 5)
- Modify: `src/ntsb_probable_cause/records/evidence.py` (+ `marks`, `narrative_share` bookkeeping fields)
- Modify: `src/ntsb_probable_cause/records/split.py` (screen, then attach marks and the share)
- Modify: `pyproject.toml` (import-linter: `records.marks` joins the "Only the splitter constructs synthesis and verdict" source list)
- Test: `tests/test_marks.py` (new), `tests/test_guard.py`, `tests/test_records.py`

**Interfaces:**
- Produces: `records.marks.MarkKind = Literal["analysis_sentence", "narrative_coverage", "unguarded_images"]`; `records.marks.CaseMark` (frozen pydantic: `kind: MarkKind`, `count: int`).
- Produces: `records.guard.sentence_needles(text: str | None, *, min_sentence_chars: int = MIN_SENTENCE_CHARS) -> frozenset[str]`; `records.guard.narrative_shares(documents: Sequence[str], narrative: str | None, *, min_sentence_chars: int = MIN_SENTENCE_CHARS) -> tuple[float, ...]` (one share per document; empty when there are no documents or no sentences); `records.guard.NARRATIVE_COVERAGE_MARK = 0.5`; `records.guard.Screen` (frozen dataclass: `leaks: tuple[Leak, ...]`, `marked: tuple[Leak, ...]`); `records.guard.screen(evidence, withheld_text, codes, *, min_sentence_chars=..., exemptions=..., marked=MARKED_SENTENCES) -> Screen`; `records.guard.MARKED_SENTENCES: frozenset[tuple[str, str]]`.
- Produces: `Evidence.marks: tuple[CaseMark, ...] = ()`, `Evidence.narrative_share: float | None = None`, both in `BOOKKEEPING_FIELDS`, so `Payload.from_evidence` (which renders `role_values()` only) never renders them. Tasks 9 and 16 read them from `Prepared.evidence`.
- `split_record`'s signature and return type are unchanged. Every caller keeps working.

**Where the mark is computed, and why there.** Rule 1: the split is the only split. `split_record` already runs the tripwire over every trial document set arm B builds (`scoring/runner.py:prepare_case`), so marks computed there describe exactly the documents the agent is given. They leave on `Evidence` as bookkeeping — like `case_id`, which the payload has never rendered — not in any evidence role, so no code path can put them into the agent's text (spec §4.4).

**The share.** For each document, the share is the number of the factual narrative's sentences found in it, divided by the number of sentences the narrative has — the measure `scripts/narrative_coverage.py` published in `docs/results/s2-narrative-coverage.txt`, now in the library. The case's share is its largest document's. A case at or above 50% is marked `narrative_coverage`, with the count of documents at or above 50%. The share is stored on every case that has documents, so any other cut can be reported later (0078 item 1).

- [ ] **Step 1: Write the failing tests**

`tests/test_marks.py` (the narratives are invented and clinical, set into a real fixture record's `narratives[0]`; the docket subtree is set directly, as `docket/attach.py` sets it):

```python
"""Marks: computed in the split, carried as bookkeeping, never rendered (S2.6 §4, 0078)."""

import copy

import pytest

from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.model.client import Payload
from ntsb_probable_cause.records.guard import (
    NARRATIVE_COVERAGE_MARK,
    narrative_shares,
    sentence_needles,
)
from ntsb_probable_cause.records.marks import CaseMark
from ntsb_probable_cause.records.split import split_record

FACTUAL = (
    "The airplane departed from runway 27 at 0915. "
    "Witnesses observed the airplane climb to about 300 feet. "
    "The engine then lost power and the airplane descended into a field. "
    "The pilot reported that the fuel selector was positioned to the left tank."
)
S1, S2, S3, S4 = (s.strip() for s in FACTUAL.split(". "))


def _case(record_fixtures: list[dict[str, object]], *documents: str) -> dict[str, object]:
    raw = copy.deepcopy(record_fixtures[0])
    narratives = raw["narratives"]
    assert isinstance(narratives, list)
    narratives[0]["concatenatedFactualNarrative"] = FACTUAL
    raw["docket"] = {"listing": "Docket item 1, 1 page.", "documents": list(documents)}
    return raw


def test_sentence_needles_are_the_guards_own_sentences() -> None:
    needles = sentence_needles(FACTUAL)
    assert len(needles) == 4
    assert "witnesses observed the airplane climb to about 300 feet" in needles


def test_one_share_per_document() -> None:
    shares = narrative_shares([f"{S1}. {S2}.", f"{S3}.", "Nothing shared."], FACTUAL)
    assert shares == (0.5, 0.25, 0.0)
    assert narrative_shares([], FACTUAL) == ()
    assert narrative_shares(["x"], None) == ()


def test_half_the_narrative_in_one_document_marks_the_case(
    record_fixtures: list[dict[str, object]],
) -> None:
    evidence, _, _ = split_record(_case(record_fixtures, f"{S1}. {S2}.", f"{S3}."))
    assert evidence.narrative_share == NARRATIVE_COVERAGE_MARK
    assert evidence.marks == (CaseMark(kind="narrative_coverage", count=1),)


def test_under_half_is_recorded_but_not_marked(record_fixtures: list[dict[str, object]]) -> None:
    evidence, _, _ = split_record(_case(record_fixtures, f"{S1}.", f"{S3}."))
    assert evidence.narrative_share == 0.25
    assert evidence.marks == ()


def test_no_documents_no_share(record_fixtures: list[dict[str, object]]) -> None:
    raw = copy.deepcopy(record_fixtures[0])
    evidence, _, _ = split_record(raw)
    assert evidence.narrative_share is None
    assert evidence.marks == ()


def test_a_mark_never_reaches_the_payload(record_fixtures: list[dict[str, object]]) -> None:
    evidence, _, _ = split_record(_case(record_fixtures, f"{S1}. {S2}. {S3}."))
    assert evidence.marks
    text = Payload.from_evidence(evidence).text
    assert "narrative_coverage" not in text
    assert "narrative_share" not in text
    assert "marks" not in Payload.from_evidence(evidence).fields()


def test_the_whole_narrative_in_a_document_still_refuses(
    record_fixtures: list[dict[str, object]],
) -> None:
    with pytest.raises(LeakageError, match="text from factual_narrative"):
        split_record(_case(record_fixtures, FACTUAL))
```

In `tests/test_records.py`, the schema test is unchanged in form — `BOOKKEEPING_FIELDS` now names the two new fields, and the test reads it. Add one assertion to `test_evidence_schema_is_exactly_the_evidence_roles_plus_bookkeeping`:

```python
    assert {"marks", "narrative_share"} <= BOOKKEEPING_FIELDS
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_marks.py tests/test_records.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ntsb_probable_cause.records.marks'`.

- [ ] **Step 3: Create `records/marks.py`**

```python
"""Marks: notes on a case kept in logs and results, never in the agent's text (S2.6 §4.4).

A mark says a case belongs to a group that is scored separately beside every result. It is
never written into evidence text: a marker there would tell the agent the NTSB leaned on
that text, which hints at the answer, and a live case -- whose report is not yet written --
could never carry one.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

# analysis_sentence: a docket document shares sentences with the analysis narrative (0077).
# narrative_coverage: one document holds at least half the factual narrative (0078).
# unguarded_images: an image sent in v3 whose page's transcription failed (0082).
MarkKind = Literal["analysis_sentence", "narrative_coverage", "unguarded_images"]


class CaseMark(BaseModel):
    """One mark: its kind, and how many sentences, documents or images it counts."""

    model_config = ConfigDict(frozen=True)
    kind: MarkKind
    count: int
```

- [ ] **Step 4: Refactor the needles out of `find_leaks`, and add the share and the screen**

In `records/guard.py`, add `from collections.abc import Iterable, Mapping, Sequence` (extending the existing import), then replace the needle-building loop inside `find_leaks` with a call to a new private helper, so the sentences the share counts are exactly the sentences the tripwire searches for:

```python
def _needles(source: str, text: str | None, min_sentence_chars: int) -> list[tuple[str, str, str]]:
    """The whole text and each sentence of one withheld text, as the tripwire searches them."""
    if not text:
        return []
    whole = normalise_text(text)
    whole_stripped = _strip_needle(whole)
    needles: list[tuple[str, str, str]] = []
    # Never exempted for boilerplate: only a single isolated sentence can be boilerplate.
    if len(whole_stripped) >= min_sentence_chars:
        needles.append(("text", source, whole_stripped))
    for sentence in _SENTENCE_END.split(whole):
        stripped = _strip_needle(sentence)
        if (
            len(stripped) >= min_sentence_chars
            and stripped != whole_stripped
            and not _BOILERPLATE_SENTENCE.match(stripped)
        ):
            needles.append(("sentence", source, stripped))
    return needles
```

and in `find_leaks` the first loop becomes:

```python
    needles = [
        needle
        for source, text in withheld_text.items()
        for needle in _needles(source, text, min_sentence_chars)
    ]
```

(`find_leaks`'s behaviour is unchanged; `tests/test_guard.py` passing unchanged proves it.) Then add, after `find_leaks`:

```python
# Decision 0078: a case is marked narrative_coverage when one docket document holds at least
# this share of the factual narrative's sentences (docs/results/s2-narrative-coverage.txt:
# 3 of 379 development cases).
NARRATIVE_COVERAGE_MARK = 0.5

# Sentence matches that mark the case instead of refusing it, one role/source pair each.
# Only a sentence is ever marked: a whole withheld text, a probable-cause sentence or a code
# still refuses, in every role. Empty until decision 0077 is adopted (S2.6 Task 5).
MARKED_SENTENCES: frozenset[tuple[str, str]] = frozenset()


def sentence_needles(
    text: str | None, *, min_sentence_chars: int = MIN_SENTENCE_CHARS
) -> frozenset[str]:
    """The sentences of one withheld text, normalised exactly as the tripwire searches them."""
    return frozenset(
        needle for kind, _, needle in _needles("", text, min_sentence_chars) if kind == "sentence"
    )


def narrative_shares(
    documents: Sequence[str],
    narrative: str | None,
    *,
    min_sentence_chars: int = MIN_SENTENCE_CHARS,
) -> tuple[float, ...]:
    """Per document, the share of the narrative's sentences found in it (decision 0078).

    Empty when there are no documents or the narrative has no sentence long enough to
    search for -- a case with nothing to compare has no share, not a share of zero.
    """
    needles = sentence_needles(narrative, min_sentence_chars=min_sentence_chars)
    if not needles or not documents:
        return ()
    return tuple(
        sum(1 for needle in needles if needle in haystack) / len(needles)
        for haystack in (normalise_text(document) for document in documents)
    )


@dataclass(frozen=True)
class Screen:
    """What the tripwire found: leaks, which refuse the case, and marked sentences."""

    leaks: tuple[Leak, ...]
    marked: tuple[Leak, ...]


def screen(  # noqa: PLR0913 -- find_leaks' parameters plus the marked pairs.
    evidence: Mapping[str, EvidenceValue],
    withheld_text: Mapping[str, str | None],
    codes: Iterable[str],
    *,
    min_sentence_chars: int = MIN_SENTENCE_CHARS,
    exemptions: frozenset[tuple[str, str]] = SENTENCE_CHECK_EXEMPTIONS,
    marked: frozenset[tuple[str, str]] = MARKED_SENTENCES,
) -> Screen:
    """``find_leaks``, with sentence matches in the marked role/source pairs set apart."""
    found = find_leaks(
        evidence,
        withheld_text,
        codes,
        min_sentence_chars=min_sentence_chars,
        exemptions=exemptions,
    )

    def is_marked(leak: Leak) -> bool:
        return leak.kind == "sentence" and (leak.evidence_role, leak.source) in marked

    return Screen(
        leaks=tuple(leak for leak in found if not is_marked(leak)),
        marked=tuple(leak for leak in found if is_marked(leak)),
    )
```

If `ruff` reports `PLR0913` not triggered (it counts keyword-only arguments too, so it should), drop the `noqa` — never leave an unused suppression (`RUF100`).

- [ ] **Step 5: Add the two bookkeeping fields to `Evidence`**

In `records/evidence.py`:

```python
from ntsb_probable_cause.records.marks import CaseMark

BOOKKEEPING_FIELDS = frozenset({"case_id", "docket_url", "excluded", "marks", "narrative_share"})
```

and, after `excluded`:

```python
    # Set only by split_record (S2.6 spec §4.4); bookkeeping, so never rendered into a payload.
    marks: tuple[CaseMark, ...] = ()
    narrative_share: float | None = None
```

Update the class docstring's second sentence to: `Bookkeeping fields (identity, exclusions, marks) are never rendered into a payload.`

- [ ] **Step 6: Compute marks in `split_record`**

In `records/split.py`, import `NARRATIVE_COVERAGE_MARK, narrative_shares, screen` from `records.guard` (drop `find_leaks`) and `CaseMark` from `records.marks`, and replace everything from `leaks = find_leaks(` to the end with:

```python
    screened = screen(
        role_values, withheld, verdict.codes(), min_sentence_chars=min_sentence_chars
    )
    if screened.leaks:
        summary = "; ".join(str(leak) for leak in screened.leaks[:5])
        raise LeakageError(f"{case_id}: {summary}", leaks=screened.leaks)
    marks: list[CaseMark] = []
    if screened.marked:
        marks.append(CaseMark(kind="analysis_sentence", count=len(screened.marked)))
    shares = narrative_shares(
        evidence.docket_documents or (),
        synthesis.factual_narrative,
        min_sentence_chars=min_sentence_chars,
    )
    covering = sum(1 for share in shares if share >= NARRATIVE_COVERAGE_MARK)
    if covering:
        marks.append(CaseMark(kind="narrative_coverage", count=covering))
    marked = evidence.model_copy(
        update={"marks": tuple(marks), "narrative_share": max(shares, default=None)}
    )
    return marked, synthesis, verdict
```

and add to the docstring: `Marks (S2.6 spec §4) are computed here, from the same screen, and returned on the evidence as bookkeeping.`

- [ ] **Step 7: The import contract**

In `pyproject.toml`, add `"ntsb_probable_cause.records.marks",` to the `source_modules` of the contract named "Only the splitter constructs synthesis and verdict", after `"ntsb_probable_cause.records.guard",`.

- [ ] **Step 8: Run the tests to see them pass, then the whole check**

Run: `uv run pytest tests/test_marks.py tests/test_guard.py tests/test_records.py tests/test_boundary.py -v`, then `make check`
Expected: PASS; green. `test_guard.py` and `test_boundary.py` pass unchanged — the refactor changed no behaviour.

- [ ] **Step 9: Commit**

```bash
git add src/ntsb_probable_cause/records/marks.py src/ntsb_probable_cause/records/guard.py src/ntsb_probable_cause/records/evidence.py src/ntsb_probable_cause/records/split.py pyproject.toml tests/test_marks.py tests/test_records.py docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: marks computed in the split; the narrative-coverage mark at 50% (decision 0078)"
```

---

### Task 5: The analysis-sentence mark (spec §4.2, decision 0077; no model, no cost)

**Starts only if** `docs/results/s26-analysis-handcheck.txt` ends `outcome: adopted` (Task 2). Otherwise Andy's decision replaces this task.

**Files:**
- Modify: `src/ntsb_probable_cause/records/guard.py` (`MARKED_SENTENCES`)
- Test: `tests/test_marks.py`

**Interfaces:**
- Consumes: Task 4's `screen`, `CaseMark`, `split_record`.
- Produces: `MARKED_SENTENCES == frozenset({("docket_documents", "analysis_narrative")})`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_marks.py` (add `from ntsb_probable_cause.records.guard import MARKED_SENTENCES` to the imports):

```python
QUOTED = (
    "Examination of the engine revealed no mechanical anomalies"
    " that would have precluded normal operation."
)
ANALYSIS = QUOTED + " The fuel selector was found positioned to an empty tank."
CAUSE = (
    "The pilot's improper fuel management, which resulted in a loss of engine power due to"
    " fuel starvation."
)


def _analysed(record_fixtures: list[dict[str, object]], *documents: str) -> dict[str, object]:
    raw = _case(record_fixtures, *documents)
    narratives = raw["narratives"]
    assert isinstance(narratives, list)
    narratives[0]["analysisNarrative"] = ANALYSIS
    narratives[0]["probableCause"] = CAUSE
    return raw


def test_only_the_docket_documents_analysis_pair_is_marked() -> None:
    assert frozenset({("docket_documents", "analysis_narrative")}) == MARKED_SENTENCES


def test_an_analysis_sentence_in_a_document_marks_and_reaches_the_agent(
    record_fixtures: list[dict[str, object]],
) -> None:
    document = f"Docket item 1, 2 pages.\n[page 1 of 2]\n{QUOTED}"
    evidence, _, _ = split_record(_analysed(record_fixtures, document))
    assert CaseMark(kind="analysis_sentence", count=1) in evidence.marks
    assert "no mechanical anomalies" in Payload.from_evidence(evidence).text
    assert "analysis_sentence" not in Payload.from_evidence(evidence).text


def test_an_analysis_sentence_outside_the_documents_still_refuses(
    record_fixtures: list[dict[str, object]],
) -> None:
    raw = _analysed(record_fixtures)
    narratives = raw["narratives"]
    assert isinstance(narratives, list)
    narratives[0]["prelimNarrative"] = QUOTED
    with pytest.raises(LeakageError, match="sentence from analysis_narrative in prelim"):
        split_record(raw)


def test_a_probable_cause_in_a_document_still_refuses(
    record_fixtures: list[dict[str, object]],
) -> None:
    with pytest.raises(LeakageError, match="from probable_cause in docket_documents"):
        split_record(_analysed(record_fixtures, f"Letter.\n{CAUSE}"))


def test_the_whole_analysis_in_a_document_still_refuses(
    record_fixtures: list[dict[str, object]],
) -> None:
    with pytest.raises(LeakageError, match="text from analysis_narrative in docket_documents"):
        split_record(_analysed(record_fixtures, ANALYSIS))


def test_a_code_in_a_document_still_refuses(record_fixtures: list[dict[str, object]]) -> None:
    raw = _analysed(record_fixtures)
    _, _, verdict = split_record(raw)
    code = verdict.codes()[0]
    with pytest.raises(LeakageError, match="code from codes in docket_documents"):
        split_record(_analysed(record_fixtures, f"Table row {code} noted."))
```

(If `record_fixtures[0]` has no verdict code, pick the first fixture that does with `next(...)`; the test must never pass vacuously.)

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_marks.py -v`
Expected: the pair test and the marking test FAIL (`MARKED_SENTENCES` is empty, and the analysis sentence refuses with `LeakageError`); the four "still refuses" tests PASS already — they are the guarantees 0077 item 2 keeps.

- [ ] **Step 3: Adopt the pair**

In `records/guard.py`:

```python
# Sentence matches that mark the case instead of refusing it, one role/source pair each.
# Only a sentence is ever marked: a whole withheld text, a probable-cause sentence or a code
# still refuses, in every role.
# - docket_documents / analysis_narrative (0077, adopted after Andy's hand-check,
#   docs/results/s26-analysis-handcheck.txt): the analysis is written from the docket at the
#   end of the investigation, so a shared sentence is usually the analysis quoting evidence.
#   Measured error: the conclusions that file counts.
MARKED_SENTENCES: frozenset[tuple[str, str]] = frozenset(
    {(EvidenceRole.DOCKET_DOCUMENTS.value, "analysis_narrative")}
)
```

- [ ] **Step 4: Run the tests, then the whole check**

Run: `uv run pytest tests/test_marks.py tests/test_guard.py tests/test_boundary.py -v`, then `make check`
Expected: PASS; green. A boundary test that asserted an analysis sentence in a docket document *refuses* is now wrong by decision: change it to assert the mark, and name it in the commit message.

- [ ] **Step 5: Measure what changed on `dev-400`** (free; reads the local cache; a few minutes)

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
uv run python -m scripts.docket_leak_scan --sample dev-400
```

This is S2's one-shot scan, which compares against pinned pre-0050 exemptions and is not changed. It is run here only to confirm that the 36/17 figures still reproduce on this commit, so the marked-case count in Task 15 can be read against them. Nothing is written; nothing in git changes. Log the output's `analysis_narrative` line in Deviations if it differs from `docs/results/s2-docket-leak.txt`.

- [ ] **Step 6: Commit**

```bash
git add src/ntsb_probable_cause/records/guard.py tests/test_marks.py tests/test_boundary.py docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: analysis sentences in docket documents mark the case, not refuse it (decision 0077)"
```

---

## Part 2 — after S2.4 lands on `main`

### Task 6: Merge `main` (S2.4) into the branch

**Starts when** S2.4's pull request has merged into `main` (its close-out puts the As-built record on `docs/specs/2026-09-23-s24-model-switch-design.md` and `docs/results/s24-bars.txt` on `main`).

**Files:** whatever the merge touches; then `Makefile` (the targets Tasks 1–2 could not add).

- [ ] **Step 1: Confirm S2.4 is on `main`**

```bash
git fetch origin
git log --oneline -5 origin/main
git show origin/main:docs/results/s24-bars.txt | head -5
```

Expected: an `S2.4: the model switch` merge commit, and the results file present. If not, stop: the rest of Part 2 waits.

- [ ] **Step 2: Merge, never rebase** (0033: a rebase would rewrite commits that later results name)

```bash
git merge origin/main
```

Expected conflicts, each resolved by keeping both sides:
- `docs/decisions/README.md`: the rows of S2.5 (from 0060), S2.4 (its one record) and S2.6 (to 0083), in number order.
- `docs/specs/2026-09-12-architecture-and-roadmap.md`: S2.4's appended entry and status line, and S2.5's and S2.6's.
- `CLAUDE.md`: S2.4's appended "Model access", "Eval bars to beat" and "Commands" text, beside S2.5's.
- `pyproject.toml`: `version` takes `main`'s value (S2.4's release); S2.6's dependencies and contract edit stay.
- `uv.lock`: take either side, then run `uv lock` to regenerate it.
- `Makefile`: both sides' targets.

- [ ] **Step 3: If `s25-recorder` has moved on since the branch was cut, merge it too**

```bash
git log --oneline s26-widened-docket..s25-recorder
git merge s25-recorder   # only if the first command printed anything
```

(At the time of writing, `s25-recorder` is one commit ahead: `806caaf`, runbook corrections.)

- [ ] **Step 4: The whole check**

Run: `make check`
Expected: green. A test S2.4 wrote that S2.6's Tasks 4–5 now contradict (for example a boundary test expecting an analysis sentence to refuse) is fixed to the decision, and named in the merge commit's message.

- [ ] **Step 5: The targets Part 1 could not add**

Append to `Makefile` after the `recorder-report` target, and add the names to the `.PHONY` line:

```make
page-kinds:
	uv run python -m scripts.page_kinds --sample dev-400 --include-photo-only --out docs/results/s26-page-kinds.txt
# S2.6 spec §6.2 step 1: free, reads the docket cache; writes the private page frame under data/.

analysis-handcheck:
	uv run python -m scripts.analysis_handcheck sheet --sample dev-400
# S2.6 spec §4.2: free; writes the private marking page under data/handcheck/s26-analysis/.
```

- [ ] **Step 6: Record what S2.6 cites from S2.4**

Add one Deviations line naming the S2.4 results S2.6 will cite, by file and line label only: `docs/results/s24-bars.txt`, the held-out arm B `failures by reason:` line, and the ceiling and arm B tables. Copy no number here; Tasks 15 and 18 cite the file.

- [ ] **Step 7: Commit the merge**

```bash
git add -A
git commit -m "S2.6: merge main (S2.4, the model switch) into the widened docket"
```

(`git add -A` is right here and only here: the merge result is the whole tree. Check `git status --short` shows nothing under `data/` first.)

---

### Task 7: The $40 budget, and spend records for preparation jobs (decisions 0081, 0083)

**Files:**
- Modify: `src/ntsb_probable_cause/settings.py` (`monthly_budget_usd` default)
- Modify: `src/ntsb_probable_cause/scoring/runner.py` (`RunSpec.budget_usd` default)
- Modify: `src/ntsb_probable_cause/scoring/budget.py` (+ `SpendRecord`, `SPEND_FILE`, `write_spend`, `reserve_within_budget`; `month_spent` counts spend rows)
- Test: `tests/test_budget.py`, `tests/test_sources_settings.py`

**Interfaces:**
- Produces: `budget.SPEND_FILE = "spend.jsonl"`; `budget.SpendRecord` (frozen pydantic, `extra="forbid"`: `job_id: str`, `kind: Literal["inventory", "transcriber-test", "transcription"]`, `model: str`, `started: datetime`, `calls: int`, `cost_usd: float`, `commit_sha: str`, `dirty: bool`); `budget.write_spend(runs_dir: Path, record: SpendRecord) -> None` (appends a row under `runs_dir/<job_id>/spend.jsonl`); `budget.reserve_within_budget(runs_dir: Path, job_id: str, projected_usd: float, budget_usd: float, *, now: datetime) -> None` (raises `BudgetError`); `month_spent` now sums `RunRecord` rows and `SpendRecord` rows started in the month.

**Why spend rows, and why several per job.** The budget guard (0045) counts what `month_spent` reads, and until now that was only evaluation runs' `run.jsonl`. Transcription is paid preparation (0081 item 2) and must count too. A job appends one row per chunk of calls (Task 11 uses 50 pages), so a job killed after an hour still shows the hour's spend to the next run's budget check, as S1's abort path does for evaluation runs.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget.py` (add imports as needed: `from datetime import UTC, datetime`, `import pytest`, `from ntsb_probable_cause.errors import BudgetError`, and the new names from `ntsb_probable_cause.scoring.budget`):

```python
def _spend(job_id: str, cost: float, started: datetime) -> SpendRecord:
    return SpendRecord(
        job_id=job_id,
        kind="transcription",
        model="google/gemini-3.1-flash-lite",
        started=started,
        calls=50,
        cost_usd=cost,
        commit_sha="abc1234",
        dirty=False,
    )


def test_month_spent_counts_preparation_spend_rows(tmp_path: Path) -> None:
    now = datetime(2026, 10, 3, tzinfo=UTC)
    write_spend(tmp_path, _spend("t1", 0.40, now))
    write_spend(tmp_path, _spend("t1", 0.35, now))
    write_spend(tmp_path, _spend("t0", 9.99, datetime(2026, 9, 30, tzinfo=UTC)))
    assert month_spent(tmp_path, now=now) == pytest.approx(0.75)


def test_reserve_within_budget_refuses_past_the_month(tmp_path: Path) -> None:
    now = datetime(2026, 10, 3, tzinfo=UTC)
    write_spend(tmp_path, _spend("t1", 30.0, now))
    with pytest.raises(BudgetError, match="exceeds the \\$40.00 budget"):
        reserve_within_budget(tmp_path, "t2", 11.0, 40.0, now=now)
    reserve_within_budget(tmp_path, "t2", 9.0, 40.0, now=now)
    assert open_reservations(tmp_path) == {"t2": 9.0}
```

Append to `tests/test_sources_settings.py`:

```python
def test_the_development_budget_is_forty_dollars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision 0083: $40 a month during development, until S4."""
    monkeypatch.delenv("NTSB_MONTHLY_BUDGET_USD", raising=False)
    assert Settings(_env_file=None).monthly_budget_usd == 40.0  # type: ignore[call-arg]
    assert RunSpec(sample="dev-400", arm="ceiling").budget_usd == 40.0
```

(import `RunSpec` from `ntsb_probable_cause.scoring.runner` and `Settings` if absent; if the file already constructs `Settings` without `_env_file`, follow its existing pattern instead.)

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_budget.py tests/test_sources_settings.py -v`
Expected: FAIL — `ImportError` for `SpendRecord`, and `25.0 != 40.0`.

- [ ] **Step 3: Implement**

`settings.py`:

```python
    # Decision 0083: $40 a month during the development stages, until the live board (S4).
    monthly_budget_usd: float = Field(default=40.0, gt=0)
```

`scoring/runner.py`, in `RunSpec`: `budget_usd: float = 40.0` (same comment, one line).

`scoring/budget.py` (extend the imports with `from typing import Literal` and `from pydantic import BaseModel, ConfigDict`, and `write_jsonl` from `scoring.records`):

```python
SPEND_FILE = "spend.jsonl"


class SpendRecord(BaseModel):
    """Paid work that is not an evaluation run: evidence preparation (decision 0081).

    A job appends one row per chunk of calls, so a job that dies mid-way has still recorded
    what it spent up to its last chunk.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str
    kind: Literal["inventory", "transcriber-test", "transcription"]
    model: str
    started: datetime
    calls: int
    cost_usd: float
    commit_sha: str
    dirty: bool


def write_spend(runs_dir: Path, record: SpendRecord) -> None:
    """Append one spend row under the job's own folder in the runs directory."""
    write_jsonl(runs_dir / record.job_id / SPEND_FILE, [record])


def reserve_within_budget(
    runs_dir: Path, job_id: str, projected_usd: float, budget_usd: float, *, now: datetime
) -> None:
    """Refuse a preparation job that would take the month past its budget, then reserve it.

    The same rule as an evaluation run's (``runner._reserve_budget``, 0045): spend so far,
    plus every other open reservation, plus this job's projection, must fit the budget.
    """
    with budget_lock(runs_dir):
        spent = month_spent(runs_dir, now=now)
        reserved = sum(v for k, v in open_reservations(runs_dir).items() if k != job_id)
        if spent + reserved + projected_usd > budget_usd:
            raise BudgetError(
                f"projected ${projected_usd:.2f} plus ${spent:.2f} spent and ${reserved:.2f} "
                f"reserved by other runs exceeds the ${budget_usd:.2f} budget"
            )
        reserve(runs_dir, job_id, projected_usd, now=now)
```

and in `month_spent`, after the `run.jsonl` loop (docstring: add "and every preparation job's spend rows (0081)"):

```python
    for spend_file in sorted(runs_dir.glob(f"*/{SPEND_FILE}")):
        for spend in read_jsonl(spend_file, SpendRecord):
            if spend.started.year == now.year and spend.started.month == now.month:
                total += spend.cost_usd
```

`SpendRecord` is defined above `month_spent` so the name resolves; import `BudgetError` from `ntsb_probable_cause.errors`.

- [ ] **Step 4: Run the tests, then the whole check**

Run: `uv run pytest tests/test_budget.py tests/test_sources_settings.py -v`, then `make check`
Expected: PASS; green. A test that relied on the $25 default to trip the budget guard now needs an explicit `budget_usd=25.0`; pin it that way (never change its expected number) and list it in the commit message.

- [ ] **Step 5: Commit**

```bash
git add src/ntsb_probable_cause/settings.py src/ntsb_probable_cause/scoring/runner.py src/ntsb_probable_cause/scoring/budget.py tests/ docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: the \$40 development budget (0083); preparation spend counts against the month (0081)"
```

---

### Task 8: The evidence-version axis (spec §3, decision 0076)

**Files:**
- Modify: `src/ntsb_probable_cause/scoring/records.py` (+ `EvidenceVersion`; `RunRecord.evidence_version`)
- Modify: `src/ntsb_probable_cause/scoring/runner.py` (`RunSpec.evidence_version`; `spec_json`; the run record)
- Modify: `src/ntsb_probable_cause/scoring/report.py` (`provenance`; `refuse_cross_version`; `comparison_heading`)
- Modify: `src/ntsb_probable_cause/scoring/ledger.py` (a versioned table)
- Modify: `apps/eval/__main__.py` (`run --evidence-version`; `report --versions-compared`; `resolve_latest` filters on the version)
- Test: `tests/test_runner.py`, `tests/test_report.py`, `tests/test_ledger.py`, `tests/test_eval_app.py`

**Interfaces:**
- Produces: `scoring.records.EvidenceVersion = Literal["v1", "v2", "v3"]`; `RunRecord.evidence_version: EvidenceVersion = "v1"` (a run from before S2.6 reads as v1, 0076 item 2); `RunSpec.evidence_version: EvidenceVersion = "v1"`; `spec_json(...)["evidence_version"]`, placed right after `"arm"`; `report.refuse_cross_version(this: RunRecord, other: RunRecord, *, versions_compared: bool) -> None` (raises `ConfigurationError`); `report.comparison_heading` prefixes `evidence-version comparison (decision 0076): <a> against <b> -- ` when the versions differ; `resolve_latest(..., version: str = "v1")`.
- Until Task 14, a run with `evidence_version` other than `"v1"` is refused by `Runner.run` with `ConfigurationError("evidence version v2 is not built yet")`, so the axis cannot be recorded for evidence that is not actually there.

**Example of what the refusal prevents.** `ntsb-eval report <B-v2 run> --against <B-v1 run>` without the flag stops with: `… reads the docket at evidence version v2 and … at v1; a comparison across versions is not an arm comparison (decision 0076). Pass --versions-compared to print it under its own heading.` With the flag, the comparison prints under `evidence-version comparison (decision 0076): v2 against v1 -- against <id>:`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_report.py` (reuse the file's own `RunRecord`-building helper or the `run_record` fixture from `conftest.py`, via `model_copy(update=...)`):

```python
def test_a_run_from_before_s26_reads_as_v1(run_record: RunRecord) -> None:
    legacy = run_record.model_dump()
    legacy.pop("evidence_version", None)
    assert RunRecord.model_validate(legacy).evidence_version == "v1"


def test_comparing_across_versions_is_refused_without_the_flag(run_record: RunRecord) -> None:
    v2 = run_record.model_copy(update={"evidence_version": "v2", "run_id": "r-v2"})
    with pytest.raises(ConfigurationError, match="decision 0076"):
        report.refuse_cross_version(v2, run_record, versions_compared=False)
    report.refuse_cross_version(v2, run_record, versions_compared=True)
    report.refuse_cross_version(run_record, run_record, versions_compared=False)


def test_a_cross_version_comparison_is_labelled(run_record: RunRecord) -> None:
    v2 = run_record.model_copy(update={"evidence_version": "v2"})
    heading = report.comparison_heading(v2, run_record)
    assert heading.startswith("evidence-version comparison (decision 0076): v2 against v1 -- ")
    assert report.comparison_heading(run_record, run_record).startswith("against ")


def test_provenance_names_the_version(run_record: RunRecord) -> None:
    assert "evidence=v1" in report.provenance(run_record)
```

Append to `tests/test_runner.py`:

```python
def test_spec_json_records_the_evidence_version_after_the_arm() -> None:
    spec = RunSpec(sample="dev-400", arm="B")
    keys = list(spec_json(spec, commit_sha="abc1234", dirty=False, case_ids=()))
    assert keys[keys.index("arm") + 1] == "evidence_version"
    assert spec_json(spec, commit_sha="abc1234", dirty=False, case_ids=())["evidence_version"] == "v1"
```

and one test that `Runner.run` with `RunSpec(..., evidence_version="v2")` raises `ConfigurationError` matching `not built yet` before any model call (copy the file's existing `Runner` construction helper; assert the `RecordingFakeClient` recorded no payloads).

Append to `tests/test_ledger.py`:

```python
def test_a_new_ledger_carries_the_version_column(tmp_path: Path, run_record: RunRecord) -> None:
    ledger = tmp_path / "ledger.md"
    append_row(ledger, run_record.model_copy(update={"sample": "heldout-400"}), "r/cases.jsonl")
    text = ledger.read_text()
    assert "| evidence |" in text
    assert "| v1 |" in text


def test_an_old_ledger_gains_a_versioned_table_below_it(
    tmp_path: Path, run_record: RunRecord
) -> None:
    ledger = tmp_path / "ledger.md"
    ledger.write_text(
        "# Held-out ledger\n\n| date | sample | arm | exclusions | includes | model | commit "
        "| cost USD | results |\n|---|---|---|---|---|---|---|---|---|\n| old row |\n"
    )
    held = run_record.model_copy(update={"sample": "heldout-400", "evidence_version": "v2"})
    append_row(ledger, held, "r/cases.jsonl")
    append_row(ledger, held, "r/cases.jsonl")
    text = ledger.read_text()
    assert text.count("| evidence |") == 1
    assert text.index("| old row |") < text.index("From S2.6")
    assert text.count("| v2 |") == 2
```

In `tests/test_eval_app.py`, follow the existing report-command tests: two run folders on different versions; `report A --against B` exits non-zero with the 0076 message; with `--versions-compared` it prints the labelled heading.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_report.py tests/test_runner.py tests/test_ledger.py tests/test_eval_app.py -v -k "version or ledger"`
Expected: FAIL — `RunRecord` has no `evidence_version`; `report` has no `refuse_cross_version`.

- [ ] **Step 3: Implement**

`scoring/records.py`:

```python
# Decision 0076: what the docket holds once read. v1 = text layers (S2); v2 = + transcriptions
# (S2.6); v3 = + pictures alongside the text (S2.6 probe). An axis, not an arm.
EvidenceVersion = Literal["v1", "v2", "v3"]
```

and in `RunRecord`, after `arm`:

```python
    # "v1" on a run from before S2.6, which read text layers only (0076 item 2).
    evidence_version: EvidenceVersion = "v1"
```

`scoring/runner.py`: `RunSpec` gains `evidence_version: EvidenceVersion = "v1"` after `arm`; `spec_json` gains `"evidence_version": spec.evidence_version,` right after `"arm"`; `build_record` passes `evidence_version=spec.evidence_version`; and at the top of `Runner.run`, beside the other pre-flight refusals:

```python
        if spec.evidence_version != "v1":
            # Replaced in Task 14 (v2) and Task 16 (v3) by the readers that build them.
            raise ConfigurationError(
                f"evidence version {spec.evidence_version} is not built yet"
            )
```

`scoring/report.py`: in `provenance`, change the second line to `f"sample={record.sample} arm={record.arm} evidence={record.evidence_version} model={record.model} "`; add (importing `ConfigurationError`):

```python
def refuse_cross_version(this: RunRecord, other: RunRecord, *, versions_compared: bool) -> None:
    """Two runs on different evidence versions are not an arm comparison (decision 0076).

    Refused unless the caller asked for an evidence-version comparison by name, which is then
    printed under its own heading, so the output cannot be mistaken for "choosing helps".
    """
    if this.evidence_version == other.evidence_version or versions_compared:
        return
    raise ConfigurationError(
        f"{this.run_id} reads the docket at evidence version {this.evidence_version} and "
        f"{other.run_id} at {other.evidence_version}; a comparison across versions is not an "
        "arm comparison (decision 0076). Pass --versions-compared to print it under its own "
        "heading."
    )
```

and rename S2.4's `comparison_heading` body to `_model_heading` (unchanged), with:

```python
def comparison_heading(this: RunRecord, other: RunRecord) -> str:
    """The line above a paired comparison: labelled across models (0031) and versions (0076)."""
    heading = _model_heading(this, other)
    if this.evidence_version != other.evidence_version:
        return (
            f"evidence-version comparison (decision 0076): {this.evidence_version} against "
            f"{other.evidence_version} -- {heading}"
        )
    return heading
```

`scoring/ledger.py`: keep `_HEADER`'s intro, and replace the table header with a versioned one used for new ledgers and appended once to an old one:

```python
_INTRO = "# Held-out ledger\n\nEvery run that touched a held-out sample (decision 0026).\n"
_VERSIONED_TABLE = (
    "| date | sample | arm | evidence | exclusions | includes | model | commit | cost USD "
    "| results |\n|---|---|---|---|---|---|---|---|---|---|\n"
)
_VERSIONED_SECTION = (
    "\n## From S2.6: with the evidence version (decision 0076)\n\n"
    "Every row above this table read the docket at evidence version v1.\n\n" + _VERSIONED_TABLE
)
```

and in `append_row`:

```python
    if not ledger.exists():
        ledger.write_text(_INTRO + "\n" + _VERSIONED_TABLE)
    elif "| evidence |" not in ledger.read_text():
        with ledger.open("a") as handle:
            handle.write(_VERSIONED_SECTION)
    with ledger.open("a") as handle:
        handle.write(
            f"| {run.started.date()} | {run.sample} | {run.arm} | {run.evidence_version} | "
            f"{','.join(run.exclusions) or '-'} | {','.join(run.includes) or '-'} | "
            f"{run.model} | {run.commit_sha}{'*' if run.dirty else ''} | "
            f"{run.cost_usd:.2f} | {results_ref(results_file)} |\n"
        )
```

Delete `_HEADER` once nothing uses it (vulture will say).

`apps/eval/__main__.py`: `run_p.add_argument("--evidence-version", choices=("v1", "v2", "v3"), default="v1")`, passed as `evidence_version=args.evidence_version` into `RunSpec`; `report_p.add_argument("--versions-compared", action="store_true", help="compare runs on different evidence versions, under a labelled heading (0076)")`; in `_cmd_report`, before the heading, `report.refuse_cross_version(run_record, other_record, versions_compared=args.versions_compared)`; `resolve_latest` gains `version: str = "v1"` and skips `record.evidence_version != version`, with one docstring sentence: `A run on another evidence version is skipped too (0076): "latest B" means the latest B on v1 unless asked.` A `ConfigurationError` from `report` must reach the user as a one-line error the way the command's other refusals do; follow the existing pattern in `main`.

- [ ] **Step 4: Run the tests, then the whole check**

Run: the Step 2 command, then `make check`
Expected: PASS; green. Tests that assert the exact `provenance` text or the exact `spec_json` keys gain the new field; say so in the commit message.

- [ ] **Step 5: Commit**

```bash
git add src/ntsb_probable_cause/scoring/ apps/eval/__main__.py tests/ docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: the evidence version is an axis every run records; cross-version comparisons are refused unless labelled (0076)"
```

---

### Task 9: Marks in the results, and every result printed twice (spec §4.4)

**Files:**
- Modify: `src/ntsb_probable_cause/scoring/records.py` (`CaseResult.marks`, `CaseResult.narrative_share`)
- Modify: `src/ntsb_probable_cause/scoring/runner.py` (`_case_result` copies them from the evidence)
- Modify: `src/ntsb_probable_cause/scoring/report.py` (+ `unmarked`, `marks_summary`, `share_bands`)
- Modify: `apps/eval/__main__.py` (`_cmd_report` prints the unmarked table, the marked groups and, with `--against`, the comparison on cases unmarked in both runs)
- Test: `tests/test_report.py`, `tests/test_runner.py`, `tests/test_eval_app.py`

**Interfaces:**
- Consumes: `Evidence.marks`, `Evidence.narrative_share` (Task 4); `records.marks.CaseMark`.
- Produces: `CaseResult.marks: tuple[CaseMark, ...] = ()`; `CaseResult.narrative_share: float | None = None`; `report.unmarked(results: Sequence[CaseResult]) -> list[CaseResult]`; `report.marks_summary(results: Sequence[CaseResult]) -> str`; `report.share_bands(results: Sequence[CaseResult]) -> str`; `report.MARK_NOTES: dict[str, str]`.

**What the report prints** where any case carries a mark (the example is invented):

```
unmarked cases only (S2.6 spec §4.4):
| slice | n | top-1 | ... |
marks (S2.6 spec §4.4; never in the agent's text):
- analysis_sentence: 15 cases (31 counted); top-1 26.7% [10.9, 52.0] (n=15)
- narrative_coverage: 3 cases (3 counted); top-1 33.3% [6.1, 79.2] (n=3)
  at about three development cases this row makes the cases visible; it cannot show whether coverage inflates the score (decision 0078 item 3)
narrative share, largest single document: at least 25% 21, at least 50% 3, at least 80% 2, of 361 cases with a share
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_report.py` (build `CaseResult`s the way the file already does, with `model_copy(update=...)`):

```python
def test_unmarked_drops_every_marked_case(case_result: CaseResult) -> None:
    marked = case_result.model_copy(
        update={"case_id": "M", "marks": (CaseMark(kind="analysis_sentence", count=2),)}
    )
    assert [r.case_id for r in report.unmarked([case_result, marked])] == [case_result.case_id]


def test_marks_summary_rows_and_the_coverage_note(case_result: CaseResult) -> None:
    coverage = case_result.model_copy(
        update={"marks": (CaseMark(kind="narrative_coverage", count=1),)}
    )
    text = report.marks_summary([coverage, case_result])
    assert "narrative_coverage: 1 cases (1 counted); top-1" in text
    assert "decision 0078 item 3" in text
    assert report.marks_summary([case_result]) == "marks: none"


def test_share_bands_count_cases_at_each_cut(case_result: CaseResult) -> None:
    rows = [case_result.model_copy(update={"narrative_share": s}) for s in (0.1, 0.3, 0.6, 0.9)]
    rows.append(case_result.model_copy(update={"narrative_share": None}))
    assert report.share_bands(rows) == (
        "narrative share, largest single document: at least 25% 3, at least 50% 2, "
        "at least 80% 1, of 4 cases with a share"
    )
```

(If `tests/test_report.py` has no `case_result` fixture, add one to `tests/conftest.py` beside `run_record`, built from a scored `CaseResult` the file already constructs.)

Append to `tests/test_runner.py` a test that an arm B case whose docket document holds half the factual narrative (reuse `tests/test_marks.py`'s invented `FACTUAL`, and the file's existing arm B fake docket helper) produces a `CaseResult` with `marks == (CaseMark(kind="narrative_coverage", count=1),)` and `narrative_share == 0.5`, and that no payload the fake client recorded contains `narrative_coverage`.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_report.py tests/test_runner.py -v -k "mark or share"`
Expected: FAIL — `CaseResult` rejects `marks` (`extra="forbid"`).

- [ ] **Step 3: Implement**

`scoring/records.py`, in `CaseResult` after `documents_not_read` (importing `CaseMark` from `ntsb_probable_cause.records.marks`):

```python
    # S2.6 spec §4.4: the case's marks and its largest single-document share of the factual
    # narrative (0078), from the split. Never in the agent's text; reported as groups.
    marks: tuple[CaseMark, ...] = ()
    narrative_share: float | None = None
```

`scoring/runner.py`, in `_case_result`'s `CaseResult(...)`: `marks=ctx.evidence.marks, narrative_share=ctx.evidence.narrative_share,`. (`_leaked_case` sets neither: a refused case has no evidence.)

`scoring/report.py`:

```python
# One line of caution per mark kind whose group is too small to carry a claim.
MARK_NOTES = {
    "narrative_coverage": (
        "at about three development cases this row makes the cases visible; it cannot show "
        "whether coverage inflates the score (decision 0078 item 3)"
    ),
}
_SHARE_CUTS = (0.25, 0.5, 0.8)


def unmarked(results: Sequence[CaseResult]) -> list[CaseResult]:
    """The cases carrying no mark: the second of the two tables spec §4.4 asks for."""
    return [r for r in results if not r.marks]


def marks_summary(results: Sequence[CaseResult]) -> str:
    """Each mark kind as its own group: cases, what the marks counted, and top-1."""
    kinds = sorted({mark.kind for r in results for mark in r.marks})
    if not kinds:
        return "marks: none"
    lines = ["marks (S2.6 spec §4.4; never in the agent's text):"]
    for kind in kinds:
        group = [r for r in results if any(m.kind == kind for m in r.marks)]
        counted = sum(m.count for r in group for m in r.marks if m.kind == kind)
        cell = proportion([r.scores.occurrence_top1 for r in group if r.scores is not None])
        lines.append(f"- {kind}: {len(group)} cases ({counted} counted); top-1 {fmt_n(cell)}")
        if kind in MARK_NOTES:
            lines.append(f"  {MARK_NOTES[kind]}")
    return "\n".join(lines)


def share_bands(results: Sequence[CaseResult]) -> str:
    """How many cases reach each cut of the stored share, so another cut needs no re-run."""
    shares = [r.narrative_share for r in results if r.narrative_share is not None]
    bands = ", ".join(
        f"at least {cut:.0%} {sum(1 for s in shares if s >= cut)}" for cut in _SHARE_CUTS
    )
    return f"narrative share, largest single document: {bands}, of {len(shares)} cases with a share"
```

`apps/eval/__main__.py`, in `_cmd_report`, after the failures line:

```python
    if any(r.marks for r in cases):
        text += (
            "\n\nunmarked cases only (S2.6 spec §4.4):\n"
            + report.summarise(report.unmarked(cases), floor=floor)
            + "\n\n"
            + report.marks_summary(cases)
        )
    if any(r.narrative_share is not None for r in cases):
        text += "\n" + report.share_bands(cases)
```

and in the `--against` block, after the existing comparison:

```python
        marked_ids = {r.case_id for r in [*cases, *other_cases] if r.marks}
        if marked_ids:
            text += (
                f"\n\non cases unmarked in both runs ({len(marked_ids)} marked cases left out):\n"
                + report.compare(
                    [r for r in cases if r.case_id not in marked_ids],
                    [r for r in other_cases if r.case_id not in marked_ids],
                )
            )
```

- [ ] **Step 4: Run the tests, then the whole check**

Run: the Step 2 command, then `make check`
Expected: PASS; green.

- [ ] **Step 5: Commit**

```bash
git add src/ntsb_probable_cause/scoring/ apps/eval/__main__.py tests/ docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: marks reach the case results; the report prints all cases, unmarked cases and each marked group (spec §4.4)"
```

---

### Task 10: An image input at the model seam; the candidates' prices and reasoning levels (spec §7.2, §8.2)

*Depends on decision W1 (images never through the batch service).*

**Files:**
- Modify: `src/ntsb_probable_cause/model/client.py` (+ `PageImage`; `Payload` carries images; `Payload.for_page`)
- Modify: `src/ntsb_probable_cause/model/openrouter.py` (`request_body` sends image parts)
- Modify: `src/ntsb_probable_cause/model/batch.py` (`submit` refuses a request carrying an image)
- Modify: `src/ntsb_probable_cause/sources.py` (+ `GEMINI_36_FLASH`, `QWEN_35_122B`; `ReasoningEffort` gains `"minimal"`; + `LOWEST_REASONING`)
- Test: `tests/test_model_client.py`, `tests/test_openrouter.py`, `tests/test_batch.py`, `tests/test_sources_settings.py`

**Interfaces:**
- Produces: `model.client.PageImage` (frozen pydantic: `media_type: Literal["image/jpeg", "image/png"]`, `data: bytes`; property `sha256: str`; method `data_url() -> str`); `Payload.images -> tuple[PageImage, ...]`; `Payload.from_evidence(evidence, *, images: Sequence[PageImage] = ())`; `Payload.for_page(image: PageImage, *, text_layer: str | None = None) -> Payload`.
- Produces: `request_body` sends `"content": [{"type": "text", "text": ...}?, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}, ...]` when the payload carries images, and exactly today's string content when it does not.
- Produces: `sources.GEMINI_36_FLASH`, `sources.QWEN_35_122B` (`ModelPrice`, standard prices); `sources.ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]`; `sources.LOWEST_REASONING: dict[str, ReasoningEffort]`.

**The facts, and where they come from** (OpenRouter models list, <https://openrouter.ai/api/v1/models>, read 2026-09-24): Gemini 3.6 Flash $0.75/$3.75 per million tokens in/out, reasoning levels `minimal`–`high` and mandatory; Gemini 3.1 Flash Lite `minimal`–`high` (already priced in `sources.py` from S1); GPT-6 Luna `none`–`max`; Qwen3.5 122B $0.26/$2.08, no batch variant, reasoning optional with no listed levels. All four list `structured_outputs`. The batch refusal cites <https://openrouter.ai/docs/batch-quickstart>, read 2026-09-24.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_model_client.py`:

```python
def test_a_page_payload_carries_one_image_and_only_its_text_layer() -> None:
    image = PageImage(media_type="image/jpeg", data=b"\xff\xd8jpeg")
    plain = Payload.for_page(image)
    mixed = Payload.for_page(image, text_layer="FUEL SELECTOR: BOTH")
    assert plain.images == (image,) and plain.text == ""
    assert mixed.text == "FUEL SELECTOR: BOTH"
    assert image.data_url().startswith("data:image/jpeg;base64,")
    assert plain != mixed


def test_an_evidence_payload_has_no_images_unless_given(
    record_fixtures: list[dict[str, object]],
) -> None:
    evidence, _, _ = split_record(record_fixtures[0])
    assert Payload.from_evidence(evidence).images == ()
```

Append to `tests/test_openrouter.py`:

```python
def test_request_body_sends_image_parts_after_the_text() -> None:
    image = PageImage(media_type="image/jpeg", data=b"\xff\xd8jpeg")
    body = request_body(
        Payload.for_page(image, text_layer="typed words"),
        ModelSettings(model="google/gemini-3.1-flash-lite", price_variant="standard"),
        system="instruction",
        history=(),
    )
    assert body["messages"] == [
        {"role": "system", "content": "instruction"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "typed words"},
                {"type": "image_url", "image_url": {"url": image.data_url()}},
            ],
        },
    ]


def test_an_image_page_with_no_text_layer_sends_the_image_alone() -> None:
    image = PageImage(media_type="image/jpeg", data=b"\xff\xd8jpeg")
    body = request_body(Payload.for_page(image), ModelSettings(), system="s", history=())
    messages = body["messages"]
    assert isinstance(messages, list)
    assert messages[1]["content"] == [{"type": "image_url", "image_url": {"url": image.data_url()}}]
```

Append to `tests/test_batch.py` (use the file's existing `BatchRunner` construction and fake transport):

```python
def test_the_batch_service_refuses_an_image() -> None:
    """OpenRouter batch documentation, read 2026-09-24: base64 and data: images are rejected."""
    image = PageImage(media_type="image/jpeg", data=b"\xff\xd8jpeg")
    request = BatchRequest(custom_id="p1", payload=Payload.for_page(image), settings=ModelSettings())
    with pytest.raises(ConfigurationError, match="images cannot go through the batch service"):
        _runner().submit([request])
```

(`_runner()` stands for however `tests/test_batch.py` already builds a `BatchRunner` over a mock transport; the assertion must hold before any request is sent — assert the mock saw no request.)

Append to `tests/test_sources_settings.py`:

```python
def test_the_transcriber_candidates_are_priced_and_levelled() -> None:
    """OpenRouter models API, read 2026-09-24 (S2.6 spec §7.2)."""
    assert sources.price_of("google/gemini-3.6-flash") is sources.GEMINI_36_FLASH
    assert sources.price_of("qwen/qwen3.5-122b-a10b") is sources.QWEN_35_122B
    assert sources.LOWEST_REASONING == {
        "google/gemini-3.1-flash-lite": "minimal",
        "google/gemini-3.6-flash": "minimal",
        "openai/gpt-6-luna": "none",
        "qwen/qwen3.5-122b-a10b": "none",
    }
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_model_client.py tests/test_openrouter.py tests/test_batch.py tests/test_sources_settings.py -v -k "image or page or candidates"`
Expected: FAIL — `ImportError: cannot import name 'PageImage'`.

- [ ] **Step 3: `sources.py`**

After `GLM_53_FLASH_BATCH`:

```python
# https://openrouter.ai/api/v1/models, read 2026-09-24: the transcriber candidates of S2.6
# spec §7.2 that S1 had not priced. Standard prices only: an image cannot go through the batch
# service (https://openrouter.ai/docs/batch-quickstart, read 2026-09-24), and Qwen has no
# batch variant at all.
GEMINI_36_FLASH = ModelPrice(
    "google/gemini-3.6-flash", 0.75, 3.75, "OpenRouter models API, 2026-09-24"
)
QWEN_35_122B = ModelPrice("qwen/qwen3.5-122b-a10b", 0.26, 2.08, "OpenRouter models API, 2026-09-24")
```

Add both to `_PRICES`. Change `ReasoningEffort` and add the table:

```python
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
}
```

- [ ] **Step 4: `model/client.py`**

Add `import base64` and `import hashlib`, and before `Payload`:

```python
class PageImage(BaseModel):
    """One page image for a model: a rendered page, never an image pulled out of a PDF (0075)."""

    model_config = ConfigDict(frozen=True)
    media_type: Literal["image/jpeg", "image/png"]
    data: bytes

    @property
    def sha256(self) -> str:
        """The image's hash."""
        return hashlib.sha256(self.data).hexdigest()

    def data_url(self) -> str:
        """The image as a ``data:`` URL, the form the chat-completions endpoint accepts."""
        return f"data:{self.media_type};base64,{base64.b64encode(self.data).decode('ascii')}"
```

In `Payload`: the class docstring's first line becomes `The exact text and images a model would receive. Built only by Payload.from_evidence, or for one page's transcription by Payload.for_page.`; `__slots__ = ("_images", "_text")`; `__init__(self, text: str, *, images: tuple[PageImage, ...] = (), _token: object)` also sets `_images`; `from_evidence(cls, evidence: Evidence, *, images: Sequence[PageImage] = ())` passes `images=tuple(images)` (docstring: `images are the v3 probe's pictures (S2.6 §10), chosen by the runner from pages whose transcription passed this same guard; empty otherwise.`); and add:

```python
    @classmethod
    def for_page(cls, image: PageImage, *, text_layer: str | None = None) -> Payload:
        """A page transcription's request: one page image and, on a mixed page, that page's
        own text layer (S2.6 §8.2). It takes no evidence and no record, so no withheld text
        has a way in; ``tests/test_boundary.py`` checks the caller passes only the page's own
        text layer.
        """
        return cls(text_layer or "", images=(image,), _token=_CONSTRUCTION_TOKEN)

    @property
    def images(self) -> tuple[PageImage, ...]:
        """The images sent after the text, in order; empty for a text-only payload."""
        return self._images
```

`__eq__` compares `_text` and `_images`; `__hash__` is `hash((self._text, tuple(i.sha256 for i in self._images)))`.

- [ ] **Step 5: `model/openrouter.py`**

Replace `messages.append({"role": "user", "content": payload.text})` with `messages.append({"role": "user", "content": _user_content(payload)})` and add:

```python
def _user_content(payload: Payload) -> str | list[dict[str, object]]:
    """The user message: the text alone, byte for byte as before S2.6, unless images ride too.

    With images, the text (when there is any) comes first, then each image as a ``data:``
    URL -- the chat-completions content-parts form.
    """
    if not payload.images:
        return payload.text
    parts: list[dict[str, object]] = []
    if payload.text:
        parts.append({"type": "text", "text": payload.text})
    parts.extend(
        {"type": "image_url", "image_url": {"url": image.data_url()}} for image in payload.images
    )
    return parts
```

- [ ] **Step 6: `model/batch.py`**

At the top of `BatchRunner.submit`, before anything is sent (import `ConfigurationError`):

```python
        if any(request.payload.images for request in requests):
            # https://openrouter.ai/docs/batch-quickstart, read 2026-09-24: "Image parts must be
            # public http(s) URLs. Base64 and data: URI images are rejected on every provider."
            raise ConfigurationError(
                "images cannot go through the batch service: OpenRouter rejects base64 and "
                "data: images in a batch. Send image requests synchronously (S2.6, decision W1)."
            )
```

- [ ] **Step 7: Run the tests, then the whole check**

Run: the Step 2 command, then `make check`
Expected: PASS; green. Every existing request-body test passes unchanged, which is the proof that a text-only request is byte for byte what it was.

- [ ] **Step 8: Commit**

```bash
git add src/ntsb_probable_cause/model/ src/ntsb_probable_cause/sources.py tests/ docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: page images at the model seam, never through the batch service; transcriber candidates priced"
```

---

### Task 11: The transcription module (spec §7, §8.1–§8.3; decisions 0079, 0081; no paid call)

**Files:**
- Create: `src/ntsb_probable_cause/docket/transcribe.py`
- Modify: `src/ntsb_probable_cause/docket/pages.py` (+ `page_text`; in `pages.py`, not `extract.py`, because Task 14 makes `extract.py` import `transcribe.py`, which imports this)
- Modify: `src/ntsb_probable_cause/settings.py` (+ `transcription_dir`, derived from `data_dir`)
- Modify: `tests/boundary.py`, `tests/test_boundary.py` (the transcription boundary and its mutation test)
- Create: `tests/test_docket_transcribe.py`

**Interfaces:**
- Consumes: `docket.render.render_pages`, `RenderedPage`, `MEDIA_TYPE`, `Resolution`; `model.client.PageImage`, `Payload.for_page`, `ModelClient`, `ModelSettings`, `cost_usd`; `sources.LOWEST_REASONING`.
- Produces: `docket.transcribe.PageLabel` (the eight inventory kinds, a `Literal`); `PAGE_LABELS: tuple[PageLabel, ...]`; `ILLEGIBLE = "[illegible]"`; `Instruction` (frozen dataclass: `version: str`, `system: str`, `mixed_system: str`, `copies_words: bool`; method `schema() -> dict[str, object]`); `TRANSCRIBE` (version `"t1"`) and `LABEL` (version `"i1"`, copies no words); `TranscriptionKey` (frozen pydantic: `document_sha256: str`, `page: int`, `model: str`, `instruction: str`, `dpi: int`; method `digest() -> str`); `Transcription` (frozen pydantic record, below); `TranscriptionCache(root: Path)` with `get(key) -> Transcription | None` and `put(record) -> None`; `PageJob` (frozen dataclass: `key: TranscriptionKey`, `load: Callable[[], bytes]`, `mixed: bool`); `request_for(rendered, instruction, *, text_layer) -> tuple[Payload, str]`; `settings_for(model, instruction) -> ModelSettings`; `parse_reply(content, instruction) -> tuple[str, PageLabel]`; `read_page(job, client, instruction, *, now) -> Transcription`; `transcribe_all(jobs, client_factory, cache, instruction, *, workers=8, chunk=50, on_chunk=..., retry_failed=False, now=...) -> list[Transcription]`.
- Produces: `docket.pages.page_text(data: bytes, page: int) -> str`; `Settings.transcription_dir: Path` (default `<data_dir>/transcriptions`, `NTSB_TRANSCRIPTION_DIR`).

**The cache key, and one departure from the spec's wording.** Spec §8.3 keys the cache on "the page image's hash, the model, the instruction's version and the resolution". This plan keys it on **the document's content hash and the page number** in place of the image hash, and stores the image hash in the record. The two identify the same thing — the same document bytes drawn at the same resolution give the same image (checked while planning: rendering is repeatable) — but the document key lets an evaluation run find a page's transcription without drawing every page first. A change of model, instruction or resolution still changes the key. Logged in Deviations.

**The instruction (version t1), fixed before any test runs** because the transcriber test measures it:

> You copy the words on one page image from an aviation accident investigation docket. Copy every word you can read, in reading order, one line of the page per line, exactly as written: keep numbers, units, dates, abbreviations and spelling as they are. Where you cannot read a word, write [illegible] in its place; never guess. Do not describe pictures, summarise, explain, correct or add anything that is not written on the page. If the page holds no words, return an empty text. Say what the page mainly shows, as exactly one of: typed text, handwriting, filled form, photograph, diagram or chart, logo or letterhead only, mixed, blank.

On a mixed page the same instruction is followed by: *This page already has a text layer, which is given with the image. Copy only words in the page's images that are not already in that text layer; if there are none, return an empty text.*

The inventory's instruction (version i1) asks for the kind alone and copies no words, so nothing graphic or personal is stored (spec §6.2 item 3).

- [ ] **Step 1: Write the failing tests**

`tests/test_docket_transcribe.py`:

```python
"""Transcription: request, reply, cache and pool, with a fake client (S2.6 §8)."""

import json
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ntsb_probable_cause.docket.transcribe import (
    ILLEGIBLE,
    LABEL,
    TRANSCRIBE,
    PageJob,
    Transcription,
    TranscriptionCache,
    TranscriptionKey,
    parse_reply,
    read_page,
    transcribe_all,
)
from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.model.client import RecordingFakeClient, Usage
from tests.pdf_builder import PageSpec, build_pdf

NOW = datetime(2026, 10, 1, tzinfo=UTC)
TYPED = "Engine sputtered at 800 ft. Switched tanks, no change."
DOC = build_pdf([PageSpec(text=TYPED), PageSpec(text=TYPED, images=("/DCTDecode",))])


def _key(page: int = 1, model: str = "google/gemini-3.1-flash-lite") -> TranscriptionKey:
    return TranscriptionKey(
        document_sha256="d" * 64, page=page, model=model, instruction="t1", dpi=150
    )


def _reply(text: str, kind: str = "handwriting") -> str:
    return json.dumps({"text": text, "page_kind": kind})


def test_the_instruction_forbids_guessing_and_describing() -> None:
    assert ILLEGIBLE in TRANSCRIBE.system and "never guess" in TRANSCRIBE.system
    assert "Do not describe pictures" in TRANSCRIBE.system
    assert "Copy only words in the page's images" in TRANSCRIBE.mixed_system
    assert "text" in TRANSCRIBE.schema()["properties"]  # type: ignore[operator]
    assert "text" not in LABEL.schema()["properties"]  # type: ignore[operator]


def test_parse_reply_reads_words_and_kind() -> None:
    assert parse_reply(_reply(f"Switched to {ILLEGIBLE} tank"), TRANSCRIBE) == (
        f"Switched to {ILLEGIBLE} tank",
        "handwriting",
    )
    assert parse_reply(_reply("words it was told not to copy", "photograph"), LABEL) == (
        "",
        "photograph",
    )


@pytest.mark.parametrize(
    "content", [None, "not json", "[]", json.dumps({"text": "x", "page_kind": "poem"})]
)
def test_parse_reply_refuses_a_bad_reply(content: str | None) -> None:
    with pytest.raises(SchemaError):
        parse_reply(content, TRANSCRIBE)


def test_read_page_sends_the_image_and_records_cost_and_kind() -> None:
    client = RecordingFakeClient(
        [_reply("Engine sputtered at 800 ft.")], usage=[Usage(prompt_tokens=1000, completion_tokens=20)]
    )
    record = read_page(PageJob(_key(), lambda: DOC, mixed=False), client, TRANSCRIBE, now=lambda: NOW)
    assert record.status == "transcribed"
    assert record.text == "Engine sputtered at 800 ft."
    assert record.page_kind == "handwriting"
    assert record.cost_usd == pytest.approx((1000 * 0.25 + 20 * 1.50) / 1e6)
    (payload,) = client.payloads
    assert payload.text == "" and len(payload.images) == 1
    assert client.systems == [TRANSCRIBE.system]
    assert client.settings[0].price_variant == "standard"
    assert client.settings[0].reasoning_effort == "minimal"


def test_a_mixed_page_sends_its_own_text_layer_and_the_mixed_instruction() -> None:
    client = RecordingFakeClient([_reply("")])
    read_page(PageJob(_key(page=2), lambda: DOC, mixed=True), client, TRANSCRIBE, now=lambda: NOW)
    assert TYPED.split(".")[0] in client.payloads[0].text
    assert client.systems == [TRANSCRIBE.mixed_system]


def test_a_bad_reply_is_a_failed_page_that_still_costs() -> None:
    client = RecordingFakeClient(["no"], usage=[Usage(prompt_tokens=1000, completion_tokens=5)])
    record = read_page(PageJob(_key(), lambda: DOC, mixed=False), client, TRANSCRIBE, now=lambda: NOW)
    assert record.status == "failed"
    assert record.error is not None and record.error.startswith("schema:")
    assert record.cost_usd > 0
    assert record.text == ""


def test_the_key_changes_with_model_instruction_and_resolution() -> None:
    base = _key()
    assert base.digest() == _key().digest()
    assert base.digest() != _key(model="google/gemini-3.6-flash").digest()
    assert base.digest() != base.model_copy(update={"instruction": "t2"}).digest()
    assert base.digest() != base.model_copy(update={"dpi": 200}).digest()


def test_the_cache_round_trips(tmp_path: Path) -> None:
    cache = TranscriptionCache(tmp_path)
    record = Transcription(key=_key(), status="transcribed", text="x", page_kind="blank", created=NOW)
    assert cache.get(_key()) is None
    cache.put(record)
    assert cache.get(_key()) == record


def test_transcribe_all_skips_cached_pages_and_reports_chunks(tmp_path: Path) -> None:
    cache = TranscriptionCache(tmp_path)
    cache.put(Transcription(key=_key(1), status="transcribed", text="", page_kind="blank", created=NOW))
    jobs = [PageJob(_key(n), lambda: DOC, mixed=False) for n in (1, 2)]
    chunks: list[int] = []
    made: list[int] = []
    lock = threading.Lock()

    def factory() -> RecordingFakeClient:
        with lock:
            made.append(1)
        return RecordingFakeClient([_reply("words")])

    def on_chunk(records: Sequence[Transcription]) -> None:
        chunks.append(len(records))

    done = transcribe_all(jobs, factory, cache, TRANSCRIBE, workers=2, chunk=1, on_chunk=on_chunk)
    assert [r.key.page for r in done] == [2]
    assert chunks == [1]
    assert cache.get(_key(2)) is not None
    assert len(made) <= 2


def test_a_failed_page_is_retried_only_when_asked(tmp_path: Path) -> None:
    cache = TranscriptionCache(tmp_path)
    cache.put(Transcription(key=_key(1), status="failed", error="model: ModelError", created=NOW))
    jobs = [PageJob(_key(1), lambda: DOC, mixed=False)]
    factory = lambda: RecordingFakeClient([_reply("words")])  # noqa: E731
    assert transcribe_all(jobs, factory, cache, TRANSCRIBE, workers=1) == []
    (again,) = transcribe_all(jobs, factory, cache, TRANSCRIBE, workers=1, retry_failed=True)
    assert again.status == "transcribed"
```

Append to `tests/test_boundary.py` (the check itself goes in `tests/boundary.py`, beside the file's other checks):

```python
def test_a_transcription_request_holds_only_the_image_instruction_and_text_layer(
    record_fixtures: list[dict[str, object]],
) -> None:
    """S2.6 spec §8.2 and §12: nothing but the page -- in particular no withheld text."""
    document = build_pdf([PageSpec(text="FUEL SELECTOR BOTH. MIXTURE RICH.", images=("/DCTDecode",))])
    (rendered,) = render_pages(document)
    for raw in record_fixtures:
        payload, system = request_for(rendered, TRANSCRIBE, text_layer=page_text(document, 1))
        body = request_body(payload, settings_for("google/gemini-3.1-flash-lite", TRANSCRIBE),
                            system=system, history=())
        assert_transcription_request_only(
            body, system=TRANSCRIBE.mixed_system, image=payload.images[0],
            text_layer=page_text(document, 1),
        )
        _, synthesis, verdict = split_record(raw)
        sent = json.dumps(body)
        for text in (*synthesis.texts().values(), verdict.probable_cause):
            assert not text or normalise_text(text)[:60] not in normalise_text(sent)


def test_the_transcription_boundary_check_can_fail(
    record_fixtures: list[dict[str, object]],
) -> None:
    """The mutation: a request that also carries the case's own narrative must be caught."""
    document = build_pdf([PageSpec(text="FUEL SELECTOR BOTH.", images=("/DCTDecode",))])
    (rendered,) = render_pages(document)
    evidence, _, _ = split_record(record_fixtures[0])
    layer = page_text(document, 1)
    image = request_for(rendered, TRANSCRIBE, text_layer=layer)[0].images[0]
    rogue = Payload.for_page(image, text_layer=f"{layer}\n{evidence.prelim_narrative or 'x'}")
    body = request_body(rogue, settings_for("google/gemini-3.1-flash-lite", TRANSCRIBE),
                        system=TRANSCRIBE.mixed_system, history=())
    with pytest.raises(AssertionError):
        assert_transcription_request_only(
            body, system=TRANSCRIBE.mixed_system, image=image, text_layer=layer
        )
```

In `tests/boundary.py`:

```python
def assert_transcription_request_only(
    body: Mapping[str, object], *, system: str, image: PageImage, text_layer: str | None
) -> None:
    """S2.6 spec §8.2: the fixed instruction, the page image and that page's own text layer.

    Equality, not a search: anything else in the request -- a field, a message, another
    image, one more character of text -- fails, so no withheld text can ride along unseen.
    """
    expected: list[dict[str, object]] = []
    if text_layer:
        expected.append({"type": "text", "text": text_layer})
    expected.append({"type": "image_url", "image_url": {"url": image.data_url()}})
    assert body["messages"] == [
        {"role": "system", "content": system},
        {"role": "user", "content": expected},
    ]
```

(Import what these need into `tests/test_boundary.py`: `json`, `build_pdf`/`PageSpec`, `render_pages`, `page_text`, `TRANSCRIBE`, `request_for`, `settings_for`, `request_body`, `normalise_text`, `Payload`, and `assert_transcription_request_only` from `tests.boundary`; `PageImage` into `tests/boundary.py`. Let ruff format tidy the call layout.)

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_docket_transcribe.py tests/test_boundary.py -v -k "transcri or page"`
Expected: FAIL — `ModuleNotFoundError: No module named 'ntsb_probable_cause.docket.transcribe'`.

- [ ] **Step 3: `docket/pages.py` and `settings.py`**

In `docket/pages.py`:

```python
def page_text(data: bytes, page: int) -> str:
    """One page's text layer (1-based), as ``extract_pdf`` reads it; empty if unreadable."""
    try:
        return (PdfReader(io.BytesIO(data)).pages[page - 1].extract_text() or "").strip()
    except Exception:  # an unreadable page has no text layer, as in extract_pdf
        return ""
```

In `settings.py`: `transcription_dir: Path = Path("data/transcriptions")` beside `docket_dir`, with a comment `# S2.6 (decision 0081): the per-page transcription cache; never committed.`, and in `model_post_init`: `if "transcription_dir" not in self.model_fields_set: object.__setattr__(self, "transcription_dir", self.data_dir / "transcriptions")`. Add a test beside the existing `docket_dir` derivation test in `tests/test_sources_settings.py`, and a line under "Settings come from the environment" in `CLAUDE.md` naming `NTSB_TRANSCRIPTION_DIR`.

- [ ] **Step 4: `docket/transcribe.py`**

```python
"""Transcription: the words on a page image, copied and nothing else (S2.6 §7, §8; 0079-0081).

A dedicated transcriber reads each page once and the agent reads the text: the agent's own
model reads handwriting poorly (spec §7.1). Transcription is evidence preparation (0081):
cached once per page under ``NTSB_DATA_DIR``, paid once, reused by every run and arm, and
costed apart from the agent's per-case cap.

A request holds only the page image, a fixed instruction and -- on a mixed page -- that
page's own text layer (spec §8.2); ``tests/test_boundary.py`` checks nothing else is sent.
Every image call is synchronous at the standard price: the batch service rejects images
(``model/batch.py``).
"""

import hashlib
import json
import os
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.pages import page_text
from ntsb_probable_cause.docket.render import MEDIA_TYPE, RenderedPage, Resolution, render_pages
from ntsb_probable_cause.errors import DocketError, ModelError, SchemaError
from ntsb_probable_cause.model.client import (
    ModelClient,
    ModelSettings,
    PageImage,
    Payload,
    cost_usd,
)

PageLabel = Literal[
    "typed text",
    "handwriting",
    "filled form",
    "photograph",
    "diagram or chart",
    "logo or letterhead only",
    "mixed",
    "blank",
]
PAGE_LABELS: tuple[PageLabel, ...] = (
    "typed text",
    "handwriting",
    "filled form",
    "photograph",
    "diagram or chart",
    "logo or letterhead only",
    "mixed",
    "blank",
)
# Decision 0079: what the transcriber writes for a word it cannot read, instead of a guess.
ILLEGIBLE = "[illegible]"
MAX_OUTPUT_TOKENS = 4000
_ERROR_CHARS = 200


@dataclass(frozen=True)
class Instruction:
    """A fixed instruction, its version (in every cache key), and whether it copies words."""

    version: str
    system: str
    mixed_system: str
    copies_words: bool

    def schema(self) -> dict[str, object]:
        """The reply's JSON schema: the page kind, and the words when the instruction copies."""
        properties: dict[str, object] = {"page_kind": {"type": "string", "enum": list(PAGE_LABELS)}}
        if self.copies_words:
            properties["text"] = {"type": "string"}
        return {
            "type": "object",
            "properties": properties,
            "required": sorted(properties),
            "additionalProperties": False,
        }


_KINDS = "Say what the page mainly shows, as exactly one of: " + ", ".join(PAGE_LABELS) + "."
_COPY = (
    "You copy the words on one page image from an aviation accident investigation docket. "
    "Copy every word you can read, in reading order, one line of the page per line, exactly "
    "as written: keep numbers, units, dates, abbreviations and spelling as they are. Where you "
    f"cannot read a word, write {ILLEGIBLE} in its place; never guess. Do not describe "
    "pictures, summarise, explain, correct or add anything that is not written on the page. "
    "If the page holds no words, return an empty text. "
)
_MIXED = (
    " This page already has a text layer, which is given with the image. Copy only words in "
    "the page's images that are not already in that text layer; if there are none, return an "
    "empty text."
)
_LOOK = (
    "You see one page image from an aviation accident investigation docket. "
    + _KINDS
    + " Do not copy any words and do not describe the page."
)

# Version t1 (S2.6 Task 11): fixed before the transcriber test, which measures it. Any
# change is a new version, and so a new cache key and a re-run of the test.
TRANSCRIBE = Instruction("t1", _COPY + _KINDS, _COPY + _KINDS + _MIXED, copies_words=True)
# Version i1: the inventory's labeller (spec §6.2 item 3). Categories only, never words.
LABEL = Instruction("i1", _LOOK, _LOOK, copies_words=False)


class TranscriptionKey(BaseModel):
    """What identifies one reading of one page: the document, page, model, instruction, dpi."""

    model_config = ConfigDict(frozen=True)
    document_sha256: str
    page: int
    model: str
    instruction: str
    dpi: int

    def digest(self) -> str:
        """A stable hash of every field: the cache file's name."""
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class Transcription(BaseModel):
    """One page's reading, or why it failed, with what it cost (0081 item 3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    key: TranscriptionKey
    status: Literal["transcribed", "failed"]
    text: str = ""
    page_kind: PageLabel | None = None
    image_sha256: str | None = None
    image_area_share: float | None = None
    mixed: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    created: datetime


class TranscriptionCache:
    """One JSON file per reading under a root directory, written atomically."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: TranscriptionKey) -> Path:
        digest = key.digest()
        return self._root / digest[:2] / f"{digest}.json"

    def get(self, key: TranscriptionKey) -> Transcription | None:
        """The cached reading for a key, or ``None``."""
        path = self._path(key)
        return Transcription.model_validate_json(path.read_text()) if path.is_file() else None

    def put(self, record: Transcription) -> None:
        """Write a reading; a kill mid-write leaves the old file or none, never half of one."""
        path = self._path(record.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.partial")
        partial.write_text(record.model_dump_json())
        partial.replace(path)


@dataclass(frozen=True)
class PageJob:
    """One page to read: its key, how to load its document's bytes, and whether it is mixed."""

    key: TranscriptionKey
    load: Callable[[], bytes]
    mixed: bool


def request_for(
    rendered: RenderedPage, instruction: Instruction, *, text_layer: str | None
) -> tuple[Payload, str]:
    """The only request a reading sends: the image, the instruction, the page's own text."""
    image = PageImage(media_type=MEDIA_TYPE, data=rendered.data)
    if text_layer:
        return Payload.for_page(image, text_layer=text_layer), instruction.mixed_system
    return Payload.for_page(image), instruction.system


def settings_for(model: str, instruction: Instruction) -> ModelSettings:
    """Standard price (images cannot be batched), temperature 0, lowest reasoning, recorded."""
    return ModelSettings(
        model=model,
        price_variant="standard",
        temperature=0.0,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        json_schema=instruction.schema(),
        schema_name="page",
        reasoning_effort=sources.LOWEST_REASONING[model],
    )


def parse_reply(content: str | None, instruction: Instruction) -> tuple[str, PageLabel]:
    """The words (empty for an instruction that copies none) and the page kind."""
    try:
        body = json.loads(content or "")
    except json.JSONDecodeError as error:
        raise SchemaError(f"reply is not JSON: {error.msg}") from error
    if not isinstance(body, dict):
        raise SchemaError("reply is not a JSON object")
    kind = body.get("page_kind")
    if kind not in PAGE_LABELS:
        raise SchemaError(f"page_kind is not one of the labels: {kind!r}")
    text = body.get("text", "") if instruction.copies_words else ""
    if not isinstance(text, str):
        raise SchemaError("text is not a string")
    return text.strip(), cast(PageLabel, kind)


def read_page(
    job: PageJob,
    client: ModelClient,
    instruction: Instruction,
    *,
    now: Callable[[], datetime],
) -> Transcription:
    """Draw the page, send it, parse the reply. Every outcome is a record; nothing raises."""
    key = job.key
    try:
        data = job.load()
        (rendered,) = render_pages(data, [key.page], dpi=cast(Resolution, key.dpi))
    except DocketError as error:
        return Transcription(
            key=key, status="failed", error=f"render: {error}"[:_ERROR_CHARS], mixed=job.mixed,
            created=now(),
        )
    text_layer = page_text(data, key.page) if job.mixed else None
    payload, system = request_for(rendered, instruction, text_layer=text_layer)
    settings = settings_for(key.model, instruction)
    try:
        reply = client.complete(payload, settings, system=system)
    except ModelError as error:
        return Transcription(
            key=key, status="failed", error=f"model: {type(error).__name__}",
            image_sha256=rendered.sha256, image_area_share=rendered.image_area_share,
            mixed=job.mixed, created=now(),
        )
    cost, _ = cost_usd(reply, settings)
    try:
        text, kind = parse_reply(reply.content, instruction)
    except SchemaError as error:
        return Transcription(
            key=key, status="failed", error=f"schema: {error}"[:_ERROR_CHARS],
            image_sha256=rendered.sha256, image_area_share=rendered.image_area_share,
            mixed=job.mixed, prompt_tokens=reply.usage.prompt_tokens,
            completion_tokens=reply.usage.completion_tokens, cost_usd=cost, created=now(),
        )
    return Transcription(
        key=key, status="transcribed", text=text, page_kind=kind,
        image_sha256=rendered.sha256, image_area_share=rendered.image_area_share,
        mixed=job.mixed, prompt_tokens=reply.usage.prompt_tokens,
        completion_tokens=reply.usage.completion_tokens, cost_usd=cost, created=now(),
    )


def transcribe_all(  # noqa: PLR0913 -- every parameter is a seam a test or a caller needs.
    jobs: Sequence[PageJob],
    client_factory: Callable[[], ModelClient],
    cache: TranscriptionCache,
    instruction: Instruction,
    *,
    workers: int = 8,
    chunk: int = 50,
    on_chunk: Callable[[Sequence[Transcription]], None] = lambda _records: None,
    retry_failed: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[Transcription]:
    """Read every page not already cached, on a pool of threads with one client each.

    Each reading is cached the moment it returns, so an interrupted job loses only the pages
    in flight. ``on_chunk`` is handed every ``chunk`` new readings, and the remainder at the
    end or on an interruption, so the caller can append a spend row (0081) as money is
    spent. A page cached as failed is read again only with ``retry_failed``. The caller owns
    the clients the factory makes and closes them afterwards.
    """
    pending = [
        job
        for job in jobs
        if (cached := cache.get(job.key)) is None or (retry_failed and cached.status == "failed")
    ]
    local = threading.local()

    def work(job: PageJob) -> Transcription:
        client = getattr(local, "client", None)
        if client is None:
            client = local.client = client_factory()
        record = read_page(job, client, instruction, now=now)
        cache.put(record)
        return record

    done: list[Transcription] = []
    unreported: list[Transcription] = []
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = [pool.submit(work, job) for job in pending]
    try:
        for future in as_completed(futures):
            record = future.result()
            done.append(record)
            unreported.append(record)
            if len(unreported) >= chunk:
                on_chunk(unreported)
                unreported = []
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        if unreported:
            on_chunk(unreported)
    return done
```

Let `ruff format` lay out the keyword-argument calls; the content is what matters.

- [ ] **Step 5: Run the tests, then the whole check**

Run: the Step 2 command, then `make check`
Expected: PASS; green. `import-linter`: `docket.transcribe` imports `model.client`, which is allowed (the model boundary contract forbids `model` importing `scoring` or the withheld modules, not `docket` importing `model`). Vulture scans `src`, `apps`, `scripts` and `infra` at 80% confidence; an unused module-level name scores 60%, so `LABEL` (first used by Task 12) is not reported.

- [ ] **Step 6: Commit**

```bash
git add src/ntsb_probable_cause/docket/transcribe.py src/ntsb_probable_cause/docket/pages.py src/ntsb_probable_cause/settings.py tests/ CLAUDE.md docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: transcription -- the fixed instruction, the per-page cache, the worker pool, the boundary (0079, 0081)"
```

---

### Task 12: The inventory (spec §6; decision 0074 item 2; paid, about $0.20; three stops)

*Depends on decisions W2 (photo-only entries), W3 (the mixed-page cut-off rule) and W6 (the stop rule's number).*

**Files:**
- Create: `src/ntsb_probable_cause/docket/documents.py` (documents from the cache, by case and listing index)
- Create: `src/ntsb_probable_cause/scoring/preparation.py` (a paid preparation job: reservation, spend rows, clients)
- Create: `scripts/page_inventory.py`
- Modify: `src/ntsb_probable_cause/docket/transcribe.py` (+ `MIXED_PAGE_MIN_IMAGE_SHARE`, set from the result)
- Modify: `Makefile` (+ `s26-inventory-probe`, `s26-inventory`)
- Create: `tests/test_docket_documents.py`, `tests/test_preparation.py`, `tests/test_page_inventory.py`
- Output: `docs/results/s26-inventory.txt` (committed); `data/s26/inventory/` (private: `sample.jsonl`, `pages/<n>.jpg`, `check.html`)

**Interfaces:**
- Produces: `docket.documents.CachedDocuments(client: DocketClient)` with `listing(mkey: int) -> Listing`, `document(mkey: int, index: int) -> bytes`, `loader(mkey: int, index: int) -> Callable[[], bytes]` (thread-safe; the client is built with a transport that refuses every request, so a miss is loud and free).
- Produces: `scoring.preparation.run_preparation(*, kind: Literal["inventory", "transcriber-test", "transcription"], jobs: Sequence[PageJob], instruction: Instruction, settings: Settings, commit: tuple[str, bool], expected_cost_per_page_usd: float, workers: int = 8, retry_failed: bool = False, client_factory: Callable[[ExitStack], Callable[[], ModelClient]] | None = None, now: Callable[[], datetime] = ...) -> list[Transcription]`. Refuses mixed models in one job; reserves `pending pages × expected cost` against `settings.monthly_budget_usd` (Task 7), appends a spend row per chunk, settles the reservation at the end, even on an abort.
- Produces: `scripts.page_inventory.draw_sample(frame, *, allocation, seed) -> list[dict[str, object]]`, `weighted_word_share(labels, population, *, counted=WORDS) -> float`, `final_labels(labels, marks) -> dict[int, str]`, `mixed_cut(rows: Sequence[tuple[float, str]]) -> float`, and the constants below. Task 13 reads `data/s26/inventory/sample.jsonl` and the inventory labels from the transcription cache.
- Produces: `docket.transcribe.MIXED_PAGE_MIN_IMAGE_SHARE: float` — a text-and-image page whose images cover less than this share of it is not sent (0079 item 3). Task 14 reads it.

**The sample (spec §6.2 item 2), fixed now.** Seed `20260924`. 300 pages from the page frame: image-only pages 68 fatal + 67 non-fatal; text-and-image pages 68 fatal + 67 non-fatal; text-only pages 15 + 15 as a control. Equal numbers per kind over-represent image-only pages against their share of the population, so every estimate over "all image-bearing pages" is weighted back by the frame's own page counts per stratum, and each stratum's own proportions are reported beside it. Decision W2 adds the photo-only documents as their own stratum, 15 fatal + 15 non-fatal (330 pages in all).

**The stop rule (spec §6.4), fixed now — decision W6.** Images "hold words" when a page labelled image-only is typed text, handwriting, a filled form or mixed, or when a text-and-image page is handwriting, a filled form or mixed (its typed text is already in the text layer). If the weighted share of image-bearing pages whose images hold words is **under 10%**, transcription stops (§6.4), and the stage records why.

**The mixed-page cut-off (W3), fixed now.** Among the sampled text-and-image pages, for each candidate cut of image-area share — 2%, 5%, 10%, 20%, in that order — take the pages below it. A cut is admissible when at most 1 in 20 of those pages have images that hold words. The chosen cut is the largest cut such that it and every smaller one are admissible; if the first is not, the cut is 0 and every text-and-image page is sent. Example: if the pages under 5% are 58 logos and 1 handwritten note (1 in 59), and the pages under 10% add 12 pages of which 3 hold handwriting (4 in 71), the cut is 5%.

**What Andy checks (spec §6.2 item 4).** A seeded 60 of the 330 (seed `20260925`), each shown as its image beside its label, marked right or wrong, with the right label chosen when wrong. Where Andy checked a page, his label is the one used.

- [ ] **Step 1: Confirm the photo-only pages are in the frame (decision W2)**

Task 1 fetched them (`--include-photo-only`). Check that `data/s26/pages-dev-400.jsonl` has rows with `"photo_only": true` and that `docs/results/s26-page-kinds.txt`'s `fetched and read:` line is not zero; if either fails, stop and re-run Task 1 Step 10. `ALLOCATION` below already holds the photo-only stratum.

- [ ] **Step 2: Write the failing tests**

`tests/test_docket_documents.py`: build a one-case cache in `tmp_path` in `DocketClient`'s layout (copy the listing from `tests/fixtures/docket/ERA17LA217/listing.html`, and write `1.bin` holding a `build_pdf` document with a `fetch.json` entry giving its `sha256` and the listing's `href` for index 1), then assert `CachedDocuments(client).document(mkey, 1)` returns those bytes, `loader(mkey, 1)()` returns the same, and an index the listing lacks raises `DocketError`.

`tests/test_preparation.py`:

```python
"""A paid preparation job: reserved, spent in rows, settled (decisions 0045, 0081)."""

import json
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ntsb_probable_cause.docket.transcribe import TRANSCRIBE, PageJob, TranscriptionKey
from ntsb_probable_cause.errors import BudgetError, ConfigurationError
from ntsb_probable_cause.model.client import RecordingFakeClient, Usage
from ntsb_probable_cause.scoring.budget import month_spent, open_reservations
from ntsb_probable_cause.scoring.preparation import run_preparation
from ntsb_probable_cause.settings import Settings
from tests.pdf_builder import PageSpec, build_pdf

NOW = datetime(2026, 10, 2, tzinfo=UTC)
DOC = build_pdf([PageSpec(text="Engine sputtered at 800 ft. Switched tanks.")] * 3)


def _jobs(model: str = "google/gemini-3.1-flash-lite") -> list[PageJob]:
    return [
        PageJob(
            TranscriptionKey(document_sha256="d" * 64, page=n, model=model, instruction="t1", dpi=150),
            lambda: DOC,
            mixed=False,
        )
        for n in (1, 2, 3)
    ]


def _factory(_stack: ExitStack) -> RecordingFakeClient:
    return RecordingFakeClient(
        [json.dumps({"text": "words", "page_kind": "typed text"})],
        usage=[Usage(prompt_tokens=1000, completion_tokens=100)],
    )


def test_spend_is_recorded_and_the_reservation_settled(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, monthly_budget_usd=40.0)
    done = run_preparation(
        kind="transcription", jobs=_jobs(), instruction=TRANSCRIBE, settings=settings,
        commit=("abc1234", False), expected_cost_per_page_usd=0.01, workers=1,
        client_factory=lambda stack: lambda: _factory(stack), now=lambda: NOW,
    )
    assert len(done) == 3
    assert month_spent(settings.runs_dir, now=NOW) == pytest.approx(3 * (250 + 150) / 1e6)
    assert open_reservations(settings.runs_dir) == {}


def test_a_job_over_the_budget_is_refused_before_any_call(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, monthly_budget_usd=0.01)
    with pytest.raises(BudgetError):
        run_preparation(
            kind="transcription", jobs=_jobs(), instruction=TRANSCRIBE, settings=settings,
            commit=("abc1234", False), expected_cost_per_page_usd=0.01, workers=1,
            client_factory=lambda stack: lambda: _factory(stack), now=lambda: NOW,
        )


def test_one_job_one_model(tmp_path: Path) -> None:
    jobs = [*_jobs(), *_jobs("google/gemini-3.6-flash")]
    with pytest.raises(ConfigurationError, match="one model"):
        run_preparation(
            kind="transcription", jobs=jobs, instruction=TRANSCRIBE,
            settings=Settings(data_dir=tmp_path), commit=("abc1234", False),
            expected_cost_per_page_usd=0.01, client_factory=lambda s: lambda: _factory(s),
        )
```

`tests/test_page_inventory.py`:

```python
"""scripts/page_inventory.py: the sample, the weights, the cut-off and the stop rule."""

from scripts import page_inventory as inv


def _frame() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for kind, count in (("image only", 200), ("text and image", 400), ("text only", 300)):
        for i in range(count):
            rows.append(
                {"case_id": f"C{i % 40}", "mkey": i, "fatal": i % 2 == 0, "document": 1,
                 "page": i, "pages": 999, "kind": kind}
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
        {"case_id": f"P{i}", "mkey": i, "fatal": i % 2 == 0, "document": 9, "page": i,
         "pages": 99, "kind": "image only", "photo_only": True}
        for i in range(40)
    ]
    sample = inv.draw_sample(_frame() + photos)
    assert sum(1 for r in sample if r["stratum"] == "photo-only/fatal") == 15
    assert not any(r.get("photo_only") for r in sample if r["stratum"] != "photo-only/fatal"
                   and r["stratum"] != "photo-only/non-fatal")


def test_weighted_share_weights_each_stratum_by_its_population() -> None:
    labels = {"image only/fatal": ["handwriting"] * 1 + ["photograph"] * 1,
              "text and image/fatal": ["typed text"] * 2}
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
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/test_docket_documents.py tests/test_preparation.py tests/test_page_inventory.py -v`
Expected: FAIL — the three modules do not exist.

- [ ] **Step 4: `docket/documents.py`**

```python
"""Docket documents from the cache, by case key and listing index (S2.6)."""

import threading
from collections.abc import Callable

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.listing import Listing, parse_listing
from ntsb_probable_cause.errors import DocketError


class CachedDocuments:
    """Read documents the docket client has cached; safe to share between threads.

    The client decides whether a miss may fetch: S2.6's scripts build it with a transport
    that refuses every request, so a page never costs a fetch it was not meant to.
    """

    def __init__(self, client: DocketClient) -> None:
        self._client = client
        self._listings: dict[int, Listing] = {}
        self._lock = threading.Lock()

    def listing(self, mkey: int) -> Listing:
        """The case's parsed listing, parsed once."""
        with self._lock:
            if mkey not in self._listings:
                self._listings[mkey] = parse_listing(self._client.listing_html(mkey), mkey=mkey)
            return self._listings[mkey]

    def document(self, mkey: int, index: int) -> bytes:
        """One document's bytes, by its listing index."""
        for entry in self.listing(mkey).entries:
            if entry.index == index:
                return self._client.document(mkey, index, entry.href)
        raise DocketError(f"docket {mkey}: no document at index {index}")

    def loader(self, mkey: int, index: int) -> Callable[[], bytes]:
        """A zero-argument loader for a ``PageJob``."""
        return lambda: self.document(mkey, index)
```

- [ ] **Step 5: `scoring/preparation.py`**

```python
"""A paid evidence-preparation job: reserved, spent row by row, settled (0045, 0081).

Transcription and the inventory are paid once per page and reused by every run (0081). They
count against the monthly budget like any run: the job reserves its projection before its
first call, appends a spend row as each chunk of pages returns, and settles the reservation
when it ends -- also when it is interrupted, since the spend rows already say what it cost.
"""

from collections.abc import Callable, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from typing import Literal

from ntsb_probable_cause.docket.transcribe import (
    Instruction,
    PageJob,
    Transcription,
    TranscriptionCache,
    transcribe_all,
)
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.model.client import ModelClient
from ntsb_probable_cause.model.openrouter import OpenRouterClient
from ntsb_probable_cause.scoring.budget import (
    SpendRecord,
    reserve_within_budget,
    settle,
    write_spend,
)
from ntsb_probable_cause.settings import Settings

Kind = Literal["inventory", "transcriber-test", "transcription"]


def openrouter_clients(settings: Settings) -> Callable[[ExitStack], Callable[[], ModelClient]]:
    """A factory of OpenRouter clients, each closed when the job's exit stack unwinds."""
    key = settings.openrouter_api_key
    if key is None or not key.get_secret_value():
        raise ConfigurationError("OPENROUTER_API_KEY is not set")
    secret = key.get_secret_value()

    def per_job(stack: ExitStack) -> Callable[[], ModelClient]:
        def make() -> ModelClient:
            return stack.enter_context(
                OpenRouterClient(secret, base_url=settings.openrouter_base_url)
            )

        return make

    return per_job


def run_preparation(  # noqa: PLR0913 -- one keyword per fact the job records.
    *,
    kind: Kind,
    jobs: Sequence[PageJob],
    instruction: Instruction,
    settings: Settings,
    commit: tuple[str, bool],
    expected_cost_per_page_usd: float,
    workers: int = 8,
    retry_failed: bool = False,
    client_factory: Callable[[ExitStack], Callable[[], ModelClient]] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[Transcription]:
    """Read the jobs' pages not yet cached, within the month's budget, recording the spend."""
    models = {job.key.model for job in jobs}
    if len(models) > 1:
        raise ConfigurationError(f"one model per preparation job, not {sorted(models)}")
    model = next(iter(models), "")
    cache = TranscriptionCache(settings.transcription_dir)
    pending = sum(
        1
        for job in jobs
        if (hit := cache.get(job.key)) is None or (retry_failed and hit.status == "failed")
    )
    started = now()
    sha, dirty = commit
    job_id = f"{started:%Y%m%dT%H%M%S}-{sha}-{kind}"
    reserve_within_budget(
        settings.runs_dir,
        job_id,
        pending * expected_cost_per_page_usd,
        settings.monthly_budget_usd,
        now=started,
    )

    def on_chunk(records: Sequence[Transcription]) -> None:
        write_spend(
            settings.runs_dir,
            SpendRecord(
                job_id=job_id,
                kind=kind,
                model=model,
                started=started,
                calls=len(records),
                cost_usd=sum(r.cost_usd for r in records),
                commit_sha=sha,
                dirty=dirty,
            ),
        )

    factory = client_factory or openrouter_clients(settings)
    try:
        with ExitStack() as stack:
            return transcribe_all(
                jobs,
                factory(stack),
                cache,
                instruction,
                workers=workers,
                on_chunk=on_chunk,
                retry_failed=retry_failed,
                now=now,
            )
    finally:
        settle(settings.runs_dir, job_id)
```

(`OpenRouterClient` is a context manager; its default `requests_per_minute=60` applies per worker thread. Check the exact `OpenRouterClient.__init__` keywords in `model/openrouter.py` after the merge and match them.)

- [ ] **Step 6: `scripts/page_inventory.py`**

```python
"""The inventory: what the image-bearing pages show, in measured proportions (S2.6 §6).

Status
    One-shot (S2.6, Task 12). Five subcommands, run in order:
      sample -- draw the 330 pages from the page frame (seeded) and draw each to a private image
      probe  -- label one page, to confirm the model accepts the request (paid, under a cent)
      label  -- label all 330 with Gemini 3.1 Flash Lite at minimal reasoning (paid, ~$0.20)
      check  -- write Andy's page for a seeded 60 of the 330
      score  -- write docs/results/s26-inventory.txt: counts, Andy's check, the mixed-page
                cut-off and the stop rule (spec §6.4)
    Everything but the results file lives under data/s26/inventory/ and is never committed.
    The labeller writes categories only, never words or descriptions (spec §6.2 item 3).
"""

import argparse
import hashlib
import html
import json
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.documents import CachedDocuments
from ntsb_probable_cause.docket.render import RESOLUTION, render_pages
from ntsb_probable_cause.docket.transcribe import (
    LABEL,
    PAGE_LABELS,
    PageJob,
    TranscriptionCache,
    TranscriptionKey,
    read_page,
)
from ntsb_probable_cause.gitinfo import commit_state
from ntsb_probable_cause.scoring.metrics import wilson
from ntsb_probable_cause.scoring.preparation import openrouter_clients, run_preparation
from ntsb_probable_cause.settings import Settings
from scripts import marking_page
from scripts.marking_page import Card, Choice

SEED = 20260924
CHECK_SEED = 20260925
CHECK_SIZE = 60
MODEL = "google/gemini-3.1-flash-lite"
# Conservative: the reservation is sized from this, the spend rows record the real cost.
EXPECTED_COST_PER_PAGE_USD = 0.002
ALLOCATION: dict[tuple[str, bool], int] = {
    ("image only", True): 68,
    ("image only", False): 67,
    ("text and image", True): 68,
    ("text and image", False): 67,
    ("text only", True): 15,
    ("text only", False): 15,
    # Decision W2 (Andy, 2026-09-24): the photo-only documents S2 never fetched, as their own
    # stratum, so an ordinary scan and a wreckage photograph are never drawn from one pool.
    ("photo-only", True): 15,
    ("photo-only", False): 15,
}
IMAGE_BEARING = ("image only", "text and image", "photo-only")
# Whether a page's images hold words (decision W6): on an image-only page typed text counts,
# because nothing else holds it; on a text-and-image page it does not, because the text
# layer already holds it. A photo-only page has no text layer, like an image-only one.
_IMAGE_ONLY_WORDS = frozenset({"typed text", "handwriting", "filled form", "mixed"})
WORDS = {
    "image only": _IMAGE_ONLY_WORDS,
    "text and image": frozenset({"handwriting", "filled form", "mixed"}),
    "photo-only": _IMAGE_ONLY_WORDS,
}
STOP_SHARE = 0.10
CUTS = (0.02, 0.05, 0.10, 0.20)
MAX_WORDS_BELOW_CUT = 1 / 20
FOLDER = Path("s26") / "inventory"


def sample_kind(row: Mapping[str, object]) -> str:
    """The page's kind for sampling: a page of a photo-only document is its own kind (W2)."""
    return "photo-only" if row.get("photo_only") else str(row["kind"])


def _stratum(kind: object, fatal: object) -> str:
    return f"{kind}/{'fatal' if fatal else 'non-fatal'}"


def draw_sample(
    frame: Sequence[Mapping[str, object]],
    *,
    allocation: Mapping[tuple[str, bool], int] = ALLOCATION,
    seed: int = SEED,
) -> list[dict[str, object]]:
    """The seeded, stratified sample, numbered 1..n in stratum order."""
    rng = random.Random(seed)  # noqa: S311 -- sampling, not security
    sample: list[dict[str, object]] = []
    for (kind, fatal), size in allocation.items():
        pool = sorted(
            (r for r in frame if sample_kind(r) == kind and r["fatal"] == fatal),
            key=lambda r: (str(r["case_id"]), int(str(r["document"])), int(str(r["page"]))),
        )
        for row in rng.sample(pool, min(size, len(pool))):
            sample.append({**row, "stratum": _stratum(kind, fatal)})
    for number, row in enumerate(sample, start=1):
        row["n"] = number
    return sample


def weighted_word_share(
    labels: Mapping[str, Sequence[str]],
    population: Mapping[str, int],
    *,
    counted: Mapping[str, frozenset[str]] = WORDS,
) -> float:
    """Of all image-bearing pages, the share whose label is ``counted`` for its kind.

    Weighted by each stratum's population in the frame. By default it counts pages whose
    images hold words (decision W6); the transcriber test's estimate passes the picture
    labels instead, to size the v3 probe.
    """
    total = 0.0
    hits = 0.0
    for stratum, stratum_labels in labels.items():
        kind = stratum.split("/")[0]
        if kind not in counted or not stratum_labels:
            continue
        share = sum(1 for label in stratum_labels if label in counted[kind]) / len(stratum_labels)
        hits += population[stratum] * share
        total += population[stratum]
    return hits / total if total else 0.0


def mixed_cut(rows: Sequence[tuple[float, str]]) -> float:
    """The largest run of admissible cuts of image-area share (decision W3)."""
    chosen = 0.0
    for cut in CUTS:
        below = [label for share, label in rows if share < cut]
        held = sum(1 for label in below if label in WORDS["text and image"])
        if below and held / len(below) > MAX_WORDS_BELOW_CUT:
            break
        chosen = cut
    return chosen


def stop_outcome(share: float) -> str:
    """Spec §6.4 with decision W6's number."""
    if share < STOP_SHARE:
        return (
            f"stop: {share:.1%} of image-bearing pages hold words in their images, under "
            f"{STOP_SHARE:.0%}; transcription is not worth its cost (spec §6.4)"
        )
    return f"go on: {share:.1%} of image-bearing pages hold words in their images"


# --- the subcommands (plumbing; the rules above are what the tests pin) ---


def _offline() -> httpx.BaseTransport:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline: the inventory reads the docket cache only")

    return httpx.MockTransport(refuse)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _key(row: Mapping[str, object]) -> TranscriptionKey:
    return TranscriptionKey(
        document_sha256=str(row["document_sha256"]),
        page=int(str(row["page"])),
        model=MODEL,
        instruction=LABEL.version,
        dpi=RESOLUTION,
    )


def _jobs(rows: Sequence[Mapping[str, object]], documents: CachedDocuments) -> list[PageJob]:
    return [
        PageJob(_key(r), documents.loader(int(str(r["mkey"])), int(str(r["document"]))), False)
        for r in rows
    ]


def cmd_sample(settings: Settings, documents: CachedDocuments) -> str:
    """Draw the sample; draw each page to a private JPEG; record hashes and image share."""
    folder = settings.data_dir / FOLDER
    (folder / "pages").mkdir(parents=True, exist_ok=True)
    frame = _read_jsonl(settings.data_dir / "s26" / "pages-dev-400.jsonl")
    sample = draw_sample(frame)
    for row in sample:
        data = documents.document(int(str(row["mkey"])), int(str(row["document"])))
        (page,) = render_pages(data, [int(str(row["page"]))])
        (folder / "pages" / f"{row['n']}.jpg").write_bytes(page.data)
        row["document_sha256"] = hashlib.sha256(data).hexdigest()
        row["image_area_share"] = page.image_area_share
    (folder / "sample.jsonl").write_text("".join(json.dumps(r) + "\n" for r in sample))
    population = Counter(_stratum(sample_kind(r), r["fatal"]) for r in frame)
    (folder / "population.json").write_text(json.dumps(population))
    return f"{len(sample)} pages drawn to {folder}"


def cmd_check(settings: Settings) -> str:
    """Andy's page: a seeded 60, each image beside its label."""
    folder = settings.data_dir / FOLDER
    sample = _read_jsonl(folder / "sample.jsonl")
    cache = TranscriptionCache(settings.transcription_dir)
    rng = random.Random(CHECK_SEED)  # noqa: S311 -- sampling, not security
    chosen = sorted(rng.sample(sample, CHECK_SIZE), key=lambda r: int(str(r["n"])))
    cards = []
    for row in chosen:
        record = cache.get(_key(row))
        label = record.page_kind if record is not None else "(no label)"
        cards.append(
            Card(
                row=int(str(row["n"])),
                body_html=(
                    f'<p class="meta">Page {row["n"]} · the model says: <b>{html.escape(str(label))}</b></p>'
                    f'<img src="pages/{row["n"]}.jpg" alt="page {row["n"]}">'
                ),
                choices=(
                    Choice("label", ("right", "wrong")),
                    Choice("correct label", PAGE_LABELS, required=False),
                ),
            )
        )
    intro = (
        "<p>Each card shows one docket page and the kind of page the model says it is. Mark the "
        "label right or wrong; when wrong, pick the right kind. The kinds: "
        + ", ".join(PAGE_LABELS)
        + ".</p>"
    )
    (folder / "check.html").write_text(
        marking_page.render(
            title="Inventory check (S2.6 spec §6.2)",
            intro_html=intro,
            cards=cards,
            storage_key="s26-inventory-check",
            csv_name="inventory-check-marks.csv",
        )
    )
    return f"page at {folder / 'check.html'}"


def final_labels(
    labels: Mapping[int, str], marks: Mapping[int, Mapping[str, str]]
) -> dict[int, str]:
    """The model's labels, with Andy's where he marked one wrong and gave the right kind."""
    final = dict(labels)
    for n, fields in marks.items():
        if fields.get("label") == "wrong" and fields.get("correct label"):
            final[n] = fields["correct label"]
    return final


def score_text(
    sample: Sequence[Mapping[str, object]],
    labels: Mapping[int, str],
    marks: Mapping[int, Mapping[str, str]],
    population: Mapping[str, int],
    cost_usd: float,
) -> str:
    """The results file: counts only."""
    final = final_labels(labels, marks)
    agree = checked = 0
    confusion: Counter[tuple[str, str]] = Counter()
    for n, fields in marks.items():
        if fields.get("label") not in ("right", "wrong"):
            continue
        checked += 1
        if fields["label"] == "right":
            agree += 1
        elif fields.get("correct label"):
            confusion[(labels.get(n, "?"), fields["correct label"])] += 1
    by_stratum: dict[str, list[str]] = {}
    for row in sample:
        n = int(str(row["n"]))
        if n in final:
            by_stratum.setdefault(str(row["stratum"]), []).append(final[n])
    share = weighted_word_share(by_stratum, population)
    mixed_rows = [
        (float(str(r["image_area_share"])), final[int(str(r["n"]))])
        for r in sample
        if str(r["stratum"]).startswith("text and image") and int(str(r["n"])) in final
    ]
    cut = mixed_cut(mixed_rows)
    low, high = wilson(agree, checked)
    lines = [
        "# the inventory: what image-bearing pages show (S2.6 spec §6) -- counts only",
        f"sample: {len(sample)} pages from the dev-400 page frame, seed {SEED}; labeller "
        f"{MODEL} at minimal reasoning, instruction {LABEL.version}; labelled "
        f"{len(labels)}; cost ${cost_usd:.4f}",
        "",
        "## labels by stratum (Andy's label where he checked the page)",
    ]
    for stratum, stratum_labels in sorted(by_stratum.items()):
        counts = Counter(stratum_labels)
        lines.append(
            f"  {stratum} (population {population.get(stratum, 0)}): "
            + ", ".join(f"{label} {counts[label]}" for label in PAGE_LABELS if counts[label])
        )
    lines += [
        "",
        "## Andy's check",
        f"  {agree} of {checked} labels right ({agree / checked if checked else 0:.1%} "
        f"[{low:.1%}, {high:.1%}], Wilson 95%)",
        *(f"  labelled {a}, Andy says {b}: {k}" for (a, b), k in sorted(confusion.items())),
        "",
        "## the mixed-page cut-off (decision W3)",
        f"  cut: text-and-image pages whose images cover under {cut:.0%} of the page are not "
        f"sent (from {len(mixed_rows)} sampled text-and-image pages; candidates "
        + ", ".join(f"{c:.0%}" for c in CUTS)
        + f"; at most 1 in {round(1 / MAX_WORDS_BELOW_CUT)} below the cut may hold words)",
        "",
        "## the stop rule (spec §6.4, decision W6)",
        f"  weighted over all image-bearing dev-400 pages: {stop_outcome(share)}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:  # noqa: PLR0911 -- one return per subcommand
    """Run one subcommand."""
    parser = argparse.ArgumentParser(prog="page_inventory")
    parser.add_argument("command", choices=("sample", "probe", "label", "check", "score"))
    parser.add_argument("--marks", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    settings = Settings()
    documents = CachedDocuments(DocketClient(settings.docket_dir, transport=_offline()))
    folder = settings.data_dir / FOLDER
    if args.command == "sample":
        print(cmd_sample(settings, documents))
        return 0
    if args.command == "check":
        print(cmd_check(settings))
        return 0
    sample = _read_jsonl(folder / "sample.jsonl")
    if args.command == "probe":
        with ExitStack() as stack:
            client = openrouter_clients(settings)(stack)()
            record = read_page(
                _jobs(sample[:1], documents)[0], client, LABEL, now=lambda: datetime.now(UTC)
            )
        print(f"probe: {record.status}, kind {record.page_kind}, error {record.error}, "
              f"{record.prompt_tokens}+{record.completion_tokens} tokens, ${record.cost_usd:.5f}")
        return 0 if record.status == "transcribed" else 1
    if args.command == "label":
        done = run_preparation(
            kind="inventory", jobs=_jobs(sample, documents), instruction=LABEL,
            settings=settings, commit=commit_state(), workers=args.workers,
            expected_cost_per_page_usd=EXPECTED_COST_PER_PAGE_USD,
        )
        failed = sum(1 for r in done if r.status == "failed")
        print(f"labelled {len(done)} pages, {failed} failed, ${sum(r.cost_usd for r in done):.4f}")
        return 0
    cache = TranscriptionCache(settings.transcription_dir)
    records = {int(str(r["n"])): cache.get(_key(r)) for r in sample}
    labels = {n: rec.page_kind for n, rec in records.items() if rec and rec.page_kind}
    cost = sum(rec.cost_usd for rec in records.values() if rec)
    population = json.loads((folder / "population.json").read_text())
    marks = marking_page.read_marks(args.marks) if args.marks else {}
    text = score_text(sample, labels, marks, population, cost)
    # Private: the transcriber test (Task 13) draws its handwriting and photo pages from these.
    (folder / "labels.json").write_text(json.dumps(final_labels(labels, marks)))
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Let `ruff format` break the two long f-string lines in `cmd_check` and `main` (split each into two adjacent f-strings); ruff's line-length rule would otherwise flag them.

- [ ] **Step 7: Run the tests, then the whole check**

Run: the Step 3 command, then `make check`
Expected: PASS; green.

- [ ] **Step 8: The targets, and commit the code**

Append to `Makefile` (and `.PHONY`):

```make
s26-inventory-probe:
	uv run python -m scripts.page_inventory sample
	uv run python -m scripts.page_inventory probe
# S2.6 spec §6.2: draws the 330-page sample (free), then labels ONE page (under a cent).

s26-inventory:
	uv run python -m scripts.page_inventory label
	uv run python -m scripts.page_inventory check
# S2.6 spec §6.2: labels the 330 (about $0.20), then writes Andy's 60-page check.
```

```bash
git add src/ntsb_probable_cause/docket/documents.py src/ntsb_probable_cause/scoring/preparation.py scripts/page_inventory.py Makefile tests/ docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: the inventory -- sample, labeller, Andy's check page, cut-off and stop rule (spec §6)"
```

- [ ] **Step 9: STOP — Andy runs the one-page probe** (under a cent; about a minute, most of it drawing 330 pages)

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
export OPENROUTER_API_KEY="$(pass show api/openrouter)"
make s26-inventory-probe
```

Expected: `330 pages drawn to …` and `probe: transcribed, kind <one of the eight>, error None, …`. The tree is unchanged afterwards (everything is under `data/`). If the probe fails, its error names the cause; record it in Deviations and stop (spec §17: a candidate that rejects our requests).

- [ ] **Step 10: STOP — Andy runs the labelling** (about $0.20, estimate; about 5 minutes)

Same two exports, then `make s26-inventory`. Expected: `labelled 330 pages, 0 failed, $0.1…` and the check page's path. The tree is unchanged afterwards. The month's spend now includes the job's spend rows (`uv run ntsb-eval report --latest …` lists open reservations; there should be none).

- [ ] **Step 11: STOP — Andy checks 60 labels** (about 20 minutes)

Andy opens `/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data/s26/inventory/check.html`, marks each label right or wrong (choosing the right kind when wrong), and downloads the CSV.

- [ ] **Step 12: Score, set the cut-off, commit**

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
uv run python -m scripts.page_inventory score --marks ~/Downloads/inventory-check-marks.csv --out docs/results/s26-inventory.txt
```

Copy the cut from the results file into `docket/transcribe.py`:

```python
# Decision W3 / 0079 item 3: a text-and-image page whose images cover less than this share of
# the page is not sent -- its images are logos. Chosen by the rule fixed in the S2.6 plan
# (Task 12), from docs/results/s26-inventory.txt.
MIXED_PAGE_MIN_IMAGE_SHARE = <the cut, e.g. 0.05>
```

```bash
git add docs/results/s26-inventory.txt src/ntsb_probable_cause/docket/transcribe.py docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: the inventory, labelled and checked; the mixed-page cut-off (spec §6)"
```

- [ ] **Step 13: STOP — report to Andy, and the stop point (spec §6.4)**

In plain words with a glossary: what the pages show, how often the labeller was right, the cut-off and what it means, and the stop rule's outcome. If the outcome is `stop`, the stage records it (spec §6.4): Tasks 13–16 are skipped, the marks, the renderer and the evidence-version axis ship, and the close-out says why.

---

### Task 13: The transcriber test (spec §7; decision 0080; paid, about $4–8 at standard prices; five stops)

**Starts only if** Task 12's stop rule said `go on`.

**Files:**
- Create: `scripts/transcriber_test.py`
- Create: `tests/test_transcriber_test.py`
- Create: `tests/fixtures/openrouter/transcription/<model>.json` (one recorded reply per candidate, of an **invented** page, so committing it commits no docket text)
- Create: `docs/decisions/<next free number>-the-transcriber-is-<model>.md` (the next free number at the time: spec §14); modify `docs/decisions/README.md`
- Modify: `src/ntsb_probable_cause/docket/render.py` (`RESOLUTION`, only if the rule picks 200)
- Modify: `src/ntsb_probable_cause/docket/transcribe.py` (+ `TRANSCRIBER`)
- Modify: `Makefile` (+ `s26-transcriber-keys`, `s26-transcriber-probe`, `s26-transcriber-run`, `s26-transcriber-resolution`)
- Output: `docs/results/s26-transcriber-test.txt` (committed); `data/s26/transcriber-test/` (private: `keys.jsonl`, `pages/`, `handwriting.html`, `handwriting.json`, `photos.html`)

**Interfaces:**
- Consumes: Task 11 (`TRANSCRIBE`, `LABEL`, `PageJob`, `TranscriptionKey`, `TranscriptionCache`, `request_for`, `settings_for`, `parse_reply`), Task 12 (`CachedDocuments`, `run_preparation`, `data/s26/inventory/labels.json` and `sample.jsonl`, `MIXED_PAGE_MIN_IMAGE_SHARE`), Task 2 (`marking_page`).
- Produces: `docket.transcribe.TRANSCRIBER: str` (the chosen model id) — Task 14 reads it; `render.RESOLUTION` settled.
- Produces (pure, pinned by tests): `lines_of`, `line_hits`, `inventing_lines`, `typed_errors`, `draft_letter`, `agreed_lines`, `CandidateResult`, `choose`, `choose_resolution`, and the rule's constants.

**The answer keys (spec §7.3, and a fourth from decision W7), fixed now.** Seed `20260926`.
- *Typed:* 100 text-only pages (50 fatal, 50 non-fatal) whose text layer has between 300 and 3,000 characters — at least `classify.BORN_DIGITAL_MIN_CHARS_PER_PAGE`, and no more than one reply comfortably copies. Each is drawn to an image and transcribed; the text layer is the answer. A best case, stated.
- *Handwriting:* 25 pages. First, the inventory's pages whose final label is `handwriting`; topped up, if fewer, from image-only pages in documents whose title category is `pilot_form_6120`, in seeded order, labelled 25 at a time with the inventory's labeller until 25 are found or 200 have been tried.
- *No-word photographs:* 50 pages. The inventory's `photograph` pages, topped up the same way from image-only pages in documents whose category is `photos`.
- *Full-page scans with a machine-read text layer (decision W7, Andy, 2026-09-24):* 25 text-and-image pages, not in the inventory's sample and not from a photo-only document, whose images cover at least 70% of the page, in seeded order. Every candidate reads them with the mixed-page instruction (the page's own text layer given, only missing words asked for). Andy marks each model's added words: *all on the page and new*, *repeats the text layer*, or *some invented*. No answer key is typed: the check is for invented words, which the gate counts.

**The handwriting key, and how Andy's time is spent.** All four candidates transcribe every handwriting page. On Andy's page, each handwriting page shows its image, the four versions under the letters A–D (shuffled per page, so no model's name can sway him), the lines all four agree on — accepted — and a text box prefilled with the version that agrees most with the other three. Andy edits the box into the page's true text, one line per written line, writing `[illegible]` where he cannot read a word either. A seeded 1 in 10 of the agreed lines is flagged "check this line"; if one is wrong, he corrects it in the box and says so. Afterwards, each key line that matches one of the versions word for word is counted as *picked* and every other line as *typed* (spec §17).

**The measures (spec §7.4).** Line accuracy: key lines a model reproduced exactly, whitespace aside, each of its lines used once, pooled over all handwriting pages; `[illegible]` counts right when the key has `[illegible]` in the same place. Invented text on handwriting: a model line holding a word (two or more letters or digits) that appears nowhere in the page's key — a guess where `[illegible]` was due counts here — per 100 key lines. Invented text on photographs: a page where Andy marks any output word as not on the page. Invented text on full-page scans: a page where Andy marks a model's added words *some invented*; *repeats the text layer* is counted and published but not gated (it wastes the agent's reading, it does not mislead it). Typed errors: the characters of the longer of key and transcription left unmatched by an alignment (`difflib.SequenceMatcher`, no junk heuristic), per 100 key characters, whitespace collapsed.

**The rule, in code, before the test runs.** See `choose` below: out if more than 2 invented lines per 100 handwriting lines, more than 1 in 20 photo pages with invented words, or more than 1 in 20 full-page scans with invented added words; of the rest, the cheapest — by **measured cost per test page**, which counts each model's real token use rather than its list price — whose handwriting line accuracy is within 5 points of the best and whose typed errors are within 1 per 100 characters of the best. Then 150 or 200 dots per inch: 200 only if the chosen model's handwriting accuracy is more than 5 points higher at 200.

- [ ] **Step 1: Write the failing tests**

`tests/test_transcriber_test.py`:

```python
"""scripts/transcriber_test.py: the measures and the rule, fixed before the test runs (0080)."""

import json
from pathlib import Path

import pytest

from ntsb_probable_cause.docket.transcribe import TRANSCRIBE, parse_reply
from scripts import transcriber_test as tt


def _result(model: str, **overrides: float) -> tt.CandidateResult:
    values: dict[str, float] = {
        "cost_per_page": 0.001,
        "hw_lines": 375,
        "hw_right": 300,
        "hw_inventing": 3,
        "photo_pages": 50,
        "photo_invented": 1,
        "typed_chars": 100_000,
        "typed_errors": 500,
        "mixed_pages": 25,
        "mixed_invented": 0,
    }
    values.update(overrides)
    return tt.CandidateResult(model=model, **{k: v for k, v in values.items()})  # type: ignore[arg-type]


def test_lines_collapse_whitespace_and_drop_blanks() -> None:
    assert tt.lines_of("  Fuel   BOTH \n\n Mixture RICH") == ["Fuel BOTH", "Mixture RICH"]


def test_line_hits_use_each_line_once() -> None:
    assert tt.line_hits(["a b", "a b", "c"], ["a b", "c", "d"]) == 2


def test_illegible_is_right_where_the_key_has_it() -> None:
    key = tt.lines_of("Switched to [illegible] tank")
    assert tt.line_hits(key, tt.lines_of("Switched to [illegible] tank")) == 1
    assert tt.line_hits(key, tt.lines_of("Switched to left tank")) == 0


def test_a_guess_where_the_key_is_illegible_is_invented() -> None:
    key = "Switched to [illegible] tank\nno change"
    assert tt.inventing_lines(key, tt.lines_of("Switched to left tank\nno change")) == 1
    assert tt.inventing_lines(key, tt.lines_of("Switched to [illegible] tank")) == 0


def test_typed_errors_count_one_wrong_character() -> None:
    errors, chars = tt.typed_errors("left magneto replaced 12/03/17", "left magneto replaced 12/08/17")
    assert (errors, chars) == (1, 30)


def test_the_draft_is_the_version_that_agrees_most() -> None:
    versions = {"A": ["x", "y", "z"], "B": ["x", "y", "q"], "C": ["x", "p", "q"], "D": ["r"]}
    assert tt.draft_letter(versions) == "B"
    assert tt.agreed_lines({"A": ["x", "y"], "B": ["y", "x"]}, order=["x", "y"]) == ["x", "y"]


def test_the_gate_removes_an_inventing_model() -> None:
    results = [
        _result("cheap", cost_per_page=0.0005, hw_inventing=9),  # 2.4 per 100 lines
        _result("dear", cost_per_page=0.003),
    ]
    chosen, notes = tt.choose(results)
    assert chosen == "dear"
    assert any("cheap: out" in note for note in notes)


def test_the_photo_gate_is_one_in_twenty() -> None:
    chosen, _ = tt.choose([_result("a", photo_invented=3), _result("b", photo_invented=2)])
    assert chosen == "b"


def test_the_full_page_scan_gate_is_one_in_twenty() -> None:
    """Decision W7: 2 of 25 scans with invented added words is over 1 in 20; 1 is not."""
    chosen, notes = tt.choose(
        [_result("a", cost_per_page=0.0005, mixed_invented=2), _result("b", mixed_invented=1)]
    )
    assert chosen == "b"
    assert any("a: out" in note and "full-page scans" in note for note in notes)


def test_the_cheapest_within_the_margins_wins() -> None:
    results = [
        _result("best", cost_per_page=0.004, hw_right=320),
        _result("close", cost_per_page=0.001, hw_right=303),  # 80.8% against 85.3%: within 5
        _result("far", cost_per_page=0.0005, hw_right=290),  # 77.3%: not within 5
    ]
    assert tt.choose(results)[0] == "close"


def test_typed_errors_must_be_within_one_per_hundred() -> None:
    results = [
        _result("best", cost_per_page=0.004, typed_errors=300),
        _result("sloppy", cost_per_page=0.001, typed_errors=1_400),
    ]
    assert tt.choose(results)[0] == "best"


def test_no_model_passing_means_no_transcriber() -> None:
    assert tt.choose([_result("a", hw_inventing=20)])[0] is None


def test_resolution_200_only_for_more_than_five_points() -> None:
    assert tt.choose_resolution(0.80, 0.85) == 150
    assert tt.choose_resolution(0.80, 0.851) == 200


@pytest.mark.parametrize("path", sorted(Path("tests/fixtures/openrouter/transcription").glob("*.json")))
def test_every_recorded_candidate_reply_parses(path: Path) -> None:
    """Each candidate's real reply to the invented probe page (Step 7) parses as a reading."""
    reply = json.loads(path.read_text())
    text, kind = parse_reply(reply["content"], TRANSCRIBE)
    assert "Engine sputtered at 800 ft." in text
    assert kind in {"typed text", "mixed", "filled form"}
```

(The last test collects nothing until Step 7 records the replies; it then pins each candidate's real reply shape, as S1's probe fixtures pin the answering replies.)

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_transcriber_test.py -v`
Expected: FAIL — `ImportError: cannot import name 'transcriber_test' from 'scripts'`.

- [ ] **Step 3: Implement the measures and the rule** (top of `scripts/transcriber_test.py`)

```python
"""The transcriber test: three answer keys, four candidates, a rule fixed in advance (0080).

Status
    One-shot (S2.6, Task 13). Subcommands, in order:
      keys        -- draw the typed, handwriting and photograph pages (paid: cents, for top-ups)
      probe       -- one invented page per candidate; records each reply as a test fixture
      run         -- all four candidates on every key page at 150 dpi (paid, ~$4-8)
      handwriting -- write Andy's handwriting-key page
      photos      -- write Andy's invented-words page
      resolution  -- the chosen model at 200 dpi on the handwriting and typed keys (paid)
      score       -- apply the rule; write docs/results/s26-transcriber-test.txt
      estimate    -- the stage's re-estimated cost (decision 0083 item 2's pause point)
    Keys, page images, Andy's sheets and every transcription live under data/ and are never
    committed; the results file holds counts only. The recorded probe replies are of an
    invented page and hold no docket text.
"""

import argparse
import html
import json
import operator
import random
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from functools import reduce
from pathlib import Path

# The rule (spec §7.4, decision 0080), fixed before the test runs.
GATE_INVENTED_LINES_PER_100 = 2.0
GATE_INVENTED_PHOTO_SHARE = 1 / 20
GATE_INVENTED_MIXED_SHARE = 1 / 20  # decision W7: the photographs' bar
HANDWRITING_MARGIN = 0.05
TYPED_MARGIN_PER_100 = 1.0
RESOLUTION_MARGIN = 0.05
SPOT_CHECK_EVERY = 10

_WORD = re.compile(r"[A-Za-z0-9]{2,}")
_ILLEGIBLE_WORD = "illegible"


def lines_of(text: str) -> list[str]:
    """Non-empty lines with whitespace collapsed: the unit of the handwriting key."""
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def line_hits(key: Sequence[str], version: Sequence[str]) -> int:
    """Key lines the version holds exactly, each version line used at most once."""
    return sum((Counter(key) & Counter(version)).values())


def inventing_lines(key_text: str, version: Sequence[str]) -> int:
    """Version lines holding a word found nowhere in the page's key (the invented-text gate).

    A word where the key has ``[illegible]`` counts: that is the guess 0079 forbids.
    """
    known = {word.lower() for word in _WORD.findall(key_text)}
    return sum(
        1
        for line in version
        if any(
            word.lower() not in known and word.lower() != _ILLEGIBLE_WORD
            for word in _WORD.findall(line)
        )
    )


def typed_errors(key: str, version: str) -> tuple[int, int]:
    """(character errors, key characters), whitespace collapsed on both sides."""
    a, b = " ".join(key.split()), " ".join(version.split())
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return max(len(a), len(b)) - matched, len(a)


def draft_letter(versions: Mapping[str, Sequence[str]]) -> str:
    """The version whose lines the other three share most: the draft Andy edits."""
    return max(
        sorted(versions),
        key=lambda v: sum(line_hits(versions[v], versions[o]) for o in versions if o != v),
    )


def agreed_lines(versions: Mapping[str, Sequence[str]], *, order: Sequence[str]) -> list[str]:
    """Lines every version holds, in the draft's order."""
    common = reduce(operator.and_, (Counter(v) for v in versions.values()))
    agreed: list[str] = []
    for line in order:
        if common[line] > 0:
            agreed.append(line)
            common[line] -= 1
    return agreed


@dataclass(frozen=True)
class CandidateResult:
    """One candidate's counts over the three keys, and its measured cost per test page."""

    model: str
    cost_per_page: float
    hw_lines: int
    hw_right: int
    hw_inventing: int
    photo_pages: int
    photo_invented: int
    typed_chars: int
    typed_errors: int
    mixed_pages: int = 0
    mixed_invented: int = 0

    @property
    def hw_accuracy(self) -> float:
        """Share of handwriting key lines reproduced exactly."""
        return self.hw_right / self.hw_lines if self.hw_lines else 0.0

    @property
    def invented_per_100_lines(self) -> float:
        """Inventing lines per 100 handwriting key lines."""
        return 100 * self.hw_inventing / self.hw_lines if self.hw_lines else 0.0

    @property
    def photo_invented_share(self) -> float:
        """Share of no-word photograph pages with an invented word."""
        return self.photo_invented / self.photo_pages if self.photo_pages else 0.0

    @property
    def mixed_invented_share(self) -> float:
        """Share of full-page scans whose added words hold an invented word (decision W7)."""
        return self.mixed_invented / self.mixed_pages if self.mixed_pages else 0.0

    @property
    def typed_errors_per_100(self) -> float:
        """Character errors per 100 characters of typed key."""
        return 100 * self.typed_errors / self.typed_chars if self.typed_chars else 0.0


def choose(results: Sequence[CandidateResult]) -> tuple[str | None, list[str]]:
    """Spec §7.4: the gate, then the cheapest within both margins of the best. Notes say why."""
    notes: list[str] = []
    passed: list[CandidateResult] = []
    for r in results:
        if r.invented_per_100_lines > GATE_INVENTED_LINES_PER_100:
            notes.append(
                f"{r.model}: out -- {r.invented_per_100_lines:.1f} inventing lines per 100 "
                f"handwriting lines (gate {GATE_INVENTED_LINES_PER_100:.0f})"
            )
        elif r.photo_invented_share > GATE_INVENTED_PHOTO_SHARE:
            notes.append(
                f"{r.model}: out -- invented words on {r.photo_invented} of {r.photo_pages} "
                "no-word photograph pages (gate 1 in 20)"
            )
        elif r.mixed_invented_share > GATE_INVENTED_MIXED_SHARE:
            notes.append(
                f"{r.model}: out -- invented added words on {r.mixed_invented} of "
                f"{r.mixed_pages} full-page scans (gate 1 in 20)"
            )
        else:
            passed.append(r)
    if not passed:
        notes.append("no candidate passed the gate: transcription stops (spec §7.4 item 3)")
        return None, notes
    best_hw = max(r.hw_accuracy for r in passed)
    best_typed = min(r.typed_errors_per_100 for r in passed)
    eligible = [
        r
        for r in passed
        if r.hw_accuracy >= best_hw - HANDWRITING_MARGIN
        and r.typed_errors_per_100 <= best_typed + TYPED_MARGIN_PER_100
    ]
    for r in passed:
        if r not in eligible:
            notes.append(f"{r.model}: passed the gate, outside a margin of the best")
    chosen = min(eligible, key=lambda r: r.cost_per_page)
    notes.append(f"{chosen.model}: chosen -- the cheapest within both margins")
    return chosen.model, notes


def choose_resolution(accuracy_150: float, accuracy_200: float) -> int:
    """Spec §7.5: 200 dpi only for more than 5 points of handwriting accuracy."""
    return 200 if accuracy_200 - accuracy_150 > RESOLUTION_MARGIN else 150
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run pytest tests/test_transcriber_test.py -v`
Expected: PASS (the fixture-parsing test collects no case yet).

- [ ] **Step 5: Implement the subcommands** (the rest of `scripts/transcriber_test.py`)

Extend the module's import block with:

```python
import hashlib
import io
import statistics

import httpx
from PIL import Image, ImageDraw, ImageFont

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.classify import BORN_DIGITAL_MIN_CHARS_PER_PAGE, document_category
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.documents import CachedDocuments
from ntsb_probable_cause.docket.pages import page_text
from ntsb_probable_cause.docket.render import RESOLUTION, render_pages
from ntsb_probable_cause.docket.transcribe import (
    LABEL,
    MIXED_PAGE_MIN_IMAGE_SHARE,
    TRANSCRIBE,
    PageJob,
    TranscriptionCache,
    TranscriptionKey,
    parse_reply,
    request_for,
    settings_for,
)
from ntsb_probable_cause.errors import ModelError, SchemaError
from ntsb_probable_cause.gitinfo import commit_state
from ntsb_probable_cause.model.client import cost_usd
from ntsb_probable_cause.scoring.budget import SPEND_FILE, SpendRecord, write_spend
from ntsb_probable_cause.scoring.metrics import wilson
from ntsb_probable_cause.scoring.preparation import openrouter_clients, run_preparation
from ntsb_probable_cause.scoring.records import RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings
from scripts import marking_page
from scripts import page_inventory as inventory
from scripts.marking_page import Card, Choice
```

Then, below the rule:

```python
CANDIDATES = (
    "google/gemini-3.1-flash-lite",
    "google/gemini-3.6-flash",
    "qwen/qwen3.5-122b-a10b",
    "openai/gpt-6-luna",
)
LETTERS = ("A", "B", "C", "D")
# Conservative per-page reservations; the spend rows record what was really spent.
EXPECTED_COST_PER_PAGE_USD = {
    "google/gemini-3.1-flash-lite": 0.003,
    "google/gemini-3.6-flash": 0.008,
    "qwen/qwen3.5-122b-a10b": 0.006,
    "openai/gpt-6-luna": 0.002,
}
LABELLER = "google/gemini-3.1-flash-lite"
AGENT_MODEL = "openai/gpt-6-luna"
SEED = 20260926
TYPED_PAGES, HANDWRITING_PAGES, PHOTO_PAGES, MIXED_PAGES = 100, 25, 50, 25
FULL_SCAN_SHARE = 0.70  # decision W7: a mixed page this much image is a scan with a text layer
TYPED_MAX_CHARS = 3000
TOP_UP_BATCH, TOP_UP_LIMIT = 25, 200
MONTH_BUDGET_USD = 40.0  # decision 0083
PICTURES = frozenset({"photograph", "diagram or chart", "mixed"})
FOLDER = Path("s26") / "transcriber-test"
PROBE_LINES = (
    "PILOT STATEMENT - INVENTED TEST PAGE",
    "Engine sputtered at 800 ft.",
    "Switched to right tank, no change.",
    "Fuel selector BOTH, mixture RICH.",
)
FIXTURES = Path("tests/fixtures/openrouter/transcription")


def _offline() -> httpx.BaseTransport:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline: the transcriber test reads the docket cache only")

    return httpx.MockTransport(refuse)


def _read(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _int(row: Mapping[str, object], name: str) -> int:
    return int(str(row[name]))


def _place(row: Mapping[str, object]) -> tuple[str, int, int]:
    return str(row["case_id"]), _int(row, "document"), _int(row, "page")


def _key(row: Mapping[str, object], model: str, *, instruction: str, dpi: int) -> TranscriptionKey:
    return TranscriptionKey(
        document_sha256=str(row["document_sha256"]),
        page=_int(row, "page"),
        model=model,
        instruction=instruction,
        dpi=dpi,
    )


def _hashed(rows: Sequence[Mapping[str, object]], docs: CachedDocuments) -> list[dict[str, object]]:
    hashed: list[dict[str, object]] = []
    for row in rows:
        data = docs.document(_int(row, "mkey"), _int(row, "document"))
        hashed.append({**row, "document_sha256": hashlib.sha256(data).hexdigest()})
    return hashed


def _category(row: Mapping[str, object], docs: CachedDocuments) -> str:
    for entry in docs.listing(_int(row, "mkey")).entries:
        if entry.index == _int(row, "document"):
            return document_category(entry.title)
    return "other"


def _text(cache: TranscriptionCache, row: Mapping[str, object], model: str, *, dpi: int) -> str:
    record = cache.get(_key(row, model, instruction=TRANSCRIBE.version, dpi=dpi))
    return record.text if record is not None and record.status == "transcribed" else ""


def _top_up(
    have: list[dict[str, object]],
    pool: Sequence[Mapping[str, object]],
    want: int,
    label: str,
    docs: CachedDocuments,
    settings: Settings,
) -> list[dict[str, object]]:
    """Label pool pages 25 at a time with the inventory's labeller until ``want`` are found."""
    cache = TranscriptionCache(settings.transcription_dir)
    tried = 0
    while len(have) < want and tried < min(len(pool), TOP_UP_LIMIT):
        chunk = _hashed(pool[tried : tried + TOP_UP_BATCH], docs)
        tried += len(chunk)
        jobs = [
            PageJob(
                _key(row, LABELLER, instruction=LABEL.version, dpi=RESOLUTION),
                docs.loader(_int(row, "mkey"), _int(row, "document")),
                mixed=False,
            )
            for row in chunk
        ]
        run_preparation(
            kind="transcriber-test",
            jobs=jobs,
            instruction=LABEL,
            settings=settings,
            commit=commit_state(),
            expected_cost_per_page_usd=EXPECTED_COST_PER_PAGE_USD[LABELLER],
            workers=4,
        )
        for row in chunk:
            record = cache.get(_key(row, LABELLER, instruction=LABEL.version, dpi=RESOLUTION))
            if record is not None and record.page_kind == label:
                have.append(row)
    return have[:want]


def _typed_rows(frame: Sequence[Mapping[str, object]], rng: random.Random) -> list[dict[str, object]]:
    typed: list[dict[str, object]] = []
    for fatal in (True, False):
        pool = sorted(
            (
                dict(row)
                for row in frame
                if row["kind"] == "text only"
                and row["fatal"] == fatal
                and BORN_DIGITAL_MIN_CHARS_PER_PAGE <= _int(row, "chars") <= TYPED_MAX_CHARS
            ),
            key=_place,
        )
        typed.extend(rng.sample(pool, min(TYPED_PAGES // 2, len(pool))))
    return typed


def _full_scans(
    frame: Sequence[Mapping[str, object]],
    sampled: set[tuple[str, int, int]],
    docs: CachedDocuments,
    rng: random.Random,
) -> list[dict[str, object]]:
    """Decision W7: text-and-image pages at least 70% image, in seeded order, until 25."""
    pool = sorted(
        (
            dict(r)
            for r in frame
            if r["kind"] == "text and image"
            and not r.get("photo_only")
            and _place(r) not in sampled
        ),
        key=_place,
    )
    rng.shuffle(pool)
    chosen: list[dict[str, object]] = []
    for row in pool:
        if len(chosen) >= MIXED_PAGES:
            break
        data = docs.document(_int(row, "mkey"), _int(row, "document"))
        (page,) = render_pages(data, [_int(row, "page")])
        if page.image_area_share >= FULL_SCAN_SHARE:
            chosen.append(row)
    return _hashed(chosen, docs)


def cmd_keys(settings: Settings, docs: CachedDocuments) -> str:
    """Draw the three keys (spec §7.3), topping up with the labeller where the inventory is short."""
    s26 = settings.data_dir / "s26"
    frame = _read(s26 / "pages-dev-400.jsonl")
    sample = {_int(row, "n"): row for row in _read(s26 / "inventory" / "sample.jsonl")}
    labels_file = (s26 / "inventory" / "labels.json").read_text()
    labels = {int(n): label for n, label in json.loads(labels_file).items()}
    rng = random.Random(SEED)  # noqa: S311 -- sampling, not security
    typed = _hashed(_typed_rows(frame, rng), docs)
    sampled = {_place(row) for row in sample.values()}
    image_only = sorted(
        (dict(r) for r in frame if r["kind"] == "image only" and _place(r) not in sampled),
        key=_place,
    )
    rng.shuffle(image_only)

    def from_inventory(label: str) -> list[dict[str, object]]:
        return [dict(sample[n]) for n, lab in sorted(labels.items()) if lab == label]

    forms = [row for row in image_only if _category(row, docs) == "pilot_form_6120"]
    photo_docs = [row for row in image_only if _category(row, docs) == "photos"]
    handwriting = _top_up(
        from_inventory("handwriting"), forms, HANDWRITING_PAGES, "handwriting", docs, settings
    )
    photos = _top_up(
        from_inventory("photograph"), photo_docs, PHOTO_PAGES, "photograph", docs, settings
    )
    scans = _full_scans(frame, sampled, docs, rng)
    groups = (("typed", typed), ("handwriting", handwriting), ("photo", photos), ("mixed", scans))
    rows = [
        {**row, "set": name, "k": k}
        for name, group in groups
        for k, row in enumerate(group, start=1)
    ]
    folder = settings.data_dir / FOLDER
    (folder / "pages").mkdir(parents=True, exist_ok=True)
    for row in rows:
        data = docs.document(_int(row, "mkey"), _int(row, "document"))
        (page,) = render_pages(data, [_int(row, "page")])
        (folder / "pages" / f"{row['set']}-{row['k']}.jpg").write_bytes(page.data)
    (folder / "keys.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    counts = Counter(str(row["set"]) for row in rows)
    return (
        f"keys: typed {counts['typed']}, handwriting {counts['handwriting']}, "
        f"photo {counts['photo']}, full-page scans {counts['mixed']}"
    )


def probe_page() -> bytes:
    """An invented, clinical page drawn as an image-only PDF: safe to transcribe and commit."""
    image = Image.new("L", (1275, 1650), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=40)
    for i, line in enumerate(PROBE_LINES):
        draw.text((100, 150 + 90 * i), line, fill=0, font=font)
    out = io.BytesIO()
    image.save(out, format="PDF", resolution=150)
    return out.getvalue()


def cmd_probe(settings: Settings) -> str:
    """One invented page per candidate; each reply is recorded as a test fixture."""
    (rendered,) = render_pages(probe_page())
    payload, system = request_for(rendered, TRANSCRIBE, text_layer=None)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    sha, dirty = commit_state()
    started = datetime.now(UTC)
    lines: list[str] = []
    total = 0.0
    with ExitStack() as stack:
        make = openrouter_clients(settings)(stack)
        for model in CANDIDATES:
            model_settings = settings_for(model, TRANSCRIBE)
            try:
                reply = make().complete(payload, model_settings, system=system)
            except ModelError as error:
                lines.append(f"{model}: FAILED -- {type(error).__name__}: {str(error)[:200]}")
                continue
            cost, _ = cost_usd(reply, model_settings)
            total += cost
            name = model.replace("/", "__") + ".json"
            (FIXTURES / name).write_text(reply.model_dump_json(indent=1) + "\n")
            try:
                text, kind = parse_reply(reply.content, TRANSCRIBE)
            except SchemaError as error:
                lines.append(f"{model}: the reply did not parse -- {error}")
                continue
            copied = sum(1 for line in PROBE_LINES if line in text)
            lines.append(
                f"{model}: ok, kind {kind}, {copied} of {len(PROBE_LINES)} lines copied, "
                f"{reply.usage.prompt_tokens}+{reply.usage.completion_tokens} tokens, "
                f"${cost:.5f}"
            )
    write_spend(
        settings.runs_dir,
        SpendRecord(
            job_id=f"{started:%Y%m%dT%H%M%S}-{sha}-transcriber-probe",
            kind="transcriber-test",
            model=",".join(CANDIDATES),
            started=started,
            calls=len(CANDIDATES),
            cost_usd=total,
            commit_sha=sha,
            dirty=dirty,
        ),
    )
    return "\n".join(lines)


def cmd_run(settings: Settings, docs: CachedDocuments, *, models: Sequence[str], dpi: int) -> str:
    """Each model reads every key page it is asked to, at one resolution."""
    keys = _read(settings.data_dir / FOLDER / "keys.jsonl")
    if dpi != RESOLUTION:  # the resolution comparison reads only the handwriting and typed keys
        keys = [row for row in keys if row["set"] in ("handwriting", "typed")]
    out: list[str] = []
    for model in models:
        done = run_preparation(
            kind="transcriber-test",
            jobs=[
                PageJob(
                    _key(row, model, instruction=TRANSCRIBE.version, dpi=dpi),
                    docs.loader(_int(row, "mkey"), _int(row, "document")),
                    mixed=row["set"] == "mixed",
                )
                for row in keys
            ],
            instruction=TRANSCRIBE,
            settings=settings,
            commit=commit_state(),
            expected_cost_per_page_usd=EXPECTED_COST_PER_PAGE_USD[model],
            workers=4,
        )
        failed = sum(1 for r in done if r.status == "failed")
        out.append(
            f"{model} at {dpi} dpi: {len(done)} pages read, {failed} failed, "
            f"${sum(r.cost_usd for r in done):.4f}"
        )
    return "\n".join(out)


def cmd_handwriting(settings: Settings) -> str:
    """Andy's key page: image, four lettered versions, agreed lines, spot checks, a draft."""
    folder = settings.data_dir / FOLDER
    rows = [r for r in _read(folder / "keys.jsonl") if r["set"] == "handwriting"]
    cache = TranscriptionCache(settings.transcription_dir)
    pages: dict[int, dict[str, object]] = {}
    for row in rows:
        k = _int(row, "k")
        order = random.Random(SEED + k).sample(CANDIDATES, len(CANDIDATES))  # noqa: S311
        letters = dict(zip(LETTERS, order, strict=True))
        versions = {
            letter: lines_of(_text(cache, row, model, dpi=RESOLUTION))
            for letter, model in letters.items()
        }
        draft = draft_letter(versions)
        pages[k] = {
            "letters": letters,
            "versions": versions,
            "draft": draft,
            "agreed": agreed_lines(versions, order=versions[draft]),
        }
    pooled = [(k, i) for k, page in pages.items() for i in range(len(page["agreed"]))]  # type: ignore[arg-type]
    spot_rng = random.Random(SEED + 1)  # noqa: S311 -- sampling, not security
    spot = set(spot_rng.sample(pooled, len(pooled) // SPOT_CHECK_EVERY))
    cards: list[Card] = []
    for k, page in sorted(pages.items()):
        agreed = page["agreed"]
        versions = page["versions"]
        assert isinstance(agreed, list) and isinstance(versions, dict)
        page["spot"] = [line for i, line in enumerate(agreed) if (k, i) in spot]
        blocks = "".join(
            f"<h4>{letter}</h4><pre>{html.escape(chr(10).join(lines))}</pre>"
            for letter, lines in sorted(versions.items())
        )
        agreed_html = "".join(
            f"<li>{html.escape(line)}{' <mark>check this line</mark>' if (k, i) in spot else ''}</li>"
            for i, line in enumerate(agreed)
        )
        cards.append(
            Card(
                row=k,
                body_html=(
                    f'<p class="meta">Handwriting page {k}</p>'
                    f'<img src="pages/handwriting-{k}.jpg" alt="page {k}">{blocks}'
                    f"<p>All four agree on (accepted):</p><ul>{agreed_html}</ul>"
                ),
                choices=(
                    Choice(
                        "spot check",
                        ("all correct", "some wrong, fixed in the key"),
                        required=bool(page["spot"]),
                    ),
                ),
                text_fields=(("key", "\n".join(versions[str(page["draft"])])),),
            )
        )
    (folder / "handwriting.json").write_text(json.dumps(pages))
    intro = (
        "<p>For each page: make the text box the page's true text, one line per written line. "
        "Write [illegible] for a word you cannot read either. The four versions are shown under "
        "letters, shuffled per page. Lines marked <mark>check this line</mark> are agreed by all "
        "four: check them against the image, fix any that are wrong in the box, and answer the "
        "spot check.</p>"
    )
    (folder / "handwriting.html").write_text(
        marking_page.render(
            title="Handwriting answer key (S2.6 spec §7.3)",
            intro_html=intro,
            cards=cards,
            storage_key="s26-handwriting-key",
            csv_name="handwriting-key.csv",
        )
    )
    return f"page at {folder / 'handwriting.html'}"


def cmd_photos(settings: Settings) -> str:
    """Andy's page: every word any candidate wrote for a no-word photograph."""
    folder = settings.data_dir / FOLDER
    rows = [r for r in _read(folder / "keys.jsonl") if r["set"] == "photo"]
    cache = TranscriptionCache(settings.transcription_dir)
    sheet: dict[int, dict[str, object]] = {}
    cards: list[Card] = []
    for row in rows:
        k = _int(row, "k")
        order = random.Random(SEED + 100 + k).sample(CANDIDATES, len(CANDIDATES))  # noqa: S311
        for i, model in enumerate(order, start=1):
            text = _text(cache, row, model, dpi=RESOLUTION)
            if not re.search(r"[A-Za-z0-9]{2,}", text):
                continue
            number = 10 * k + i
            sheet[number] = {"k": k, "model": model}
            cards.append(
                Card(
                    row=number,
                    body_html=(
                        f'<p class="meta">Photograph {k}, version {LETTERS[i - 1]}</p>'
                        f'<img src="pages/photo-{k}.jpg" alt="photograph {k}">'
                        f"<pre>{html.escape(text)}</pre>"
                    ),
                    choices=(Choice("words", ("all on the page", "some invented")),),
                )
            )
    (folder / "photos.json").write_text(json.dumps(sheet))
    intro = (
        "<p>Each card is a photograph and the words one transcriber wrote for it. Most will be "
        "real (a registration, a placard). Mark <b>some invented</b> if any word is not on the "
        "page.</p>"
    )
    (folder / "photos.html").write_text(
        marking_page.render(
            title="Invented words on photographs (S2.6 spec §7.3)",
            intro_html=intro,
            cards=cards,
            storage_key="s26-photo-words",
            csv_name="photo-words.csv",
        )
    )
    return f"{len(cards)} outputs with words; page at {folder / 'photos.html'}"


def cmd_mixed(settings: Settings, docs: CachedDocuments) -> str:
    """Andy's page (decision W7): the words each candidate added to a full-page scan."""
    folder = settings.data_dir / FOLDER
    rows = [r for r in _read(folder / "keys.jsonl") if r["set"] == "mixed"]
    cache = TranscriptionCache(settings.transcription_dir)
    sheet: dict[int, dict[str, object]] = {}
    cards: list[Card] = []
    for row in rows:
        k = _int(row, "k")
        data = docs.document(_int(row, "mkey"), _int(row, "document"))
        layer = page_text(data, _int(row, "page"))
        order = random.Random(SEED + 200 + k).sample(CANDIDATES, len(CANDIDATES))  # noqa: S311
        for i, model in enumerate(order, start=1):
            text = _text(cache, row, model, dpi=RESOLUTION)
            if not re.search(r"[A-Za-z0-9]{2,}", text):
                continue
            number = 10 * k + i
            sheet[number] = {"k": k, "model": model}
            cards.append(
                Card(
                    row=number,
                    body_html=(
                        f'<p class="meta">Full-page scan {k}, version {LETTERS[i - 1]}</p>'
                        f'<img src="pages/mixed-{k}.jpg" alt="page {k}">'
                        f"<details><summary>the page's text layer</summary>"
                        f"<pre>{html.escape(layer)}</pre></details>"
                        f"<p>Words this version added:</p><pre>{html.escape(text)}</pre>"
                    ),
                    choices=(
                        Choice(
                            "added words",
                            ("all on the page and new", "repeats the text layer", "some invented"),
                        ),
                    ),
                )
            )
    (folder / "mixed.json").write_text(json.dumps(sheet))
    intro = (
        "<p>Each card is a scanned page that already has a machine-read text layer, and the words "
        "one transcriber added to it. Mark <b>some invented</b> if any added word is not on the "
        "page; <b>repeats the text layer</b> if the added words are already in the text layer "
        "(open it under the image); otherwise <b>all on the page and new</b>.</p>"
    )
    (folder / "mixed.html").write_text(
        marking_page.render(
            title="Words added to full-page scans (S2.6, decision W7)",
            intro_html=intro,
            cards=cards,
            storage_key="s26-mixed-words",
            csv_name="mixed-words.csv",
        )
    )
    return f"{len(cards)} outputs with added words; page at {folder / 'mixed.html'}"


def _result(
    model: str,
    keys: Sequence[Mapping[str, object]],
    key_texts: Mapping[int, str],
    photo_invented: int,
    typed_answers: Mapping[int, str],
    cache: TranscriptionCache,
    *,
    dpi: int,
    mixed_invented: int = 0,
) -> CandidateResult:
    hw_lines = hw_right = hw_inventing = 0
    for row in (r for r in keys if r["set"] == "handwriting"):
        key_text = key_texts[_int(row, "k")]
        version = lines_of(_text(cache, row, model, dpi=dpi))
        hw_lines += len(lines_of(key_text))
        hw_right += line_hits(lines_of(key_text), version)
        hw_inventing += inventing_lines(key_text, version)
    typed_chars = typed_errs = 0
    for row in (r for r in keys if r["set"] == "typed"):
        errors, chars = typed_errors(typed_answers[_int(row, "k")], _text(cache, row, model, dpi=dpi))
        typed_errs += errors
        typed_chars += chars
    readings = [
        cache.get(_key(r, model, instruction=TRANSCRIBE.version, dpi=dpi)) for r in keys
    ]
    costs = [r.cost_usd for r in readings if r is not None]
    return CandidateResult(
        model=model,
        cost_per_page=sum(costs) / len(costs) if costs else 0.0,
        hw_lines=hw_lines,
        hw_right=hw_right,
        hw_inventing=hw_inventing,
        photo_pages=sum(1 for r in keys if r["set"] == "photo"),
        photo_invented=photo_invented,
        typed_chars=typed_chars,
        typed_errors=typed_errs,
        mixed_pages=sum(1 for r in keys if r["set"] == "mixed"),
        mixed_invented=mixed_invented,
    )


def cmd_score(
    settings: Settings,
    docs: CachedDocuments,
    handwriting_csv: Path,
    photos_csv: Path,
    mixed_csv: Path,
) -> str:
    """Apply the rule to every candidate; add the resolution comparison once it has run."""
    folder = settings.data_dir / FOLDER
    keys = _read(folder / "keys.jsonl")
    cache = TranscriptionCache(settings.transcription_dir)
    pages = json.loads((folder / "handwriting.json").read_text())
    photo_sheet = json.loads((folder / "photos.json").read_text())
    hw_marks = marking_page.read_marks(handwriting_csv)
    photo_marks = marking_page.read_marks(photos_csv)
    unmarked = [n for n in photo_sheet if photo_marks.get(int(n), {}).get("words") == ""]
    if unmarked or len(photo_marks) < len(photo_sheet):
        raise SystemExit("some photograph outputs are unmarked")
    mixed_sheet = json.loads((folder / "mixed.json").read_text())
    mixed_marks = marking_page.read_marks(mixed_csv)
    if any(mixed_marks.get(int(n), {}).get("added words", "") == "" for n in mixed_sheet):
        raise SystemExit("some full-page scan outputs are unmarked")
    mixed_by_mark = Counter(
        (str(mixed_sheet[str(n)]["model"]), fields["added words"])
        for n, fields in mixed_marks.items()
        if str(n) in mixed_sheet
    )
    key_texts = {k: fields["key"] for k, fields in hw_marks.items()}
    typed_answers = {
        _int(r, "k"): page_text(docs.document(_int(r, "mkey"), _int(r, "document")), _int(r, "page"))
        for r in keys
        if r["set"] == "typed"
    }
    invented = Counter(
        str(photo_sheet[str(n)]["model"])
        for n, fields in photo_marks.items()
        if fields.get("words") == "some invented"
    )
    results = [
        _result(
            m,
            keys,
            key_texts,
            invented[m],
            typed_answers,
            cache,
            dpi=RESOLUTION,
            mixed_invented=mixed_by_mark[(m, "some invented")],
        )
        for m in CANDIDATES
    ]
    chosen, notes = choose(results)
    spot_total = spot_changed = picked = typed_lines = 0
    for k, page in pages.items():
        key_lines = Counter(lines_of(key_texts[int(k)]))
        spot_total += len(page.get("spot", []))
        spot_changed += sum(1 for line in page.get("spot", []) if key_lines[line] == 0)
        seen = {line for lines in page["versions"].values() for line in lines}
        for line in key_lines.elements():
            if line in seen:
                picked += 1
            else:
                typed_lines += 1
    lines = [
        "# the transcriber test (S2.6 spec §7, decision 0080) -- counts only",
        f"keys: {sum(1 for r in keys if r['set'] == 'typed')} typed pages, "
        f"{len(pages)} handwriting pages ({sum(r.hw_lines for r in results[:1])} key lines), "
        f"{results[0].photo_pages} no-word photographs; {RESOLUTION} dpi; instruction "
        f"{TRANSCRIBE.version}; standard prices (images cannot be batched)",
        f"handwriting key: {picked} lines picked from a version, {typed_lines} typed by Andy; "
        f"spot check of agreed lines: {spot_changed} of {spot_total} wrong in all four",
        "",
    ]
    for r in results:
        price = sources.price_of(r.model)
        low, high = wilson(r.hw_right, r.hw_lines)
        lines += [
            f"## {r.model} (${price.input_usd_per_mtok}/${price.output_usd_per_mtok} per M "
            f"tokens; measured ${r.cost_per_page:.5f} per test page)",
            f"  invented: {r.hw_inventing} lines ({r.invented_per_100_lines:.1f} per 100 "
            f"handwriting lines); {r.photo_invented} of {r.photo_pages} photographs",
            f"  handwriting lines right: {r.hw_right} of {r.hw_lines} ({r.hw_accuracy:.1%} "
            f"[{low:.1%}, {high:.1%}], Wilson 95%, lines not independent)",
            f"  typed errors: {r.typed_errors_per_100:.2f} per 100 characters "
            f"({r.typed_errors} of {r.typed_chars})",
            f"  full-page scans (decision W7): invented added words on {r.mixed_invented} of "
            f"{r.mixed_pages}; repeated the text layer on "
            f"{mixed_by_mark[(r.model, 'repeats the text layer')]}",
        ]
    lines += ["", "## the rule", *notes]
    if chosen is not None:
        at_200 = _result(chosen, keys, key_texts, 0, typed_answers, cache, dpi=200)
        if at_200.cost_per_page > 0:
            base = next(r for r in results if r.model == chosen)
            dpi = choose_resolution(base.hw_accuracy, at_200.hw_accuracy)
            lines += [
                "",
                "## resolution (spec §7.5)",
                f"  {chosen}: handwriting {base.hw_accuracy:.1%} at 150 dpi, "
                f"{at_200.hw_accuracy:.1%} at 200; typed errors {base.typed_errors_per_100:.2f} "
                f"and {at_200.typed_errors_per_100:.2f} per 100 characters",
                f"  chosen: {dpi} dpi",
            ]
    return "\n".join(lines)


def _latest_heldout_b_cost_per_case(settings: Settings) -> float:
    """Arm B's cost per case on its latest finished heldout-400 run (the S2.4 bar)."""
    records = [
        record
        for path in sorted(settings.runs_dir.glob("*-heldout-400-B/run.jsonl"))
        for record in read_jsonl(path, RunRecord)
        if record.finished is not None and record.arm == "B" and record.cases
    ]
    latest = max(records, key=lambda r: r.started)
    return latest.cost_usd / latest.cases


def cmd_estimate(settings: Settings, transcriber: str, dpi: int) -> str:
    """Decision 0083 item 2: the stage's spend so far plus its re-estimated rest, against $40."""
    s26 = settings.data_dir / "s26"
    spent = sum(
        s.cost_usd
        for path in sorted(settings.runs_dir.glob(f"*/{SPEND_FILE}"))
        for s in read_jsonl(path, SpendRecord)
    )
    frame = _read(s26 / "pages-dev-400.jsonl")
    sample = _read(s26 / "inventory" / "sample.jsonl")
    mixed = [r for r in sample if str(r["stratum"]).startswith("text and image")]
    sent_share = sum(
        1 for r in mixed if float(str(r["image_area_share"])) >= MIXED_PAGE_MIN_IMAGE_SHARE
    ) / max(1, len(mixed))
    image_only = sum(1 for r in frame if r["kind"] == "image only")
    text_and_image = sum(1 for r in frame if r["kind"] == "text and image")
    dev_pages = image_only + round(text_and_image * sent_share)
    cache = TranscriptionCache(settings.transcription_dir)
    keys = _read(settings.data_dir / FOLDER / "keys.jsonl")
    readings = [cache.get(_key(r, transcriber, instruction=TRANSCRIBE.version, dpi=dpi)) for r in keys]
    per_page = statistics.mean(r.cost_usd for r in readings if r is not None)
    transcription = 2 * dev_pages * per_page  # held-out assumed equal to development (spec §11)
    b_case = _latest_heldout_b_cost_per_case(settings)
    # A floor: v2 adds transcribed text to every payload, which the S2.4 cost per case lacks.
    runs = b_case * (401 + 401 + 400 + 400) + 2 * b_case * 401  # four batch runs; W5's standard B-v2
    labels = json.loads((s26 / "inventory" / "labels.json").read_text())
    by_stratum: dict[str, list[str]] = {}
    for row in sample:
        if str(row["n"]) in labels:
            by_stratum.setdefault(str(row["stratum"]), []).append(labels[str(row["n"])])
    population = json.loads((s26 / "inventory" / "population.json").read_text())
    picture_share = inventory.weighted_word_share(
        by_stratum, population, counted={"image only": PICTURES, "text and image": PICTURES, "photo-only": PICTURES}
    )
    luna_photo_tokens = [
        r.prompt_tokens
        for r in (
            cache.get(_key(row, AGENT_MODEL, instruction=TRANSCRIBE.version, dpi=RESOLUTION))
            for row in keys
            if row["set"] == "photo"
        )
        if r is not None
    ]
    image_tokens = statistics.median(luna_photo_tokens) - len(TRANSCRIBE.system) / 4
    images_per_case = (image_only + text_and_image) * picture_share / 401
    luna = sources.price_of(AGENT_MODEL)
    v3 = 401 * (2 * b_case + 2 * images_per_case * image_tokens * luna.input_usd_per_mtok / 1e6)
    total = spent + transcription + runs + v3
    verdict = (
        f"pause: the stage passes ${MONTH_BUDGET_USD:.0f} -- Andy decides (decision 0083 item 2)"
        if total > MONTH_BUDGET_USD
        else f"within ${MONTH_BUDGET_USD:.0f}"
    )
    return "\n".join(
        [
            f"spent on S2.6 so far (preparation spend rows): ${spent:.2f}",
            f"dev-400 pages to transcribe: {image_only} image-only + {sent_share:.0%} of "
            f"{text_and_image} text-and-image = {dev_pages}; held-out assumed the same",
            f"{transcriber} at {dpi} dpi: ${per_page:.5f} per page measured; transcription of "
            f"both samples ${transcription:.2f}",
            f"arm B runs (dev B-v1, B-v2, B-v2 standard; held-out B-v1, B-v2) at "
            f"${b_case:.5f} per case (latest heldout-400 arm B run): ${runs:.2f}, a floor",
            f"v3 probe: {images_per_case:.1f} picture pages per case at {image_tokens:.0f} tokens "
            f"each, GPT-6 Luna standard: ${v3:.2f}",
            f"stage total: ${total:.2f} -- {verdict}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand."""
    parser = argparse.ArgumentParser(prog="transcriber_test")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("keys", "probe", "run", "handwriting", "photos", "mixed"):
        commands.add_parser(name)
    resolution_p = commands.add_parser("resolution")
    resolution_p.add_argument("--model", required=True, choices=CANDIDATES)
    score_p = commands.add_parser("score")
    score_p.add_argument("--handwriting", type=Path, required=True)
    score_p.add_argument("--photos", type=Path, required=True)
    score_p.add_argument("--mixed", type=Path, required=True)
    score_p.add_argument("--out", type=Path)
    estimate_p = commands.add_parser("estimate")
    estimate_p.add_argument("--model", required=True, choices=CANDIDATES)
    estimate_p.add_argument("--dpi", type=int, choices=(150, 200), default=RESOLUTION)
    args = parser.parse_args(argv)
    settings = Settings()
    docs = CachedDocuments(DocketClient(settings.docket_dir, transport=_offline()))
    if args.command == "keys":
        text = cmd_keys(settings, docs)
    elif args.command == "probe":
        text = cmd_probe(settings)
    elif args.command == "run":
        text = cmd_run(settings, docs, models=CANDIDATES, dpi=RESOLUTION)
    elif args.command == "resolution":
        text = cmd_run(settings, docs, models=(args.model,), dpi=200)
    elif args.command == "handwriting":
        text = cmd_handwriting(settings)
    elif args.command == "photos":
        text = cmd_photos(settings)
    elif args.command == "mixed":
        text = cmd_mixed(settings, docs)
    elif args.command == "score":
        text = cmd_score(settings, docs, args.handwriting, args.photos, args.mixed)
        if args.out:
            args.out.write_text(text + "\n")
    else:
        text = cmd_estimate(settings, args.model, args.dpi)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Let `ruff format` settle the long lines; where a line is still over 100 characters inside a string, split the string. Each subcommand gets one test over a `tmp_path` data directory: `cmd_keys` with an inventory whose labels already reach 25 and 50 (no top-up, so no client); `cmd_handwriting` and `cmd_photos` over a cache written by the test; `cmd_score` over two CSVs the test writes; `cmd_estimate` over spend rows, a frame, an inventory and a runs directory the test writes. `cmd_probe` and `cmd_run` are covered through `run_preparation`'s own tests and the recorded fixtures.

- [ ] **Step 6: Commit the tool and targets**

Append to `Makefile` (and `.PHONY`):

```make
s26-transcriber-keys:
	uv run python -m scripts.transcriber_test keys
# S2.6 spec §7.3: draws the three answer keys; labels top-up pages if the inventory is short (cents).

s26-transcriber-probe:
	uv run python -m scripts.transcriber_test probe
# One invented page per candidate (under a cent in all); records each reply as a test fixture.

s26-transcriber-run:
	uv run python -m scripts.transcriber_test run
	uv run python -m scripts.transcriber_test handwriting
	uv run python -m scripts.transcriber_test photos
	uv run python -m scripts.transcriber_test mixed
# All four candidates on every key page at 150 dpi (~$4-8 at standard prices), then Andy's two pages.

s26-transcriber-resolution:
	uv run python -m scripts.transcriber_test resolution --model $(MODEL)
# The chosen model at 200 dpi on the handwriting and typed keys (~$0.30-1).
```

```bash
git add scripts/transcriber_test.py tests/test_transcriber_test.py Makefile docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: the transcriber test -- keys, candidates, Andy's pages, and the rule fixed in code (0080)"
```

- [ ] **Step 7: STOP — Andy draws the keys and probes the candidates** (a few cents; about 10 minutes)

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
export OPENROUTER_API_KEY="$(pass show api/openrouter)"
make s26-transcriber-keys
make s26-transcriber-probe
```

Expected: `keys: typed 100, handwriting 25, photo 50, full-page scans 25` (fewer is logged in Deviations: the spec's "about"), and `ok` for all four candidates with every probe line copied. Afterwards the tree holds four new fixture files under `tests/fixtures/openrouter/transcription/` — replies to the invented page only. Read one before committing, confirm it holds only the invented lines, then:

```bash
uv run pytest tests/test_transcriber_test.py -v
git add tests/fixtures/openrouter/transcription/ docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: each transcriber candidate's reply to the invented probe page, recorded"
```

A candidate that fails the probe (for example Qwen rejecting reasoning level `none`) is recorded in Deviations with its error; the setting is corrected once in `sources.LOWEST_REASONING` with the reason, or the candidate is dropped (spec §17), and Andy is told before Step 8.

- [ ] **Step 8: STOP — Andy runs the test** (about $4–8 at standard prices, estimate; about 30–60 minutes)

Same exports, then `make s26-transcriber-run`. Expected: four `run_preparation` summaries and the two page paths. The tree is unchanged afterwards (everything is under `data/`).

- [ ] **Step 9: STOP — Andy builds the handwriting key and reviews the photograph and full-page-scan words** (about 1½–2 hours)

Andy opens `…/data/s26/transcriber-test/handwriting.html`, edits each page's key and answers each spot check, and downloads `handwriting-key.csv`; then opens `…/photos.html`, marks each output, and downloads `photo-words.csv`.

- [ ] **Step 10: Score, and resolution**

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
uv run python -m scripts.transcriber_test score --handwriting ~/Downloads/handwriting-key.csv --photos ~/Downloads/photo-words.csv --mixed ~/Downloads/mixed-words.csv --out docs/results/s26-transcriber-test.txt
```

If a model was chosen, **STOP** — Andy runs the resolution comparison (same exports; `make s26-transcriber-resolution MODEL=<the chosen model id>`, about $0.30–1, estimate), then the score command again, which adds the resolution section. If no model passed the gate, go to Step 13.

- [ ] **Step 11: Record the choice**

Set in `docket/transcribe.py`:

```python
# The transcriber chosen by the rule of decision 0080, recorded in decision 0084
# (docs/results/s26-transcriber-test.txt).
TRANSCRIBER = "<chosen model id>"
```

and, only if the rule chose 200, `RESOLUTION: Resolution = 200` in `docket/render.py` with the same citation. Write `docs/decisions/<next free number>-the-transcriber-is-<short-name>.md` in the house format (Context: the test and its keys; Decision: the model and the resolution; Why: the rule's outcome, citing the results file for every number; What this rules out: the other candidates, each with the rule's reason; Status: Accepted, <date> (Andy)), add its row to `docs/decisions/README.md`, and commit:

```bash
git add docs/results/s26-transcriber-test.txt docs/decisions/ src/ntsb_probable_cause/docket/ docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: the transcriber test, scored; the transcriber and its resolution (decision 0084)"
```

- [ ] **Step 12: STOP — the pause point (decision 0083 item 2)**

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
uv run python -m scripts.transcriber_test estimate --model <the chosen model id> --dpi <150 or 200>
```

Report the result to Andy in plain words: the test's outcome, the choice and why, and the stage's re-estimated total. If it reads `pause`, Andy decides between spreading the stage over months and transcribing fewer pages (for example image-only pages first); record his answer in Deviations. Nothing further runs until he answers.

- [ ] **Step 13: If no model passed.** The stage records it (spec §7.4 item 3): the results file says so, the transcriber decision is written as "no transcriber", Tasks 14–17 are skipped, and the close-out states what shipped (marks, renderer, axis, inventory) and what did not.

---

### Task 14: v2 in the docket tool (spec §8; decisions 0079, 0081)

**Starts only if** Task 13 chose a transcriber and Andy answered the pause point.

**Files:**
- Modify: `src/ntsb_probable_cause/docket/pages.py` (+ `image_count`), `docket/render.py` (+ `image_area_shares`)
- Modify: `src/ntsb_probable_cause/docket/transcribe.py` (+ `pages_to_read`, `ReadingLookup`)
- Modify: `src/ntsb_probable_cause/docket/extract.py` (readings; the transcribed marker; the image-words heading)
- Modify: `src/ntsb_probable_cause/docket/manifest.py` (`read_docket(..., readings=...)`; per-document counts; `Docket.readings`)
- Modify: `src/ntsb_probable_cause/scoring/runner.py` (`CachedDocketReader` versions; v2 allowed; preparation cost per case)
- Modify: `src/ntsb_probable_cause/scoring/records.py` (`CaseResult.preparation_cost_usd`), `scoring/report.py` (+ `preparation_summary`; the transcribed-cases comparison)
- Modify: `apps/eval/__main__.py` (+ `transcribe`; `run --evidence-version v2` reads the cache and refuses an unfinished one)
- Modify: `Makefile` (+ `s26-transcribe-dev`)
- Test: `tests/test_docket_extract.py`, `tests/test_docket_manifest.py`, `tests/test_docket_transcribe.py`, `tests/test_runner.py`, `tests/test_boundary.py`, `tests/test_eval_app.py`, `tests/test_report.py`

**Interfaces:**
- Produces: `docket.pages.image_count(page: PageObject) -> int`; `docket.render.image_area_shares(data: bytes) -> tuple[float, ...]` (object boxes only, nothing drawn); `docket.transcribe.pages_to_read(data: bytes) -> list[tuple[int, bool]]` — `(page, mixed)` for every image-only page and every text-and-image page at or above `MIXED_PAGE_MIN_IMAGE_SHARE`; `docket.transcribe.ReadingLookup(cache, *, model=TRANSCRIBER, instruction=TRANSCRIBE.version, dpi=RESOLUTION)` with `for_document(data: bytes) -> dict[int, Transcription]`, `done_file(sample: str) -> Path`, `is_done(sample: str) -> bool`, `mark_done(sample: str, summary: Mapping[str, object]) -> None`.
- Produces: `docket.extract.TRANSCRIBED_MARKER = "[page {n} of {total}, transcribed from an image]"`; `docket.extract.IMAGE_WORDS_HEADING = "[words in the page's images, transcribed]"`; `extract_pdf(data, *, readings: Mapping[int, Transcription] | None = None)` — with `readings=None`, byte-for-byte S2's output; `ExtractedDocument` + `transcribed_pages: int = 0`, `transcription_failed: int = 0`, `preparation_cost_usd: float = 0.0`.
- Produces: `DocumentRecord` + `transcribed_pages: int = 0`, `transcription_failed: int = 0`; `Docket` + `readings: dict[int, dict[int, Transcription]] = {}`, property `preparation_cost_usd`; `read_docket(client, mkey, *, readings: ReadingLookup | None = None)`.
- Produces: `CachedDocketReader(client, *, readings: ReadingLookup | None = None)` with `version: Literal["v1", "v2"]`; `DocketReader` protocol gains `version`; `CaseResult.preparation_cost_usd: float = 0.0`; `report.preparation_summary(results) -> str`; `ntsb-eval transcribe --sample S --expected-cost-per-page-usd X [--workers 8] [--retry-failed] [--dry-run]`.

**What the agent reads in v2** (spec §8.1; the example text is invented):

```
Docket item 4, 3 pages, of which 3 held readable text.
[page 1 of 3]
NTSB Form 6120.1 ...typed text layer...
[page 2 of 3, transcribed from an image]
Engine sputtered at 800 ft. Switched to [illegible] tank, no change.
[page 3 of 3]
Examination of the fuel system ...typed text layer...
[words in the page's images, transcribed]
LEFT TANK 2 GAL
```

A page whose transcription failed contributes what S2 gave it (its marker and any stray characters) and is counted `transcription_failed`; a mixed page under the cut-off was never sent and adds nothing. Transcribed text is part of the document's text, so the attach step's name and amateur-built replacements (0044, 0046), the split and the tripwire (with Task 4–5's marks) all apply to it unchanged (spec §8.4).

**Why a finished-transcription file.** A v2 run must read v2 evidence, not v1 with some pages missing. `ntsb-eval transcribe` writes `<transcription_dir>/done/<sample>-<key>.json` only when every page it chose has a cached reading (transcribed or failed). `ntsb-eval run --evidence-version v2` refuses without it, naming the command to run. The reader's `version` must match the run's, or `Runner.run` refuses: v2 evidence cannot be recorded as v1, or the other way round.

- [ ] **Step 1: Write the failing tests**

`tests/test_docket_extract.py` (append; `Transcription` records built directly, no model):

```python
def _reading(page: int, text: str, *, status: str = "transcribed", mixed: bool = False) -> Transcription:
    return Transcription(
        key=TranscriptionKey(document_sha256="d" * 64, page=page, model="m", instruction="t1", dpi=150),
        status=status,  # type: ignore[arg-type]
        text=text,
        page_kind="handwriting",
        mixed=mixed,
        cost_usd=0.001,
        created=datetime(2026, 10, 1, tzinfo=UTC),
    )


TYPED = "Examination of the fuel system found fuel in both wing tanks."
DOC = build_pdf([PageSpec(text=TYPED), PageSpec(images=("/DCTDecode",)), PageSpec(text=TYPED, images=("/DCTDecode",))])


def test_without_readings_the_text_is_s2s() -> None:
    assert extract_pdf(DOC).text == extract_pdf(DOC, readings=None).text
    assert "transcribed" not in extract_pdf(DOC).text


def test_an_image_page_reads_as_its_transcription_with_its_own_marker() -> None:
    result = extract_pdf(DOC, readings={2: _reading(2, "Engine sputtered at 800 ft.")})
    assert "[page 2 of 3, transcribed from an image]\nEngine sputtered at 800 ft." in result.text
    assert result.transcribed_pages == 1
    assert result.chars_by_page[1] == len("Engine sputtered at 800 ft.")
    assert result.preparation_cost_usd == pytest.approx(0.001)


def test_a_mixed_page_keeps_its_text_layer_and_adds_the_image_words() -> None:
    result = extract_pdf(DOC, readings={3: _reading(3, "LEFT TANK 2 GAL", mixed=True)})
    page_three = result.text.split("[page 3 of 3]")[1]
    assert TYPED.split(" in ")[0] in page_three
    assert page_three.endswith("[words in the page's images, transcribed]\nLEFT TANK 2 GAL")


def test_a_failed_page_adds_nothing_and_is_counted() -> None:
    result = extract_pdf(DOC, readings={2: _reading(2, "", status="failed")})
    assert result.transcription_failed == 1
    assert "transcribed from an image" not in result.text
```

`tests/test_docket_manifest.py` (append; use the file's existing fake `DocketClient` pattern with one scanned document): with a `ReadingLookup` over a `tmp_path` cache holding a transcription for every page, the document that S2 marked `unreadable: scan` is now `read`, with `transcribed_pages` equal to its pages, and its text carries the transcribed marker; without readings it is still `unreadable: scan`.

`tests/test_docket_transcribe.py` (append):

```python
def test_pages_to_read_takes_image_pages_and_mixed_pages_over_the_cut() -> None:
    document = build_pdf(
        [
            PageSpec(text=TYPED),
            PageSpec(images=("/CCITTFaxDecode",)),
            PageSpec(text=TYPED, images=("/DCTDecode",)),
            PageSpec(),
        ]
    )
    # A 100 x 100 image on a letter page covers about 2% of it.
    chosen = pages_to_read(document)
    assert (2, False) in chosen
    assert ((3, True) in chosen) == (100 * 100 / (612 * 792) >= MIXED_PAGE_MIN_IMAGE_SHARE)
    assert all(page not in (1, 4) for page, _ in chosen)


def test_the_lookup_finds_a_documents_readings_and_the_done_file(tmp_path: Path) -> None:
    cache = TranscriptionCache(tmp_path)
    document = build_pdf([PageSpec(images=("/DCTDecode",))])
    lookup = ReadingLookup(cache, model="m", instruction="t1", dpi=150)
    sha = hashlib.sha256(document).hexdigest()
    key = TranscriptionKey(document_sha256=sha, page=1, model="m", instruction="t1", dpi=150)
    cache.put(Transcription(key=key, status="transcribed", text="x", page_kind="blank", created=NOW))
    assert lookup.for_document(document) == {1: cache.get(key)}
    assert not lookup.is_done("dev-400")
    lookup.mark_done("dev-400", {"pages": 1})
    assert lookup.is_done("dev-400")
```

`tests/test_boundary.py` (append): a v2 case whose transcription contains the case's own probable cause is refused (`LeakageError` names `probable_cause in docket_documents`), and a transcription containing the owner's recorded name reaches the payload with the name replaced by `Owner or operator` (0046) — build both through `read_docket` with a lookup over a `tmp_path` cache, as the manifest test does.

`tests/test_runner.py` (append): `Runner.run` with `RunSpec(arm="B", evidence_version="v2")` and a v1 reader raises `ConfigurationError` matching `v1 evidence`; with a v2 reader over a docket with one transcribed page it answers the case and the `CaseResult` has `preparation_cost_usd` equal to the reading's cost; `RunSpec(evidence_version="v3")` is still refused (`not built yet`).

`tests/test_eval_app.py` (append): `run --arm B --evidence-version v2` without a done file exits non-zero naming `ntsb-eval transcribe --sample`; `transcribe --dry-run` prints the page count and projected cost and calls no model.

`tests/test_report.py` (append):

```python
def test_preparation_summary_is_apart_from_the_cap(case_result: CaseResult) -> None:
    rows = [case_result.model_copy(update={"preparation_cost_usd": c}) for c in (0.01, 0.03)]
    assert report.preparation_summary(rows) == (
        "evidence preparation (transcription; paid once, apart from the per-case cap, "
        "decision 0081): $0.0200 per case, $0.04 in all, 2 of 2 cases with transcribed pages"
    )
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_docket_extract.py tests/test_docket_manifest.py tests/test_docket_transcribe.py tests/test_runner.py tests/test_boundary.py tests/test_eval_app.py tests/test_report.py -v -k "reading or transcri or v2 or preparation or pages_to_read"`
Expected: FAIL on the missing names.

- [ ] **Step 3: Page counts without drawing**

`docket/pages.py`:

```python
def image_count(page: PageObject) -> int:
    """How many images the page's resources draw, forms followed, none decoded."""
    try:
        return len(list(_images(page.get("/Resources"), set())))
    except Exception:  # a broken page draws nothing we can count
        return 0
```

`docket/render.py`:

```python
def image_area_shares(data: bytes) -> tuple[float, ...]:
    """Every page's image-area share, from the images' boxes alone: nothing is drawn."""
    try:
        document = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as error:
        raise DocketError(f"not a PDF: {error}") from error
    try:
        shares: list[float] = []
        for index in range(len(document)):
            try:
                page = document[index]
            except pdfium.PdfiumError:  # a page PDFium cannot load covers nothing we can see
                shares.append(0.0)
                continue
            try:
                shares.append(_image_area_share(page))
            finally:
                page.close()
        return tuple(shares)
    finally:
        document.close()
```

- [ ] **Step 4: Which pages are read, and where their readings are**

`docket/transcribe.py` (import `hashlib`, `io`, `PdfReader`, `document_facts` from `docket.pages`, `image_area_shares` and `RESOLUTION` from `docket.render`):

```python
def pages_to_read(data: bytes) -> list[tuple[int, bool]]:
    """``(page, mixed)`` for every page v2 transcribes (0074, 0079 item 3, decision W3).

    Every image-only page; a text-and-image page only when its images cover at least
    ``MIXED_PAGE_MIN_IMAGE_SHARE`` of it; never a text-only or blank page.
    """
    chosen: list[tuple[int, bool]] = []
    shares = image_area_shares(data)
    for number, page in enumerate(document_facts(data), start=1):
        share = shares[number - 1] if number <= len(shares) else 0.0
        if page.kind == "image only":
            chosen.append((number, False))
        elif page.kind == "text and image" and share >= MIXED_PAGE_MIN_IMAGE_SHARE:
            chosen.append((number, True))
    return chosen


class ReadingLookup:
    """The chosen transcriber's cached readings, by document; and whether a sample is done."""

    def __init__(
        self,
        cache: TranscriptionCache,
        *,
        model: str = TRANSCRIBER,
        instruction: str = TRANSCRIBE.version,
        dpi: int = RESOLUTION,
    ) -> None:
        self._cache = cache
        self._model = model
        self._instruction = instruction
        self._dpi = dpi

    def for_document(self, data: bytes) -> dict[int, Transcription]:
        """Every page of the document that has a reading, by page number."""
        sha = hashlib.sha256(data).hexdigest()
        try:
            pages = len(PdfReader(io.BytesIO(data)).pages)
        except Exception:  # the same boundary as extract: an unreadable file has no readings
            return {}
        readings: dict[int, Transcription] = {}
        for page in range(1, pages + 1):
            key = TranscriptionKey(
                document_sha256=sha,
                page=page,
                model=self._model,
                instruction=self._instruction,
                dpi=self._dpi,
            )
            record = self._cache.get(key)
            if record is not None:
                readings[page] = record
        return readings

    def done_file(self, sample: str) -> Path:
        """Where ``ntsb-eval transcribe`` records that a sample's readings are complete."""
        stamp = hashlib.sha256(
            f"{self._model}|{self._instruction}|{self._dpi}".encode()
        ).hexdigest()[:12]
        return self._cache.root / "done" / f"{sample}-{stamp}.json"

    def is_done(self, sample: str) -> bool:
        """Whether every page the sample needs has a reading (transcribed or failed)."""
        return self.done_file(sample).is_file()

    def mark_done(self, sample: str, summary: Mapping[str, object]) -> None:
        """Record a finished sample, with its counts."""
        path = self.done_file(sample)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(summary), indent=1) + "\n")
```

(`TranscriptionCache` gains a read-only `root` property returning its directory.)

- [ ] **Step 5: `extract_pdf` reads the readings**

In `docket/extract.py` (import `Mapping` and `Transcription`):

```python
# Decision 0079: a transcribed page says where its text came from, never what it means.
TRANSCRIBED_MARKER = "[page {n} of {total}, transcribed from an image]"
IMAGE_WORDS_HEADING = "[words in the page's images, transcribed]"
```

`ExtractedDocument` gains the three fields. In `extract_pdf`, add `*, readings: Mapping[int, Transcription] | None = None`, initialise `transcribed = failed = 0` and `cost = 0.0`, and replace the loop's last two lines with:

```python
        reading = readings.get(n) if readings is not None else None
        marker = PAGE_MARKER.format(n=n, total=total)
        if reading is not None:
            cost += reading.cost_usd
            failed += reading.status == "failed"
        if reading is not None and reading.status == "transcribed" and reading.text:
            if reading.mixed:
                text = f"{text}\n{IMAGE_WORDS_HEADING}\n{reading.text}"
            else:
                marker = TRANSCRIBED_MARKER.format(n=n, total=total)
                text = reading.text
            transcribed += 1
        counts.append(len(text))
        parts.append(marker + "\n" + text)
```

and return `ExtractedDocument(chars_by_page=tuple(counts), text="\n".join(parts), transcribed_pages=transcribed, transcription_failed=failed, preparation_cost_usd=cost)`. With `readings=None` every branch is skipped, so the text is S2's exactly — the first test proves it.

- [ ] **Step 6: `read_docket` takes the lookup**

In `docket/manifest.py`: `DocumentRecord` gains `transcribed_pages: int = 0` and `transcription_failed: int = 0`; `Docket` gains `readings: dict[int, dict[int, Transcription]] = {}` and

```python
    @property
    def preparation_cost_usd(self) -> float:
        """What reading this docket's pages cost, paid once and apart from the cap (0081)."""
        return sum(r.cost_usd for pages in self.readings.values() for r in pages.values())
```

`read_docket(client, mkey, *, readings: ReadingLookup | None = None)`: after `content = client.document(...)`, `document_readings = readings.for_document(content) if readings is not None else None`; `extracted = extract_pdf(content, readings=document_readings)`; pass `transcribed_pages=extracted.transcribed_pages, transcription_failed=extracted.transcription_failed` into both `_record` calls (add them to `_record`'s keywords); and after the loop, `readings_by_document[entry.index] = document_readings or {}`, returned on the `Docket`. The scan test follows from the counts: a scanned page with a transcription now counts its characters, so `classify_pages` no longer calls the document a scan.

- [ ] **Step 7: The runner, the records, the report**

`scoring/runner.py`:

```python
class DocketReader(Protocol):
    """Where arm B (and later the loop) gets a case's docket from."""

    version: Literal["v1", "v2"]

    def read(self, mkey: int) -> Docket:
        """The docket for a case's internal key."""
        ...


class CachedDocketReader:
    """The real reader: the client's cache (spec §7.1); with readings, evidence version v2."""

    def __init__(self, client: DocketClient, *, readings: ReadingLookup | None = None) -> None:
        self._client = client
        self._readings = readings
        self.version: Literal["v1", "v2"] = "v1" if readings is None else "v2"

    def read(self, mkey: int) -> Docket:
        """The docket for a case's internal key, fetched (or read from cache) and classified."""
        return read_docket(self._client, mkey, readings=self._readings)
```

In `Runner.run`, replace Task 8's refusal with:

```python
        if spec.evidence_version == "v3":
            raise ConfigurationError("evidence version v3 is not built yet")  # Task 16
        if spec.arm == "B" and self._docket is not None:
            wanted = "v1" if spec.evidence_version == "v1" else "v2"
            if self._docket.version != wanted:
                raise ConfigurationError(
                    f"a {spec.evidence_version} run needs a {wanted} docket reader; this one "
                    f"reads {self._docket.version} evidence (decision 0076)"
                )
```

`Prepared` and `_CaseContext` gain `preparation_cost_usd: float = 0.0`, set from `docket.preparation_cost_usd` in `prepare_case`'s arm B branch and copied through `_answer_case` / `_prepare_contexts`; `_case_result` passes `preparation_cost_usd=ctx.preparation_cost_usd`. `CaseResult` (records.py) gains `preparation_cost_usd: float = 0.0` with the comment `# Decision 0081: transcription paid for this case's docket -- apart from cost_usd and the cap.` Every test fake reader gains `version = "v1"`.

`scoring/report.py`:

```python
def preparation_summary(results: Sequence[CaseResult]) -> str:
    """Transcription's cost per case, printed apart from the agent's (decision 0081)."""
    paid = [r.preparation_cost_usd for r in results if r.preparation_cost_usd > 0]
    total = sum(paid)
    per_case = total / len(paid) if paid else 0.0
    return (
        "evidence preparation (transcription; paid once, apart from the per-case cap, "
        f"decision 0081): ${per_case:.4f} per case, ${total:.2f} in all, {len(paid)} of "
        f"{len(results)} cases with transcribed pages"
    )
```

`apps/eval/__main__.py`, `_cmd_report`: when the run's `evidence_version` is not `v1`, append `report.preparation_summary(cases)`; and in the `--against` block, when the versions differ, also print the comparison restricted to cases with `preparation_cost_usd > 0` in this run, headed `on the <n> cases with transcribed pages:` (spec §9.1: "for the cases that hold image pages").

- [ ] **Step 8: The `transcribe` command, and v2 runs**

`apps/eval/__main__.py`:

```python
    transcribe_p = commands.add_parser(
        "transcribe", help="read a sample's image pages once, into the cache (S2.6, 0081)"
    )
    transcribe_p.add_argument("--sample", choices=samples.SAMPLES, required=True)
    transcribe_p.add_argument("--expected-cost-per-page-usd", type=float, required=True)
    transcribe_p.add_argument("--workers", type=int, default=8)
    transcribe_p.add_argument("--retry-failed", action="store_true")
    transcribe_p.add_argument("--dry-run", action="store_true", help="count and price only")
```

```python
def _cmd_transcribe(args: argparse.Namespace, settings: Settings) -> None:
    """Every page v2 needs, for one sample: counted, priced, then read once (0081)."""
    raws = samples.load_cases(settings.data_dir / "processed", samples.sample_ids(args.sample))
    client = DocketClient(
        settings.docket_dir, seconds_per_request=settings.docket_seconds_per_request
    )
    docs = CachedDocuments(client)
    cache = TranscriptionCache(settings.transcription_dir)
    jobs: list[PageJob] = []
    for raw in raws:
        mkey = raw.get("mKey")
        if not isinstance(mkey, int):
            continue
        try:
            entries = docs.listing(mkey).entries
        except DocketError:
            continue
        for entry in entries:
            if entry.is_photo_only() or not entry.is_pdf():
                continue
            try:
                data = docs.document(mkey, entry.index)
            except DocketError:
                continue
            sha = hashlib.sha256(data).hexdigest()
            for page, mixed in pages_to_read(data):
                key = TranscriptionKey(
                    document_sha256=sha,
                    page=page,
                    model=TRANSCRIBER,
                    instruction=TRANSCRIBE.version,
                    dpi=RESOLUTION,
                )
                jobs.append(PageJob(key, docs.loader(mkey, entry.index), mixed))
    pending = [
        j for j in jobs
        if (hit := cache.get(j.key)) is None or (args.retry_failed and hit.status == "failed")
    ]
    projected = len(pending) * args.expected_cost_per_page_usd
    print(
        f"{args.sample}: {len(jobs)} pages to read with {TRANSCRIBER} at {RESOLUTION} dpi, "
        f"{len(pending)} not yet read; projected ${projected:.2f}"
    )
    if args.dry_run:
        return
    done = run_preparation(
        kind="transcription",
        jobs=jobs,
        instruction=TRANSCRIBE,
        settings=settings,
        commit=ledger.commit_state(),
        expected_cost_per_page_usd=args.expected_cost_per_page_usd,
        workers=args.workers,
        retry_failed=args.retry_failed,
    )
    readings = [cache.get(j.key) for j in jobs]
    failed = sum(1 for r in readings if r is not None and r.status == "failed")
    print(
        f"read {len(done)} pages now (${sum(r.cost_usd for r in done):.2f}); "
        f"{failed} of {len(jobs)} failed in all"
    )
    if all(r is not None for r in readings):
        ReadingLookup(cache).mark_done(
            args.sample,
            {"pages": len(jobs), "failed": failed, "model": TRANSCRIBER, "dpi": RESOLUTION},
        )
```

Decision W2: v2 and v3 read the photo-only documents too. So in this command drop `entry.is_photo_only() or` from the skip, and in `read_docket` skip a photo-only entry only when `readings is None` (v1 keeps S2's rule exactly); test both. Counts only are printed: on `heldout-400` this command reads pages by program and no person sees them.

In `_cmd_run`, for arm B: `readings = ReadingLookup(TranscriptionCache(settings.transcription_dir)) if args.evidence_version != "v1" else None`; if `readings` is set and `not readings.is_done(args.sample)`, exit with `f"{args.sample} is not fully transcribed: run ntsb-eval transcribe --sample {args.sample} first"`; build `CachedDocketReader(docket_client, readings=readings)`.

- [ ] **Step 9: Run the tests, then the whole check**

Run: the Step 2 command, then `make check`
Expected: PASS; green. Every S2 docket test passes unchanged — v1 is untouched.

- [ ] **Step 10: The target, and commit**

```make
s26-transcribe-dev:
	uv run ntsb-eval transcribe --sample dev-400 --expected-cost-per-page-usd $(PER_PAGE) --dry-run
	uv run ntsb-eval transcribe --sample dev-400 --expected-cost-per-page-usd $(PER_PAGE)
# S2.6 spec §8.3: reads every image page dev-400 needs, once, into the cache. PER_PAGE is the
# transcriber's measured cost per page from docs/results/s26-transcriber-test.txt, rounded up.
```

```bash
git add src/ tests/ apps/eval/__main__.py Makefile docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: v2 in the docket tool -- transcribed pages, their marker, a finished-transcription check (0079, 0081)"
```

---

### Task 15: Do transcriptions help? B-v1 and B-v2 on `dev-400` (spec §9.1; Andy runs; paid)

**Files:**
- Modify: `Makefile` (+ `s26-dev-runs`)
- Create: `docs/results/s26-armB-v2-dev.txt`

- [ ] **Step 1: The target**

```make
s26-dev-runs:
	uv run ntsb-eval run --arm B --sample dev-400 --evidence-version v1 --expected-cost-per-case-usd $(PER_CASE)
	uv run ntsb-eval run --arm B --sample dev-400 --evidence-version v2 --expected-cost-per-case-usd $(PER_CASE)
# S2.6 spec §9.1: both at one commit, marks in force. Development runs write no ledger row, so
# the tree stays clean and one recipe is safe. PER_CASE: S2.4's arm B cost per case on
# heldout-400 (docs/results/s24-bars.txt), rounded up by half for v2's added text.
```

Commit it (`S2.6: make target for the dev-400 B-v1 and B-v2 runs`).

- [ ] **Step 2: STOP — Andy transcribes `dev-400`** (the estimate from Task 13 Step 12; about 1–3 hours at 8 workers)

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
export OPENROUTER_API_KEY="$(pass show api/openrouter)"
make s26-transcribe-dev PER_PAGE=<measured cost per page, rounded up>
```

Expected: the dry run's page count and projected cost first (compare with Task 13's estimate; stop if it is more than a quarter higher, and report), then the reading, then `… failed in all`. The tree is unchanged afterwards (the cache is under `data/`). If it is interrupted, run it again: cached pages are skipped. Failed pages over 2% of the total: run once more with `--retry-failed` before going on, and log the count.

- [ ] **Step 3: STOP — Andy runs B-v1 and B-v2** (about $2–4 in all, estimate; each run about 30–90 minutes on the batch service)

Same exports; `git status --short` must be empty; then `make s26-dev-runs PER_CASE=<value>`. Note both run ids. The tree is unchanged afterwards (development runs write no ledger row).

- [ ] **Step 4: The results file**

```bash
{
  uv run ntsb-eval report <B-v2 run id> --against <B-v1 run id> --versions-compared; echo
  uv run ntsb-eval report <B-v1 run id>
} > docs/results/s26-armB-v2-dev.txt
```

Expected: both tables with their unmarked and marked rows (Task 9), the preparation line (Task 14), and the paired difference overall, on cases unmarked in both runs, and on the cases with transcribed pages, each by fatal and non-fatal through the slices. Commit (`S2.6: B-v2 against B-v1 on dev-400 (spec §9.1)`).

- [ ] **Step 5: STOP — report to Andy** in plain words with a glossary: does reading the words in images change the diagnosis on development cases, overall and where image pages exist; what the marked groups show; what it cost. Published whichever way it comes out.

---

### Task 16: v3 — pictures alongside the text (spec §10; decision 0082)

*Depends on decision W5.*

**Files:**
- Modify: `src/ntsb_probable_cause/scoring/runner.py` (`picture_pages`; images in `prepare_case` up to the cap; `unguarded_images`; the v3 refusals)
- Modify: `src/ntsb_probable_cause/scoring/records.py` (`fingerprint` covers images; `CaseResult.images_sent`, `images_not_sent`)
- Modify: `src/ntsb_probable_cause/scoring/report.py` (+ `image_summary`; the without-unguarded table)
- Modify: `apps/eval/__main__.py` (v3 uses the v2 reader and `--sync --price-variant standard`)
- Test: `tests/test_runner.py`, `tests/test_boundary.py`, `tests/test_report.py`

**Interfaces:**
- Consumes: `Docket.readings` (Task 14), `Payload.from_evidence(..., images=...)` (Task 10), `CaseMark` (Task 4).
- Produces: `runner.PICTURE_KINDS = frozenset({"photograph", "diagram or chart", "mixed"})`; `runner.IMAGE_TOKENS_ESTIMATE: int` (from Task 13 Step 12's measured GPT-6 Luna tokens per image, cited); `runner.picture_pages(docket, attached) -> list[tuple[int, int, bool]]` — `(document, page, unguarded)`; `estimated_cost_usd(payload_text, system, spec, *, images: int = 0)` and `over_cap(..., *, images: int = 0)`; `CachedDocketReader.picture(mkey, index, page) -> PageImage`; `CaseResult.images_sent: int = 0`, `images_not_sent: int = 0`; `report.image_summary(results) -> str`.

**The rule, from spec §10.3 and 0082, as code:** a page is a picture if its reading passed (`transcribed`) and its kind is photograph, diagram or chart, or mixed — its words, if any, already passed the tripwire with the document's text; a page whose reading **failed** is sent anyway and counted `unguarded`. Pictures go in page order, document by document in the order attached, until the next would take the case over the cap; the rest are counted `images_not_sent`. A case with any unguarded picture is marked `unguarded_images` with the count. This mark is the one computed outside `split_record`, because pictures never pass through the split; it is added to the evidence's marks in `prepare_case`, the one place pictures are chosen.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_runner.py` (it already imports `small_docket` from `tests.test_attach`, `prepare_case`, `estimated_cost_usd`, `runner`, `FakeDocketReader`; add `dataclasses`, `CaseMark`, `PageImage`, `Transcription`, `TranscriptionKey`, `picture_pages`):

```python
PICTURE = PageImage(media_type="image/jpeg", data=b"\xff\xd8picture")
V3 = RunSpec(
    sample="dev-400", arm="B", evidence_version="v3", sync=True, price_variant="standard"
)


def _reading(page: int, status: str, kind: str | None) -> Transcription:
    return Transcription(
        key=TranscriptionKey(document_sha256="d" * 64, page=page, model="m", instruction="t1", dpi=150),
        status=status,  # type: ignore[arg-type]
        page_kind=kind,  # type: ignore[arg-type]
        created=datetime(2026, 10, 1, tzinfo=UTC),
    )


def _v3_docket() -> Docket:
    """Document 1: a photograph (read), a typed page (read), and a page whose reading failed."""
    docket = small_docket({1: "[page 1 of 3]\nThe crankshaft was intact.\n"})
    readings = {
        1: {
            1: _reading(1, "transcribed", "photograph"),
            2: _reading(2, "transcribed", "typed text"),
            3: _reading(3, "failed", None),
        }
    }
    return docket.model_copy(update={"readings": readings})


def test_picture_pages_are_pictures_and_failed_pages() -> None:
    assert picture_pages(_v3_docket(), [1]) == [(1, 1, False), (1, 3, True)]
    assert picture_pages(_v3_docket(), []) == []


def test_v3_sends_the_pictures_and_marks_the_unguarded_one(
    record_fixtures: list[dict[str, object]],
) -> None:
    drawn: list[tuple[int, int, int]] = []

    def picture(mkey: int, index: int, page: int) -> PageImage:
        drawn.append((mkey, index, page))
        return PICTURE

    prepared = prepare_case(record_fixtures[0], V3, load_tables(), _v3_docket(), picture=picture)
    assert drawn == [(1, 1, 1), (1, 1, 3)]
    assert prepared.payload.images == (PICTURE, PICTURE)
    assert CaseMark(kind="unguarded_images", count=1) in prepared.evidence.marks
    assert "unguarded_images" not in prepared.payload.text
    assert (prepared.images_sent, prepared.images_not_sent) == (2, 0)


def test_v3_stops_adding_pictures_at_the_cap(record_fixtures: list[dict[str, object]]) -> None:
    roomy = prepare_case(record_fixtures[0], V3, load_tables(), _v3_docket(), picture=lambda *_: PICTURE)
    one_picture = estimated_cost_usd(roomy.payload.text, roomy.system, V3, images=1)
    tight = dataclasses.replace(V3, cap_usd=one_picture * 1.0001)
    prepared = prepare_case(
        record_fixtures[0], tight, load_tables(), _v3_docket(), picture=lambda *_: PICTURE
    )
    assert (prepared.images_sent, prepared.images_not_sent) == (1, 1)
    assert prepared.attached == roomy.attached  # the text fits either way


def test_v2_sends_no_pictures(record_fixtures: list[dict[str, object]]) -> None:
    v2 = dataclasses.replace(V3, evidence_version="v2")
    prepared = prepare_case(record_fixtures[0], v2, load_tables(), _v3_docket(), picture=lambda *_: PICTURE)
    assert prepared.payload.images == ()


def test_v3_needs_arm_b_the_sync_path_and_the_standard_price(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    run = runner(tmp_path, RecordingFakeClient([GOOD, REFINE]), docket=FakeDocketReader(_v3_docket()))
    with pytest.raises(ConfigurationError, match="standard"):
        run.run(RunSpec(sample="dev-400", arm="B", evidence_version="v3"), record_fixtures[:1])
```

Append to `tests/test_boundary.py`:

```python
def test_a_v3_case_whose_document_holds_the_cause_is_refused_before_any_picture(
    record_fixtures: list[dict[str, object]],
) -> None:
    raw = next(r for r in record_fixtures if probable_cause(r))
    docket = small_docket({1: f"[page 1 of 3]\n{probable_cause(raw)}\n"}).model_copy(
        update={"readings": {1: {1: _photograph_reading()}}}
    )
    spec = RunSpec(sample="dev-400", arm="B", evidence_version="v3", sync=True, price_variant="standard")
    drawn: list[int] = []
    with pytest.raises(LeakageError, match="probable_cause in docket_documents"):
        prepare_case(raw, spec, load_tables(), docket, picture=lambda *a: drawn.append(1) or PICTURE)
    assert drawn == []


def test_the_fingerprint_changes_with_a_picture(record_fixtures: list[dict[str, object]]) -> None:
    evidence, _, _ = split_record(record_fixtures[0])
    other = PageImage(media_type="image/jpeg", data=b"\xff\xd8other")
    assert fingerprint(Payload.from_evidence(evidence, images=[PICTURE])) != fingerprint(
        Payload.from_evidence(evidence, images=[other])
    )
```

(`_photograph_reading()` returns the `transcribed`/`photograph` reading `tests/test_runner.py` builds; import `probable_cause` from `ntsb_probable_cause.fields`. `lambda *a: drawn.append(1) or PICTURE` records a call and returns the picture; mypy accepts it because `append` returns `None`.)

Append to `tests/test_report.py`:

```python
def test_image_summary_counts_pictures_and_cases_cut_short(case_result: CaseResult) -> None:
    rows = [case_result.model_copy(update={"images_sent": 2, "images_not_sent": 1}), case_result]
    assert report.image_summary(rows) == (
        "pictures: 2 sent to 1 of 2 cases; 1 cases cut short by the cap (decision 0082 item 4)"
    )
```

and, in `tests/test_eval_app.py`, a v3 run folder with one `unguarded_images` case: `report` prints `without the unguarded_images cases (decision 0082 item 3):` followed by a table whose `all` row has one fewer case.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_runner.py tests/test_boundary.py tests/test_report.py -v -k "v3 or picture or image"`
Expected: FAIL.

- [ ] **Step 3: Implement**

`scoring/runner.py`:

```python
# Spec §10.1: the page kinds that go to the agent as pictures in v3. Text pages stay text:
# the agent's model reads handwriting worse than the transcriber (spec §7.1), and the guard
# could not check a picture of text.
PICTURE_KINDS = frozenset({"photograph", "diagram or chart", "mixed"})
# GPT-6 Luna's prompt tokens per page image at RESOLUTION, measured on the transcriber test's
# photograph pages (S2.6 Task 13 Step 12, docs/results/s26-transcriber-test.txt).
IMAGE_TOKENS_ESTIMATE = <the measured value>


def picture_pages(docket: Docket, attached: Sequence[int]) -> list[tuple[int, int, bool]]:
    """``(document, page, unguarded)`` for every page v3 shows as a picture, in order."""
    chosen: list[tuple[int, int, bool]] = []
    for index in attached:
        for page, reading in sorted(docket.readings.get(index, {}).items()):
            if reading.status == "transcribed" and reading.page_kind in PICTURE_KINDS:
                chosen.append((index, page, False))
            elif reading.status == "failed":
                chosen.append((index, page, True))
    return chosen
```

`estimated_cost_usd` gains `*, images: int = 0` and adds `images * IMAGE_TOKENS_ESTIMATE` to `prompt_tokens`; `over_cap` passes it through. `prepare_case` gains `picture: Callable[[int, int, int], PageImage] | None = None`; at the end of its arm B branch, before building `Prepared`:

```python
    images: list[PageImage] = []
    not_sent = 0
    if spec.evidence_version == "v3":
        if picture is None:
            raise ConfigurationError("a v3 run needs a reader that can draw pictures")
        candidates = picture_pages(docket, attached)
        unguarded = 0
        for position, (index, page, is_unguarded) in enumerate(candidates):
            if over_cap(payload.text, system, spec, images=len(images) + 1):
                not_sent = len(candidates) - position
                break
            images.append(picture(docket.mkey, index, page))
            unguarded += is_unguarded
        if unguarded:
            mark = CaseMark(kind="unguarded_images", count=unguarded)
            evidence = evidence.model_copy(update={"marks": (*evidence.marks, mark)})
        payload = Payload.from_evidence(evidence, images=images)
```

`Prepared` and `_CaseContext` gain `images_sent`/`images_not_sent`, copied into `CaseResult`. The case's own over-cap check (`_answer_case`) passes `images=len(prepared.payload.images)`.

`Runner.run`: replace the v3 refusal with

```python
        if spec.evidence_version == "v3" and (
            spec.arm != "B" or not spec.sync or spec.price_variant != "standard"
        ):
            raise ConfigurationError(
                "a v3 run is arm B, --sync, --price-variant standard: its pictures cannot go "
                "through the batch service (S2.6 decision W1)"
            )
```

and pass `picture=self._docket.picture` into `prepare_case` from `_prepare` when the version is v3 (`DocketReader` gains `picture`, implemented by `CachedDocketReader` with a `CachedDocuments` over its client and `render_pages(...)[0]` into a `PageImage(media_type=MEDIA_TYPE, data=...)`). A v3 run uses the v2 reader (`wanted = "v2"` for both).

`scoring/records.py`: `fingerprint` hashes `payload.text` and, when present, each image's `sha256` in order, so two payloads differing only in a picture differ.

`scoring/report.py`:

```python
def image_summary(results: Sequence[CaseResult]) -> str:
    """How many pictures reached the agent, and how many cases the cap cut short (0082 item 4)."""
    sent = sum(r.images_sent for r in results)
    cut = sum(1 for r in results if r.images_not_sent)
    with_pictures = sum(1 for r in results if r.images_sent)
    return (
        f"pictures: {sent} sent to {with_pictures} of {len(results)} cases; {cut} cases cut "
        "short by the cap (decision 0082 item 4)"
    )
```

and `apps/eval/__main__.py`'s `_cmd_report`, for a v3 run: append `image_summary(cases)` and, when any case carries `unguarded_images`, `"without the unguarded_images cases (decision 0082 item 3):\n" + summarise([r for r in cases if not any(m.kind == "unguarded_images" for m in r.marks)], floor=floor)`.

- [ ] **Step 4: Run the tests, then the whole check; commit**

Run: the Step 2 command, then `make check`. Expected: PASS; green.

```bash
git add src/ apps/eval/__main__.py tests/ docs/plans/2026-09-23-s26-widened-docket.md
git commit -m "S2.6: v3 -- pictures alongside the text, up to the cap; unguarded pictures marked (0082)"
```

---

### Task 17: Does seeing the pictures help? The v3 probe on `dev-400` (spec §10; Andy runs; paid)

- [ ] **Step 1: The target**

```make
s26-v3-probe:
	uv run ntsb-eval run --arm B --sample dev-400 --evidence-version v2 --sync --price-variant standard --expected-cost-per-case-usd $(PER_CASE)
	uv run ntsb-eval run --arm B --sample dev-400 --evidence-version v3 --sync --price-variant standard --expected-cost-per-case-usd $(PER_CASE_V3)
# S2.6 spec §10, decision W5: B-v2 and B-v3 both on the standard path, so the pictures are the
# only difference. Development only, not a bar. Sync runs are one case at a time: hours each.
```

Commit it.

- [ ] **Step 2: STOP — Andy runs the probe** (about $6–10 in all at standard prices, estimate: B-v2 at twice its batch cost, and B-v3 with its pictures; about 2–4 hours each, one case at a time)

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
export OPENROUTER_API_KEY="$(pass show api/openrouter)"
git status --short   # must be empty
make s26-v3-probe PER_CASE=<2 x Task 15's B-v2 cost per case, rounded up> PER_CASE_V3=<Task 13's v3 per-case estimate, rounded up>
```

The tree is unchanged afterwards. If the month's budget refuses the second run, wait for the next month or ask Andy (decision 0083).

- [ ] **Step 3: The results file**

```bash
{
  uv run ntsb-eval report <B-v3 run id> --against <standard B-v2 run id> --versions-compared; echo
  echo "noise floor (decision W5): the same B-v2 evidence, standard path against batch"
  uv run ntsb-eval report <standard B-v2 run id> --against <Task 15's batch B-v2 run id>
} > docs/results/s26-v3-probe-dev.txt
```

Expected: the v3 table, its unmarked and marked rows, the table without `unguarded_images` cases, the picture line and the paired difference; then the noise floor: the standard B-v2 against the batch B-v2, same evidence version and model, whose paired difference is chance and transport alone. A v3 difference inside that floor is reported as no effect. Commit (`S2.6: the v3 probe on dev-400 (spec §10)`).

- [ ] **Step 4: STOP — report to Andy**, including what it settles for S3 (spec §10.6): a real gain gives S3's loop an image tool and a B-v3 comparison; none keeps S3 on v2. Whether v3 ever runs on held-out is Andy's decision here, recorded in Deviations.

---

### Task 18: The new bar — B-v1 and B-v2 on `heldout-400`, once each (spec §9.3; Andy runs; paid)

**Files:**
- Modify: `Makefile` (+ `s26-transcribe-heldout`, `s26-bars-v1`, `s26-bars-v2` — one held-out run per recipe)
- Create: `docs/results/s26-bars.txt`
- Modify: `docs/results/heldout-ledger.md` (two rows, appended by the runs, into the versioned table of Task 8)

- [ ] **Step 1: The targets**

```make
s26-transcribe-heldout:
	uv run ntsb-eval transcribe --sample heldout-400 --expected-cost-per-page-usd $(PER_PAGE) --dry-run
	uv run ntsb-eval transcribe --sample heldout-400 --expected-cost-per-page-usd $(PER_PAGE)
# S2.6 spec §9.3: counts and cost only are printed; no held-out page is seen by a person.

s26-bars-v1:
	uv run ntsb-eval run --arm B --sample heldout-400 --evidence-version v1 --expected-cost-per-case-usd $(PER_CASE)
# ONCE. Appends a ledger row: commit that row before s26-bars-v2, or the held-out guard refuses it.

s26-bars-v2:
	uv run ntsb-eval run --arm B --sample heldout-400 --evidence-version v2 --expected-cost-per-case-usd $(PER_CASE)
# ONCE, after s26-bars-v1's ledger row is committed.
```

Commit them.

- [ ] **Step 2: STOP — Andy transcribes `heldout-400`** (estimated, not counted, until the dry run's first line replaces the estimate; about 1–3 hours)

```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
export OPENROUTER_API_KEY="$(pass show api/openrouter)"
make s26-transcribe-heldout PER_PAGE=<as in Task 15>
```

The dry run prints the page count and projected cost first. If the projection is more than a quarter over Task 13's estimate, or the month cannot hold it, stop and ask Andy. Afterwards the tree is unchanged.

- [ ] **Step 3: STOP — Andy runs B-v1 on held-out** (about $1–2, estimate; 30–90 minutes)

`git status --short` must be empty and `make check` green. Then `make s26-bars-v1 PER_CASE=<value>`. Afterwards the tree has **one** change: a new row in `docs/results/heldout-ledger.md`. Commit it alone:

```bash
git add docs/results/heldout-ledger.md
git commit -m "S2.6: ledger row for B-v1 on heldout-400"
```

- [ ] **Step 4: STOP — Andy runs B-v2 on held-out** (about $1–2, estimate; 30–90 minutes)

`git status --short` must be empty. Then `make s26-bars-v2 PER_CASE=<value>`. Afterwards the tree again has one change, the second ledger row; commit it the same way. The two runs sit on commits that differ only by the first ledger row, so the code is one commit's (the S2.4 precedent, recorded in Deviations).

- [ ] **Step 5: The results file**

```bash
{
  uv run ntsb-eval report <held-out B-v2 id> --against <held-out B-v1 id> --versions-compared; echo
  uv run ntsb-eval report <held-out B-v1 id> --against <S2.4's held-out arm B id, from docs/results/s24-bars.txt>; echo
  uv run ntsb-eval report <held-out B-v2 id> --against <S2.4's held-out ceiling id, from docs/results/s24-bars.txt>
} > docs/results/s26-bars.txt
```

Expected: B-v2 against B-v1 (the transcription effect on held-out); B-v1 against S2.4's B-v1 (what the marks changed: S2.4's refused cases are answered here and appear in the marked rows); B-v2 against the ceiling; and the `Baseline floor` line every `heldout-400` report prints. Commit (`S2.6: B-v1 and B-v2 on heldout-400; B-v2 is the bar for S3 (spec §9.3)`).

- [ ] **Step 6: STOP — report to Andy**: the new bar, in plain words, beside S2.4's, with the marked groups and what they show. B-v2 is the bar S3's loop must beat, on v2 (spec §9.3).

---

### Task 19: Close-out (decision 0017)

- [ ] **Step 1: Documentation**

`CLAUDE.md`, appended rather than rewritten:
- "Eval bars to beat": an S2.6 paragraph with B-v1 and B-v2 on `heldout-400` copied from `docs/results/s26-bars.txt` (top-1, top-3, finding recall@10, with intervals; the paired B-v2 − B-v1 difference; the marked groups), stating that B-v2 is S3's bar on v2, and the S2.4 figures left in place.
- "Required components": the docket client now also renders pages (`docket/render.py`) and reads transcriptions (`docket/transcribe.py`, v2); the evidence-version axis (0076); marks (0077, 0078, 0082).
- "Commands": `make page-kinds`, `make analysis-handcheck`, the `s26-*` targets, `ntsb-eval transcribe`, `run --evidence-version`, `report --versions-compared`; settings `NTSB_TRANSCRIPTION_DIR`.
- The top-level `../CLAUDE.md` goal 4 already carries the 2026-09-23 amendment pointing at 0074; confirm, do not repeat it.

`README.md`: the same commands.

- [ ] **Step 2: Run the close-stage skill**

Invoke `close-stage`: As-built record (Delivered; Done means, one line per spec §15 item with its evidence; Departures, from the Deviations below; Decisions taken: the transcriber decision and any Andy took in the walkthrough; Implementation record with the stage's total spend from the spend rows and the S2.6 runs), specification marked Implemented, the roadmap's S2.6 entry marked done, this plan deleted, `scripts/check_docs.py` passing. `version` in `pyproject.toml`: the next minor above `main`'s at merge time.

- [ ] **Step 3: Pull request**

S2.6 sits on `s25-recorder`, so its pull request can merge only after S2.5's. If S2.5 has merged: merge `main` into the branch, `make check`, and open `S2.6: the widened docket` against `main`. If not: open it as a draft against `s25-recorder`'s successor on `main` once that lands, and tell Andy. Merge with a merge commit, never squash (0033). After the merge Andy runs `gh release create v<version> --generate-notes`.

---

## Deviations

*Log every departure from the specification here, dated, with the reason. Moved into the As-built record at close-out (decision 0017).*

- 2026-09-24, plan: **images cannot use the batch service** (OpenRouter batch documentation, read 2026-09-24). The spec's transcription, inventory and v3 costs assumed batch prices; every image call runs synchronously at the standard price, twice the batch price. Stage estimate $26–46 instead of $17–27. Andy chose this (W1, 2026-09-24).
- 2026-09-24, plan: the transcription cache is keyed by the **document's content hash and page number** in place of the page image's hash (spec §8.3); the image hash is stored in each record. Same identity (rendering is repeatable, checked while planning), and a run can find a page's reading without drawing it.
- 2026-09-24, plan: spec §4.4's "the case's log line" is the case's row in the run's `cases.jsonl`: the runner writes no per-case log line, only batch progress lines. Marks are on `CaseResult.marks`.
- 2026-09-24, plan: the held-out ledger's version column is a new table appended below the existing rows, headed "From S2.6", because a markdown table cannot gain a column for new rows only. The rows above it are read as v1 (0076 item 4).
- 2026-09-24, plan: the renderer's test pages are built in the tests with Pillow and pypdf, not committed real pages (spec §12). Andy chose this (W4, 2026-09-24).
- 2026-09-24, plan: "the cheapest" candidate (spec §7.4 item 2) is judged by **measured cost per test page**, which counts each model's real token use, rather than list price; a model that writes twice the tokens at the same price is not cheaper.
- 2026-09-24, plan: the inventory's §6.4 stop rule has a number — under 10% of image-bearing pages with words in their images — and mixed pages are chosen by an image-area cut-off with a rule fixed in advance. Andy decided both (W3 and W6, 2026-09-24).
- 2026-09-24, plan: the recorded transcriber replies (spec §12) are of an invented page drawn in code, so a committed fixture carries no docket text.
- 2026-09-24, plan (checked, no change): pypdf warns that it needs `fontTools` to decode some fonts, and the project does not install it. An ad-hoc check over every `dev-400` PDF found 686 pages in 44 documents that warn; with `fontTools` installed, 20 of them extract differently, and the share of their words in the vendored word list is the same (78.9% either way; 4 pages under 20% either way). S2's text layer is not materially garbled, so no dependency is added.
- 2026-09-24, Task 1 Step 10: `scripts.page_kinds`'s scripted count on `dev-400` (401 cases, 3,516 cached PDFs, 8 not a PDF, 0 fetch failures, 0 no-cached-listing) differs slightly from the design session's ad-hoc four-kind totals (spec §1): text only 5,005 against 5,006 (-1), image only 3,274 against 3,281 (-7), text and image 8,402 against 8,403 (-1), blank 109 against 109 (exact). The image-only breakdown (spec §5.2) differs more: rotated 527 against 527 (exact), 5+ images (tiled) 201 against 200 (+1), fax (CCITT) 883 against 929 (-46), JPEG 2000 60 against 250 (-190), JBIG2 42 against 54 (-12). Measured, not guessed (fix round 1, throwaway script under `/Users/floyda/.claude/jobs/95263328/tmp/chain_encoding_probe.py`, not in the repo): a chained `/Filter` array is not the explanation. Over the same 3,274 image-only pages, counting each of the three encodings both by `_encoding`'s own rule (the *last* filter in the chain) and by "anywhere in the chain" gives identical totals either way -- fax (CCITT) 883/883, JPEG 2000 60/60, JBIG2 42/42 -- and only 8 of the 3,274 pages have an image with more than one filter in its `/Filter` array at all. So the gap against the ad-hoc figures is not a last-vs-first convention difference; its real cause is still unknown (candidates not checked: a different page or document set, per-image rather than per-page counting, or a bug in the uncommitted ad-hoc script), and is not chased further here. Per the brief, the scripted numbers in `docs/results/s26-page-kinds.txt` stand and are what later tasks and the As-built record cite; the design-session figures in spec §1 and §5.2 are not corrected in place (the spec is amended separately if needed). Additionally, `--include-photo-only` fetched and read all 146 of the 146 photo-only PDFs the ad-hoc count found (831 declared pages; 831 pages read, split 48/322/460/1 by kind), with 0 fetch failures, matching decision W2's count exactly.
