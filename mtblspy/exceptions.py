class SubmissionError(RuntimeError):
    """Base exception for reusable submission workflow errors."""


class AuthenticationError(SubmissionError):
    """Authentication or automatic session refresh failed."""


class SubmissionAPIError(SubmissionError):
    """Raised when the MetaboLights API returns an error payload."""

    def __init__(self, message, errors=None):
        super().__init__(message)
        self.errors = list(errors or [])
