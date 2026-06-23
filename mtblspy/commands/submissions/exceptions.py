class SubmissionError(RuntimeError):
    """Base exception for reusable submission workflow errors."""


class AuthenticationError(SubmissionError):
    """Raised when an authenticated submission workflow has no API token."""


class SubmissionAPIError(SubmissionError):
    """Raised when the MetaboLights API returns an error payload."""

