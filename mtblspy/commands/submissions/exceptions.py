class SubmissionError(RuntimeError):
    """Base exception for reusable submission workflow errors."""


class AuthenticationError(SubmissionError):
    """Raised when an authenticated submission workflow has no API token."""


class SubmissionAPIError(SubmissionError):
    """Raised when the MetaboLights API returns an error payload."""

    def __init__(self, message, errors=None):
        super().__init__(message)
        self.errors = list(errors or [])
