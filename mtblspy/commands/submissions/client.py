import base64
from ftplib import FTP, error_perm
import json
import posixpath
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import requests

from mtblspy.config import (
    get_api_key,
    get_base_url,
    get_credential_base_url,
    get_jwt_token,
    get_refresh_token,
    get_user_name,
    save_config,
    save_jwt_token,
    save_refresh_token,
)
from mtblspy.commands.output import resolve_json_output_path, write_json_file
from mtblspy.commands.submissions.exceptions import AuthenticationError, SubmissionAPIError
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
class ValidationRootCauseResult:
    validation_result: ValidationResult
    isa_json_path: Path


@dataclass
class MetadataUploadResult:
    study_id: str
    uploaded_files: list[Path]
    responses: list[Any]
    skipped_files: list[Path] = field(default_factory=list)
    validation_result: ValidationResult | None = None


@dataclass
class DataUploadResult:
    study_id: str
    uploaded_files: list[str]
    skipped_files: list[str]
    missing_on_local: list[str]
    errors: list[str] = field(default_factory=list)


@dataclass
class FileDownloadResult:
    study_id: str
    downloaded_files: list[Path]
    skipped_files: list[str]
    missing_files: list[str]
    errors: list[str] = field(default_factory=list)


@dataclass
class FileDeleteResult:
    study_id: str
    deleted_files: list[str]
    missing_files: list[str]
    errors: list[str] = field(default_factory=list)


@dataclass
class FtpTemporaryCleanupResult:
    study_id: str
    deleted_files: list[str]
    errors: list[str] = field(default_factory=list)


@dataclass
class DataUploadPlan:
    files: list[Path]
    empty_folders: list[str]
    skipped_files: list[str]
    missing_on_local: list[str]


class SubmissionClient:
    def __init__(self, base_url=None, api_token=None):
        self.rest_api_base_url = get_rest_api_base_url(base_url or get_base_url())
        self.submission_api_base_url = get_submission_api_base_url(self.rest_api_base_url)
        self.credential_base_url = get_credential_base_url(self.rest_api_base_url)
        self.api_token = api_token

    def get_auth_headers(self):
        api_token = self.api_token or get_api_key(credential_base_url=self.credential_base_url)
        if api_token:
            return {"user-token": api_token.strip()}
        return self.get_submission_headers()

    def get_submission_headers(self, force_refresh=False):
        jwt_token = None if force_refresh else get_jwt_token(
            self.submission_api_base_url,
            credential_base_url=self.credential_base_url,
        )
        if not jwt_token and not force_refresh:
            jwt_token = get_jwt_token(
                self.rest_api_base_url,
                credential_base_url=self.credential_base_url,
            )
        if jwt_token and not force_refresh and not is_jwt_expired(jwt_token):
            return {"accept": "application/json", "Authorization": f"Bearer {jwt_token}"}

        # Try to refresh using a stored refresh token
        refresh_token = get_refresh_token(
            self.submission_api_base_url,
            credential_base_url=self.credential_base_url,
        )
        if refresh_token:
            new_jwt = self.refresh_jwt_token(refresh_token)
            if new_jwt:
                save_jwt_token(
                    self.submission_api_base_url,
                    new_jwt,
                    credential_base_url=self.credential_base_url,
                )
                return {"accept": "application/json", "Authorization": f"Bearer {new_jwt}"}

        # Final fallback: exchange stored api_token for a JWT
        api_token = self.api_token or get_api_key(credential_base_url=self.credential_base_url)
        if not api_token:
            raise AuthenticationError(
                "Not logged in. Please run 'mtbls auth login' first."
            )
        jwt_token = self.exchange_api_token_for_jwt(api_token.strip())
        save_jwt_token(
            self.submission_api_base_url,
            jwt_token,
            credential_base_url=self.credential_base_url,
        )
        return {"accept": "application/json", "Authorization": f"Bearer {jwt_token}"}

    def exchange_api_token_for_jwt(self, api_token):
        user_name = get_user_name(credential_base_url=self.credential_base_url)
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
                save_refresh_token_from_response(
                    self.submission_api_base_url,
                    response,
                    credential_base_url=self.credential_base_url,
                )
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
                save_refresh_token_from_response(
                    self.submission_api_base_url,
                    response,
                    credential_base_url=self.credential_base_url,
                )
                return new_jwt
        except requests.RequestException:
            pass

        return None

    def require_api_token(self):
        api_token = self.api_token or get_api_key(credential_base_url=self.credential_base_url)
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
        save_config(
            api_key=api_token,
            base_url=self.rest_api_base_url,
            user_name=user_name,
            credential_base_url=self.credential_base_url,
        )
        save_jwt_token(
            self.submission_api_base_url,
            jwt_token,
            credential_base_url=self.credential_base_url,
        )
        if refresh_token:
            save_refresh_token(
                self.submission_api_base_url,
                refresh_token,
                credential_base_url=self.credential_base_url,
            )

    def password_login(self, user_name, password):
        """Backward-compatible alias for username/password login."""
        self.login(user_name, password)

    def login_with_jwt(self, jwt_token, fetch_api_token=False):
        """Store an existing submission API JWT for subsequent commands."""
        jwt_token = normalize_bearer_token(jwt_token)
        if not jwt_token:
            raise AuthenticationError("JWT token cannot be empty.")
        if is_jwt_expired(jwt_token):
            raise AuthenticationError("JWT token is expired.")

        user_name = get_user_name_from_jwt(jwt_token)
        api_token = None
        if fetch_api_token:
            api_token = self.try_fetch_api_token_from_jwt(jwt_token)
        config_values = dict(
            base_url=self.rest_api_base_url,
            user_name=user_name,
            credential_base_url=self.credential_base_url,
        )
        if api_token:
            config_values["api_key"] = api_token
        save_config(
            **config_values,
        )
        save_jwt_token(
            self.submission_api_base_url,
            jwt_token,
            credential_base_url=self.credential_base_url,
        )

    def try_fetch_api_token_from_jwt(self, jwt_token):
        try:
            return self.fetch_api_token_from_accounts(jwt_token)
        except Exception:
            return None

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
        raise_for_response_error(response, "Study creation failed")
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

    def upload_metadata(
        self,
        study_id,
        metadata_path=None,
        metadata_files=None,
        selected_files=None,
        default_submission_data_path=None,
        validate_after_upload=False,
        validation_file_path=None,
        validation_max_polls=VALIDATION_MAX_POLLS,
        validation_poll_interval=VALIDATION_POLL_INTERVAL_SECONDS,
    ):
        study_id = normalize_study_id(study_id)
        file_paths, skipped_files = resolve_metadata_file_paths(
            study_id,
            metadata_path=metadata_path,
            metadata_files=metadata_files,
            selected_files=selected_files,
            default_submission_data_path=default_submission_data_path,
            return_skipped=True,
        )
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
                    errors.append(format_metadata_upload_error(file_path.name, response))
                    continue
                responses.append(get_response_payload(response))
            except Exception as exc:
                errors.append(f"{file_path.name}: {exc}")

        if errors:
            raise SubmissionAPIError(
                f"Metadata upload failed for {len(errors)} file(s).",
                errors=errors,
            )

        validation_result = None
        if validate_after_upload:
            validation_result = self.validate_study(
                study_id,
                validation_file_path=validation_file_path,
                max_polls=validation_max_polls,
                poll_interval=validation_poll_interval,
            )

        return MetadataUploadResult(
            study_id=study_id,
            uploaded_files=file_paths,
            skipped_files=skipped_files,
            responses=responses,
            validation_result=validation_result,
        )

    def download_metadata_files(
        self,
        study_id,
        target_path=None,
        selected_files=None,
    ):
        study_id = normalize_study_id(study_id)
        selected_file_names = parse_selected_metadata_files(selected_files)
        if selected_file_names:
            file_names = selected_file_names
            skipped_files = []
        else:
            file_names = self.get_study_metadata_file_names(study_id)
            skipped_files = []
        if not file_names:
            raise SubmissionAPIError(f"No metadata files found for {study_id}.")

        target_root = resolve_download_target_path(target_path, study_id)
        target_root.mkdir(parents=True, exist_ok=True)
        downloaded_files = []
        missing_files = []
        errors = []

        for file_name in file_names:
            try:
                output_path = target_root / file_name
                self.download_metadata_file(study_id, file_name, output_path)
                downloaded_files.append(output_path.resolve())
            except FileNotFoundError:
                missing_files.append(file_name)
            except SubmissionAPIError as exc:
                if exc.errors:
                    errors.extend(f"{file_name}: {error}" for error in exc.errors)
                else:
                    errors.append(f"{file_name}: {exc}")
            except Exception as exc:
                errors.append(f"{file_name}: {exc}")

        return FileDownloadResult(
            study_id=study_id,
            downloaded_files=downloaded_files,
            skipped_files=skipped_files,
            missing_files=missing_files,
            errors=errors,
        )

    def get_study_metadata_file_names(self, study_id):
        isa_json = self.get_study_isa_json(study_id)
        file_names = collect_metadata_file_names(isa_json)
        if "i_Investigation.txt" not in file_names:
            file_names.insert(0, "i_Investigation.txt")
        return file_names

    def download_metadata_file(self, study_id, file_name, output_path):
        headers = self.get_auth_headers()
        soft_errors = []
        not_found_count = 0
        for url in build_metadata_download_urls(self.rest_api_base_url, study_id, file_name):
            response = requests.get(url, headers=headers, timeout=60)
            status_code = int(response.status_code)
            if 200 <= status_code < 300:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(response.content)
                return output_path
            if status_code == 404:
                not_found_count += 1
                soft_errors.append(format_metadata_file_response_error(url, response))
                continue
            if status_code in (400, 405):
                soft_errors.append(format_metadata_file_response_error(url, response))
                continue
            try:
                response.raise_for_status()
            except requests.RequestException as exc:
                raise SubmissionAPIError(
                    f"Unable to download metadata file {file_name} for {study_id}.",
                    errors=[format_metadata_file_response_error(url, response)],
                ) from exc
        if not_found_count and not_found_count == len(soft_errors):
            raise FileNotFoundError(file_name)
        raise SubmissionAPIError(
            f"Unable to download metadata file {file_name} for {study_id}.",
            errors=soft_errors,
        )

    def delete_metadata_files(self, study_id, selected_files):
        study_id = normalize_study_id(study_id)
        file_names = parse_comma_separated_values(selected_files)
        if not file_names:
            raise SubmissionAPIError(
                "Metadata delete requires --files with comma-separated metadata filenames."
            )

        response = self.post_metadata_delete_files(study_id, build_delete_files_payload(file_names))
        if not is_successful_response(response):
            raise SubmissionAPIError(
                f"Metadata delete failed for {study_id}.",
                errors=[format_metadata_file_response_error(response.url, response)],
            )
        deleted_files, errors = parse_metadata_delete_response(response, file_names)

        return FileDeleteResult(
            study_id=study_id,
            deleted_files=deleted_files,
            missing_files=[],
            errors=errors,
        )

    def post_metadata_delete_files(self, study_id, payload):
        return requests.post(
            f"{self.rest_api_base_url.rstrip('/')}/studies/{study_id}/files",
            headers={
                **self.get_auth_headers(),
                "accept": "application/json",
                "Content-Type": "application/json",
            },
            params={"location": "study", "force": "false"},
            json=payload,
            timeout=60,
        )

    def download_data_files(
        self,
        study_id,
        target_path=None,
        selected_files=None,
        download_all=False,
        ftp_factory=None,
        progress_callback=None,
    ):
        study_id = normalize_study_id(study_id)
        selected_file_names = parse_comma_separated_values(selected_files)
        if selected_file_names and download_all:
            raise SubmissionAPIError("Use either --files or --all, not both.")
        if not selected_file_names and not download_all:
            raise SubmissionAPIError(
                "Data download requires --files because study data files can be large. "
                "Use --files with comma-separated file or folder names, or pass --all to download all data files."
            )
        ftp_details = self.get_private_ftp_credentials(study_id)
        ftp = connect_ftp(ftp_details, ftp_factory=ftp_factory)
        target_root = resolve_data_download_target_path(target_path, study_id)
        downloaded_files = []
        skipped_files = []
        missing_files = []
        errors = []

        try:
            upload_root = enter_ftp_upload_root(ftp, ftp_details.ftp_folder)
            remote_files, _remote_folders = index_ftp_data_files(ftp, upload_root)
            selected_remote_files, missing_files = select_remote_data_files(remote_files, selected_file_names)
            emit_file_download_progress(progress_callback, "start", total=len(selected_remote_files))
            target_root.mkdir(parents=True, exist_ok=True)

            for relative_path in selected_remote_files:
                try:
                    output_path = target_root / Path(relative_path)
                    download_ftp_file(ftp, upload_root, relative_path, output_path)
                    downloaded_files.append(output_path.resolve())
                    emit_file_download_progress(
                        progress_callback,
                        "item",
                        path=relative_path,
                        status="downloaded",
                    )
                except Exception as exc:
                    errors.append(f"{relative_path}: {exc}")
                    emit_file_download_progress(
                        progress_callback,
                        "item",
                        path=relative_path,
                        status="failed",
                    )
        finally:
            try:
                ftp.quit()
            except Exception:
                pass

        return FileDownloadResult(
            study_id=study_id,
            downloaded_files=downloaded_files,
            skipped_files=skipped_files,
            missing_files=missing_files,
            errors=errors,
        )

    def upload_data_files(
        self,
        study_id,
        data_files_root_path,
        selected_files=None,
        skip_uploaded_files=None,
        skip_empty_folders=None,
        ftp_factory=None,
        progress_callback=None,
    ):
        study_id = normalize_study_id(study_id)
        plan = resolve_data_upload_plan(
            data_files_root_path,
            selected_files=selected_files,
            skip_uploaded_files=skip_uploaded_files,
            skip_empty_folders=skip_empty_folders,
        )
        emit_data_upload_progress(
            progress_callback,
            "start",
            total=len(plan.files) + len(plan.empty_folders),
        )
        if plan.missing_on_local:
            return DataUploadResult(
                study_id=study_id,
                uploaded_files=[],
                skipped_files=plan.skipped_files,
                missing_on_local=plan.missing_on_local,
            )

        if not plan.files and not plan.empty_folders:
            return DataUploadResult(
                study_id=study_id,
                uploaded_files=[],
                skipped_files=plan.skipped_files,
                missing_on_local=[],
            )

        ftp_details = self.get_private_ftp_credentials(study_id)
        ftp = connect_ftp(ftp_details, ftp_factory=ftp_factory)
        root_path = Path(data_files_root_path).expanduser().resolve()
        uploaded_files = []
        skipped_files = list(plan.skipped_files)
        errors = []

        try:
            upload_root = enter_ftp_upload_root(ftp, ftp_details.ftp_folder)
            remote_files, remote_folders = index_ftp_data_files(ftp, upload_root)

            for empty_folder in plan.empty_folders:
                if empty_folder in remote_folders:
                    skipped_files.append(f"{empty_folder}/")
                    emit_data_upload_progress(
                        progress_callback,
                        "item",
                        path=f"{empty_folder}/",
                        status="skipped",
                    )
                    continue
                try:
                    ensure_ftp_directory(ftp, empty_folder, root_directory=upload_root)
                    uploaded_files.append(f"{empty_folder}/")
                    emit_data_upload_progress(
                        progress_callback,
                        "item",
                        path=f"{empty_folder}/",
                        status="uploaded",
                    )
                except Exception:
                    skipped_files.append(f"{empty_folder}/")
                    emit_data_upload_progress(
                        progress_callback,
                        "item",
                        path=f"{empty_folder}/",
                        status="skipped",
                    )

            for file_path in plan.files:
                relative_path = to_posix_relative_path(file_path, root_path)
                local_size = file_path.stat().st_size
                remote_size = remote_files.get(relative_path)
                if remote_size is None and relative_path in remote_files:
                    skipped_files.append(relative_path)
                    emit_data_upload_progress(
                        progress_callback,
                        "item",
                        path=relative_path,
                        status="skipped",
                    )
                    continue
                if remote_size == local_size:
                    skipped_files.append(relative_path)
                    emit_data_upload_progress(
                        progress_callback,
                        "item",
                        path=relative_path,
                        status="skipped",
                    )
                    continue

                try:
                    upload_ftp_file(ftp, upload_root, file_path, relative_path)
                    uploaded_files.append(relative_path)
                    emit_data_upload_progress(
                        progress_callback,
                        "item",
                        path=relative_path,
                        status="uploaded",
                    )
                except Exception as exc:
                    errors.append(f"{relative_path}: {exc}")
                    emit_data_upload_progress(
                        progress_callback,
                        "item",
                        path=relative_path,
                        status="failed",
                    )
        finally:
            try:
                ftp.quit()
            except Exception:
                pass

        return DataUploadResult(
            study_id=study_id,
            uploaded_files=uploaded_files,
            skipped_files=skipped_files,
            missing_on_local=[],
            errors=errors,
        )

    def clear_ftp_temporary_files(self, study_id, ftp_factory=None):
        study_id = normalize_study_id(study_id)
        ftp_details = self.get_private_ftp_credentials(study_id)
        ftp = connect_ftp(ftp_details, ftp_factory=ftp_factory)

        try:
            upload_root = enter_ftp_upload_root(ftp, ftp_details.ftp_folder)
            deleted_files, errors = delete_ftp_temporary_files(ftp, upload_root)
        finally:
            try:
                ftp.quit()
            except Exception:
                pass

        return FtpTemporaryCleanupResult(
            study_id=study_id,
            deleted_files=deleted_files,
            errors=errors,
        )

    def validate_study(
        self,
        study_id,
        validation_file_path=None,
        max_polls=VALIDATION_MAX_POLLS,
        poll_interval=VALIDATION_POLL_INTERVAL_SECONDS,
        use_isa_json=False,
        include_root_causes=False,
    ):
        study_id = normalize_study_id(study_id)
        isa_json = self.get_study_isa_json(study_id) if use_isa_json else None
        report = self.run_study_validation(study_id, isa_json=isa_json, max_polls=max_polls, poll_interval=poll_interval)
        report_path = save_validation_report(
            study_id,
            report,
            validation_file_path,
            isa_json=isa_json,
            include_root_causes=include_root_causes,
        )
        errors = get_validation_errors(report)
        if isa_json:
            errors = enrich_validation_errors_with_isa_json(errors, isa_json)
        return ValidationResult(report=report, errors=errors, report_path=report_path)

    def find_validation_root_causes(
        self,
        study_id,
        isa_json_file_path=None,
        validation_file_path=None,
        max_polls=VALIDATION_MAX_POLLS,
        poll_interval=VALIDATION_POLL_INTERVAL_SECONDS,
    ):
        study_id = normalize_study_id(study_id)
        isa_json = self.get_study_isa_json(study_id)
        isa_json_path = save_isa_json(study_id, isa_json, isa_json_file_path)
        report = self.run_study_validation(study_id, isa_json=isa_json, max_polls=max_polls, poll_interval=poll_interval)
        report_path = save_validation_report(
            study_id,
            report,
            validation_file_path,
            isa_json=isa_json,
            include_root_causes=True,
        )
        errors = enrich_validation_errors_with_isa_json(get_validation_errors(report), isa_json)
        validation_result = ValidationResult(report=report, errors=errors, report_path=report_path)
        return ValidationRootCauseResult(validation_result=validation_result, isa_json_path=isa_json_path)

    def run_study_validation(
        self,
        study_id,
        isa_json=None,
        max_polls=VALIDATION_MAX_POLLS,
        poll_interval=VALIDATION_POLL_INTERVAL_SECONDS,
    ):
        study_id = normalize_study_id(study_id)
        validation_url = f"{self.submission_api_base_url.rstrip('/')}/submissions/v2/validations/{study_id}"
        headers = self.get_submission_headers()

        response = post_validation_request(validation_url, headers, isa_json=isa_json)
        if response.status_code == 401:
            headers = self.get_submission_headers(force_refresh=True)
            response = post_validation_request(validation_url, headers, isa_json=isa_json)
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

    def get_study_isa_json(self, study_id):
        study_id = normalize_study_id(study_id)
        response = requests.get(
            f"{self.rest_api_base_url.rstrip('/')}/studies/{study_id}",
            headers=self.get_auth_headers(),
            timeout=30,
        )
        response.raise_for_status()
        return extract_isa_json(response.json())


def normalize_study_id(study_id):
    return study_id.upper().strip()


def post_validation_request(validation_url, headers, isa_json=None):
    kwargs = {
        "headers": headers,
        "params": {"run_metadata_modifiers": "false", "override_previous_task_results": "true"},
        "timeout": 30,
    }
    if isa_json is not None:
        kwargs["json"] = isa_json
    return requests.post(validation_url, **kwargs)


def extract_isa_json(response_data):
    if not isinstance(response_data, dict):
        return response_data

    content = response_data.get("content")
    if isinstance(content, dict):
        return extract_isa_json(content)

    for key in ("isaInvestigation", "isaJson", "isa_json", "study"):
        value = response_data.get(key)
        if isinstance(value, dict):
            return value

    return response_data


def get_project_root():
    return Path(__file__).resolve().parents[3]


def resolve_study_input_data_folder(data_folder=None):
    if data_folder is None:
        data_folder = DEFAULT_STUDY_INPUT_DATA_FOLDER
    data_folder = Path(data_folder).expanduser()
    return data_folder.resolve()


def save_sample_study_input(data_folder=None, output_path=None, overwrite=True):
    if output_path:
        output_path = resolve_json_output_path(
            output_path,
            DEFAULT_STUDY_INPUT_DATA_FOLDER,
            DEFAULT_STUDY_INPUT_FILE_NAME,
        )
    else:
        output_path = resolve_study_input_data_folder(data_folder) / DEFAULT_STUDY_INPUT_FILE_NAME
    if output_path.exists() and not overwrite:
        raise SubmissionAPIError(f"Study input file already exists: {output_path}")
    if output_path.exists() and output_path.is_dir():
        raise SubmissionAPIError(f"Study input path is a directory: {output_path}")

    request = get_default_study_creation_request()
    return write_json_file(request.model_dump(by_alias=True), output_path)


def is_metadata_filename(filename):
    if not filename:
        return False
    if len(filename) <= 6:
        return False
    return (
        filename.startswith(("a_", "s_", "i_")) and filename.endswith(".txt")
    ) or (filename.startswith("m_") and filename.endswith(".tsv"))


def parse_selected_metadata_files(selected_files):
    return parse_comma_separated_values(selected_files)


def parse_comma_separated_values(values):
    if not values:
        return []
    if isinstance(values, str):
        raw_values = values.split(",")
    else:
        raw_values = values

    parsed_values = []
    seen = set()
    for raw_value in raw_values:
        value = str(raw_value).strip()
        if value and value not in seen:
            parsed_values.append(value)
            seen.add(value)
    return parsed_values


def resolve_download_target_path(target_path, study_id):
    if not target_path:
        return (DEFAULT_LOCAL_SUBMISSION_DATA_PATH / normalize_study_id(study_id)).resolve()
    return Path(target_path).expanduser().resolve()


def resolve_data_download_target_path(target_path, study_id):
    if not target_path:
        return (DEFAULT_LOCAL_SUBMISSION_DATA_PATH / normalize_study_id(study_id) / "FILES").resolve()
    return Path(target_path).expanduser().resolve()


def collect_metadata_file_names(value):
    file_names = []
    seen = set()

    def add_file_name(candidate):
        candidate = str(candidate).strip()
        file_name = posixpath.basename(candidate)
        if is_metadata_filename(file_name) and file_name not in seen:
            file_names.append(file_name)
            seen.add(file_name)

    def visit(item):
        if isinstance(item, dict):
            for key, child_value in item.items():
                add_file_name(key)
                visit(child_value)
            return
        if isinstance(item, list):
            for child_value in item:
                visit(child_value)
            return
        if isinstance(item, str):
            add_file_name(item)

    visit(value)
    file_names.sort(key=metadata_file_sort_key)
    return file_names


def metadata_file_sort_key(file_name):
    prefixes = {"i_": 0, "s_": 1, "a_": 2, "m_": 3}
    for prefix, index in prefixes.items():
        if file_name.startswith(prefix):
            return (index, file_name)
    return (99, file_name)


def build_metadata_download_urls(base_url, study_id, file_name):
    base_url = base_url.rstrip("/")
    study_id = normalize_study_id(study_id)
    quoted_file_name = quote(file_name)
    file_query = urlencode({"file": file_name})
    return [
        f"{base_url}/studies/{study_id}/download?{file_query}",
        f"{base_url}/studies/{study_id}/files/{quoted_file_name}",
        f"{base_url}/studies/{study_id}/metadata-files/{quoted_file_name}",
        f"{base_url}/studies/{study_id}/metadata/{quoted_file_name}",
        f"{base_url}/studies/{study_id}/download/{quoted_file_name}",
    ]


def build_delete_files_payload(file_names):
    return {"files": [{"name": file_name} for file_name in file_names]}


def parse_metadata_delete_response(response, requested_files):
    response_data = get_response_payload(response)
    messages = collect_response_error_messages(response_data)
    blocked_files = set()
    confirmed_deleted_files = set()
    errors = []
    for message in messages:
        message_text = str(message).strip()
        if not message_text:
            continue
        matched_files = [file_name for file_name in requested_files if file_name in message_text]
        if matched_files and is_metadata_delete_success_message(message_text):
            confirmed_deleted_files.update(matched_files)
            continue
        if matched_files or is_metadata_delete_failure_message(message_text):
            errors.append(message_text)
            blocked_files.update(matched_files)

    if errors:
        deleted_files = [file_name for file_name in requested_files if file_name in confirmed_deleted_files]
    else:
        deleted_files = [file_name for file_name in requested_files if file_name not in blocked_files]
    if errors and not blocked_files and not confirmed_deleted_files:
        deleted_files = []
    return deleted_files, deduplicate_strings(errors)


def is_metadata_delete_success_message(message):
    normalized_message = str(message).lower()
    return "deleted" in normalized_message or "is deleted" in normalized_message


def is_metadata_delete_failure_message(message):
    normalized_message = str(message).lower()
    failure_terms = ("not allowed", "cannot", "failed", "error", "denied")
    delete_terms = ("delete", "remove")
    return any(term in normalized_message for term in failure_terms) and any(
        term in normalized_message for term in delete_terms
    )


def format_metadata_file_response_error(url, response):
    status_code = getattr(response, "status_code", "unknown")
    reason = getattr(response, "reason", "") or ""
    status = f"HTTP {status_code}"
    if reason:
        status = f"{status} {reason}"
    try:
        details = extract_response_errors(response)
    except Exception:
        details = []
    if details:
        return f"{status} - {'; '.join(details)} for url: {url}"
    return f"{status} for url: {url}"


def resolve_metadata_file_paths(
    study_id,
    metadata_path=None,
    metadata_files=None,
    selected_files=None,
    default_submission_data_path=None,
    return_skipped=False,
):
    default_data_path = (
        Path(default_submission_data_path).expanduser()
        if default_submission_data_path
        else DEFAULT_LOCAL_SUBMISSION_DATA_PATH
    )
    base_path = Path(metadata_path).expanduser() if metadata_path else default_data_path / study_id
    base_path = base_path.resolve()
    metadata_files = list(metadata_files or [])
    selected_file_names = parse_selected_metadata_files(selected_files)

    if metadata_files and selected_file_names:
        raise SubmissionAPIError("Metadata files and selected files cannot both be provided.")

    if base_path.is_file():
        if metadata_files or selected_file_names:
            raise SubmissionAPIError("Metadata files cannot be selected when metadata path is a file.")
        file_paths = [base_path]
        skipped_files = []
    else:
        if not base_path.exists():
            raise SubmissionAPIError(f"Metadata path does not exist: {base_path}")
        if not base_path.is_dir():
            raise SubmissionAPIError(f"Metadata path is not a file or directory: {base_path}")

        metadata_file_paths = sorted(
            path.resolve()
            for path in base_path.iterdir()
            if path.is_file() and is_metadata_filename(path.name)
        )
        if metadata_files:
            file_paths = []
            for metadata_file in metadata_files:
                file_path = Path(metadata_file).expanduser()
                if not file_path.is_absolute():
                    file_path = base_path / file_path
                file_paths.append(file_path.resolve())
            selected_names = {path.name for path in file_paths}
            skipped_files = [path for path in metadata_file_paths if path.name not in selected_names]
        elif selected_file_names:
            file_paths = [(base_path / selected_file).resolve() for selected_file in selected_file_names]
            selected_names = {Path(selected_file).name for selected_file in selected_file_names}
            skipped_files = [path for path in metadata_file_paths if path.name not in selected_names]
        else:
            file_paths = metadata_file_paths
            skipped_files = []

    invalid_paths = [path for path in file_paths if not path.exists() or not path.is_file()]
    if invalid_paths:
        missing = ", ".join(str(path) for path in invalid_paths)
        raise SubmissionAPIError(f"Metadata file does not exist: {missing}")

    invalid_names = [path.name for path in file_paths if not is_metadata_filename(path.name)]
    if invalid_names:
        names = ", ".join(invalid_names)
        raise SubmissionAPIError(f"Unsupported metadata file name(s): {names}")

    validate_metadata_file_names_for_study(file_paths, study_id)

    if return_skipped:
        return file_paths, skipped_files
    return file_paths


def validate_metadata_file_names_for_study(file_paths, study_id):
    errors = []
    for path in file_paths:
        error = metadata_filename_study_id_error(path.name, study_id)
        if error:
            errors.append(error)
    if errors:
        raise SubmissionAPIError(
            f"Metadata file name validation failed for {normalize_study_id(study_id)}.",
            errors=errors,
        )


def metadata_filename_study_id_error(file_name, study_id):
    study_id = normalize_study_id(study_id)
    if file_name.startswith("i_"):
        return None
    if file_name.startswith("s_"):
        expected_name = f"s_{study_id}.txt"
        if file_name != expected_name:
            return f"{file_name}: sample file name must be {expected_name}."
        return None
    if file_name.startswith("a_") and not has_study_id_name_part(file_name.removeprefix("a_").removesuffix(".txt"), study_id):
        return f"{file_name}: assay file name must be a_{study_id}.txt, a_{study_id}_*.txt, or a_{study_id}-*.txt."
    if file_name.startswith("m_") and not has_study_id_name_part(file_name.removeprefix("m_").removesuffix(".tsv"), study_id):
        return f"{file_name}: metabolite assignment file name must be m_{study_id}.tsv, m_{study_id}_*.tsv, or m_{study_id}-*.tsv."
    return None


def has_study_id_name_part(name_part, study_id):
    if name_part == study_id:
        return True
    return name_part.startswith(f"{study_id}_") or name_part.startswith(f"{study_id}-")


def resolve_data_upload_plan(
    data_files_root_path,
    selected_files=None,
    skip_uploaded_files=None,
    skip_empty_folders=None,
):
    root_path = Path(data_files_root_path).expanduser().resolve()
    if not root_path.exists():
        raise SubmissionAPIError(f"Data files root path does not exist: {root_path}")
    if not root_path.is_dir():
        raise SubmissionAPIError(f"Data files root path is not a directory: {root_path}")

    selected_entries = parse_comma_separated_values(selected_files)
    skip_entries = parse_comma_separated_values(skip_uploaded_files)
    skip_empty_entries = parse_comma_separated_values(skip_empty_folders)

    selected_paths = selected_entries or ["."]
    files_by_relative_path = {}
    empty_folders_by_relative_path = {}
    missing_on_local = []

    for selected_path in selected_paths:
        collect_data_upload_paths(
            root_path,
            selected_path,
            files_by_relative_path,
            empty_folders_by_relative_path,
            missing_on_local,
        )

    skipped_files = []
    for skip_path in skip_entries:
        skip_candidate = resolve_data_candidate_path(root_path, skip_path)
        if not skip_candidate.exists():
            missing_on_local.append(skip_path)
            continue
        for relative_path in iter_data_relative_paths(root_path, skip_candidate):
            if relative_path in files_by_relative_path:
                files_by_relative_path.pop(relative_path)
                skipped_files.append(relative_path)
            if relative_path in empty_folders_by_relative_path:
                empty_folders_by_relative_path.pop(relative_path)
                skipped_files.append(f"{relative_path}/")

    for skip_empty_folder in skip_empty_entries:
        folder_candidate = resolve_data_candidate_path(root_path, skip_empty_folder)
        if not folder_candidate.exists():
            missing_on_local.append(skip_empty_folder)
            continue
        if not folder_candidate.is_dir():
            missing_on_local.append(skip_empty_folder)
            continue
        relative_path = to_posix_relative_path(folder_candidate, root_path)
        if relative_path in empty_folders_by_relative_path:
            empty_folders_by_relative_path.pop(relative_path)
            skipped_files.append(f"{relative_path}/")

    return DataUploadPlan(
        files=list(files_by_relative_path.values()),
        empty_folders=list(empty_folders_by_relative_path),
        skipped_files=sorted(set(skipped_files)),
        missing_on_local=parse_comma_separated_values(missing_on_local),
    )


def emit_data_upload_progress(progress_callback, event, **payload):
    if not progress_callback:
        return
    try:
        progress_callback({"event": event, **payload})
    except Exception:
        pass


def emit_file_download_progress(progress_callback, event, **payload):
    if not progress_callback:
        return
    try:
        progress_callback({"event": event, **payload})
    except Exception:
        pass


def collect_data_upload_paths(
    root_path,
    selected_path,
    files_by_relative_path,
    empty_folders_by_relative_path,
    missing_on_local,
):
    candidate = resolve_data_candidate_path(root_path, selected_path)
    if not candidate.exists():
        missing_on_local.append(selected_path)
        return

    if candidate.is_file():
        files_by_relative_path[to_posix_relative_path(candidate, root_path)] = candidate
        return

    if not candidate.is_dir():
        missing_on_local.append(selected_path)
        return

    found_file = False
    for file_path in sorted(path for path in candidate.rglob("*") if path.is_file()):
        found_file = True
        files_by_relative_path[to_posix_relative_path(file_path, root_path)] = file_path

    for folder_path in sorted(path for path in candidate.rglob("*") if path.is_dir()):
        if is_empty_directory(folder_path):
            empty_folders_by_relative_path[to_posix_relative_path(folder_path, root_path)] = folder_path

    if not found_file and is_empty_directory(candidate):
        empty_folders_by_relative_path[to_posix_relative_path(candidate, root_path)] = candidate


def resolve_data_candidate_path(root_path, requested_path):
    candidate = Path(requested_path).expanduser()
    if not candidate.is_absolute():
        candidate = root_path / candidate
    return candidate.resolve()


def iter_data_relative_paths(root_path, candidate):
    if candidate.is_file():
        return [to_posix_relative_path(candidate, root_path)]
    if candidate.is_dir():
        relative_paths = [
            to_posix_relative_path(path, root_path)
            for path in sorted(candidate.rglob("*"))
            if path.is_file() or is_empty_directory(path)
        ]
        if is_empty_directory(candidate):
            relative_paths.append(to_posix_relative_path(candidate, root_path))
        return relative_paths
    return []


def is_empty_directory(path):
    return path.is_dir() and not any(path.iterdir())


def to_posix_relative_path(path, root_path):
    relative_path = Path(path).resolve().relative_to(Path(root_path).resolve())
    if str(relative_path) == ".":
        return "."
    return relative_path.as_posix()


def connect_ftp(ftp_details, ftp_factory=None):
    ftp_factory = ftp_factory or FTP
    ftp_host = normalize_ftp_host(ftp_details.ftp_host)
    ftp = ftp_factory(ftp_host, timeout=60)
    ftp.login(ftp_details.ftp_user, ftp_details.ftp_password)
    return ftp


def normalize_ftp_host(ftp_host):
    if "://" not in ftp_host:
        return ftp_host
    return urlsplit(ftp_host).netloc or urlsplit(ftp_host).path


def index_ftp_data_files(ftp, remote_root):
    files = {}
    folders = set()
    remote_root = remote_root or "."
    try:
        index_ftp_directory(ftp, remote_root, "", files, folders)
    except Exception:
        return files, folders
    return files, folders


def index_ftp_directory(ftp, remote_directory, relative_directory, files, folders):
    for name, facts in ftp.mlsd(remote_directory):
        if name in (".", ".."):
            continue
        entry_type = facts.get("type", "")
        relative_path = join_relative_path(relative_directory, name)
        remote_path = join_remote_path(remote_directory, name)
        if entry_type == "dir":
            folders.add(relative_path)
            index_ftp_directory(ftp, remote_path, relative_path, files, folders)
        elif entry_type == "file":
            files[relative_path] = parse_ftp_size(facts.get("size"))


def parse_ftp_size(size):
    try:
        return int(size)
    except (TypeError, ValueError):
        return None


def join_relative_path(parent, child):
    if not parent:
        return child
    return f"{parent.rstrip('/')}/{child.lstrip('/')}"


def join_remote_path(parent, child):
    if not parent:
        return child
    return posixpath.join(parent, child)


def enter_ftp_upload_root(ftp, ftp_folder):
    ftp_folder = (ftp_folder or "").strip()
    if not ftp_folder:
        return get_ftp_current_directory(ftp)

    candidates = [ftp_folder]
    stripped_folder = ftp_folder.strip("/")
    if stripped_folder and stripped_folder != ftp_folder:
        candidates.append(stripped_folder)
    basename = posixpath.basename(stripped_folder)
    if basename and basename not in candidates:
        candidates.append(basename)

    for candidate in candidates:
        try:
            ftp.cwd(candidate)
            return get_ftp_current_directory(ftp)
        except error_perm:
            continue

    return get_ftp_current_directory(ftp)


def get_ftp_current_directory(ftp):
    try:
        return ftp.pwd()
    except Exception:
        return "."


def ensure_ftp_directory(ftp, remote_directory, root_directory=None):
    if root_directory:
        try:
            ftp.cwd(root_directory)
        except error_perm:
            pass
    if not remote_directory:
        return
    parts = [part for part in remote_directory.split("/") if part]
    if remote_directory.startswith("/"):
        try:
            ftp.cwd("/")
        except error_perm:
            pass

    for part in parts:
        try:
            ftp.cwd(part)
        except error_perm:
            try:
                ftp.mkd(part)
            except error_perm:
                ftp.cwd(part)
            else:
                ftp.cwd(part)


def upload_ftp_file(ftp, root_directory, file_path, relative_path):
    remote_directory = posixpath.dirname(relative_path)
    remote_filename = posixpath.basename(relative_path)
    temporary_filename = get_temporary_ftp_filename(remote_filename)
    local_size = file_path.stat().st_size
    try:
        create_ftp_directory_path(ftp, root_directory, remote_directory)
        ensure_ftp_directory(ftp, remote_directory, root_directory=root_directory)
        with file_path.open("rb") as file_handle:
            ftp.storbinary(f"STOR {temporary_filename}", file_handle)
        verify_ftp_file_size(ftp, temporary_filename, local_size, relative_path)
        ftp.rename(temporary_filename, remote_filename)
    except error_perm:
        upload_ftp_file_by_relative_path(ftp, root_directory, file_path, relative_path)


def upload_ftp_file_by_relative_path(ftp, root_directory, file_path, relative_path):
    temporary_relative_path = get_temporary_ftp_relative_path(relative_path)
    local_size = file_path.stat().st_size
    if root_directory:
        try:
            ftp.cwd(root_directory)
        except error_perm:
            pass
    with file_path.open("rb") as file_handle:
        ftp.storbinary(f"STOR {temporary_relative_path}", file_handle)
    verify_ftp_file_size(ftp, temporary_relative_path, local_size, relative_path)
    ftp.rename(temporary_relative_path, relative_path)


def verify_ftp_file_size(ftp, temporary_path, expected_size, final_relative_path):
    uploaded_size = get_ftp_file_size(ftp, temporary_path)
    if uploaded_size is None:
        return
    if uploaded_size == expected_size:
        return

    try:
        ftp.delete(temporary_path)
    except Exception:
        pass
    raise SubmissionAPIError(
        f"Uploaded temporary file size mismatch for {final_relative_path}: "
        f"expected {expected_size} bytes, got {uploaded_size} bytes."
    )


def get_ftp_file_size(ftp, remote_path):
    try:
        return parse_ftp_size(ftp.size(remote_path))
    except Exception:
        pass

    directory = posixpath.dirname(remote_path) or "."
    filename = posixpath.basename(remote_path)
    try:
        for name, facts in ftp.mlsd(directory):
            if name == filename:
                return parse_ftp_size(facts.get("size"))
    except Exception:
        return None
    return None


def select_remote_data_files(remote_files, selected_files=None):
    available_files = sorted(relative_path for relative_path in remote_files if is_data_download_filename(relative_path))
    available_file_set = set(available_files)
    if not selected_files:
        return available_files, []

    selected_remote_files = []
    missing_files = []
    seen = set()
    for selected_file in selected_files:
        normalized_selection = selected_file.strip().strip("/")
        if not normalized_selection:
            continue
        matches = []
        if normalized_selection in available_file_set:
            matches.append(normalized_selection)
        prefix = f"{normalized_selection.rstrip('/')}/"
        matches.extend(path for path in available_files if path.startswith(prefix))
        if not matches:
            missing_files.append(selected_file)
            continue
        for path in sorted(matches):
            if path not in seen:
                selected_remote_files.append(path)
                seen.add(path)
    return selected_remote_files, missing_files


def is_data_download_filename(relative_path):
    file_name = posixpath.basename(relative_path)
    return bool(file_name) and not file_name.startswith(".ftp_") and not is_metadata_filename(file_name)


def download_ftp_file(ftp, root_directory, relative_path, output_path):
    if root_directory:
        try:
            ftp.cwd(root_directory)
        except error_perm:
            pass
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as output_file:
        ftp.retrbinary(f"RETR {relative_path}", output_file.write)


def get_temporary_ftp_relative_path(relative_path):
    remote_directory = posixpath.dirname(relative_path)
    remote_filename = posixpath.basename(relative_path)
    temporary_filename = get_temporary_ftp_filename(remote_filename)
    if not remote_directory:
        return temporary_filename
    return posixpath.join(remote_directory, temporary_filename)


def get_temporary_ftp_filename(filename):
    return f".ftp_{filename}"


def delete_ftp_temporary_files(ftp, remote_root):
    deleted_files = []
    errors = []
    try:
        walk_and_delete_ftp_temporary_files(ftp, remote_root or ".", "", deleted_files, errors)
    except Exception as exc:
        errors.append(f"Unable to scan FTP folder: {exc}")
    return deleted_files, errors


def walk_and_delete_ftp_temporary_files(ftp, remote_directory, relative_directory, deleted_files, errors):
    try:
        entries = list(ftp.mlsd(remote_directory))
    except Exception:
        walk_and_delete_ftp_temporary_files_by_nlst(
            ftp,
            remote_directory,
            relative_directory,
            deleted_files,
            errors,
        )
        return

    for name, facts in entries:
        if name in (".", ".."):
            continue
        entry_type = facts.get("type", "")
        relative_path = join_relative_path(relative_directory, name)
        remote_path = join_remote_path(remote_directory, name)
        if entry_type == "dir":
            walk_and_delete_ftp_temporary_files(ftp, remote_path, relative_path, deleted_files, errors)
        elif entry_type == "file" and name.startswith(".ftp_"):
            try:
                ftp.delete(remote_path)
                deleted_files.append(relative_path)
            except Exception as exc:
                errors.append(f"{relative_path}: {exc}")


def walk_and_delete_ftp_temporary_files_by_nlst(ftp, remote_directory, relative_directory, deleted_files, errors):
    try:
        entries = ftp.nlst(remote_directory)
    except Exception as exc:
        errors.append(f"{relative_directory or '.'}: {exc}")
        return

    for entry in entries:
        remote_path = normalize_ftp_nlst_path(remote_directory, entry)
        if not remote_path:
            continue
        name = posixpath.basename(remote_path.rstrip("/"))
        if name in ("", ".", ".."):
            continue
        relative_path = join_relative_path(relative_directory, name)
        if name.startswith(".ftp_"):
            try:
                ftp.delete(remote_path)
                deleted_files.append(relative_path)
            except Exception as exc:
                errors.append(f"{relative_path}: {exc}")
            continue
        if is_ftp_directory(ftp, remote_path):
            walk_and_delete_ftp_temporary_files_by_nlst(
                ftp,
                remote_path,
                relative_path,
                deleted_files,
                errors,
            )


def normalize_ftp_nlst_path(remote_directory, entry):
    entry_path = str(entry).strip().rstrip("/")
    if not entry_path:
        return ""
    remote_directory = (remote_directory or ".").rstrip("/")
    if entry_path.startswith("/") or remote_directory in ("", "."):
        return entry_path
    if entry_path.startswith(f"{remote_directory}/"):
        return entry_path
    return join_remote_path(remote_directory, entry_path)


def is_ftp_directory(ftp, remote_path):
    current_directory = get_ftp_current_directory(ftp)
    try:
        ftp.cwd(remote_path)
    except Exception:
        return False
    finally:
        try:
            ftp.cwd(current_directory)
        except Exception:
            pass
    return True


def create_ftp_directory_path(ftp, root_directory, remote_directory):
    if not remote_directory:
        return
    if root_directory:
        try:
            ftp.cwd(root_directory)
        except error_perm:
            pass

    current_path = ""
    for part in [part for part in remote_directory.split("/") if part]:
        current_path = join_relative_path(current_path, part)
        try:
            ftp.mkd(current_path)
        except error_perm:
            pass


def get_response_payload(response):
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


def format_metadata_upload_error(file_name, response):
    response_data = get_response_payload(response)
    message = extract_response_error_message(response_data)
    if message:
        return f"{file_name}: HTTP {response.status_code} - {message}"
    return f"{file_name}: HTTP {response.status_code}"


def extract_response_error_message(response_data):
    if isinstance(response_data, dict):
        for key in ("message", "error_message", "errorMessage", "err", "error"):
            value = response_data.get(key)
            if value:
                return str(value)
        return json.dumps(response_data, default=str)
    if response_data:
        return str(response_data)
    return ""


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


def save_refresh_token_from_response(submission_api_base_url, response, credential_base_url=None):
    refresh_token = get_refresh_token_from_response(response)
    if refresh_token:
        save_refresh_token(
            submission_api_base_url,
            refresh_token,
            credential_base_url=credential_base_url,
        )


def is_jwt_expired(jwt_token, leeway_seconds=60):
    data = decode_jwt_payload(jwt_token)
    if not data:
        return False

    exp = data.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return exp <= time.time() + leeway_seconds


def normalize_bearer_token(token):
    token = (token or "").strip()
    if token.lower().startswith("bearer "):
        return token.split(" ", 1)[1].strip()
    return token


def decode_jwt_payload(jwt_token):
    parts = jwt_token.split(".")
    if len(parts) != 3:
        return {}

    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
    except (ValueError, TypeError):
        return {}


def get_user_name_from_jwt(jwt_token):
    data = decode_jwt_payload(jwt_token)
    for claim in ("email", "preferred_username", "upn", "sub"):
        value = data.get(claim)
        if value:
            return str(value)
    return None


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


def raise_for_response_error(response, context):
    status_code = getattr(response, "status_code", None)
    try:
        is_error = status_code is not None and int(status_code) >= 400
    except (TypeError, ValueError):
        is_error = False
    if not is_error:
        return

    reason = getattr(response, "reason", "") or ""
    message = f"{context}: HTTP {status_code}"
    if reason:
        message = f"{message} {reason}"
    errors = extract_response_errors(response)
    raise SubmissionAPIError(message, errors=errors)


def extract_response_errors(response):
    try:
        response_data = response.json()
    except ValueError:
        response_data = getattr(response, "text", "")
    errors = collect_response_error_messages(response_data)
    return deduplicate_strings(errors)


def collect_response_error_messages(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        errors = []
        for item in value:
            errors.extend(collect_response_error_messages(item))
        return errors
    if not isinstance(value, dict):
        return [str(value)]

    field = first_present_value(value, "field", "fieldName", "property", "propertyPath", "path", "name")
    message = first_present_value(value, "message", "errorMessage", "error_message", "detail", "reason", "cause")
    if field and message and not isinstance(message, (dict, list)):
        return [f"{field}: {message}"]

    errors = []
    preferred_keys = (
        "message",
        "errorMessage",
        "error_message",
        "detail",
        "details",
        "error",
        "errors",
        "violations",
        "rootCauses",
        "causes",
        "fieldErrors",
        "validationErrors",
    )
    for key in preferred_keys:
        if key in value:
            child_errors = collect_response_error_messages(value[key])
            if key in {"errors", "violations", "rootCauses", "causes", "fieldErrors", "validationErrors"}:
                errors.extend(child_errors)
            else:
                errors.extend(child_errors)
    if errors:
        return errors

    for key, child_value in value.items():
        for child_error in collect_response_error_messages(child_value):
            errors.append(f"{key}: {child_error}")
    return errors


def first_present_value(value, *keys):
    for key in keys:
        item = value.get(key)
        if item not in (None, ""):
            return item
    return None


def deduplicate_strings(values):
    deduplicated = []
    seen = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        deduplicated.append(text)
        seen.add(text)
    return deduplicated


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
    return deduplicate_validation_errors(collect_validation_errors(report))


def enrich_validation_errors_with_isa_json(errors, isa_json):
    enriched_errors = []
    for error in errors:
        enriched_error = dict(error)
        if get_first_present_validation_value(enriched_error, "value", "invalidValue", "actualValue") is None:
            metadata_path = get_first_validation_value(enriched_error, "jsonPath", "path")
            metadata_value = get_isa_json_value(isa_json, metadata_path)
            if metadata_value is not None:
                enriched_error["value"] = metadata_value
        enriched_errors.append(enriched_error)
    return enriched_errors


def collect_validation_errors(value, section_name="", assume_error=False):
    errors = []
    if isinstance(value, list):
        for item in value:
            errors.extend(collect_validation_errors(item, section_name=section_name, assume_error=assume_error))
        return errors

    if not isinstance(value, dict):
        return errors

    current_section = (
        value.get("section")
        or value.get("sectionName")
        or value.get("context")
        or section_name
    )
    if is_validation_error_item(value) or (assume_error and has_validation_message(value)):
        error = dict(value)
        if current_section:
            error.setdefault("section", current_section)
        errors.append(error)

    for key in ("violations", "details", "errors", "rootCauses", "causes"):
        if key in value:
            errors.extend(
                collect_validation_errors(
                    value[key],
                    section_name=current_section,
                    assume_error=key in ("errors", "rootCauses", "causes"),
                )
            )

    for key in ("content", "taskResult", "task_result", "messages", "validation", "validations", "report", "reports", "children"):
        if key in value:
            errors.extend(collect_validation_errors(value[key], section_name=current_section))

    return errors


def is_validation_error_item(value):
    if not isinstance(value, dict):
        return False

    for key in ("type", "status", "severity", "level"):
        indicator = value.get(key)
        if isinstance(indicator, str) and indicator.upper() in ("ERROR", "FAIL", "FAILED", "FATAL"):
            return True
    return False


def has_validation_message(value):
    return any(
        value.get(key)
        for key in (
            "message",
            "violation",
            "title",
            "val_message",
            "description",
            "reason",
            "rootCause",
            "root_cause",
        )
    )


def deduplicate_validation_errors(errors):
    deduplicated = []
    seen = set()
    for error in errors:
        key = json.dumps(error, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(error)
    return deduplicated


def format_validation_error(error):
    section = error.get("section") or "Unknown section"
    message = get_validation_error_message(error)
    details = []

    location = format_validation_location(error)
    if location:
        details.append(f"location={location}")

    field = get_validation_error_field(error)
    if field:
        details.append(f"field={field}")

    rule = get_validation_error_rule(error)
    if rule:
        details.append(f"rule={rule}")

    invalid_value = get_validation_error_value(error)
    if invalid_value is not None:
        details.append(f"value={format_validation_detail_value(invalid_value)}")

    if details:
        return f"{section}: {message} | " + " | ".join(details)
    return f"{section}: {message}"


def format_validation_location(error):
    metadata_file = get_first_validation_value(
        error,
        "metadata_file",
        "source_file",
        "sourceFile",
        "file",
        "filename",
        "fileName",
    )
    line = get_first_validation_value(error, "line", "lineNumber", "line_number", "row", "rowNumber", "row_number")
    column = get_first_validation_value(error, "column", "columnNumber", "column_number", "col")

    location = str(metadata_file) if metadata_file else ""
    if line not in (None, ""):
        location = f"{location}:{line}" if location else f"line {line}"
    if column not in (None, ""):
        location = f"{location}:{column}" if location else f"column {column}"
    return location


def get_first_validation_value(error, *keys):
    for key in keys:
        value = error.get(key)
        if value not in (None, ""):
            return value
    return None


def get_first_present_validation_value(error, *keys):
    for key in keys:
        if key in error and error[key] is not None:
            return error[key]
    return None


def get_validation_error_message(error):
    return (
        error.get("message")
        or error.get("violation")
        or error.get("title")
        or error.get("val_message")
        or error.get("description")
        or error.get("reason")
        or error.get("rootCause")
        or error.get("root_cause")
        or "Validation error"
    )


def get_validation_error_field(error):
    return get_first_validation_value(
        error,
        "field",
        "sourceColumnHeader",
        "source_column_header",
        "column",
        "property",
        "attribute",
        "path",
        "jsonPath",
    )


def get_validation_error_rule(error):
    return get_first_validation_value(
        error,
        "rule",
        "identifier",
        "ruleId",
        "rule_id",
        "val_sequence",
        "code",
        "validator",
    )


def get_validation_error_value(error):
    return get_first_present_validation_value(error, "value", "values", "invalidValue", "actualValue")


def format_validation_detail_value(value):
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def get_isa_json_value(isa_json, metadata_path):
    if not metadata_path:
        return None

    tokens = parse_metadata_path(str(metadata_path))
    current_value = isa_json
    for token in tokens:
        if isinstance(current_value, dict):
            current_value = current_value.get(token)
            continue
        if isinstance(current_value, list):
            try:
                current_value = current_value[int(token)]
                continue
            except (ValueError, IndexError):
                return None
        return None
    return current_value


def parse_metadata_path(metadata_path):
    if metadata_path.startswith("/"):
        return [token for token in metadata_path.strip("/").split("/") if token]

    path = metadata_path[2:] if metadata_path.startswith("$.") else metadata_path
    tokens = []
    current_token = []
    index_token = []
    in_index = False

    for character in path:
        if character == "." and not in_index:
            if current_token:
                tokens.append("".join(current_token))
                current_token = []
            continue
        if character == "[":
            if current_token:
                tokens.append("".join(current_token))
                current_token = []
            in_index = True
            index_token = []
            continue
        if character == "]" and in_index:
            tokens.append("".join(index_token).strip("'\""))
            in_index = False
            continue
        if in_index:
            index_token.append(character)
        else:
            current_token.append(character)

    if current_token:
        tokens.append("".join(current_token))
    return [token for token in tokens if token]


def get_validation_root_causes(errors):
    root_causes = []
    for error in errors:
        root_cause = {
            "section": error.get("section") or "Unknown section",
            "message": get_validation_error_message(error),
        }
        title = get_first_validation_value(error, "title")
        if title and title != root_cause["message"]:
            root_cause["title"] = title
        location = format_validation_location(error)
        if location:
            root_cause["location"] = location
        field = get_validation_error_field(error)
        if field:
            root_cause["field"] = field
        rule = get_validation_error_rule(error)
        if rule:
            root_cause["rule"] = rule
        column_index = get_first_validation_value(error, "sourceColumnIndex", "source_column_index")
        if column_index not in (None, ""):
            root_cause["columnIndex"] = column_index
        invalid_value = get_validation_error_value(error)
        if invalid_value is not None:
            root_cause["value"] = invalid_value
        root_causes.append(root_cause)
    return root_causes


def get_default_validation_report_path(study_id):
    return DEFAULT_LOCAL_SUBMISSION_CACHE_PATH / study_id / f"{study_id}_validation_report.json"


def get_default_isa_json_path(study_id):
    return DEFAULT_LOCAL_SUBMISSION_CACHE_PATH / study_id / f"{study_id}.json"


def get_validation_result(study_id, report, isa_json=None, include_root_causes=False):
    if not isinstance(report, dict):
        return report

    content = report.get("content")
    if isinstance(content, dict) and ("taskResult" in content or "task_result" in content):
        validation_result = content.get("taskResult") or content.get("task_result")
    else:
        validation_result = report

    if not isinstance(validation_result, dict):
        return validation_result

    output = dict(validation_result)
    output.setdefault("accession", normalize_study_id(study_id))
    if include_root_causes:
        errors = get_validation_errors(validation_result)
        if isa_json:
            errors = enrich_validation_errors_with_isa_json(errors, isa_json)
        if errors:
            output["rootCauses"] = get_validation_root_causes(errors)
    return output


def save_validation_report(study_id, report, validation_file_path=None, isa_json=None, include_root_causes=False):
    default_path = get_default_validation_report_path(study_id)
    output_path = resolve_json_output_path(
        validation_file_path,
        default_path.parent,
        default_path.name,
    )
    if output_path.exists() and output_path.is_dir():
        raise SubmissionAPIError(f"Validation report path is a directory: {output_path}")

    return write_json_file(
        get_validation_result(study_id, report, isa_json=isa_json, include_root_causes=include_root_causes),
        output_path,
    )


def save_isa_json(study_id, isa_json, isa_json_file_path=None):
    default_path = get_default_isa_json_path(study_id)
    output_path = resolve_json_output_path(
        isa_json_file_path,
        default_path.parent,
        default_path.name,
    )
    if output_path.exists() and output_path.is_dir():
        raise SubmissionAPIError(f"ISA JSON path is a directory: {output_path}")

    return write_json_file(isa_json, output_path)
