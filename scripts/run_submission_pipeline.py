#!/usr/bin/env python3
"""Run the initial MetaboLights submission flow in CI.

Inputs are provided through environment variables so the script can be used from
GitLab manual pipeline variables without putting credentials or study content in
the repository.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from mtblspy.commands.submissions.client import get_validation_errors
except Exception:  # pragma: no cover - keeps failure messages useful before install.
    get_validation_errors = None


DEFAULT_DATA_PATH = Path.home() / "metabolights_data" / "submission" / "data"


def main() -> int:
    reports_dir = env_path("REPORTS_DIR", Path.cwd() / "submission" / "reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    default_submission_data_path = env_path("DEFAULT_SUBMISSION_DATA_PATH", DEFAULT_DATA_PATH)
    study_input_file = env_path(
        "STUDY_INPUT_FILE",
        default_submission_data_path / "study_input.json",
    )
    prepare_study_input(study_input_file)

    authenticate()

    create_response_path = reports_dir / "create_response.json"
    run(
        [
            "mtbls",
            "submission",
            "create",
            "--input-file",
            str(study_input_file),
            "-o",
            str(create_response_path),
        ]
    )
    create_response = read_json(create_response_path)
    study_id = extract_study_id(create_response)
    if not study_id:
        raise PipelineError(f"Could not find study accession in {create_response_path}")
    study_id = study_id.strip().upper()
    print(f"Created provisional study: {study_id}", flush=True)

    metadata_files_path = env_path(
        "METADATA_FILES_PATH",
        default_submission_data_path / study_id,
    )
    data_files_root_path = env_path(
        "DATA_FILES_ROOT_PATH",
        metadata_files_path / "FILES",
    )

    metadata_response_path = reports_dir / "metadata_upload_response.json"
    metadata_cmd = [
        "mtbls",
        "submission",
        "metadata-upload",
        study_id,
        "--default-submission-data-path",
        str(default_submission_data_path),
        "--metadata-files-path",
        str(metadata_files_path),
        "-o",
        str(metadata_response_path),
    ]
    add_optional(metadata_cmd, "--mtbls-submission-endpoint", "MTBLS_SUBMISSION_ENDPOINT")
    add_optional(metadata_cmd, "--selected-files", "SELECTED_METADATA_FILES")
    run(metadata_cmd)
    assert_success_response(metadata_response_path, "metadata upload")

    if env_bool("CLEAN_FTP_TEMP_FILES", False):
        cleanup_response_path = reports_dir / "clean_ftp_temp_files_response.json"
        cleanup_cmd = [
            "mtbls",
            "submission",
            "clean-ftp-temp-files",
            study_id,
            "-o",
            str(cleanup_response_path),
        ]
        add_optional(cleanup_cmd, "--mtbls-submission-endpoint", "MTBLS_SUBMISSION_ENDPOINT")
        run(cleanup_cmd)
        assert_success_response(cleanup_response_path, "FTP temporary file cleanup")

    data_response_path = reports_dir / "data_upload_response.json"
    data_cmd = [
        "mtbls",
        "submission",
        "upload-data",
        study_id,
        "--data-files-root-path",
        str(data_files_root_path),
        "--no-progress",
        "-o",
        str(data_response_path),
    ]
    add_optional(data_cmd, "--mtbls-submission-endpoint", "MTBLS_SUBMISSION_ENDPOINT")
    add_optional(data_cmd, "--selected-files", "SELECTED_DATA_FILES")
    add_optional(data_cmd, "--skip-uploaded-files", "SKIP_UPLOADED_FILES")
    add_optional(data_cmd, "--skip-empty-folders", "SKIP_EMPTY_FOLDERS")
    run(data_cmd)
    assert_success_response(data_response_path, "data upload")

    if env_bool("RUN_LOCAL_VALIDATION", True):
        local_report_path = reports_dir / "local_validation_report.json"
        local_input_path = reports_dir / "local_validation_input.json"
        local_validation_cmd = [
            "mtbls",
            "submission",
            "validate",
            study_id,
            "--metadata-files-path",
            str(metadata_files_path),
            "--data-files-root-path",
            str(data_files_root_path),
            "--validation-input-path",
            str(local_input_path),
            "-o",
            str(local_report_path),
        ]
        add_optional(local_validation_cmd, "--validation-bundle-path", "VALIDATION_BUNDLE_PATH")
        add_optional(local_validation_cmd, "--validation-bundle-url", "VALIDATION_BUNDLE_URL")
        add_flag(local_validation_cmd, "--refetch-validation-bundle", "REFETCH_VALIDATION_BUNDLE")
        add_optional(local_validation_cmd, "--opa-executable-path", "OPA_EXECUTABLE_PATH")
        add_optional(local_validation_cmd, "--config-file", "VALIDATION_CONFIG_FILE")
        add_optional(local_validation_cmd, "--overridden-rules-file-path", "OVERRIDDEN_RULES_FILE_PATH")
        add_optional(local_validation_cmd, "--timeout", "LOCAL_VALIDATION_TIMEOUT")
        run(local_validation_cmd)
        assert_validation_success(local_report_path, "local validation")

    if env_bool("RUN_REMOTE_VALIDATION", True):
        remote_report_path = reports_dir / "remote_validation_report.json"
        remote_validation_cmd = [
            "mtbls",
            "submission",
            "validate",
            study_id,
            "--remote-validation",
            "-o",
            str(remote_report_path),
        ]
        add_optional(remote_validation_cmd, "--mtbls-submission-endpoint", "MTBLS_SUBMISSION_ENDPOINT")
        add_optional(remote_validation_cmd, "--mtbls-validation-endpoint", "MTBLS_VALIDATION_ENDPOINT")
        add_optional(remote_validation_cmd, "--max-polls", "REMOTE_VALIDATION_MAX_POLLS")
        add_optional(remote_validation_cmd, "--poll-interval", "REMOTE_VALIDATION_POLL_INTERVAL")
        run(remote_validation_cmd)
        assert_validation_success(remote_report_path, "remote validation")

    write_pipeline_outputs(reports_dir, study_id)
    print(f"Submission pipeline completed successfully for {study_id}", flush=True)
    return 0


def authenticate() -> None:
    if os.getenv("MTBLS_API_KEY"):
        if (
            env_bool("RUN_REMOTE_VALIDATION", True)
            and not os.getenv("MTBLS_USER")
            and not os.getenv("MTBLS_USERNAME")
        ):
            raise PipelineError(
                "Set MTBLS_USER or MTBLS_USERNAME when using MTBLS_API_KEY with remote validation."
            )
        return

    user_name = os.getenv("MTBLS_USER") or os.getenv("MTBLS_USERNAME")
    password = os.getenv("MTBLS_PASSWORD")
    if not user_name or not password:
        raise PipelineError(
            "Set either MTBLS_API_KEY plus MTBLS_USER, or MTBLS_USER and MTBLS_PASSWORD."
        )

    login_cmd = ["mtbls", "auth", "login", "--user", user_name, "--password", password]
    if os.getenv("MTBLS_BASE_URL"):
        login_cmd.extend(["--base-url", os.environ["MTBLS_BASE_URL"]])
    run(login_cmd)


def prepare_study_input(study_input_file: Path) -> None:
    study_input_file.parent.mkdir(parents=True, exist_ok=True)
    raw_json = os.getenv("STUDY_INPUT_JSON_CONTENT")
    study_input_json = os.getenv("STUDY_INPUT_JSON")

    if raw_json:
        write_json_string(study_input_file, raw_json, "STUDY_INPUT_JSON_CONTENT")
        return

    if study_input_json:
        candidate = expand_path(study_input_json)
        if candidate.exists():
            if candidate.resolve() != study_input_file.resolve():
                shutil.copyfile(candidate, study_input_file)
            return
        if study_input_json.lstrip().startswith(("{", "[")):
            write_json_string(study_input_file, study_input_json, "STUDY_INPUT_JSON")
            return
        raise PipelineError(
            "STUDY_INPUT_JSON must be either raw JSON content or a path to an existing JSON file."
        )

    if not study_input_file.exists():
        raise PipelineError(
            f"Study input file does not exist: {study_input_file}. "
            "Set STUDY_INPUT_JSON, STUDY_INPUT_JSON_CONTENT, or STUDY_INPUT_FILE."
        )


def write_json_string(path: Path, raw_json: str, variable_name: str) -> None:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise PipelineError(f"{variable_name} is not valid JSON: {exc}") from exc
    path.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")


def run(args: list[str]) -> None:
    print("+ " + " ".join(mask_sensitive_args(args)), flush=True)
    completed = subprocess.run(args, check=False)
    if completed.returncode != 0:
        raise PipelineError(
            f"Command failed with exit code {completed.returncode}: "
            + " ".join(mask_sensitive_args(args))
        )


def add_optional(args: list[str], option: str, env_name: str) -> None:
    value = os.getenv(env_name)
    if value:
        args.extend([option, value])


def add_flag(args: list[str], option: str, env_name: str) -> None:
    if env_bool(env_name, False):
        args.append(option)


def assert_success_response(path: Path, label: str) -> None:
    payload = read_json(path)
    status = str(payload.get("status", "success")).lower()
    errors = payload.get("errors") or []
    if status not in {"success", "succeeded"} or errors:
        raise PipelineError(f"{label} failed. See {path}")


def assert_validation_success(path: Path, label: str) -> None:
    payload = read_json(path)
    status = str(payload.get("status", "")).lower()
    errors = collect_validation_errors(payload)
    if status in {"failed", "error", "fail", "fatal"} or errors:
        print(f"{label} found {len(errors)} error(s). Report: {path}", flush=True)
        raise PipelineError(f"{label} failed validation checks. See {path}")


def collect_validation_errors(payload: dict) -> list[dict]:
    explicit_errors = payload.get("errors")
    if isinstance(explicit_errors, list) and explicit_errors:
        return explicit_errors
    if get_validation_errors:
        return get_validation_errors(payload)
    return []


def extract_study_id(payload: dict) -> str | None:
    studies = payload.get("studies")
    if isinstance(studies, dict) and studies:
        return next(iter(studies.keys()))
    return payload.get("study_id") or payload.get("accession")


def write_pipeline_outputs(reports_dir: Path, study_id: str) -> None:
    (reports_dir / "study_id.txt").write_text(study_id + "\n", encoding="utf-8")
    (reports_dir / "submission.env").write_text(f"STUDY_ID={study_id}\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def env_path(name: str, default: Path) -> Path:
    return expand_path(os.getenv(name, str(default)))


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def mask_sensitive_args(args: list[str]) -> list[str]:
    masked: list[str] = []
    hide_next = False
    for arg in args:
        if hide_next:
            masked.append("****")
            hide_next = False
            continue
        masked.append(arg)
        if arg in {"--password"}:
            hide_next = True
    return masked


class PipelineError(RuntimeError):
    pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
