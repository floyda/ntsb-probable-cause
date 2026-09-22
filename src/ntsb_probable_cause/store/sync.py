"""Pull/push the SQLite store between a location and a local working file (spec S2.5 §9.3, Task 10).

A :class:`Location` is one string: a local path, or an ``s3://bucket/key`` URL. For a local
location, the local path *is* the store -- :func:`pull` and :func:`push` are no-ops, and
``apps/recorder`` opens :class:`~ntsb_probable_cause.store.Store` directly at that path. For an
``s3://`` location, the store opens at a temporary working file under ``NTSB_DATA_DIR`` (never
a path relative to the process's working directory -- see ``settings.py``'s note on
``docket_dir`` for why a relative path here is dangerous, not merely untidy): :func:`pull`
downloads the object there before the night starts, and :func:`push` uploads it back after
``Store.close()`` has checkpointed the WAL, so the uploaded file is always complete.

``boto3`` is behind the optional ``aws`` extra (controller note 3) and is imported lazily, only
by :func:`s3_client`, so importing this module -- and running the test suite, which never
installs that extra -- never requires it. Tests exercise :func:`pull`/:func:`push` entirely
through the ``s3`` keyword, with a fake :class:`S3Like` that never touches AWS.
"""

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from ntsb_probable_cause.errors import ConfigurationError

_S3_PREFIX = "s3://"

# boto3's own error codes for "no such object": "NoSuchKey" from the object API, "404" from the
# HEAD request `download_file` issues first to size the transfer. Named here, not inline, so
# the one place that reads them (`s3_client`'s adapter, below) states the intent plainly.
_MISSING_OBJECT_CODES = frozenset({"404", "NoSuchKey"})


class ObjectNotFoundError(Exception):
    """Raised by an :class:`S3Like` implementation's ``download_file`` for a missing object.

    :func:`pull` reads this as "first run: start empty", not a failure. It is the hook
    controller note 3 asks for: a test fake raises it directly to simulate a missing object, so
    no real boto3/botocore error type is ever needed to exercise that path.
    """


class Location(BaseModel, frozen=True):
    """Where the store's file lives, as one string: a local path or an ``s3://bucket/key`` URL.

    A plain ``str`` field, not a richer union, because the value round-trips verbatim through
    :attr:`~ntsb_probable_cause.settings.Settings.store` (``str``, not ``Path``, for the same
    reason -- see that field's own comment: ``Path("s3://b/k")`` silently collapses the double
    slash after the scheme) and because the two shapes are told apart by one prefix check, not
    by parsing.
    """

    raw: str

    def __init__(self, raw: str) -> None:
        super().__init__(raw=raw)

    @property
    def is_s3(self) -> bool:
        """Whether this location names an S3 object rather than a local path."""
        return self.raw.startswith(_S3_PREFIX)

    def bucket_key(self) -> tuple[str, str]:
        """The bucket and key an ``s3://bucket/key`` location names.

        Raises ``ValueError`` for a non-``s3://`` location, or one with no key at all (e.g.
        ``s3://bucket``) -- a location that names a bucket alone is never a valid store target.
        """
        if not self.is_s3:
            raise ValueError(f"not an s3:// location: {self.raw!r}")
        bucket, _, key = self.raw[len(_S3_PREFIX) :].partition("/")
        if not bucket or not key:
            raise ValueError(f"malformed s3:// location (need s3://bucket/key): {self.raw!r}")
        return bucket, key


class S3Like(Protocol):
    """The two boto3 S3 client methods this module needs -- narrow enough for a test fake."""

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        """Download ``bucket``/``key`` to ``filename``; raise on a missing object (module note)."""
        ...

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        """Upload ``filename`` to ``bucket``/``key``, replacing any existing object."""
        ...


def pull(location: Location, local: Path, *, s3: S3Like | None = None) -> None:
    """Copy the store from ``location`` to ``local``; a no-op for a local location.

    A missing S3 object (:class:`ObjectNotFoundError`) means first run: ``local`` is left absent,
    and the caller's ``Store(local).migrate()`` then creates an empty schema there.
    """
    if not location.is_s3:
        return
    bucket, key = location.bucket_key()
    client = s3 if s3 is not None else s3_client()
    try:
        client.download_file(bucket, key, str(local))
    except ObjectNotFoundError:
        return


def push(local: Path, location: Location, *, s3: S3Like | None = None) -> None:
    """Copy ``local`` to ``location``; a no-op for a local location (it already is the store).

    Call this only after ``Store.close()``: close checkpoints the WAL, so ``local`` is complete
    on disk by the time it is uploaded.
    """
    if not location.is_s3:
        return
    bucket, key = location.bucket_key()
    client = s3 if s3 is not None else s3_client()
    client.upload_file(str(local), bucket, key)


def s3_client() -> S3Like:
    """The real boto3 S3 client, adapted to :class:`S3Like`.

    Imports ``boto3`` lazily -- only this function, called only for a real ``s3://`` store,
    needs it -- so the optional ``aws`` extra (controller note 3) never touches the rest of the
    import graph. Raises :class:`~ntsb_probable_cause.errors.ConfigurationError` if it is not
    installed, rather than letting a bare ``ImportError`` surface from inside a nightly run.
    """
    try:
        # Deliberately not a top-level import (controller note 3): boto3 is the optional `aws`
        # extra, absent from a plain `uv sync`, so importing it must stay confined to this one
        # function, reached only for a real `s3://` store.
        import boto3  # noqa: PLC0415
        from botocore.exceptions import ClientError  # noqa: PLC0415
    except ImportError as error:
        raise ConfigurationError(
            "boto3 is not installed; install the 'aws' extra to use an s3:// store "
            "(uv sync --extra aws)."
        ) from error

    class _BotoS3:
        """Adapts boto3's client to :class:`S3Like`.

        Translates a missing object to :class:`ObjectNotFoundError` so :func:`pull` never needs
        to know about ``botocore``.
        """

        def __init__(self) -> None:
            self._client = boto3.client("s3")

        def download_file(self, bucket: str, key: str, filename: str) -> None:
            try:
                self._client.download_file(bucket, key, filename)
            except ClientError as error:
                code = error.response.get("Error", {}).get("Code")
                if code in _MISSING_OBJECT_CODES:
                    raise ObjectNotFoundError(f"s3://{bucket}/{key} not found") from error
                raise

        def upload_file(self, filename: str, bucket: str, key: str) -> None:
            self._client.upload_file(filename, bucket, key)

    return _BotoS3()
