"""CachedDocuments: documents read from the docket cache only, by case and listing index."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from tests.pdf_builder import PageSpec, build_pdf

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.documents import CachedDocuments
from ntsb_probable_cause.errors import DocketError

FIXTURE = Path("tests/fixtures/docket/ERA17LA217")
MKEY = 95459


def _refuse() -> httpx.BaseTransport:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline: documents come from the cache only")

    return httpx.MockTransport(refuse)


def _build_cache(tmp_path: Path) -> tuple[Path, bytes]:
    """One case in ``DocketClient``'s on-disk layout: a cached listing and one document."""
    cache = tmp_path / "docket"
    folder = cache / str(MKEY)
    folder.mkdir(parents=True)
    listing_html = (FIXTURE / "listing.html").read_text()
    (folder / "listing.html").write_text(listing_html)
    document = build_pdf([PageSpec(text="Engine sputtered at 800 ft.")])
    (folder / "1.bin").write_bytes(document)
    href = (
        "/Docket/Document/docBLOB?ID=40469808&FileExtension=.PDF"
        "&FileName=Pilot%2FOperator%20Aircraft%20Accident%20Report,"
        "%20NTSB%20Form%206120.1-Master.PDF"
    )
    fetch = {
        "listing": {
            "time": "2026-09-24T00:00:00+00:00",
            "sha256": hashlib.sha256(listing_html.encode("utf-8")).hexdigest(),
        },
        "documents": {
            "1": {
                "time": "2026-09-24T00:00:00+00:00",
                "sha256": hashlib.sha256(document).hexdigest(),
                "href": href,
            }
        },
    }
    (folder / "fetch.json").write_text(json.dumps(fetch))
    return cache, document


def test_document_and_loader_read_the_cached_bytes(tmp_path: Path) -> None:
    cache, document = _build_cache(tmp_path)
    client = DocketClient(cache, transport=_refuse())
    documents = CachedDocuments(client)
    assert documents.document(MKEY, 1) == document
    assert documents.loader(MKEY, 1)() == document


def test_a_missing_index_raises(tmp_path: Path) -> None:
    cache, _ = _build_cache(tmp_path)
    client = DocketClient(cache, transport=_refuse())
    documents = CachedDocuments(client)
    with pytest.raises(DocketError):
        documents.document(MKEY, 99)
