import json
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from mtblspy.commands.submissions.client import (
    DataUploadResult,
    MetadataUploadResult,
    ValidationResult,
    ValidationRootCauseResult,
)
from mtblspy.commands.submissions.local_validation import LocalValidationResult
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

    result = runner.invoke(cli, ["submission", "list"])

    assert result.exit_code == 0
    assert "MTBLS123" in result.output
    assert "Private" in result.output
    assert "Test Study" in result.output


@patch("mtblspy.commands.submissions.submission_list.SubmissionClient")
def test_submission_list_writes_json_output(mock_client_cls, runner, tmp_path, monkeypatch):
    monkeypatch.setattr("mtblspy.commands.submissions.submission_list.DEFAULT_LOCAL_SUBMISSION_CACHE_PATH", tmp_path)
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

    result = runner.invoke(cli, ["submission", "create", "--input-file", str(input_file)])

    assert result.exit_code == 0
    assert "Study created successfully: MTBLS-NEW" in result.output
    client.create_study.assert_called_once()


@patch("mtblspy.commands.submissions.submission_create.SubmissionClient")
def test_submission_create_writes_json_output(mock_client_cls, runner, tmp_path, monkeypatch):
    monkeypatch.setattr("mtblspy.commands.submissions.submission_create.DEFAULT_LOCAL_SUBMISSION_CACHE_PATH", tmp_path)
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
    output_file = tmp_path / "MTBLS-NEW" / "response.json"
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
    assert "Create a sample study creation JSON input file." in result.output


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


@patch("mtblspy.commands.submissions.submission_ftp_credentials.SubmissionClient")
def test_submission_ftp_credentials_writes_json_output(mock_client_cls, runner, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "mtblspy.commands.submissions.submission_ftp_credentials.DEFAULT_LOCAL_SUBMISSION_CACHE_PATH",
        tmp_path,
    )
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
    output_file = tmp_path / "MTBLS123" / "ftp.json"
    assert json.loads(output_file.read_text(encoding="utf-8"))["ftp_password"] == "ftp-password"
    assert f"FTP credentials JSON saved to {output_file}" in result.output


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
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "success"
    assert payload["uploaded_files"] == ["i_Investigation.txt"]
    assert payload["Skipped_files"] == ["s_MTBLS123.txt"]
    assert payload["Message"] == "Uploaded 1 metadata file(s) for MTBLS123."
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
    output_file = tmp_path / "cache" / "MTBLS123" / "upload.json"
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["parameters"][3]["value"] == "https://upload.example/metabolights/ws"
    assert payload["uploaded_files"] == ["i_Investigation.txt"]
    mock_client_cls.assert_called_once_with(base_url="https://upload.example/metabolights/ws")


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
            "upload-data",
            "MTBLS123",
            "--data-files-root-path",
            str(tmp_path),
            "--selected-files",
            "folder1",
            "--skip-uploaded-files",
            "folder2",
            "--skip-empty-folders",
            "empty-folder",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "success"
    assert payload["uploaded_files"] == ["folder1/file1.raw"]
    assert payload["Skipped_files"] == ["folder1/file2.raw"]
    assert payload["missing_on_local"] == []
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
            "upload-data",
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
    output_file = tmp_path / "cache" / "MTBLS123" / "data-upload.json"
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["missing_on_local"] == ["missing.raw"]
    mock_client_cls.assert_called_once_with(base_url="https://upload.example/metabolights/ws")


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
    client.validate_study.assert_called_once_with(
        "MTBLS123",
        validation_file_path=str(report_path),
        max_polls=120,
        poll_interval=5,
    )


def test_submission_help_shows_remote_and_local_validation(runner):
    result = runner.invoke(cli, ["submission", "--help"])

    assert result.exit_code == 0
    assert "compress-data-files" in result.output
    assert "validate" in result.output
    assert "validate-local" in result.output


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


@patch("mtblspy.commands.submissions.submission_validate_local.run_local_validation")
def test_submission_validate_local_command(mock_run_local_validation, runner, tmp_path):
    report_path = tmp_path / "local-validation-report.json"
    input_path = tmp_path / "local-validation-input.json"
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
            "validate-local",
            "MTBLS123",
            "--metadata-path",
            str(tmp_path),
            "-o",
            "local-report.json",
            "--validation-input-path",
            str(input_path),
        ],
    )

    assert result.exit_code == 0
    assert "Local validation completed successfully" in result.output
    assert f"Local validation report is saved as {report_path}" in result.output
    mock_run_local_validation.assert_called_once_with(
        "MTBLS123",
        metadata_path=str(tmp_path),
        data_files_path=None,
        validation_bundle_path="./bundle.tar.gz",
        validation_bundle_url="https://ebi-metabolights.github.io/mtbls-validation/bundle.tar.gz",
        refetch_validation_bundle=False,
        opa_executable_path="opa",
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

    help_result = runner.invoke(cli, ["submission", "--help"])
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
        ],
    )

    assert help_result.exit_code == 0
    assert "validation-debug" in help_result.output
    assert result.exit_code == 0
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
