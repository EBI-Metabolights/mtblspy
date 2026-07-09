import json
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from mtblspy.commands.submissions.client import (
    DataUploadResult,
    FileDeleteResult,
    FileDownloadResult,
    FtpTemporaryCleanupResult,
    MetadataUploadResult,
    ValidationResult,
    ValidationRootCauseResult,
)
from mtblspy.commands.submissions.exceptions import SubmissionAPIError
from mtblspy.commands.submissions.local_validation import LocalValidationResult
from mtblspy.commands.submissions.models import FtpUploadDetails
from mtblspy.commands.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


def load_stdout_json_prefix(output):
    payload, _index = json.JSONDecoder().raw_decode(output)
    return payload


def test_cli_help(runner):
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "MetaboLights Submission CLI" in result.output
    assert "config" in result.output
    assert "submission" in result.output


@patch("mtblspy.commands.auth.login.SubmissionClient")
def test_auth_login_success(mock_client_cls, runner):
    client = MagicMock()
    client.rest_api_base_url = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        ["auth", "login", "--user", "user@example.org", "--password", "password"],
    )

    assert result.exit_code == 0
    assert "Login successful." in result.output
    client.login.assert_called_once_with("user@example.org", "password")


@patch("mtblspy.commands.auth.login.SubmissionClient")
def test_auth_login_uses_configured_base_url(mock_client_cls, runner, monkeypatch):
    monkeypatch.setattr("mtblspy.config._CREDENTIAL_STORE.get_base_url", lambda: "https://configured.example/ws")
    client = MagicMock()
    client.rest_api_base_url = "https://configured.example/ws"
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        ["auth", "login", "--user", "user@example.org", "--password", "password"],
    )

    assert result.exit_code == 0
    mock_client_cls.assert_called_once_with(base_url=None)
    client.login.assert_called_once_with("user@example.org", "password")


@patch("mtblspy.commands.auth.login.SubmissionClient")
def test_auth_login_uses_provided_base_url(mock_client_cls, runner):
    client = MagicMock()
    client.rest_api_base_url = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        [
            "auth",
            "login",
            "--user",
            "user@example.org",
            "--password",
            "password",
            "--base-url",
            "https://wwwdev.ebi.ac.uk/metabolights/ws",
        ],
    )

    assert result.exit_code == 0
    mock_client_cls.assert_called_once_with(base_url="https://wwwdev.ebi.ac.uk/metabolights/ws")
    client.login.assert_called_once_with("user@example.org", "password")


@patch("mtblspy.commands.auth.login.SubmissionClient")
def test_auth_login_prompts_for_missing_values(mock_client_cls, runner):
    client = MagicMock()
    client.rest_api_base_url = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        ["auth", "login"],
        input="user@example.org\npassword\n",
    )

    assert result.exit_code == 0
    assert "Please enter your MetaboLights username or email" in result.output
    client.login.assert_called_once_with("user@example.org", "password")


@patch("mtblspy.commands.auth.logout.clear_session")
@patch("mtblspy.commands.auth.logout.SubmissionClient")
def test_auth_logout_clears_current_session(mock_client_cls, mock_clear_session, runner):
    client = MagicMock()
    client.rest_api_base_url = "https://www.ebi.ac.uk/metabolights/ws"
    client.submission_api_base_url = "https://www.ebi.ac.uk/metabolights/ws3"
    client.credential_base_url = None
    mock_client_cls.return_value = client

    result = runner.invoke(cli, ["auth", "logout"])

    assert result.exit_code == 0
    assert "Logged out" in result.output
    mock_clear_session.assert_called_once_with(
        "https://www.ebi.ac.uk/metabolights/ws",
        "https://www.ebi.ac.uk/metabolights/ws3",
        credential_base_url=None,
    )


@patch("mtblspy.commands.auth.logout.clear_session")
@patch("mtblspy.commands.auth.logout.SubmissionClient")
def test_auth_logout_with_base_url_clears_url_specific_session(mock_client_cls, mock_clear_session, runner):
    client = MagicMock()
    client.rest_api_base_url = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    client.submission_api_base_url = "https://wwwdev.ebi.ac.uk/metabolights/ws3"
    client.credential_base_url = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_client_cls.return_value = client

    result = runner.invoke(cli, ["auth", "logout", "--base-url", "https://wwwdev.ebi.ac.uk/metabolights/ws"])

    assert result.exit_code == 0
    mock_client_cls.assert_called_once_with(base_url="https://wwwdev.ebi.ac.uk/metabolights/ws")
    mock_clear_session.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws",
        "https://wwwdev.ebi.ac.uk/metabolights/ws3",
        credential_base_url="https://wwwdev.ebi.ac.uk/metabolights/ws",
    )


@patch("mtblspy.commands.auth.logout.clear_session")
@patch("mtblspy.commands.auth.logout.SubmissionClient")
def test_auth_logout_warns_when_env_credentials_remain(
    mock_client_cls,
    mock_clear_session,
    runner,
    monkeypatch,
):
    monkeypatch.setenv("MTBLS_API_KEY", "env-key")
    client = MagicMock()
    client.rest_api_base_url = "https://www.ebi.ac.uk/metabolights/ws"
    client.submission_api_base_url = "https://www.ebi.ac.uk/metabolights/ws3"
    client.credential_base_url = None
    mock_client_cls.return_value = client

    result = runner.invoke(cli, ["auth", "logout"])

    assert result.exit_code == 0
    assert "MTBLS_API_KEY" in result.output
    mock_clear_session.assert_called_once()


def test_config_show_prints_effective_config(runner, monkeypatch):
    monkeypatch.setenv("MTBLS_BASE_URL", "https://example.org/metabolights/ws")

    result = runner.invoke(cli, ["config", "show"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {"base_url": "https://example.org/metabolights/ws"}


@patch("mtblspy.commands.config.config_set.save_config")
@patch("mtblspy.commands.config.config_set.get_config")
def test_config_set_saves_base_url(mock_get_config, mock_save_config, runner):
    mock_get_config.return_value = {"base_url": "https://wwwdev.ebi.ac.uk/metabolights/ws"}

    result = runner.invoke(cli, ["config", "set", "--base-url", "https://wwwdev.ebi.ac.uk/metabolights/ws"])

    assert result.exit_code == 0
    mock_save_config.assert_called_once_with(base_url="https://wwwdev.ebi.ac.uk/metabolights/ws")
    assert "Base URL saved: https://wwwdev.ebi.ac.uk/metabolights/ws" in result.output


@patch("mtblspy.commands.submissions.submission_list.SubmissionClient")
def test_submission_list_success(mock_client_cls, runner):
    client = MagicMock()
    client.rest_api_base_url = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    client.list_studies.return_value = [
        {"accession": "MTBLS123", "status": "Private", "title": "Test Study"}
    ]
    mock_client_cls.return_value = client

    result = runner.invoke(cli, ["submission", "list", "--base-url", "https://wwwdev.ebi.ac.uk/metabolights/ws"])

    assert result.exit_code == 0
    mock_client_cls.assert_called_once_with(base_url="https://wwwdev.ebi.ac.uk/metabolights/ws")
    assert "MTBLS123" in result.output
    assert "Private" in result.output
    assert "Test Study" in result.output


@patch("mtblspy.commands.submissions.submission_list.SubmissionClient")
def test_submission_list_writes_json_output(mock_client_cls, runner, tmp_path, monkeypatch):
    monkeypatch.setattr("mtblspy.commands.submissions.submission_list.DEFAULT_LOCAL_SUBMISSION_CACHE_PATH", tmp_path)
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.rest_api_base_url = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    client.list_studies.return_value = [
        {"accession": "MTBLS123", "status": "Private", "title": "Test Study"}
    ]
    mock_client_cls.return_value = client

    result = runner.invoke(cli, ["submission", "list", "-o", "studies.json"])

    assert result.exit_code == 0
    output_file = tmp_path / "studies.json"
    assert json.loads(output_file.read_text(encoding="utf-8")) == client.list_studies.return_value
    assert f"Studies JSON saved to {output_file}" in result.output


@patch("mtblspy.commands.submissions.submission_create.SubmissionClient")
def test_submission_create_json_success(mock_client_cls, runner, tmp_path):
    input_file = tmp_path / "study-create.json"
    input_file.write_text(
        json.dumps(
            {
                "title": "Metadata Test Study",
                "description": "Test Description",
                "selectedStudyCategories": {"ms-mhd-legacy": ["MS"]},
                "datasetLicenseAgreement": True,
                "datasetPolicyAgreement": True,
            }
        ),
        encoding="utf-8",
    )
    client = MagicMock()
    client.create_study.return_value = {"studies": {"MTBLS-NEW": {}}}
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        [
            "submission",
            "create",
            "--input-file",
            str(input_file),
            "--base-url",
            "https://wwwdev.ebi.ac.uk/metabolights/ws",
        ],
    )

    assert result.exit_code == 0
    mock_client_cls.assert_called_once_with(base_url="https://wwwdev.ebi.ac.uk/metabolights/ws")
    assert "Study created successfully: MTBLS-NEW" in result.output
    client.create_study.assert_called_once()


@patch("mtblspy.commands.submissions.submission_create.SubmissionClient")
def test_submission_create_failure_prints_server_response_details(mock_client_cls, runner, tmp_path):
    input_file = tmp_path / "study-create.json"
    input_file.write_text(
        json.dumps(
            {
                "title": "",
                "description": "Test Description",
                "selectedStudyCategories": {"ms-mhd-legacy": ["MS"]},
                "datasetLicenseAgreement": True,
                "datasetPolicyAgreement": True,
            }
        ),
        encoding="utf-8",
    )
    client = MagicMock()
    client.create_study.side_effect = SubmissionAPIError(
        "Study creation failed: HTTP 400 Bad Request",
        errors=[
            "Study creation request is invalid.",
            "title: must not be blank",
            "contacts[0].email: must be a valid email address",
        ],
    )
    mock_client_cls.return_value = client

    result = runner.invoke(cli, ["submission", "create", "--input-file", str(input_file)])

    assert result.exit_code == 1
    assert "Study creation failed: HTTP 400 Bad Request" in result.output
    assert "Server response:" in result.output
    assert "Study creation request is invalid." in result.output
    assert "title: must not be blank" in result.output
    assert "contacts[0].email: must be a valid email address" in result.output


@patch("mtblspy.commands.submissions.submission_create.SubmissionClient")
def test_submission_create_writes_json_output(mock_client_cls, runner, tmp_path, monkeypatch):
    monkeypatch.setattr("mtblspy.commands.submissions.submission_create.DEFAULT_LOCAL_SUBMISSION_CACHE_PATH", tmp_path)
    monkeypatch.chdir(tmp_path)
    input_file = tmp_path / "study-create.json"
    input_file.write_text(
        json.dumps(
            {
                "title": "Metadata Test Study",
                "description": "Test Description",
                "selectedStudyCategories": {"ms-mhd-legacy": ["MS"]},
                "datasetLicenseAgreement": True,
                "datasetPolicyAgreement": True,
            }
        ),
        encoding="utf-8",
    )
    client = MagicMock()
    client.create_study.return_value = {"studies": {"MTBLS-NEW": {}}}
    mock_client_cls.return_value = client

    result = runner.invoke(cli, ["submission", "create", "--input-file", str(input_file), "-o", "response.json"])

    assert result.exit_code == 0
    output_file = tmp_path / "response.json"
    assert json.loads(output_file.read_text(encoding="utf-8")) == {"studies": {"MTBLS-NEW": {}}}
    assert f"Study creation response JSON saved to {output_file}" in result.output


def test_submission_sample_input_writes_json(runner, tmp_path):
    result = runner.invoke(cli, ["submission", "templates", "study-creation-input", "--data-folder", str(tmp_path)])

    assert result.exit_code == 0
    output_file = tmp_path / "study_input.json"
    assert output_file.exists()
    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert data["title"] == "A new study submission"
    assert "Sample study input JSON saved" in result.output


def test_submission_study_creation_input_writes_named_output(runner, tmp_path, monkeypatch):
    monkeypatch.setattr("mtblspy.commands.submissions.client.DEFAULT_STUDY_INPUT_DATA_FOLDER", tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli, ["submission", "templates", "study-creation-input", "-o", "custom.json"])

    assert result.exit_code == 0
    output_file = tmp_path / "custom.json"
    assert output_file.exists()
    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert data["title"] == "A new study submission"
    assert f"Sample study input JSON saved to {output_file}" in result.output


def test_submission_templates_help_shows_child_command(runner):
    result = runner.invoke(cli, ["submission", "templates", "-h"])

    assert result.exit_code == 0
    assert "Commands:" in result.output
    assert "study-creation-input" in result.output
    assert "isa-tab-file" in result.output
    assert "result-file" in result.output
    assert "Create a sample study creation JSON input file." in result.output


@patch("mtblspy.commands.submissions.template_files.requests.get")
def test_submission_templates_isa_tab_file_downloads_template(mock_get, runner, tmp_path):
    response = MagicMock()
    response.status_code = 200
    response.content = b"template-content"
    response.headers = {"Content-Disposition": 'attachment; filename="a_assay.txt"'}
    mock_get.return_value = response

    result = runner.invoke(
        cli,
        [
            "submission",
            "templates",
            "isa-tab-file",
            "assay",
            "--template-name",
            "LC-MS",
            "--version",
            "1.0",
            "--target-path",
            str(tmp_path),
            "--mtbls-validation-endpoint",
            "https://wwwdev.ebi.ac.uk/metabolights/ws3",
        ],
    )

    assert result.exit_code == 0
    assert (tmp_path / "a_assay.txt").read_bytes() == b"template-content"
    mock_get.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws3/public/v2/submission/file-template",
        params={"file_type": "assay", "template_name": "LC-MS", "version": "1.0"},
        timeout=60,
    )


@patch("mtblspy.commands.submissions.template_files.requests.get")
def test_submission_templates_isa_tab_file_fails_when_target_exists_without_override(mock_get, runner, tmp_path):
    target_file = tmp_path / "i_investigation.txt"
    target_file.write_text("existing", encoding="utf-8")
    response = MagicMock()
    response.status_code = 200
    response.content = b"new-content"
    response.headers = {"Content-Disposition": 'attachment; filename="i_investigation.txt"'}
    mock_get.return_value = response

    result = runner.invoke(
        cli,
        [
            "submission",
            "templates",
            "isa-tab-file",
            "investigation",
            "--target-path",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    assert "Template file already exists" in result.output
    assert target_file.read_text(encoding="utf-8") == "existing"


@patch("mtblspy.commands.submissions.template_files.requests.get")
def test_submission_templates_isa_tab_file_retries_without_version_after_server_error(mock_get, runner, tmp_path):
    failed_response = MagicMock()
    failed_response.status_code = 500
    failed_response.content = b'{"error_message":"UnboundLocalError"}'
    failed_response.headers = {}

    successful_response = MagicMock()
    successful_response.status_code = 200
    successful_response.content = b"template-content"
    successful_response.headers = {"Content-Disposition": 'attachment; filename="a_assay.txt"'}
    mock_get.side_effect = [failed_response, successful_response]

    result = runner.invoke(
        cli,
        [
            "submission",
            "templates",
            "isa-tab-file",
            "assay",
            "--template-name",
            "LC-MS",
            "--version",
            "1.0",
            "--target-path",
            str(tmp_path),
            "--mtbls-validation-endpoint",
            "https://wwwdev.ebi.ac.uk/metabolights/ws3",
        ],
    )

    assert result.exit_code == 0
    assert (tmp_path / "a_assay.txt").read_bytes() == b"template-content"
    assert mock_get.call_args_list[0].kwargs["params"] == {
        "file_type": "assay",
        "template_name": "LC-MS",
        "version": "1.0",
    }
    assert mock_get.call_args_list[1].kwargs["params"] == {
        "file_type": "assay",
        "template_name": "LC-MS",
    }


@patch("mtblspy.commands.submissions.template_files.requests.get")
def test_submission_templates_result_file_uses_default_maf_type(mock_get, runner, tmp_path):
    response = MagicMock()
    response.status_code = 200
    response.content = b"maf-template"
    response.headers = {}
    mock_get.return_value = response

    result = runner.invoke(
        cli,
        [
            "submission",
            "templates",
            "result-file",
            "--template-name",
            "MS",
            "--target-path",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert (tmp_path / "assignment_MS.tsv").read_bytes() == b"maf-template"
    mock_get.assert_called_once_with(
        "https://www.ebi.ac.uk/metabolights/ws3/public/v2/submission/file-template",
        params={"file_type": "assignment", "template_name": "MS"},
        timeout=60,
    )


@patch("mtblspy.commands.submissions.submission_ftp_credentials.SubmissionClient")
def test_submission_ftp_credentials_success(mock_client_cls, runner):
    client = MagicMock()
    client.get_private_ftp_credentials.return_value = FtpUploadDetails(
        study_id="MTBLS123",
        ftp_folder="/incoming/MTBLS123",
        ftp_host="ftp-private.ebi.ac.uk",
        ftp_user="ftp-user",
        ftp_password="ftp-password",
    )
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        ["submission", "ftp-credentials", "MTBLS123", "--base-url", "https://wwwdev.ebi.ac.uk/metabolights/ws"],
    )

    assert result.exit_code == 0
    mock_client_cls.assert_called_once_with(base_url="https://wwwdev.ebi.ac.uk/metabolights/ws")
    assert "ftp-private.ebi.ac.uk" in result.output
    assert "ftp-password" in result.output
    client.get_private_ftp_credentials.assert_called_once_with("MTBLS123")


@patch("mtblspy.commands.submissions.submission_ftp_credentials.SubmissionClient")
def test_submission_ftp_credentials_writes_json_output(mock_client_cls, runner, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "mtblspy.commands.submissions.submission_ftp_credentials.DEFAULT_LOCAL_SUBMISSION_CACHE_PATH",
        tmp_path,
    )
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.get_private_ftp_credentials.return_value = FtpUploadDetails(
        study_id="MTBLS123",
        ftp_folder="/incoming/MTBLS123",
        ftp_host="ftp-private.ebi.ac.uk",
        ftp_user="ftp-user",
        ftp_password="ftp-password",
    )
    mock_client_cls.return_value = client

    result = runner.invoke(cli, ["submission", "ftp-credentials", "MTBLS123", "-o", "ftp.json"])

    assert result.exit_code == 0
    output_file = tmp_path / "ftp.json"
    assert json.loads(output_file.read_text(encoding="utf-8"))["ftp_password"] == "ftp-password"
    assert f"FTP credentials JSON saved to {output_file}" in result.output


@patch("mtblspy.commands.submissions.submission_download.SubmissionClient")
def test_submission_download_metadata_uses_base_url_and_files(mock_client_cls, runner, tmp_path):
    downloaded_file = tmp_path / "i_Investigation.txt"
    client = MagicMock()
    client.download_metadata_files.return_value = FileDownloadResult(
        study_id="MTBLS123",
        downloaded_files=[downloaded_file],
        skipped_files=[],
        missing_files=[],
    )
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        [
            "submission",
            "download",
            "MTBLS123",
            "metadata",
            "--base-url",
            "https://wwwdev.ebi.ac.uk/metabolights/ws",
            "--files",
            "i_Investigation.txt,m_MTBLS123.tsv",
            "--target-path",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    mock_client_cls.assert_called_once_with(base_url="https://wwwdev.ebi.ac.uk/metabolights/ws")
    client.download_metadata_files.assert_called_once_with(
        "MTBLS123",
        target_path=str(tmp_path),
        selected_files="i_Investigation.txt,m_MTBLS123.tsv",
    )
    payload = json.loads(result.output)
    assert payload["status"] == "success"
    assert payload["downloaded_files"] == [str(downloaded_file)]


@patch("mtblspy.commands.submissions.submission_download.SubmissionClient")
def test_submission_download_data_uses_base_url_and_files(mock_client_cls, runner, tmp_path):
    downloaded_file = tmp_path / "raw" / "file.raw"
    client = MagicMock()
    client.download_data_files.return_value = FileDownloadResult(
        study_id="MTBLS123",
        downloaded_files=[downloaded_file],
        skipped_files=[],
        missing_files=[],
    )
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        [
            "submission",
            "download",
            "MTBLS123",
            "data",
            "--base-url",
            "https://wwwdev.ebi.ac.uk/metabolights/ws",
            "--files",
            "raw",
            "--target-path",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    mock_client_cls.assert_called_once_with(base_url="https://wwwdev.ebi.ac.uk/metabolights/ws")
    client.download_data_files.assert_called_once_with(
        "MTBLS123",
        target_path=str(tmp_path),
        selected_files="raw",
        download_all=False,
    )
    payload = json.loads(result.output)
    assert payload["status"] == "success"
    assert payload["downloaded_files"] == [str(downloaded_file)]


@patch("mtblspy.commands.submissions.submission_download.SubmissionClient")
def test_submission_download_data_requires_files_or_all(mock_client_cls, runner):
    result = runner.invoke(cli, ["submission", "download", "MTBLS123", "data"])

    assert result.exit_code == 1
    assert "Data download requires --files" in result.output
    mock_client_cls.assert_not_called()


@patch("mtblspy.commands.submissions.submission_download.SubmissionClient")
def test_submission_download_data_all_requires_explicit_flag(mock_client_cls, runner, tmp_path):
    downloaded_file = tmp_path / "raw" / "file.raw"
    client = MagicMock()
    client.download_data_files.return_value = FileDownloadResult(
        study_id="MTBLS123",
        downloaded_files=[downloaded_file],
        skipped_files=[],
        missing_files=[],
    )
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        [
            "submission",
            "download",
            "MTBLS123",
            "data",
            "--all",
            "--target-path",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    client.download_data_files.assert_called_once_with(
        "MTBLS123",
        target_path=str(tmp_path),
        selected_files=None,
        download_all=True,
    )
    payload = json.loads(result.output)
    assert payload["status"] == "success"


@patch("mtblspy.commands.submissions.submission_download.SubmissionClient")
def test_submission_download_data_rejects_files_with_all(mock_client_cls, runner):
    result = runner.invoke(cli, ["submission", "download", "MTBLS123", "data", "--files", "raw", "--all"])

    assert result.exit_code == 1
    assert "Use either --files or --all" in result.output
    mock_client_cls.assert_not_called()


@patch("mtblspy.commands.submissions.submission_delete.SubmissionClient")
def test_submission_delete_metadata_uses_base_url_and_files(mock_client_cls, runner):
    client = MagicMock()
    client.delete_metadata_files.return_value = FileDeleteResult(
        study_id="MTBLS123",
        deleted_files=["i_Investigation.txt", "s_MTBLS123.txt"],
        missing_files=[],
    )
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        [
            "submission",
            "delete",
            "metadata",
            "MTBLS123",
            "--base-url",
            "https://wwwdev.ebi.ac.uk/metabolights/ws",
            "--files",
            "i_Investigation.txt,s_MTBLS123.txt",
        ],
    )

    assert result.exit_code == 0
    mock_client_cls.assert_called_once_with(base_url="https://wwwdev.ebi.ac.uk/metabolights/ws")
    client.delete_metadata_files.assert_called_once_with(
        "MTBLS123",
        selected_files="i_Investigation.txt,s_MTBLS123.txt",
    )
    payload = json.loads(result.output)
    assert payload["status"] == "success"
    assert payload["deleted_files"] == ["i_Investigation.txt", "s_MTBLS123.txt"]


@patch("mtblspy.commands.submissions.submission_delete.SubmissionClient")
def test_submission_delete_metadata_prints_api_error_details(mock_client_cls, runner):
    client = MagicMock()
    client.delete_metadata_files.side_effect = SubmissionAPIError(
        "Metadata delete failed for MTBLS123.",
        errors=["HTTP 400 BAD REQUEST - Unable to delete selected files."],
    )
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        [
            "submission",
            "delete",
            "metadata",
            "MTBLS123",
            "--files",
            "i_Investigation.txt",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "failed"
    assert payload["message"] == "Metadata delete failed for MTBLS123."
    assert payload["errors"] == ["HTTP 400 BAD REQUEST - Unable to delete selected files."]


@patch("mtblspy.commands.submissions.submission_download.SubmissionClient")
def test_submission_download_metadata_uses_output_as_target_path(mock_client_cls, runner, tmp_path):
    client = MagicMock()
    client.download_metadata_files.return_value = FileDownloadResult(
        study_id="MTBLS123",
        downloaded_files=[tmp_path / "i_Investigation.txt"],
        skipped_files=[],
        missing_files=[],
    )
    mock_client_cls.return_value = client

    result = runner.invoke(cli, ["submission", "download", "MTBLS123", "metadata", "-o", str(tmp_path)])

    assert result.exit_code == 0
    client.download_metadata_files.assert_called_once_with(
        "MTBLS123",
        target_path=str(tmp_path),
        selected_files=None,
    )


@patch("mtblspy.commands.submissions.submission_download.SubmissionClient")
def test_submission_download_data_uses_output_as_target_path(mock_client_cls, runner, tmp_path):
    client = MagicMock()
    client.download_data_files.return_value = FileDownloadResult(
        study_id="MTBLS123",
        downloaded_files=[tmp_path / "raw" / "file.raw"],
        skipped_files=[],
        missing_files=[],
    )
    mock_client_cls.return_value = client

    result = runner.invoke(cli, ["submission", "download", "MTBLS123", "data", "--files", "raw", "-o", str(tmp_path)])

    assert result.exit_code == 0
    client.download_data_files.assert_called_once_with(
        "MTBLS123",
        target_path=str(tmp_path),
        selected_files="raw",
        download_all=False,
    )


@patch("mtblspy.commands.submissions.submission_upload_metadata.SubmissionClient")
def test_submission_upload_metadata_success(mock_client_cls, runner, tmp_path):
    metadata_file = tmp_path / "i_Investigation.txt"
    skipped_file = tmp_path / "s_MTBLS123.txt"
    metadata_file.write_text("metadata", encoding="utf-8")
    skipped_file.write_text("samples", encoding="utf-8")
    client = MagicMock()
    client.rest_api_base_url = "https://www.ebi.ac.uk/metabolights/ws"
    client.upload_metadata.return_value = MetadataUploadResult(
        study_id="MTBLS123",
        uploaded_files=[metadata_file],
        skipped_files=[skipped_file],
        responses=[{"success": True}],
    )
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        [
            "submission",
            "metadata-upload",
            "MTBLS123",
            "--metadata-files-path",
            str(tmp_path),
            "--selected-files",
            "i_Investigation.txt",
            "--base-url",
            "https://wwwdev.ebi.ac.uk/metabolights/ws",
        ],
    )

    assert result.exit_code == 0
    mock_client_cls.assert_called_once_with(base_url="https://wwwdev.ebi.ac.uk/metabolights/ws")
    payload = json.loads(result.output)
    assert payload["status"] == "success"
    assert payload["uploaded_files"] == ["i_Investigation.txt"]
    assert payload["skipped_files"] == ["s_MTBLS123.txt"]
    assert payload["message"] == "Uploaded 1 metadata file(s) for MTBLS123."
    assert "Message" not in payload
    client.upload_metadata.assert_called_once()
    assert client.upload_metadata.call_args.args == ("MTBLS123",)
    assert client.upload_metadata.call_args.kwargs["metadata_path"] == str(tmp_path)
    assert client.upload_metadata.call_args.kwargs["selected_files"] == ["i_Investigation.txt"]
    assert client.upload_metadata.call_args.kwargs["default_submission_data_path"].endswith(
        "/metabolights_data/submission/data"
    )


@patch("mtblspy.commands.submissions.submission_upload_metadata.SubmissionClient")
def test_submission_upload_metadata_writes_json_output(mock_client_cls, runner, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "mtblspy.commands.submissions.submission_upload_metadata.DEFAULT_LOCAL_SUBMISSION_CACHE_PATH",
        tmp_path / "cache",
    )
    monkeypatch.chdir(tmp_path)
    metadata_file = tmp_path / "i_Investigation.txt"
    metadata_file.write_text("metadata", encoding="utf-8")

    client = MagicMock()
    client.rest_api_base_url = "https://upload.example/metabolights/ws"
    client.upload_metadata.return_value = MetadataUploadResult(
        study_id="MTBLS123",
        uploaded_files=[metadata_file],
        responses=[{"success": True}],
    )
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        [
            "submission",
            "metadata-upload",
            "MTBLS123",
            "--metadata-files-path",
            str(tmp_path),
            "--mtbls-submission-endpoint",
            "upload.example/metabolights/ws",
            "-o",
            "upload.json",
        ],
    )

    assert result.exit_code == 0
    output_file = tmp_path / "upload.json"
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["parameters"][3]["value"] == "https://upload.example/metabolights/ws"
    assert payload["uploaded_files"] == ["i_Investigation.txt"]
    mock_client_cls.assert_called_once_with(base_url="https://upload.example/metabolights/ws")


@patch("mtblspy.commands.submissions.submission_upload_metadata.SubmissionClient")
def test_submission_upload_metadata_failure_prints_readable_errors(mock_client_cls, runner, tmp_path):
    client = MagicMock()
    client.rest_api_base_url = "https://www.ebi.ac.uk/metabolights/ws"
    client.upload_metadata.side_effect = SubmissionAPIError(
        "Metadata upload failed for 2 file(s).",
        errors=[
            "i_Investigation.txt: HTTP 400 - There is no study.",
            "s_MTBLS123.txt: HTTP 400 - There is no study.",
        ],
    )
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        [
            "submission",
            "metadata-upload",
            "MTBLS123",
            "--metadata-files-path",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "failed"
    assert payload["message"] == "Metadata upload failed for 2 file(s)."
    assert payload["errors"] == [
        "i_Investigation.txt: HTTP 400 - There is no study.",
        "s_MTBLS123.txt: HTTP 400 - There is no study.",
    ]
    assert '{"content":null' not in result.output


@patch("mtblspy.commands.submissions.submission_upload_data.SubmissionClient")
def test_submission_upload_data_success(mock_client_cls, runner, tmp_path):
    client = MagicMock()
    client.rest_api_base_url = "https://www.ebi.ac.uk/metabolights/ws"
    client.upload_data_files.return_value = DataUploadResult(
        study_id="MTBLS123",
        uploaded_files=["folder1/file1.raw"],
        skipped_files=["folder1/file2.raw"],
        missing_on_local=[],
    )
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        [
            "submission",
            "data-upload",
            "MTBLS123",
            "--data-files-root-path",
            str(tmp_path),
            "--selected-files",
            "folder1",
            "--skip-uploaded-files",
            "folder2",
            "--skip-empty-folders",
            "empty-folder",
            "--base-url",
            "https://wwwdev.ebi.ac.uk/metabolights/ws",
        ],
    )

    assert result.exit_code == 0
    mock_client_cls.assert_called_once_with(base_url="https://wwwdev.ebi.ac.uk/metabolights/ws")
    payload = json.loads(result.output)
    assert payload["status"] == "success"
    assert payload["uploaded_files"] == ["folder1/file1.raw"]
    assert payload["skipped_files"] == ["folder1/file2.raw"]
    assert payload["missing_on_local"] == []
    assert "Message" not in payload
    client.upload_data_files.assert_called_once_with(
        "MTBLS123",
        data_files_root_path=str(tmp_path),
        selected_files=["folder1"],
        skip_uploaded_files=["folder2"],
        skip_empty_folders=["empty-folder"],
    )


@patch("mtblspy.commands.submissions.submission_upload_data.SubmissionClient")
def test_submission_upload_data_writes_json_output(mock_client_cls, runner, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "mtblspy.commands.submissions.submission_upload_data.DEFAULT_LOCAL_SUBMISSION_CACHE_PATH",
        tmp_path / "cache",
    )
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.rest_api_base_url = "https://upload.example/metabolights/ws"
    client.upload_data_files.return_value = DataUploadResult(
        study_id="MTBLS123",
        uploaded_files=[],
        skipped_files=[],
        missing_on_local=["missing.raw"],
    )
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        [
            "submission",
            "data-upload",
            "MTBLS123",
            "--data-files-root-path",
            str(tmp_path),
            "--selected-files",
            "missing.raw",
            "--mtbls-submission-endpoint",
            "upload.example/metabolights/ws",
            "-o",
            "data-upload.json",
        ],
    )

    assert result.exit_code == 0
    output_file = tmp_path / "data-upload.json"
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["missing_on_local"] == ["missing.raw"]
    mock_client_cls.assert_called_once_with(base_url="https://upload.example/metabolights/ws")


@patch("mtblspy.commands.submissions.submission_clean_ftp_temp_files.SubmissionClient")
def test_submission_clean_ftp_temp_files_success(mock_client_cls, runner):
    client = MagicMock()
    client.rest_api_base_url = "https://www.ebi.ac.uk/metabolights/ws"
    client.clear_ftp_temporary_files.return_value = FtpTemporaryCleanupResult(
        study_id="MTBLS123",
        deleted_files=[".ftp_file1.raw", "folder1/.ftp_file2.raw"],
        errors=[],
    )
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        ["submission", "clean-ftp-temp-files", "MTBLS123", "--base-url", "https://wwwdev.ebi.ac.uk/metabolights/ws"],
    )

    assert result.exit_code == 0
    mock_client_cls.assert_called_once_with(base_url="https://wwwdev.ebi.ac.uk/metabolights/ws")
    payload = json.loads(result.output)
    assert payload["status"] == "success"
    assert payload["deleted_files"] == [".ftp_file1.raw", "folder1/.ftp_file2.raw"]
    assert payload["errors"] == []
    assert payload["message"] == "Deleted 2 FTP temporary file(s) for MTBLS123."
    assert "Message" not in payload
    client.clear_ftp_temporary_files.assert_called_once_with("MTBLS123")


@patch("mtblspy.commands.submissions.submission_validate.SubmissionClient")
def test_submission_validate_remote_prints_json_report(mock_client_cls, runner, tmp_path):
    report_path = tmp_path / "validation-report.json"
    report_path.write_text('{"accession": "MTBLS123", "messages": {"violations": []}}\n', encoding="utf-8")

    validation_result = MagicMock()
    validation_result.errors = []
    validation_result.report_path = report_path

    client = MagicMock()
    client.validate_study.return_value = validation_result
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        [
            "submission",
            "validate",
            "MTBLS123",
            "--remote-validation",
            "--validation-file-path",
            str(report_path),
            "--base-url",
            "https://wwwdev.ebi.ac.uk/metabolights/ws",
        ],
    )

    assert result.exit_code == 0
    mock_client_cls.assert_called_once_with(base_url="https://wwwdev.ebi.ac.uk/metabolights/ws")
    payload = load_stdout_json_prefix(result.output)
    assert payload["accession"] == "MTBLS123"
    assert payload["messages"] == {"violations": []}
    assert result.output.rstrip().endswith(f"Validation report JSON saved to {report_path}")
    client.validate_study.assert_called_once_with(
        "MTBLS123",
        validation_file_path=str(report_path),
        max_polls=120,
        poll_interval=5,
    )


def test_submission_help_shows_validate_without_validate_local(runner):
    result = runner.invoke(cli, ["submission", "--help"])

    assert result.exit_code == 0
    assert "compress-data-files" in result.output
    assert "validate" in result.output
    assert "validate-local" not in result.output
    assert "validation-debug" not in result.output


def test_submission_validate_requires_data_files_root_for_local_validation(runner):
    result = runner.invoke(cli, ["submission", "validate", "MTBLS123"])

    assert result.exit_code == 1
    assert "--data-files-root-path is required unless --remote-validation is used." in result.output


def test_submission_compress_data_files_zips_dot_d_and_updates_metadata(runner, tmp_path):
    study_path = tmp_path / "MTBLS123"
    data_directory = study_path / "FILES" / "sample 01.d"
    data_directory.mkdir(parents=True)
    (data_directory / "analysis.bin").write_bytes(b"raw-data")
    metadata_file = study_path / "a_MTBLS123_lc-ms.txt"
    metadata_file.write_text(
        "Raw Spectral Data File\tDerived Spectral Data File\n"
        "FILES/sample 01.d\tFILES/sample 01.d.zip\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        cli,
        ["submission", "compress-data-files", "MTBLS123", "--study-path", str(study_path)],
    )

    zip_path = study_path / "FILES" / "sample 01.d.zip"
    assert result.exit_code == 0
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.namelist() == ["sample 01.d/analysis.bin"]
    assert data_directory.exists()
    assert metadata_file.read_text(encoding="utf-8") == (
        "Raw Spectral Data File\tDerived Spectral Data File\n"
        "FILES/sample 01.d.zip\tFILES/sample 01.d.zip\n"
    )
    assert "Compressed 1 .d directory for MTBLS123." in result.output
    assert "Updated 1 metadata file(s)." in result.output


def test_submission_compress_data_files_skips_existing_zip_without_overwrite(runner, tmp_path):
    study_path = tmp_path / "MTBLS123"
    data_directory = study_path / "FILES" / "sample.d"
    data_directory.mkdir(parents=True)
    (data_directory / "analysis.bin").write_bytes(b"raw-data")
    zip_path = study_path / "FILES" / "sample.d.zip"
    zip_path.write_bytes(b"existing")
    metadata_file = study_path / "a_MTBLS123_lc-ms.txt"
    metadata_file.write_text("FILES/sample.d\n", encoding="utf-8")

    result = runner.invoke(
        cli,
        ["submission", "compress-data-files", "MTBLS123", "--study-path", str(study_path)],
    )

    assert result.exit_code == 0
    assert zip_path.read_bytes() == b"existing"
    assert metadata_file.read_text(encoding="utf-8") == "FILES/sample.d\n"
    assert "Compressed 0 .d directories for MTBLS123." in result.output
    assert "Skipped 1 existing .d.zip file(s)." in result.output


def test_submission_compress_data_files_can_remove_original_directories(runner, tmp_path):
    study_path = tmp_path / "MTBLS123"
    data_directory = study_path / "FILES" / "sample.d"
    data_directory.mkdir(parents=True)
    (data_directory / "analysis.bin").write_bytes(b"raw-data")
    (study_path / "i_Investigation.txt").write_text("metadata\n", encoding="utf-8")

    result = runner.invoke(
        cli,
        [
            "submission",
            "compress-data-files",
            "MTBLS123",
            "--study-path",
            str(study_path),
            "--remove-original",
        ],
    )

    assert result.exit_code == 0
    assert (study_path / "FILES" / "sample.d.zip").exists()
    assert not data_directory.exists()
    assert "Removed 1 original .d directory." in result.output


def test_submission_check_folders_reports_success_for_valid_local_layout(runner, tmp_path):
    study_path = build_check_folders_study(tmp_path, "MTBLS123")
    report_path = tmp_path / "folder_check_report.json"

    result = runner.invoke(
        cli,
        [
            "submission",
            "check-folders",
            "MTBLS123",
            "--metadata-files-path",
            str(study_path),
            "--data-files-path",
            str(study_path / "FILES"),
            "-o",
            str(report_path),
        ],
    )

    assert result.exit_code == 0
    payload = load_stdout_json_prefix(result.output)
    assert payload["status"] == "success"
    assert payload["errors"] == []
    assert payload["summary"]["metadata_files"] == 4
    assert payload["summary"]["referenced_raw_files"] == 2
    assert payload["summary"]["referenced_assignment_files"] == 1
    assert json.loads(report_path.read_text(encoding="utf-8")) == payload
    assert result.output.rstrip().endswith(f"Folder check report JSON saved to {report_path}")


def test_submission_check_folders_saves_report_to_default_cache_without_output(runner, tmp_path, monkeypatch):
    study_path = build_check_folders_study(tmp_path, "MTBLS123")
    cache_path = tmp_path / "cache"
    monkeypatch.setattr(
        "mtblspy.commands.submissions.submission_check_folders.DEFAULT_LOCAL_SUBMISSION_CACHE_PATH",
        cache_path,
    )

    result = runner.invoke(
        cli,
        [
            "submission",
            "check-folders",
            "MTBLS123",
            "--metadata-files-path",
            str(study_path),
            "--data-files-path",
            str(study_path / "FILES"),
        ],
    )

    report_path = cache_path / "MTBLS123" / "MTBLS123_folder_check_report.json"
    assert result.exit_code == 0
    payload = load_stdout_json_prefix(result.output)
    assert json.loads(report_path.read_text(encoding="utf-8")) == payload
    assert result.output.rstrip().endswith(f"Folder check report JSON saved to {report_path}")


def test_submission_check_folders_reports_folder_and_reference_errors(runner, tmp_path):
    study_path = build_check_folders_study(tmp_path, "MTBLS123")
    (study_path / "bad name.txt").write_text("bad\n", encoding="utf-8")
    (study_path / "FILES" / "bad raw.raw").write_bytes(b"raw-data")
    (study_path / "a_MTBLS123_lc-ms.txt").write_text(
        "Sample Name\tAssay Name\tRaw Spectral Data File\tDerived Spectral Data File\tMetabolite Assignment File\n"
        "sample1\tassay1\tmissing.raw\tFILES/missing-derived.raw\tm_MTBLS123.tsv\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        cli,
        [
            "submission",
            "check-folders",
            "MTBLS123",
            "--metadata-files-path",
            str(study_path),
            "--data-files-path",
            str(study_path / "FILES"),
        ],
    )

    assert result.exit_code == 1
    payload = load_stdout_json_prefix(result.output)
    assert payload["status"] == "failed"
    error_codes = {error["code"] for error in payload["errors"]}
    assert "filename_contains_invalid_characters" in error_codes
    assert "metadata_filename_invalid" in error_codes
    assert "data_reference_without_files_prefix" in error_codes
    assert "referenced_data_file_missing" in error_codes


def build_check_folders_study(tmp_path, study_id):
    study_path = tmp_path / study_id
    data_path = study_path / "FILES"
    data_path.mkdir(parents=True)
    (data_path / "raw1.raw").write_bytes(b"raw-data")
    (data_path / "raw2.raw").write_bytes(b"raw-data")
    (study_path / "i_Investigation.txt").write_text(
        "INVESTIGATION\n"
        f"Investigation Identifier\t{study_id}\n"
        "Investigation Title\tValid investigation\n"
        "Investigation Description\tValid investigation description\n"
        "STUDY\n"
        f"Study Identifier\t{study_id}\n"
        "Study Title\tValid study\n"
        "Study Description\tValid study description\n"
        "STUDY DESIGN DESCRIPTORS\n"
        "Study Design Type\tcase control design\ttime series design\tmetabolite profiling\n"
        "STUDY FACTORS\n"
        "Study Factor Name\ttreatment\n"
        "Study Factor Type\ttreatment\n"
        "STUDY PROTOCOLS\n"
        "Study Protocol Name\tsample collection\n"
        "Study Protocol Type\tsample collection\n"
        "Study Protocol Description\tCollect samples\n"
        "STUDY CONTACTS\n"
        "Study Person Last Name\tSmith\n"
        "Study Person First Name\tJane\n"
        "Study Person Email\tjane@example.org\n"
        "Study Person Affiliation\tExample Institute\n"
        "Study Person Roles\tprincipal investigator\n"
        "STUDY ASSAYS\n"
        f"Study Assay File Name\ta_{study_id}_lc-ms.txt\n",
        encoding="utf-8",
    )
    (study_path / f"s_{study_id}.txt").write_text(
        "Source Name\tSample Name\tFactor Value[treatment]\n"
        "source1\tsample1\tcontrol\n"
        "source2\tsample2\ttreated\n",
        encoding="utf-8",
    )
    (study_path / f"a_{study_id}_lc-ms.txt").write_text(
        "Sample Name\tAssay Name\tRaw Spectral Data File\tMetabolite Assignment File\n"
        "sample1\tassay1\tFILES/raw1.raw\tm_MTBLS123.tsv\n"
        "sample2\tassay2\tFILES/raw2.raw\tm_MTBLS123.tsv\n",
        encoding="utf-8",
    )
    (study_path / "m_MTBLS123.tsv").write_text(
        "metabolite_identification\tdatabase_identifier\n"
        "glucose\tHMDB0000122\n",
        encoding="utf-8",
    )
    return study_path


@patch("mtblspy.commands.submissions.submission_validate.run_local_validation")
def test_submission_validate_runs_local_validation_by_default(mock_run_local_validation, runner, tmp_path):
    report_path = tmp_path / "local-validation-report.json"
    input_path = tmp_path / "local-validation-input.json"
    report_path.write_text('{"accession": "MTBLS123", "status": "success", "errors": []}\n', encoding="utf-8")
    mock_run_local_validation.return_value = LocalValidationResult(
        report={"status": "success", "errors": []},
        errors=[],
        report_path=report_path,
        validation_input_path=input_path,
    )

    result = runner.invoke(
        cli,
        [
            "submission",
            "validate",
            "MTBLS123",
            "--metadata-files-path",
            str(tmp_path),
            "--data-files-root-path",
            str(tmp_path / "FILES"),
            "-o",
            "local-report.json",
            "--validation-input-path",
            str(input_path),
        ],
    )

    assert result.exit_code == 0
    payload = load_stdout_json_prefix(result.output)
    assert payload["status"] == "success"
    assert result.output.rstrip().endswith(f"Validation report JSON saved to {report_path}")
    mock_run_local_validation.assert_called_once_with(
        "MTBLS123",
        metadata_path=str(tmp_path),
        data_files_path=str(tmp_path / "FILES"),
        default_submission_data_path=str(Path.home() / "metabolights_data" / "submission" / "data"),
        validation_bundle_path="./bundle.tar.gz",
        validation_bundle_url="https://ebi-metabolights.github.io/mtbls-validation/bundle.tar.gz",
        refetch_validation_bundle=False,
        opa_executable_path="opa",
        validation_wasm_path=None,
        validation_wasm_url=None,
        validation_file_path="local-report.json",
        validation_input_path=str(input_path),
        config_file=None,
        overridden_rules_file_path=None,
        timeout=120,
    )


@patch("mtblspy.commands.submissions.submission_validation_debug.SubmissionClient")
def test_submission_validation_debug_command(mock_client_cls, runner, tmp_path):
    isa_json_path = tmp_path / "MTBLS123.json"
    remote_report_path = tmp_path / "remote-validation.json"
    debug_report_path = tmp_path / "validation-debug.json"

    client = MagicMock()
    client.find_validation_root_causes.return_value = ValidationRootCauseResult(
        isa_json_path=isa_json_path,
        validation_result=ValidationResult(
            report={"messages": {"violations": []}},
            errors=[
                {
                    "type": "ERROR",
                    "section": "Assay",
                    "violation": "Raw data file 'missing.raw' is referenced but was not found.",
                    "sourceFile": "a_MTBLS123_lc-ms.txt",
                    "sourceColumnHeader": "Raw Spectral Data File",
                    "identifier": "rule_a_100_001",
                    "values": ["missing.raw"],
                }
            ],
            report_path=remote_report_path,
        ),
    )
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        [
            "submission",
            "validation-debug",
            "MTBLS123",
            "--isa-json-file-path",
            str(isa_json_path),
            "--validation-file-path",
            str(debug_report_path),
            "--remote-validation-file-path",
            str(remote_report_path),
            "--base-url",
            "https://wwwdev.ebi.ac.uk/metabolights/ws",
        ],
        )

    assert result.exit_code == 0
    mock_client_cls.assert_called_once_with(base_url="https://wwwdev.ebi.ac.uk/metabolights/ws")
    assert "Remote validation completed with 1 error(s)." in result.output
    assert "Raw data file 'missing.raw' is referenced but was not found." in result.output
    assert f"ISA JSON is saved as {isa_json_path}" in result.output
    assert f"Remote validation root-cause report is saved as {remote_report_path}" in result.output
    assert f"Combined validation debug report is saved as {debug_report_path}" in result.output
    saved_debug_report = json.loads(debug_report_path.read_text(encoding="utf-8"))
    assert saved_debug_report["summary"]["remoteErrorCount"] == 1
    assert saved_debug_report["summary"]["localErrorCount"] == 0
    client.find_validation_root_causes.assert_called_once_with(
        "MTBLS123",
        isa_json_file_path=str(isa_json_path),
        validation_file_path=str(remote_report_path),
        max_polls=120,
        poll_interval=5,
    )


@patch("mtblspy.commands.submissions.submission_validation_debug.run_local_validation")
@patch("mtblspy.commands.submissions.submission_validation_debug.SubmissionClient")
def test_submission_validation_debug_command_compares_local_errors(mock_client_cls, mock_run_local_validation, runner, tmp_path):
    metadata_path = tmp_path / "metadata"
    metadata_path.mkdir()
    isa_json_path = tmp_path / "MTBLS123.json"
    remote_report_path = tmp_path / "remote-validation.json"
    local_report_path = tmp_path / "local-validation.json"
    local_input_path = tmp_path / "local-input.json"
    debug_report_path = tmp_path / "validation-debug.json"

    remote_error = {
        "type": "ERROR",
        "section": "general",
        "violation": "MHD validation failed.",
        "sourceFile": "input",
        "identifier": "rule___500_100_001_01",
    }
    local_error = {
        "type": "ERROR",
        "section": "files.general",
        "violation": "Referenced raw file is missing.",
        "sourceFile": "a_MTBLS123.txt",
        "sourceColumnHeader": "Raw Spectral Data File",
        "identifier": "rule_f_400_090_001_01",
    }

    client = MagicMock()
    client.find_validation_root_causes.return_value = ValidationRootCauseResult(
        isa_json_path=isa_json_path,
        validation_result=ValidationResult(
            report={"messages": {"violations": [remote_error]}},
            errors=[remote_error],
            report_path=remote_report_path,
        ),
    )
    mock_client_cls.return_value = client
    mock_run_local_validation.return_value = LocalValidationResult(
        report={"validationResult": {"violations": [local_error]}},
        errors=[local_error],
        report_path=local_report_path,
        validation_input_path=local_input_path,
    )

    result = runner.invoke(
        cli,
        [
            "submission",
            "validation-debug",
            "MTBLS123",
            "-p",
            str(metadata_path),
            "--data-files-path",
            str(metadata_path / "FILES"),
            "--isa-json-file-path",
            str(isa_json_path),
            "-o",
            str(debug_report_path),
            "--remote-validation-file-path",
            str(remote_report_path),
        ],
    )

    assert result.exit_code == 0
    assert "Remote validation completed with 1 error(s)." in result.output
    assert "Local validation completed with 1 error(s)." in result.output
    saved_debug_report = json.loads(debug_report_path.read_text(encoding="utf-8"))
    assert saved_debug_report["summary"] == {
        "remoteErrorCount": 1,
        "localErrorCount": 1,
        "sharedErrorCount": 0,
        "remoteOnlyErrorCount": 1,
        "localOnlyErrorCount": 1,
    }
    assert saved_debug_report["remote"]["errors"] == [remote_error]
    assert saved_debug_report["local"]["errors"] == [local_error]
    assert saved_debug_report["comparison"]["remoteOnlyErrors"][0]["rule"] == "rule___500_100_001_01"
    assert saved_debug_report["comparison"]["localOnlyErrors"][0]["rule"] == "rule_f_400_090_001_01"
    mock_run_local_validation.assert_called_once()
