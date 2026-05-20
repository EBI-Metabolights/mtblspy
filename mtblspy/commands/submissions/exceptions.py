class SubmissionError(RuntimeError):
    """Base exception for reusable submission workflow errors."""


class AuthenticationError(SubmissionError):
    """Raised when an authenticated submission workflow has no API token."""


class SubmissionAPIError(SubmissionError):
    """Raised when the MetaboLights API returns an error payload."""


class StudyValidationError(SubmissionError):
    def __init__(self, study_id, errors):
        self.study_id = study_id
        self.errors = errors
        super().__init__(f"Study {study_id} has {len(errors)} validation error(s).")
