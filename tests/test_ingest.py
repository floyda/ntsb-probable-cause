import hashlib
import json
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import apps.ingest.__main__ as cli
import pytest

from ntsb_probable_cause.data.api import Page
from ntsb_probable_cause.data.ingest import (
    Month,
    fetch_months,
    latest_entries,
    manifest_path,
    month_dir,
    months_between,
    read_manifest,
    verify_entry,
)
from ntsb_probable_cause.errors import ManifestError


def page(number: int, ids: list[str], has_more: bool) -> Page:
    content = json.dumps({"hasMore": has_more, "data": [{"ntsbNumber": i} for i in ids]}).encode()
    return Page(
        number, content, tuple({"ntsbNumber": i} for i in ids), has_more, "m" if has_more else None
    )


class FakeSource:
    def __init__(self, pages: dict[date, list[Page]], fail_on: date | None = None) -> None:
        self.pages = pages
        self.fail_on = fail_on
        self.calls: list[tuple[date, date]] = []

    def cases_by_date_range(self, start: date, end: date) -> Iterable[Page]:
        self.calls.append((start, end))
        return self._iterate(start)

    def _iterate(self, start: date) -> Iterator[Page]:
        for p in self.pages.get(start, []):
            yield p
            if start == self.fail_on:
                raise RuntimeError("connection dropped")


def clock(*stamps: str) -> Iterator[datetime]:
    return iter(datetime.fromisoformat(s).replace(tzinfo=UTC) for s in stamps)


def test_months_between_includes_both_ends_and_leap_february() -> None:
    months = months_between("2019-11", "2020-02")
    assert [m.label for m in months] == ["2019-11", "2019-12", "2020-01", "2020-02"]
    assert months[-1].start == date(2020, 2, 1)
    assert months[-1].end == date(2020, 2, 29)


def test_month_parse_rejects_bad_text() -> None:
    with pytest.raises(ValueError, match="YYYY-MM"):
        Month.parse("2020-13")


def test_months_between_rejects_reversed_range() -> None:
    with pytest.raises(ValueError, match=r"2019-11.*2020-02"):
        months_between("2020-02", "2019-11")


def test_fetch_writes_pages_verbatim_and_a_manifest_line(tmp_path: Path) -> None:
    pages = [page(1, ["A", "B"], True), page(2, ["C"], False)]
    source = FakeSource({date(2016, 8, 1): pages})
    ticks = clock("2026-09-13T10:00:00")
    (entry,) = fetch_months(source, [Month(2016, 8)], tmp_path, now=lambda: next(ticks))
    directory = month_dir(tmp_path, "2016-08")
    assert (directory / "page-01.json").read_bytes() == pages[0].content
    assert (directory / "page-02.json").read_bytes() == pages[1].content
    assert entry.records == 3
    assert entry.pages[0].sha256 == hashlib.sha256(pages[0].content).hexdigest()
    assert entry.start == "2016-08-01"
    assert entry.end == "2016-08-31"
    assert read_manifest(tmp_path) == [entry]
    verify_entry(tmp_path, entry)


def test_months_in_manifest_are_skipped(tmp_path: Path) -> None:
    source = FakeSource({date(2016, 8, 1): [page(1, ["A"], False)]})
    fetch_months(source, [Month(2016, 8)], tmp_path)
    assert fetch_months(source, [Month(2016, 8)], tmp_path) == []
    assert len(source.calls) == 1


def test_refresh_refetches_and_latest_entry_wins(tmp_path: Path) -> None:
    source = FakeSource({date(2016, 8, 1): [page(1, ["A"], False)]})
    ticks = clock("2026-09-13T10:00:00", "2026-09-14T10:00:00")
    fetch_months(source, [Month(2016, 8)], tmp_path, now=lambda: next(ticks))
    source.pages[date(2016, 8, 1)] = [page(1, ["A", "B"], False)]
    fetch_months(source, [Month(2016, 8)], tmp_path, refresh=True, now=lambda: next(ticks))
    entries = read_manifest(tmp_path)
    assert len(entries) == 2
    assert latest_entries(entries)["2016-08"].records == 2
    verify_entry(tmp_path, latest_entries(entries)["2016-08"])


def test_interrupted_month_leaves_no_manifest_line_and_resumes(tmp_path: Path) -> None:
    source = FakeSource(
        {date(2016, 8, 1): [page(1, ["A"], True), page(2, ["B"], False)]}, fail_on=date(2016, 8, 1)
    )
    with pytest.raises(RuntimeError):
        fetch_months(source, [Month(2016, 8)], tmp_path)
    assert not manifest_path(tmp_path).exists()
    assert not month_dir(tmp_path, "2016-08").exists()
    source.fail_on = None
    (entry,) = fetch_months(source, [Month(2016, 8)], tmp_path)
    assert entry.records == 2


def test_verify_detects_changed_file(tmp_path: Path) -> None:
    source = FakeSource({date(2016, 8, 1): [page(1, ["A"], False)]})
    (entry,) = fetch_months(source, [Month(2016, 8)], tmp_path)
    (month_dir(tmp_path, "2016-08") / "page-01.json").write_bytes(b"{}")
    with pytest.raises(ManifestError, match="sha256"):
        verify_entry(tmp_path, entry)


def test_verify_detects_missing_file(tmp_path: Path) -> None:
    source = FakeSource({date(2016, 8, 1): [page(1, ["A"], False)]})
    (entry,) = fetch_months(source, [Month(2016, 8)], tmp_path)
    (month_dir(tmp_path, "2016-08") / "page-01.json").unlink()
    with pytest.raises(ManifestError, match="missing"):
        verify_entry(tmp_path, entry)


def test_cli_fetch_uses_settings_and_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = FakeSource({date(2016, 8, 1): [page(1, ["A"], False)]})

    class FakeClient(FakeSource):
        def __init__(self, api_key: str, *, requests_per_minute: int) -> None:
            super().__init__(source.pages)
            assert (api_key, requests_per_minute) == ("k", 30)

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setenv("NTSB_API_KEY", "k")
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli, "NtsbClient", FakeClient)
    assert cli.main(["fetch", "2016-08", "2016-08"]) == 0
    assert len(read_manifest(tmp_path / "raw")) == 1
