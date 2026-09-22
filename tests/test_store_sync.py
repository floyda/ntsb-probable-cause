"""Pull/push the SQLite store between a location and a local working file (Task 10)."""

from pathlib import Path

import pytest

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.store.sync import (
    Location,
    ObjectNotFoundError,
    S3Like,
    _is_missing_object_response,
    pull,
    push,
    s3_client,
)


def test_local_location_is_not_s3() -> None:
    assert Location("data/r.sqlite").is_s3 is False


def test_s3_location_is_s3() -> None:
    assert Location("s3://b/k").is_s3 is True


def test_bucket_key_splits_bucket_and_key() -> None:
    assert Location("s3://b/k").bucket_key() == ("b", "k")


def test_bucket_key_keeps_slashes_inside_the_key() -> None:
    assert Location("s3://bucket/prefix/recorder.sqlite").bucket_key() == (
        "bucket",
        "prefix/recorder.sqlite",
    )


def test_malformed_s3_url_with_no_key_raises() -> None:
    with pytest.raises(ValueError, match="malformed"):
        Location("s3://bucket-only").bucket_key()


def test_bucket_key_on_a_local_location_raises() -> None:
    with pytest.raises(ValueError, match="not an s3"):
        Location("data/r.sqlite").bucket_key()


class _FakeS3:
    """Copies files to/from a tmp directory and records every call (brief, Task 10)."""

    def __init__(self, store_dir: Path, *, missing: bool = False) -> None:
        self.store_dir = store_dir
        self.missing = missing
        self.downloads: list[tuple[str, str, str]] = []
        self.uploads: list[tuple[str, str, str]] = []

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        self.downloads.append((bucket, key, filename))
        source = self.store_dir / bucket / key
        if self.missing or not source.exists():
            raise ObjectNotFoundError(f"s3://{bucket}/{key} not found")
        Path(filename).write_bytes(source.read_bytes())

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self.uploads.append((filename, bucket, key))
        target = self.store_dir / bucket / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(filename).read_bytes())


def test_fake_s3_satisfies_the_protocol(tmp_path: Path) -> None:
    fake: S3Like = _FakeS3(tmp_path)
    assert fake is not None


def test_pull_downloads_from_s3(tmp_path: Path) -> None:
    store_dir = tmp_path / "bucket-store"
    (store_dir / "b").mkdir(parents=True)
    (store_dir / "b" / "k").write_bytes(b"stored bytes")
    fake = _FakeS3(store_dir)
    local = tmp_path / "local.sqlite"

    pull(Location("s3://b/k"), local, s3=fake)

    assert local.read_bytes() == b"stored bytes"
    assert fake.downloads == [("b", "k", str(local))]


def test_pull_missing_object_starts_empty(tmp_path: Path) -> None:
    fake = _FakeS3(tmp_path / "bucket-store", missing=True)
    local = tmp_path / "local.sqlite"

    pull(Location("s3://b/k"), local, s3=fake)  # does not raise

    assert not local.exists()
    assert fake.downloads == [("b", "k", str(local))]


def test_push_uploads_to_s3(tmp_path: Path) -> None:
    local = tmp_path / "local.sqlite"
    local.write_bytes(b"night's rows")
    fake = _FakeS3(tmp_path / "bucket-store")

    push(local, Location("s3://b/k"), s3=fake)

    assert (tmp_path / "bucket-store" / "b" / "k").read_bytes() == b"night's rows"
    assert fake.uploads == [(str(local), "b", "k")]


def test_pull_local_location_is_a_no_op(tmp_path: Path) -> None:
    local = tmp_path / "recorder.sqlite"
    fake = _FakeS3(tmp_path / "bucket-store")

    pull(Location(str(local)), local, s3=fake)

    assert fake.downloads == []
    assert not local.exists()  # local IS the store; nothing is created here


def test_push_local_location_is_a_no_op(tmp_path: Path) -> None:
    local = tmp_path / "recorder.sqlite"
    local.write_bytes(b"rows")
    fake = _FakeS3(tmp_path / "bucket-store")

    push(local, Location(str(local)), s3=fake)

    assert fake.uploads == []


def test_s3_client_raises_configuration_error_without_boto3() -> None:
    # boto3 is an optional extra (controller note 3) never installed in the test environment,
    # so calling s3_client() for real must fail loudly with a clear message, not an ImportError.
    with pytest.raises(ConfigurationError, match="boto3"):
        s3_client()


class _RealFailureS3:
    """An S3Like whose download fails for a reason that is NOT "object missing" (fix round 1,
    Minor 1): a permissions error, a network error -- anything else a real client can raise."""

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        raise RuntimeError("access denied")

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        raise AssertionError("not exercised in this test")


def test_pull_propagates_a_real_failure_rather_than_starting_empty(tmp_path: Path) -> None:
    """Only a missing object (ObjectNotFoundError) reads as "start empty" -- every other pull
    failure must propagate, never be silently absorbed as if the store were merely new."""
    local = tmp_path / "local.sqlite"

    with pytest.raises(RuntimeError, match="access denied"):
        pull(Location("s3://b/k"), local, s3=_RealFailureS3())

    assert not local.exists()


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"Error": {"Code": "404"}}, True),
        ({"Error": {"Code": "NoSuchKey"}}, True),
        ({"Error": {"Code": "403"}}, False),
        ({"Error": {"Code": "AccessDenied"}}, False),
        ({}, False),
        ({"Error": {}}, False),
        ("not even a dict", False),
    ],
)
def test_is_missing_object_response_translates_the_boto3_error_shape(
    response: object, expected: bool
) -> None:
    """The 404/NoSuchKey -> ObjectNotFoundError translation, exercised on the plain dict shape
    a boto3 ClientError's `.response` carries -- no `boto3`/`botocore` import anywhere here
    (fix round 1, Minor 1). `_BotoS3.download_file`'s own `except ClientError` clause, which
    needs the real exception type to match, is the one part of this translation that cannot be
    reached without boto3 installed; this test covers the actual code-to-outcome decision that
    clause delegates to, which is the part that can silently regress."""
    assert _is_missing_object_response(response) is expected


def test_pull_removes_a_stale_local_file_and_its_wal_shm_before_downloading(
    tmp_path: Path,
) -> None:
    """Fix round 1, Minor 2: a previous run that died before push can leave a stale work file,
    or a stale -wal/-shm next to one, on disk. A fresh pull must never build on top of it."""
    store_dir = tmp_path / "bucket-store"
    (store_dir / "b").mkdir(parents=True)
    (store_dir / "b" / "k").write_bytes(b"fresh bytes from s3")
    local = tmp_path / "local.sqlite"
    local.write_bytes(b"stale main file from a dead run")
    local.with_name("local.sqlite-wal").write_bytes(b"stale wal")
    local.with_name("local.sqlite-shm").write_bytes(b"stale shm")
    local.with_name("local.sqlite-journal").write_bytes(b"stale journal")
    fake = _FakeS3(store_dir)

    pull(Location("s3://b/k"), local, s3=fake)

    assert local.read_bytes() == b"fresh bytes from s3"
    assert not local.with_name("local.sqlite-wal").exists()
    assert not local.with_name("local.sqlite-shm").exists()
    assert not local.with_name("local.sqlite-journal").exists()


def test_pull_removes_stale_side_files_even_when_the_object_is_missing(tmp_path: Path) -> None:
    """The same cleanup applies on the "start empty" path -- a stale WAL must not survive to
    sit next to an absent main file either."""
    local = tmp_path / "local.sqlite"
    local.write_bytes(b"stale main file from a dead run")
    local.with_name("local.sqlite-wal").write_bytes(b"stale wal")
    fake = _FakeS3(tmp_path / "bucket-store", missing=True)

    pull(Location("s3://b/k"), local, s3=fake)

    assert not local.exists()
    assert not local.with_name("local.sqlite-wal").exists()
