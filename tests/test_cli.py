import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from mtblspy.commands.submissions.client import MetadataUploadResult
from mtblspy.commands.submissions.models import FtpUploadDetails
from mtblspy.commands.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


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
    assert "Tokens and user saved" in result.output
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
    mock_client_cls.return_value = client

    result = runner.invoke(cli, ["auth", "logout"])

    assert result.exit_code == 0
    assert "Logged out" in result.output
    mock_clear_session.assert_called_once_with(
        "https://www.ebi.ac.uk/metabolights/ws",
        "https://www.ebi.ac.uk/metabolights/ws3",
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


@patch("mtblspy.commands.submissions.submission_list.SubmissionClient")
def test_submission_list_success(mock_client_cls, runner):
    client = MagicMock()
    client.rest_api_base_url = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    client.list_studies.return_value = [
        {"accession": "MTBLS123", "status": "Private", "title": "Test Study"}
    ]
    mock_client_cls.return_value = client

    result = runner.invoke(cli, ["submission", "list"])

    assert result.exit_code == 0
    assert "MTBLS123" in result.output
    assert "Private" in result.output
    assert "Test Study" in result.output


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

    result = runner.invoke(cli, ["submission", "create", "--input-file", str(input_file)])

    assert result.exit_code == 0
    assert "Study created successfully: MTBLS-NEW" in result.output
    client.create_study.assert_called_once()


def test_submission_sample_input_writes_json(runner, tmp_path):
    result = runner.invoke(cli, ["submission", "sample-input", "--data-folder", str(tmp_path)])

    assert result.exit_code == 0
    output_file = tmp_path / "study_input.json"
    assert output_file.exists()
    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert data["title"] == "A new study submission"
    assert "Sample study input JSON saved" in result.output


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

    result = runner.invoke(cli, ["submission", "ftp-credentials", "MTBLS123"])

    assert result.exit_code == 0
    assert "ftp-private.ebi.ac.uk" in result.output
    assert "ftp-password" in result.output
    client.get_private_ftp_credentials.assert_called_once_with("MTBLS123")


@patch("mtblspy.commands.submissions.submission_upload_metadata.SubmissionClient")
def test_submission_upload_metadata_success(mock_client_cls, runner, tmp_path):
    metadata_file = tmp_path / "i_Investigation.txt"
    metadata_file.write_text("metadata", encoding="utf-8")
    client = MagicMock()
    client.upload_metadata.return_value = MetadataUploadResult(
        study_id="MTBLS123",
        uploaded_files=[metadata_file],
        responses=[{"success": True}],
    )
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        ["submission", "upload-metadata", "MTBLS123", "--metadata-path", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Uploaded 1 metadata file(s) for MTBLS123." in result.output
    assert "i_Investigation.txt" in result.output
    client.upload_metadata.assert_called_once_with(
        "MTBLS123",
        metadata_path=str(tmp_path),
        metadata_files=(),
        validate_after_upload=True,
        validation_file_path=None,
        validation_max_polls=120,
        validation_poll_interval=5,
    )


@patch("mtblspy.commands.submissions.submission_upload_metadata.SubmissionClient")
def test_submission_upload_metadata_prints_validation_errors(mock_client_cls, runner, tmp_path):
    metadata_file = tmp_path / "i_Investigation.txt"
    metadata_file.write_text("metadata", encoding="utf-8")
    report_path = tmp_path / "validation-report.json"

    validation_result = MagicMock()
    validation_result.errors = [
        {
            "type": "ERROR",
            "section": "Study",
            "title": "Missing required metadata",
            "sourceFile": "i_Investigation.txt",
            "line": 4,
            "rule": "INVESTIGATION_TITLE_REQUIRED",
        }
    ]
    validation_result.report_path = report_path

    client = MagicMock()
    client.upload_metadata.return_value = MetadataUploadResult(
        study_id="MTBLS123",
        uploaded_files=[metadata_file],
        responses=[{"success": True}],
        validation_result=validation_result,
    )
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        ["submission", "upload-metadata", "MTBLS123", "--metadata-path", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "Validation completed with 1 error(s)." in result.output
    assert "Missing required metadata" in result.output
    assert "location=i_Investigation.txt:4" in result.output
    assert f"Validation report is saved as {report_path}" in result.output


@patch("mtblspy.commands.submissions.submission_validate.SubmissionClient")
def test_submission_validate_prints_report(mock_client_cls, runner, tmp_path):
    report_path = tmp_path / "validation-report.json"
    report_path.write_text('{"messages": {"violations": []}}\n', encoding="utf-8")

    validation_result = MagicMock()
    validation_result.errors = []
    validation_result.report_path = report_path

    client = MagicMock()
    client.validate_study.return_value = validation_result
    mock_client_cls.return_value = client

    result = runner.invoke(
        cli,
        ["submission", "validate", "MTBLS123", "--validation-file-path", str(report_path)],
    )

    assert result.exit_code == 0
    assert "Validation completed successfully. No validation errors found." in result.output
    assert '{"messages": {"violations": []}}' in result.output
    assert f"Validation report is saved as {report_path}" in result.output


@patch("mtblspy.commands.submissions.submission_submit.SubmissionClient")
def test_submission_submit_blocks_status_update_when_validation_errors(mock_client_cls, runner):
    from mtblspy.commands.submissions.exceptions import StudyValidationError

    client = MagicMock()
    client.submit_study.side_effect = StudyValidationError(
        "MTBLS123",
        [
            {
                "type": "ERROR",
                "title": "Missing required metadata",
                "section": "Study",
                "sourceFile": "i_Investigation.txt",
            }
        ],
    )
    mock_client_cls.return_value = client

    result = runner.invoke(cli, ["submission", "submit", "MTBLS123", "--status", "Private"])

    assert result.exit_code != 0
    assert "Validation completed with errors" in result.output
    assert "Missing required metadata" in result.output
    assert "Study MTBLS123 has 1 validation error(s)." in result.output
