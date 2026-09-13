"""Exception hierarchy for the library."""


class NtsbError(Exception):
    """Base class for every error this library raises."""


class ConfigurationError(NtsbError):
    """A required setting, such as an API key, is missing or invalid."""


class ApiError(NtsbError):
    """The NTSB API returned an unusable response after retries."""


class ManifestError(NtsbError):
    """The raw-data manifest is missing, malformed, or disagrees with the files."""


class FixtureError(NtsbError):
    """A fixture would break the fixture policy (decision 0015)."""


class LeakageError(NtsbError):
    """Withheld synthesis or verdict content reached evidence (decision 0016)."""
