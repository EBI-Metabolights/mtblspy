import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from mtblspy.config import (
    get_api_key,
    get_base_url,
    get_jwt_token,
    get_refresh_token,
    get_user_name,
    save_config,
    save_jwt_token,
    save_refresh_token,
)
from mtblspy.commands.submissions.exceptions import AuthenticationError, StudyValidationError, SubmissionAPIError
from mtblspy.commands.submissions.models import (
    FtpUploadDetails,
    StudyCreationRequest,
    StudyInputFormat,
    get_default_study_creation_request,
)

VALIDATION_MAX_POLLS = 120
VALIDATION_POLL_INTERVAL_SECONDS = 5
METADATA_UPLOAD_TIMEOUT_SECONDS = 120
DEFAULT_LOCAL_SUBMISSION_CACHE_PATH = Path.home() / "metabolights_data" / "submission" / "cache"
DEFAULT_LOCAL_SUBMISSION_DATA_PATH = Path.home() / "metabolights_data" / "submission" / "data"
DEFAULT_STUDY_INPUT_DATA_FOLDER = DEFAULT_LOCAL_SUBMISSION_DATA_PATH
DEFAULT_STUDY_INPUT_FILE_NAME = "study_input.json"


@dataclass
class ValidationResult:
    report: dict
    errors: list[dict]
    report_path: Path


@dataclass
class StatusUpdateResult:
    study_id: str
    status: str
    response: dict | None = None


@dataclass
class MetadataUploadResult:
    study_id: str
    uploaded_files: list[Path]
    responses: list[Any]


class SubmissionClient:
    def __init__(self, base_url=None, api_token=None):
        self.rest_api_base_url = get_rest_api_base_url(base_url or get_base_url())
        self.submission_api_base_url = get_submission_api_base_url(self.rest_api_base_url)
        self.api_token = api_token

    def get_auth_headers(self):
        api_token = self.require_api_token()
        return {"user-token": api_token}

    def get_submission_headers(self, force_refresh=False):
        jwt_token = None if force_refresh else get_jwt_token(self.submission_api_base_url)
        if not jwt_token and not force_refresh:
            jwt_token = get_jwt_token(self.rest_api_base_url)
        if jwt_token and not force_refresh and not is_jwt_expired(jwt_token):
            return {"accept": "application/json", "Authorization": f"Bearer {jwt_token}"}

        # Try to refresh using a stored refresh token
        refresh_token = get_refresh_token(self.submission_api_base_url)
        if refresh_token:
            new_jwt = self.refresh_jwt_token(refresh_token)
            if new_jwt:
                save_jwt_token(self.submission_api_base_url, new_jwt)
                return {"accept": "application/json", "Authorization": f"Bearer {new_jwt}"}

        # Final fallback: exchange stored api_token for a JWT
        api_token = self.api_token or get_api_key()
        if not api_token:
            raise AuthenticationError(
                "Not logged in. Please run 'mtbls auth login' first."
            )
        jwt_token = self.exchange_api_token_for_jwt(api_token.strip())
        save_jwt_token(self.submission_api_base_url, jwt_token)
        return {"accept": "application/json", "Authorization": f"Bearer {jwt_token}"}

    def exchange_api_token_for_jwt(self, api_token):
        user_name = get_user_name()
        if not user_name:
            raise AuthenticationError(
                "Unable to get JWT token for submission API. "
                "The ws3 auth endpoint requires a user name or email. "
                "Run 'mtbls auth login' or set MTBLS_USER."
            )

        url = f"{self.submission_api_base_url.rstrip('/')}/auth/v1/token"
        errors = []
        try:
            response = requests.post(
                url,
                headers={
                    "accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "password", "username": user_name, "client_secret": api_token},
                timeout=30,
            )
            jwt_token = get_jwt_from_response(response)
            if jwt_token:
                return jwt_token
            errors.append(format_response_error("ws3 auth", response))
        except requests.RequestException as exc:
            errors.append(f"ws3 auth: {exc}")

        keycloak_url = get_keycloak_token_url(self.submission_api_base_url)
        try:
            response = requests.post(
                keycloak_url,
                headers={
                    "accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "client_credentials",
                    "client_id": f"api_user-{user_name}",
                    "client_secret": api_token,
                },
                timeout=30,
            )
            jwt_token = get_jwt_from_response(response)
            if jwt_token:
                return jwt_token
            errors.append(format_response_error("keycloak auth", response))
        except requests.RequestException as exc:
            errors.append(f"keycloak auth: {exc}")

        raise AuthenticationError("Unable to get JWT token for submission API. Attempts failed: " + "; ".join(errors))

    def refresh_jwt_token(self, refresh_token):
        """Attempt to get a new JWT using a refresh token. Returns the new JWT or None on failure."""
        refresh_url = f"{self.submission_api_base_url.rstrip('/')}/auth/v1/refresh"
        try:
            response = requests.post(
                refresh_url,
                headers={
                    "accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "client_id": "swagger-ui-test",
                    "refresh_token": refresh_token,
                },
                timeout=30,
            )
            new_jwt = get_jwt_from_response(response) if response.ok else None
            if new_jwt:
                save_refresh_token_from_response(self.submission_api_base_url, response)
                return new_jwt
        except requests.RequestException:
            pass

        # Fallback: Keycloak refresh
        keycloak_url = get_keycloak_token_url(self.submission_api_base_url)
        try:
            response = requests.post(
                keycloak_url,
                headers={
                    "accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "client_id": "swagger-ui-test",
                    "refresh_token": refresh_token,
                },
                timeout=30,
            )
            new_jwt = get_jwt_from_response(response) if response.ok else None
            if new_jwt:
                save_refresh_token_from_response(self.submission_api_base_url, response)
                return new_jwt
        except requests.RequestException:
            pass

        return None

    def require_api_token(self):
        api_token = self.api_token or get_api_key()
        if not api_token:
            raise AuthenticationError("Not logged in. Please run 'mtbls auth login' first.")
        return api_token.strip()

    def login(self, user_name, password):
        """Perform a full username+password login, fetching an API token and JWT."""
        # 1. Fetch user-token (API token) via POST /auth/login
        login_url = f"{self.rest_api_base_url.rstrip('/')}/auth/login"
        try:
            response = requests.post(
                login_url,
                headers={"accept": "application/json", "Content-Type": "application/json"},
                json={"email": user_name, "secret": password},
                timeout=30,
            )
            response.raise_for_status()
            api_token = get_api_token_from_login_response(response)
        except requests.RequestException as exc:
            message = f"Login failed at {login_url}: {exc}"
            if exc.response is not None:
                message = f"{message}. Response: {get_response_payload(exc.response)}"
            raise AuthenticationError(message) from exc

        # 2. Fetch JWT and refresh tokens via /ws3/auth/v1/token
        token_url = f"{self.submission_api_base_url.rstrip('/')}/auth/v1/token"
        jwt_token = None
        refresh_token = None
        errors = []
        try:
            response = requests.post(
                token_url,
                headers={
                    "accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "password",
                    "username": user_name,
                    "password": password,
                    "client_id": "swagger-ui-test",
                },
                timeout=30,
            )
            response.raise_for_status()
            jwt_token = get_jwt_from_response(response)
            refresh_token = get_refresh_token_from_response(response)
        except Exception as exc:
            errors.append(f"ws3 token auth: {exc}")

        # Fallback to Keycloak direct if ws3 token auth fails
        if not jwt_token:
            keycloak_url = get_keycloak_token_url(self.submission_api_base_url)
            try:
                response = requests.post(
                    keycloak_url,
                    headers={
                        "accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={
                        "grant_type": "password",
                        "username": user_name,
                        "password": password,
                        "client_id": "swagger-ui-test",
                    },
                    timeout=30,
                )
                response.raise_for_status()
                jwt_token = get_jwt_from_response(response)
                refresh_token = get_refresh_token_from_response(response)
            except Exception as exc:
                errors.append(f"keycloak token auth: {exc}")

        if not jwt_token:
            raise AuthenticationError("Unable to fetch JWT token. Attempts failed: " + "; ".join(errors))

        if not api_token:
            api_token = self.fetch_api_token_from_accounts(jwt_token)
            if not api_token:
                raise AuthenticationError(
                    f"Login succeeded but no API token found in response from {login_url} "
                    f"or {self.rest_api_base_url.rstrip('/')}/auth/accounts."
                )

        # 3. Save everything
        save_config(api_key=api_token, base_url=self.rest_api_base_url, user_name=user_name)
        save_jwt_token(self.submission_api_base_url, jwt_token)
        if refresh_token:
            save_refresh_token(self.submission_api_base_url, refresh_token)

    def password_login(self, user_name, password):
        """Backward-compatible alias for username/password login."""
        self.login(user_name, password)

    def fetch_api_token_from_accounts(self, jwt_token):
        accounts_url = f"{self.rest_api_base_url.rstrip('/')}/auth/accounts"
        try:
            response = requests.get(
                accounts_url,
                headers={"accept": "application/json", "Authorization": f"Bearer {jwt_token}"},
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            message = f"Unable to fetch API token from {accounts_url}: {exc}"
            if exc.response is not None:
                message = f"{message}. Response: {get_response_payload(exc.response)}"
            raise AuthenticationError(message) from exc

        return get_api_token_from_login_response(response)

    def verify_api_token(self, api_token):
        response = requests.get(
            f"{self.rest_api_base_url.rstrip('/')}/studies/user",
            headers={"user-token": api_token},
            timeout=10,
        )
        response.raise_for_status()
        return response

    def list_studies(self):
        response = requests.get(
            f"{self.rest_api_base_url.rstrip('/')}/studies/user",
            headers=self.get_auth_headers(),
            timeout=30,
        )
        response.raise_for_status()
        return get_studies_from_user_response(response.json())

    def create_study(self, input_file_path, input_format=StudyInputFormat.JSON):
        request = self.load_study_creation_request(input_file_path, input_format)
        response = requests.post(
            f"{self.rest_api_base_url.rstrip('/')}/provisional-studies",
            headers=self.get_auth_headers(),
            json=request.model_dump(by_alias=True),
            timeout=60,
        )
        response.raise_for_status()
        return response.json()

    def load_study_creation_request(self, input_file_path, input_format=StudyInputFormat.JSON):
        input_format = StudyInputFormat(input_format)
        if input_format is not StudyInputFormat.JSON:
            raise ValueError(f"Unsupported study creation input format: {input_format.value}")

        with Path(input_file_path).open("r", encoding="utf-8") as input_file:
            data = json.load(input_file)
        return StudyCreationRequest.model_validate(data)

    def get_private_ftp_credentials(self, study_id):
        study_id = normalize_study_id(study_id)
        response = requests.get(
            f"{self.rest_api_base_url.rstrip('/')}/studies/{study_id}/upload-info",
            headers=self.get_auth_headers(),
            timeout=30,
        )
        response.raise_for_status()
        return FtpUploadDetails.model_validate(response.json())

    def upload_metadata(self, study_id, metadata_path=None, metadata_files=None):
        study_id = normalize_study_id(study_id)
        file_paths = resolve_metadata_file_paths(study_id, metadata_path=metadata_path, metadata_files=metadata_files)
        if not file_paths:
            raise SubmissionAPIError("No ISA-Tab metadata files found to upload.")

        url = f"{self.rest_api_base_url.rstrip('/')}/studies/{study_id}/drag-drop-upload"
        headers = self.get_auth_headers()
        responses = []
        errors = []

        for file_path in file_paths:
            try:
                with file_path.open("rb") as file_handle:
                    response = requests.post(
                        url,
                        headers=headers,
                        files={"file": (file_path.name, file_handle)},
                        timeout=METADATA_UPLOAD_TIMEOUT_SECONDS,
                    )
                if response.status_code not in (200, 201):
                    errors.append(f"{file_path.name}: {response.status_code} {response.text}")
                    continue
                responses.append(get_response_payload(response))
            except Exception as exc:
                errors.append(f"{file_path.name}: {exc}")

        if errors:
            raise SubmissionAPIError("Metadata upload failed:\n" + "\n".join(errors))

        return MetadataUploadResult(study_id=study_id, uploaded_files=file_paths, responses=responses)

    def validate_study(
        self,
        study_id,
        validation_file_path=None,
        max_polls=VALIDATION_MAX_POLLS,
        poll_interval=VALIDATION_POLL_INTERVAL_SECONDS,
    ):
        study_id = normalize_study_id(study_id)
        report = self.run_study_validation(study_id, max_polls=max_polls, poll_interval=poll_interval)
        report_path = save_validation_report(study_id, report, validation_file_path)
        return ValidationResult(report=report, errors=get_validation_errors(report), report_path=report_path)

    def submit_study(
        self,
        study_id,
        status="Submitted",
        validation_file_path=None,
        validation_max_polls=VALIDATION_MAX_POLLS,
        validation_poll_interval=VALIDATION_POLL_INTERVAL_SECONDS,
    ):
        study_id = normalize_study_id(study_id)
        validation_result = self.validate_study(
            study_id,
            validation_file_path=validation_file_path,
            max_polls=validation_max_polls,
            poll_interval=validation_poll_interval,
        )
        if validation_result.errors:
            raise StudyValidationError(study_id, validation_result.errors)

        response = requests.put(
            f"{self.rest_api_base_url.rstrip('/')}/studies/{study_id}/status",
            headers=self.get_auth_headers(),
            json={"status": status},
            timeout=30,
        )
        response.raise_for_status()
        response_data = response.json() if response.content else None
        return StatusUpdateResult(study_id=study_id, status=status, response=response_data)

    def run_study_validation(
        self,
        study_id,
        max_polls=VALIDATION_MAX_POLLS,
        poll_interval=VALIDATION_POLL_INTERVAL_SECONDS,
    ):
        study_id = normalize_study_id(study_id)
        validation_url = f"{self.submission_api_base_url.rstrip('/')}/submissions/v2/validations/{study_id}"
        headers = self.get_submission_headers()

        response = requests.post(
            validation_url,
            headers=headers,
            params={"run_metadata_modifiers": "false", "override_previous_task_results": "true"},
            timeout=30,
        )
        if response.status_code == 401:
            headers = self.get_submission_headers(force_refresh=True)
            response = requests.post(
                validation_url,
                headers=headers,
                params={"run_metadata_modifiers": "false", "override_previous_task_results": "true"},
                timeout=30,
            )
        if response.status_code == 401:
            raise AuthenticationError(
                f"Submission validation API rejected the JWT token for {study_id}. "
                "Run 'mtbls auth login' and try again. "
                f"Response: {response.text}"
            )
        response.raise_for_status()
        response_data = response.json()
        raise_for_api_error(response_data)

        task_id = get_task_id(response_data)
        if not task_id:
            raise SubmissionAPIError(f"Validation task for {study_id} did not return a task id.")

        initial_status = get_task_status(response_data)
        if is_task_successful(response_data) is not True and "SUCCESS" not in initial_status.upper():
            task_headers = dict(headers)
            task_headers["Task-Id"] = task_id
            response_data = ensure_validation_task_succeeded(
                study_id,
                f"{validation_url}/{task_id}",
                task_headers,
                max_polls,
                poll_interval,
            )

        return response_data


def normalize_study_id(study_id):
    return study_id.upper().strip()


def get_project_root():
    return Path(__file__).resolve().parents[3]


def resolve_study_input_data_folder(data_folder=None):
    if data_folder is None:
        data_folder = DEFAULT_STUDY_INPUT_DATA_FOLDER
    data_folder = Path(data_folder).expanduser()
    return data_folder.resolve()


def save_sample_study_input(data_folder=None, overwrite=True):
    output_path = resolve_study_input_data_folder(data_folder) / DEFAULT_STUDY_INPUT_FILE_NAME
    if output_path.exists() and not overwrite:
        raise SubmissionAPIError(f"Study input file already exists: {output_path}")
    if output_path.exists() and output_path.is_dir():
        raise SubmissionAPIError(f"Study input path is a directory: {output_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    request = get_default_study_creation_request()
    with output_path.open("w", encoding="utf-8") as output_file:
        json.dump(request.model_dump(by_alias=True), output_file, indent=2)
        output_file.write("\n")
    return output_path


def is_metadata_filename(filename):
    if not filename:
        return False
    if len(filename) <= 6:
        return False
    return (
        filename.startswith(("a_", "s_", "i_")) and filename.endswith(".txt")
    ) or (filename.startswith("m_") and filename.endswith(".tsv"))


def resolve_metadata_file_paths(study_id, metadata_path=None, metadata_files=None):
    base_path = Path(metadata_path).expanduser() if metadata_path else DEFAULT_LOCAL_SUBMISSION_DATA_PATH / study_id
    base_path = base_path.resolve()
    metadata_files = list(metadata_files or [])

    if base_path.is_file():
        if metadata_files:
            raise SubmissionAPIError("Metadata files cannot be provided when metadata path is a file.")
        file_paths = [base_path]
    else:
        if not base_path.exists():
            raise SubmissionAPIError(f"Metadata path does not exist: {base_path}")
        if not base_path.is_dir():
            raise SubmissionAPIError(f"Metadata path is not a file or directory: {base_path}")

        if metadata_files:
            file_paths = []
            for metadata_file in metadata_files:
                file_path = Path(metadata_file).expanduser()
                if not file_path.is_absolute():
                    file_path = base_path / file_path
                file_paths.append(file_path.resolve())
        else:
            file_paths = sorted(path.resolve() for path in base_path.iterdir() if path.is_file() and is_metadata_filename(path.name))

    invalid_paths = [path for path in file_paths if not path.exists() or not path.is_file()]
    if invalid_paths:
        missing = ", ".join(str(path) for path in invalid_paths)
        raise SubmissionAPIError(f"Metadata file does not exist: {missing}")

    invalid_names = [path.name for path in file_paths if not is_metadata_filename(path.name)]
    if invalid_names:
        names = ", ".join(invalid_names)
        raise SubmissionAPIError(f"Unsupported metadata file name(s): {names}")

    return file_paths


def get_response_payload(response):
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


def is_successful_response(response):
    return 200 <= int(response.status_code) < 300


def get_jwt_from_response(response):
    jwt_token = response.headers.get("jwt") or response.headers.get("JWT")
    if jwt_token:
        return jwt_token

    authorization = response.headers.get("Authorization") or response.headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()

    try:
        response_data = response.json()
    except ValueError:
        return None

    if isinstance(response_data, dict):
        return response_data.get("jwt") or response_data.get("token") or response_data.get("access_token")
    return None


def get_refresh_token_from_response(response):
    refresh_token = response.headers.get("refresh-token") or response.headers.get("Refresh-Token")
    if refresh_token:
        return refresh_token

    try:
        response_data = response.json()
    except ValueError:
        return None

    if isinstance(response_data, dict):
        return response_data.get("refresh_token")
    return None


def get_api_token_from_login_response(response):
    api_token = response.headers.get("user-token") or response.headers.get("User-Token")
    if api_token:
        return api_token

    try:
        response_data = response.json()
    except ValueError:
        return None

    return find_api_token(response_data)


def find_api_token(value):
    if isinstance(value, dict):
        for key in ("apitoken", "apiToken", "api_token"):
            api_token = value.get(key)
            if isinstance(api_token, str) and api_token:
                return api_token
        for nested_value in value.values():
            api_token = find_api_token(nested_value)
            if api_token:
                return api_token
    if isinstance(value, list):
        for item in value:
            api_token = find_api_token(item)
            if api_token:
                return api_token
    return None


def save_refresh_token_from_response(submission_api_base_url, response):
    refresh_token = get_refresh_token_from_response(response)
    if refresh_token:
        save_refresh_token(submission_api_base_url, refresh_token)


def is_jwt_expired(jwt_token, leeway_seconds=60):
    parts = jwt_token.split(".")
    if len(parts) != 3:
        return False

    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
    except (ValueError, TypeError):
        return False

    exp = data.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return exp <= time.time() + leeway_seconds


def get_studies_from_user_response(response_data):
    if isinstance(response_data, list):
        return response_data
    if not isinstance(response_data, dict):
        return []

    for key in ("content", "data", "studies"):
        studies = response_data.get(key)
        if isinstance(studies, list):
            return studies
        if isinstance(studies, dict):
            return list(studies.values())

    return []


def get_rest_api_base_url(base_url):
    base_url = base_url.rstrip("/")
    if base_url.endswith("/ws3"):
        return f"{base_url[:-4]}/ws"
    return base_url


def get_submission_api_base_url(base_url):
    base_url = base_url.rstrip("/")
    if base_url.endswith("/ws3"):
        return base_url
    if base_url.endswith("/ws"):
        return f"{base_url[:-3]}/ws3"
    return f"{base_url}/ws3"


def get_keycloak_token_url(submission_api_base_url):
    parsed = urlsplit(submission_api_base_url.rstrip("/"))
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    context_path = parsed.path
    if context_path.endswith("/ws3"):
        context_path = context_path[: -len("/ws3")]
    if not context_path:
        context_path = "/metabolights"

    iam_path = f"{context_path}/test/iam" if parsed.netloc.startswith("wwwdev.") else f"{context_path}/iam"
    return f"{base_url}{iam_path}/realms/metabolights/protocol/openid-connect/token"


def format_response_error(name, response):
    try:
        response_data = response.json()
    except ValueError:
        response_data = response.text
    return f"{name}: {response.status_code} {response_data}"


def get_task_status(response_data):
    content = response_data.get("content", response_data)
    task = content.get("task", content) if isinstance(content, dict) else {}
    return task.get("taskStatus") or task.get("last_status") or task.get("status") or task.get("task_status") or ""


def get_task_id(response_data):
    content = response_data.get("content", response_data)
    task = content.get("task", content) if isinstance(content, dict) else {}
    return task.get("taskId") or task.get("task_id") or ""


def get_task_message(response_data):
    content = response_data.get("content", response_data)
    task = content.get("task", content) if isinstance(content, dict) else {}
    return (
        task.get("message")
        or response_data.get("successMessage")
        or response_data.get("success_message")
        or response_data.get("errorMessage")
        or response_data.get("error_message")
        or ""
    )


def is_task_ready(response_data):
    content = response_data.get("content", response_data)
    task = content.get("task", content) if isinstance(content, dict) else {}
    return bool(task.get("ready"))


def is_task_successful(response_data):
    content = response_data.get("content", response_data)
    task = content.get("task", content) if isinstance(content, dict) else {}
    return task.get("isSuccessful") if "isSuccessful" in task else task.get("is_successful")


def raise_for_api_error(response_data):
    if not isinstance(response_data, dict):
        return
    if response_data.get("status", "").lower() == "error":
        message = (
            response_data.get("errorMessage")
            or response_data.get("error_message")
            or response_data.get("errors")
            or "MetaboLights API returned an error."
        )
        raise SubmissionAPIError(str(message))


def is_validation_task_not_found(response_data):
    if not isinstance(response_data, dict):
        return False
    message = response_data.get("errorMessage") or response_data.get("error_message") or ""
    return "AsyncTaskNotFoundError" in message or "No validation task found" in message


def format_task_state(response_data):
    task_id = get_task_id(response_data) or "unknown"
    status = get_task_status(response_data) or "unknown"
    ready = is_task_ready(response_data)
    successful = is_task_successful(response_data)
    message = get_task_message(response_data)
    state = f"task_id={task_id}, status={status}, ready={ready}, successful={successful}"
    if message:
        state = f"{state}, message={message}"
    return state


def ensure_validation_task_succeeded(study_id, validation_url, headers, max_polls, poll_interval):
    last_response_data = None

    for _ in range(max_polls + 1):
        response = requests.get(validation_url, headers=headers, timeout=30)
        response_data = response.json()
        last_response_data = response_data
        if response.status_code == 404 and is_validation_task_not_found(response_data):
            time.sleep(poll_interval)
            continue
        response.raise_for_status()
        if is_validation_task_not_found(response_data):
            time.sleep(poll_interval)
            continue
        raise_for_api_error(response_data)

        status = get_task_status(response_data)
        successful = is_task_successful(response_data)
        if successful is True or "SUCCESS" in status.upper():
            return response_data
        if successful is False or any(failure in status.upper() for failure in ("FAIL", "REVOKED")):
            raise SubmissionAPIError(f"Validation task for {study_id} failed. Last state: {format_task_state(response_data)}")
        if is_task_ready(response_data) and successful is not True:
            raise SubmissionAPIError(
                f"Validation task for {study_id} did not finish successfully. Last state: {format_task_state(response_data)}"
            )

        time.sleep(poll_interval)

    message = f"Validation task for {study_id} did not complete in time."
    if last_response_data:
        message = f"{message} Last state: {format_task_state(last_response_data)}"
    raise SubmissionAPIError(message)


def get_validation_errors(report):
    if isinstance(report, list):
        return [violation for violation in report if violation.get("type", "").upper() == "ERROR"]

    content = report.get("content", report)
    task_result = content.get("taskResult", content) if isinstance(content, dict) else {}
    if isinstance(task_result, dict):
        messages = task_result.get("messages", {})
        violations = messages.get("violations", task_result.get("violations", []))
        return [violation for violation in violations if violation.get("type", "").upper() == "ERROR"]

    messages = content.get("messages", {}) if isinstance(content, dict) else {}
    violations = messages.get("violations", content.get("violations", [])) if isinstance(content, dict) else []
    if violations:
        return [violation for violation in violations if violation.get("type", "").upper() == "ERROR"]

    validation = report.get("validation", report)
    errors = []
    for section in validation.get("validations", []):
        section_name = section.get("section", "")
        for detail in section.get("details", []):
            if detail.get("status", "").upper() == "ERROR":
                error = dict(detail)
                error.setdefault("section", section_name)
                errors.append(error)
    return errors


def format_validation_error(error):
    section = error.get("section") or "Unknown section"
    message = (
        error.get("message")
        or error.get("title")
        or error.get("val_message")
        or error.get("description")
        or error.get("violation")
        or "Validation error"
    )
    metadata_file = error.get("metadata_file") or error.get("source_file") or error.get("sourceFile")
    if metadata_file:
        return f"{section}: {message} ({metadata_file})"
    return f"{section}: {message}"


def get_default_validation_report_path(study_id):
    return DEFAULT_LOCAL_SUBMISSION_CACHE_PATH / study_id / f"{study_id}_validation_report.json"


def get_validation_result(report):
    if not isinstance(report, dict):
        return report

    content = report.get("content")
    if isinstance(content, dict) and "taskResult" in content:
        return content["taskResult"]
    return report


def save_validation_report(study_id, report, validation_file_path=None):
    output_path = Path(validation_file_path).expanduser() if validation_file_path else get_default_validation_report_path(study_id)
    output_path = output_path.resolve()
    if output_path.exists() and output_path.is_dir():
        raise SubmissionAPIError(f"Validation report path is a directory: {output_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as validation_file:
        json.dump(get_validation_result(report), validation_file, indent=2)
        validation_file.write("\n")
    return output_path
