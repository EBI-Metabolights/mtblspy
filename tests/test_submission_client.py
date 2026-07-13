import json
import posixpath
from ftplib import error_perm
from unittest.mock import MagicMock, patch

import pytest

from mtblspy.commands.submissions.client import (
    SubmissionClient,
    enrich_validation_errors_with_isa_json,
    format_validation_error,
    get_validation_errors,
    get_validation_result,
    get_keycloak_token_url,
    get_studies_from_user_response,
    resolve_data_download_target_path,
    resolve_download_target_path,
    save_isa_json,
    save_sample_study_input,
    save_validation_report,
)
from mtblspy.commands.submissions.exceptions import AuthenticationError, SubmissionAPIError
from mtblspy.commands.submissions.models import StudyInputFormat


@patch("mtblspy.commands.submissions.client.save_refresh_token")
@patch("mtblspy.commands.submissions.client.save_jwt_token")
@patch("mtblspy.commands.submissions.client.save_config")
@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_login_fetches_api_token_jwt_and_refresh_token(
    mock_get_base_url,
    mock_post,
    mock_save_config,
    mock_save_jwt_token,
    mock_save_refresh_token,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    login_response = MagicMock()
    login_response.headers = {}
    login_response.json.return_value = {"content": {"apitoken": "valid-key"}}

    token_response = MagicMock()
    token_response.headers = {}
    token_response.json.return_value = {
        "access_token": "jwt-token",
        "refresh_token": "refresh-token",
        "token_type": "bearer",
    }
    mock_post.side_effect = [login_response, token_response]

    SubmissionClient().login("user@example.org", "password")

    assert mock_post.call_args_list[0].args[0] == "https://wwwdev.ebi.ac.uk/metabolights/ws/auth/login"
    assert mock_post.call_args_list[0].kwargs["headers"] == {
        "accept": "application/json",
        "Content-Type": "application/json",
    }
    assert mock_post.call_args_list[0].kwargs["json"] == {
        "email": "user@example.org",
        "secret": "password",
    }
    assert mock_post.call_args_list[1].args[0] == "https://wwwdev.ebi.ac.uk/metabolights/ws3/auth/v1/token"
    assert mock_post.call_args_list[1].kwargs["data"] == {
        "grant_type": "password",
        "username": "user@example.org",
        "password": "password",
        "client_id": "swagger-ui-test",
    }
    mock_save_config.assert_called_once_with(
        api_key="valid-key",
        base_url="https://wwwdev.ebi.ac.uk/metabolights/ws",
        user_name="user@example.org",
        credential_base_url="https://wwwdev.ebi.ac.uk/metabolights/ws",
    )
    mock_save_jwt_token.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws3",
        "jwt-token",
        credential_base_url="https://wwwdev.ebi.ac.uk/metabolights/ws",
    )
    mock_save_refresh_token.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws3",
        "refresh-token",
        credential_base_url="https://wwwdev.ebi.ac.uk/metabolights/ws",
    )


@patch("mtblspy.commands.submissions.client.save_refresh_token")
@patch("mtblspy.commands.submissions.client.save_jwt_token")
@patch("mtblspy.commands.submissions.client.save_config")
@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_login_fetches_api_token_from_accounts_when_login_token_empty(
    mock_get_base_url,
    mock_post,
    mock_get,
    mock_save_config,
    mock_save_jwt_token,
    mock_save_refresh_token,
):
    mock_get_base_url.return_value = "https://www.ebi.ac.uk/metabolights/ws"
    login_response = MagicMock()
    login_response.headers = {}
    login_response.json.return_value = {"content": {"apitoken": ""}}

    token_response = MagicMock()
    token_response.headers = {}
    token_response.json.return_value = {
        "access_token": "jwt-token",
        "refresh_token": "refresh-token",
        "token_type": "bearer",
    }

    accounts_response = MagicMock()
    accounts_response.headers = {}
    accounts_response.json.return_value = {
        "content": [
            {
                "email": "user@example.org",
                "apitoken": "valid-key",
            }
        ]
    }
    mock_post.side_effect = [login_response, token_response]
    mock_get.return_value = accounts_response

    SubmissionClient().login("user@example.org", "password")

    assert mock_get.call_args.args[0] == "https://www.ebi.ac.uk/metabolights/ws/auth/accounts"
    assert mock_get.call_args.kwargs["headers"] == {
        "accept": "application/json",
        "Authorization": "Bearer jwt-token",
    }
    mock_save_config.assert_called_once_with(
        api_key="valid-key",
        base_url="https://www.ebi.ac.uk/metabolights/ws",
        user_name="user@example.org",
        credential_base_url=None,
    )
    mock_save_jwt_token.assert_called_once_with(
        "https://www.ebi.ac.uk/metabolights/ws3",
        "jwt-token",
        credential_base_url=None,
    )
    mock_save_refresh_token.assert_called_once_with(
        "https://www.ebi.ac.uk/metabolights/ws3",
        "refresh-token",
        credential_base_url=None,
    )


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_create_study_loads_json_and_posts_camel_case_payload(
    mock_get_base_url,
    mock_get_api_key,
    mock_post,
    tmp_path,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    input_file = tmp_path / "study-create.json"
    input_file.write_text(
        json.dumps(
            {
                "title": "Metadata Test Study",
                "description": "Test Description",
                "selected_study_categories": {"ms-mhd-legacy": ["MS"]},
                "dataset_license_agreement": True,
                "dataset_policy_agreement": True,
            }
        ),
        encoding="utf-8",
    )
    response = MagicMock()
    response.json.return_value = {"studies": {"MTBLS-NEW": {}}}
    mock_post.return_value = response

    result = SubmissionClient().create_study(input_file, StudyInputFormat.JSON)

    assert result == {"studies": {"MTBLS-NEW": {}}}
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["headers"] == {"user-token": "valid-key"}
    assert kwargs["json"]["selectedStudyCategories"] == {"ms-mhd-legacy": ["MS"]}
    assert kwargs["json"]["datasetLicenseAgreement"] is True


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_create_study_raises_api_error_with_json_response_details(
    mock_get_base_url,
    mock_get_api_key,
    mock_post,
    tmp_path,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
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
    response = MagicMock()
    response.status_code = 400
    response.reason = "Bad Request"
    response.json.return_value = {
        "message": "Study creation request is invalid.",
        "errors": {
            "title": ["must not be blank"],
            "contacts[0].email": "must be a valid email address",
        },
    }
    mock_post.return_value = response

    with pytest.raises(SubmissionAPIError) as exc_info:
        SubmissionClient().create_study(input_file, StudyInputFormat.JSON)

    assert str(exc_info.value) == "Study creation failed: HTTP 400 Bad Request"
    assert exc_info.value.errors == [
        "Study creation request is invalid.",
        "title: must not be blank",
        "contacts[0].email: must be a valid email address",
    ]


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_create_study_raises_api_error_with_text_response_details(
    mock_get_base_url,
    mock_get_api_key,
    mock_post,
    tmp_path,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
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
    response = MagicMock()
    response.status_code = 500
    response.reason = "Internal Server Error"
    response.text = "Unexpected study creation failure"
    response.json.side_effect = ValueError("not json")
    mock_post.return_value = response

    with pytest.raises(SubmissionAPIError) as exc_info:
        SubmissionClient().create_study(input_file, StudyInputFormat.JSON)

    assert str(exc_info.value) == "Study creation failed: HTTP 500 Internal Server Error"
    assert exc_info.value.errors == ["Unexpected study creation failure"]


def test_get_studies_from_user_response_supports_known_response_shapes():
    expected = [{"accession": "MTBLS123", "title": "Test Study"}]

    assert get_studies_from_user_response({"content": expected}) == expected
    assert get_studies_from_user_response({"data": expected}) == expected
    assert get_studies_from_user_response({"studies": {"MTBLS123": expected[0]}}) == expected
    assert get_studies_from_user_response(expected) == expected


def test_save_sample_study_input_writes_default_json(tmp_path):
    output_path = save_sample_study_input(data_folder=tmp_path)

    assert output_path == tmp_path / "study_input.json"
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["title"] == "A new study submission"
    assert data["datasetLicenseAgreement"] is True
    assert data["datasetPolicyAgreement"] is True
    assert data["selectedStudyCategories"] == {"ms-mhd-legacy": ["MS"]}
    assert data["relatedDatasets"][0]["repository"] == "MetaboLights"
    assert data["funding"][0]["grantIdentifier"] == "EXAMPLE-GRANT-001"
    assert data["contacts"][0]["roles"][0]["annotationValue"] == "Principal Investigator"
    assert data["designDescriptors"][0]["annotationValue"] == "metabolite profiling"
    assert data["factors"] == []
    assert data["assays"] == []
    assert data["selectedSubmissionWorkflows"] == []


def test_save_sample_study_input_defaults_to_local_submission_data_folder(tmp_path, monkeypatch):
    monkeypatch.setattr("mtblspy.commands.submissions.client.DEFAULT_STUDY_INPUT_DATA_FOLDER", tmp_path)

    output_path = save_sample_study_input()

    assert output_path == tmp_path / "study_input.json"
    assert output_path.exists()


def test_save_sample_study_input_uses_filename_in_current_directory(tmp_path, monkeypatch):
    monkeypatch.setattr("mtblspy.commands.submissions.client.DEFAULT_STUDY_INPUT_DATA_FOLDER", tmp_path)
    monkeypatch.chdir(tmp_path)

    output_path = save_sample_study_input(output_path="custom_input.json")

    assert output_path == tmp_path / "custom_input.json"
    assert output_path.exists()


def test_json_download_helpers_use_current_directory_for_filenames(tmp_path, monkeypatch):
    monkeypatch.setattr("mtblspy.commands.submissions.client.DEFAULT_LOCAL_SUBMISSION_CACHE_PATH", tmp_path)
    monkeypatch.chdir(tmp_path)

    validation_path = save_validation_report(
        "MTBLS123",
        {"messages": {"summary": [], "violations": []}},
        validation_file_path="validation.json",
    )
    isa_json_path = save_isa_json("MTBLS123", {"study": {"identifier": "MTBLS123"}}, "isa.json")

    assert validation_path == tmp_path / "validation.json"
    assert isa_json_path == tmp_path / "isa.json"


def test_json_download_helpers_keep_explicit_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("mtblspy.commands.submissions.client.DEFAULT_LOCAL_SUBMISSION_CACHE_PATH", tmp_path / "cache")
    report_path = tmp_path / "reports" / "validation.json"

    output_path = save_validation_report(
        "MTBLS123",
        {"messages": {"summary": [], "violations": []}},
        validation_file_path=report_path,
    )

    assert output_path == report_path
    assert output_path.exists()


def test_download_target_paths_default_to_local_submission_data_path(tmp_path, monkeypatch):
    monkeypatch.setattr("mtblspy.commands.submissions.client.DEFAULT_LOCAL_SUBMISSION_DATA_PATH", tmp_path)

    assert resolve_download_target_path(None, "MTBLS123") == tmp_path / "MTBLS123"
    assert resolve_data_download_target_path(None, "MTBLS123") == tmp_path / "MTBLS123" / "FILES"


@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_get_private_ftp_credentials(
    mock_get_base_url,
    mock_get_api_key,
    mock_get,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    response = MagicMock()
    response.json.return_value = {
        "study_id": "MTBLS123",
        "ftp_folder": "/incoming/MTBLS123",
        "ftp_host": "ftp-private.ebi.ac.uk",
        "ftp_user": "user",
        "ftp_password": "password",
    }
    mock_get.return_value = response

    result = SubmissionClient().get_private_ftp_credentials("mtbls123")

    assert result.study_id == "MTBLS123"
    assert result.ftp_host == "ftp-private.ebi.ac.uk"
    mock_get.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws/studies/MTBLS123/upload-info",
        headers={"user-token": "valid-key"},
        timeout=30,
    )
    response.raise_for_status.assert_called_once()


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_upload_metadata_uploads_isatab_metadata_files(
    mock_get_base_url,
    mock_get_api_key,
    mock_post,
    tmp_path,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    (tmp_path / "i_Investigation.txt").write_text("investigation", encoding="utf-8")
    (tmp_path / "s_MTBLS123.txt").write_text("samples", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")
    response = MagicMock()
    response.status_code = 201
    response.content = b'{"success": true}'
    response.json.return_value = {"success": True}
    mock_post.return_value = response

    result = SubmissionClient().upload_metadata("mtbls123", metadata_path=tmp_path)

    assert [path.name for path in result.uploaded_files] == [
        "i_Investigation.txt",
        "s_MTBLS123.txt",
    ]
    assert mock_post.call_count == 2
    first_url, first_kwargs = mock_post.call_args_list[0].args[0], mock_post.call_args_list[0].kwargs
    assert first_url == "https://wwwdev.ebi.ac.uk/metabolights/ws/studies/MTBLS123/drag-drop-upload"
    assert first_kwargs["headers"] == {"user-token": "valid-key"}
    assert first_kwargs["files"]["file"][0] == "i_Investigation.txt"


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.save_jwt_token")
@patch("mtblspy.commands.submissions.client.get_refresh_token")
@patch("mtblspy.commands.submissions.client.get_jwt_token")
@patch("mtblspy.commands.submissions.client.get_user_name")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_get_submission_headers_exchanges_and_saves_jwt(
    mock_get_base_url,
    mock_get_api_key,
    mock_get_user_name,
    mock_get_jwt_token,
    mock_get_refresh_token,
    mock_save_jwt_token,
    mock_post,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    mock_get_user_name.return_value = "user@example.org"
    mock_get_jwt_token.return_value = None
    mock_get_refresh_token.return_value = None
    response = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.json.return_value = {"access_token": "jwt-token", "token_type": "bearer"}
    mock_post.return_value = response

    headers = SubmissionClient().get_submission_headers()

    assert headers == {"accept": "application/json", "Authorization": "Bearer jwt-token"}
    mock_save_jwt_token.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws3",
        "jwt-token",
        credential_base_url="https://wwwdev.ebi.ac.uk/metabolights/ws",
    )
    mock_post.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws3/auth/v1/token",
        headers={
            "accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "password", "username": "user@example.org", "client_secret": "valid-key"},
        timeout=30,
    )


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_refresh_token")
@patch("mtblspy.commands.submissions.client.get_jwt_token")
@patch("mtblspy.commands.submissions.client.get_user_name")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_get_submission_headers_requires_user_for_jwt_exchange(
    mock_get_base_url,
    mock_get_api_key,
    mock_get_user_name,
    mock_get_jwt_token,
    mock_get_refresh_token,
    mock_post,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    mock_get_user_name.return_value = None
    mock_get_jwt_token.return_value = None
    mock_get_refresh_token.return_value = None

    with pytest.raises(AuthenticationError) as exc_info:
        SubmissionClient().get_submission_headers()

    assert "requires a user name or email" in str(exc_info.value)
    mock_post.assert_not_called()


@patch("mtblspy.commands.submissions.client.save_jwt_token")
@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_refresh_token")
@patch("mtblspy.commands.submissions.client.get_jwt_token")
@patch("mtblspy.commands.submissions.client.get_user_name")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_get_submission_headers_falls_back_to_keycloak_when_ws3_auth_fails(
    mock_get_base_url,
    mock_get_api_key,
    mock_get_user_name,
    mock_get_jwt_token,
    mock_get_refresh_token,
    mock_post,
    mock_save_jwt_token,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    mock_get_user_name.return_value = "user@example.org"
    mock_get_jwt_token.return_value = None
    mock_get_refresh_token.return_value = None

    ws3_bug_response = MagicMock()
    ws3_bug_response.status_code = 401
    ws3_bug_response.headers = {}
    ws3_bug_response.json.return_value = {
        "status": "error",
        "error_message": "refresh_token Input should be a valid string",
        "content": None,
    }

    keycloak_response = MagicMock()
    keycloak_response.status_code = 200
    keycloak_response.headers = {}
    keycloak_response.json.return_value = {"access_token": "jwt-token", "token_type": "bearer"}

    mock_post.side_effect = [ws3_bug_response, keycloak_response]

    headers = SubmissionClient().get_submission_headers()

    assert headers == {"accept": "application/json", "Authorization": "Bearer jwt-token"}
    assert mock_post.call_args_list[1].args[0] == (
        "https://wwwdev.ebi.ac.uk/metabolights/test/iam/realms/metabolights/protocol/openid-connect/token"
    )
    assert mock_post.call_args_list[1].kwargs["data"] == {
        "grant_type": "client_credentials",
        "client_id": "api_user-user@example.org",
        "client_secret": "valid-key",
    }
    mock_save_jwt_token.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws3",
        "jwt-token",
        credential_base_url="https://wwwdev.ebi.ac.uk/metabolights/ws",
    )


@patch("mtblspy.commands.submissions.client.save_refresh_token")
@patch("mtblspy.commands.submissions.client.save_jwt_token")
@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_refresh_token")
@patch("mtblspy.commands.submissions.client.get_jwt_token")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_get_submission_headers_refreshes_with_stored_refresh_token(
    mock_get_base_url,
    mock_get_jwt_token,
    mock_get_refresh_token,
    mock_post,
    mock_save_jwt_token,
    mock_save_refresh_token,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_jwt_token.return_value = None
    mock_get_refresh_token.return_value = "refresh-token"
    response = MagicMock()
    response.ok = True
    response.headers = {}
    response.json.return_value = {
        "access_token": "fresh-jwt-token",
        "refresh_token": "new-refresh-token",
    }
    mock_post.return_value = response

    headers = SubmissionClient().get_submission_headers()

    assert headers == {"accept": "application/json", "Authorization": "Bearer fresh-jwt-token"}
    mock_post.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws3/auth/v1/refresh",
        headers={
            "accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "client_id": "swagger-ui-test",
            "refresh_token": "refresh-token",
        },
        timeout=30,
    )
    mock_save_jwt_token.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws3",
        "fresh-jwt-token",
        credential_base_url="https://wwwdev.ebi.ac.uk/metabolights/ws",
    )
    mock_save_refresh_token.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws3",
        "new-refresh-token",
        credential_base_url="https://wwwdev.ebi.ac.uk/metabolights/ws",
    )


@patch("mtblspy.commands.submissions.client.save_refresh_token")
@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_refresh_jwt_token_falls_back_to_keycloak_when_ws3_refresh_fails(
    mock_get_base_url,
    mock_post,
    mock_save_refresh_token,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    ws3_response = MagicMock()
    ws3_response.ok = False
    ws3_response.status_code = 401

    keycloak_response = MagicMock()
    keycloak_response.ok = True
    keycloak_response.headers = {}
    keycloak_response.json.return_value = {
        "access_token": "fresh-jwt-token",
        "refresh_token": "new-refresh-token",
    }
    mock_post.side_effect = [ws3_response, keycloak_response]

    token = SubmissionClient().refresh_jwt_token("refresh-token")

    assert token == "fresh-jwt-token"
    assert mock_post.call_args_list[1].args[0] == (
        "https://wwwdev.ebi.ac.uk/metabolights/test/iam/realms/metabolights/protocol/openid-connect/token"
    )
    assert mock_post.call_args_list[1].kwargs["data"] == {
        "grant_type": "refresh_token",
        "client_id": "swagger-ui-test",
        "refresh_token": "refresh-token",
    }
    mock_save_refresh_token.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws3",
        "new-refresh-token",
        credential_base_url="https://wwwdev.ebi.ac.uk/metabolights/ws",
    )


def test_get_keycloak_token_url_uses_wwwdev_test_iam_path():
    assert get_keycloak_token_url("https://wwwdev.ebi.ac.uk/metabolights/ws3") == (
        "https://wwwdev.ebi.ac.uk/metabolights/test/iam/realms/metabolights/protocol/openid-connect/token"
    )


@patch("mtblspy.commands.submissions.client.time.sleep")
@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_jwt_token")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_validate_study_retries_transient_task_not_found_and_saves_report(
    mock_get_base_url,
    mock_get_jwt_token,
    mock_post,
    mock_get,
    mock_sleep,
    tmp_path,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_jwt_token.return_value = "jwt-token"
    validation_start_response = MagicMock()
    validation_start_response.json.return_value = {
        "status": "success",
        "content": {
            "task": {
                "taskId": "validation-task-1",
                "taskStatus": "INITIATED",
                "ready": False,
                "isSuccessful": None,
            },
            "taskResult": None,
        },
    }
    mock_post.return_value = validation_start_response

    task_not_found_response = MagicMock()
    task_not_found_response.status_code = 404
    task_not_found_response.json.return_value = {
        "status": "error",
        "error_message": "AsyncTaskNotFoundError: No validation task found for resource_id: MTBLS123",
        "content": None,
    }
    validation_status_response = MagicMock()
    validation_status_response.status_code = 200
    validation_status_response.json.return_value = {
        "status": "success",
        "content": {
            "task": {
                "taskId": "validation-task-1",
                "taskStatus": "SUCCESS",
                "ready": True,
                "isSuccessful": True,
            },
            "taskResult": {"messages": {"summary": [], "violations": []}},
        },
    }
    mock_get.side_effect = [task_not_found_response, validation_status_response]
    report_path = tmp_path / "validation-report.json"

    result = SubmissionClient(api_token="valid-key").validate_study(
        "MTBLS123",
        validation_file_path=report_path,
    )

    assert result.errors == []
    assert json.loads(report_path.read_text(encoding="utf-8")) == {
        "messages": {"summary": [], "violations": []},
        "accession": "MTBLS123",
    }
    mock_sleep.assert_called_once_with(5)
    validation_headers = {"accept": "application/json", "Authorization": "Bearer jwt-token"}
    task_headers = {**validation_headers, "Task-Id": "validation-task-1"}
    mock_get.assert_any_call(
        "https://wwwdev.ebi.ac.uk/metabolights/ws3/submissions/v2/validations/MTBLS123/validation-task-1",
        headers=task_headers,
        timeout=30,
    )


@patch("mtblspy.commands.submissions.client.save_jwt_token")
@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_refresh_token")
@patch("mtblspy.commands.submissions.client.get_jwt_token")
@patch("mtblspy.commands.submissions.client.get_user_name")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_validate_study_refreshes_jwt_after_unauthorized_start(
    mock_get_base_url,
    mock_get_user_name,
    mock_get_jwt_token,
    mock_get_refresh_token,
    mock_post,
    mock_save_jwt_token,
    tmp_path,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_user_name.return_value = "user@example.org"
    mock_get_jwt_token.return_value = "stale-jwt-token"
    mock_get_refresh_token.return_value = None

    unauthorized_response = MagicMock()
    unauthorized_response.status_code = 401

    login_response = MagicMock()
    login_response.status_code = 200
    login_response.headers = {}
    login_response.json.return_value = {"access_token": "fresh-jwt-token", "token_type": "bearer"}

    validation_start_response = MagicMock()
    validation_start_response.status_code = 200
    validation_start_response.json.return_value = {
        "status": "success",
        "content": {
            "task": {
                "taskId": "validation-task-1",
                "taskStatus": "SUCCESS",
                "ready": True,
                "isSuccessful": True,
            },
            "taskResult": {"messages": {"summary": [], "violations": []}},
        },
    }

    mock_post.side_effect = [
        unauthorized_response,
        login_response,
        validation_start_response,
    ]

    result = SubmissionClient(api_token="valid-key").validate_study(
        "MTBLS123",
        validation_file_path=tmp_path / "validation-report.json",
    )

    assert result.errors == []
    mock_save_jwt_token.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws3",
        "fresh-jwt-token",
        credential_base_url="https://wwwdev.ebi.ac.uk/metabolights/ws",
    )
    assert mock_post.call_args_list[0].kwargs["headers"] == {
        "accept": "application/json",
        "Authorization": "Bearer stale-jwt-token",
    }
    assert mock_post.call_args_list[1].args[0] == "https://wwwdev.ebi.ac.uk/metabolights/ws3/auth/v1/token"
    assert mock_post.call_args_list[1].kwargs["data"] == {
        "grant_type": "password",
        "username": "user@example.org",
        "client_secret": "valid-key",
    }
    assert mock_post.call_args_list[2].kwargs["headers"] == {
        "accept": "application/json",
        "Authorization": "Bearer fresh-jwt-token",
    }


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.SubmissionClient.get_submission_headers")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_validate_study_raises_when_jwt_exchange_fails_without_calling_legacy_endpoint(
    mock_get_base_url,
    mock_get_submission_headers,
    mock_post,
    tmp_path,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_submission_headers.side_effect = AuthenticationError("jwt exchange failed")

    with pytest.raises(AuthenticationError, match="jwt exchange failed"):
        SubmissionClient(api_token="valid-key").validate_study(
            "MTBLS123",
            validation_file_path=tmp_path / "validation-report.json",
        )

    mock_post.assert_not_called()


def test_validation_errors_include_nested_root_cause_details():
    report = {
        "content": {
            "taskResult": {
                "messages": {
                    "violations": [
                        {
                            "type": "ERROR",
                            "section": "Assay",
                            "title": "Referenced data file is missing",
                            "sourceFile": "a_MTBLS123_lc-ms.txt",
                            "lineNumber": 12,
                            "column": "Raw Spectral Data File",
                            "ruleId": "ASSAY_FILE_EXISTS",
                            "value": "FILES/missing.raw",
                        }
                    ]
                }
            }
        }
    }

    errors = get_validation_errors(report)

    assert len(errors) == 1
    assert format_validation_error(errors[0]) == (
        "Assay: Referenced data file is missing | "
        "location=a_MTBLS123_lc-ms.txt:12:Raw Spectral Data File | "
        "field=Raw Spectral Data File | rule=ASSAY_FILE_EXISTS | value=FILES/missing.raw"
    )


def test_validation_errors_can_be_enriched_from_isa_json_path():
    isa_json = {
        "investigation": {
            "studies": [
                {
                    "title": "",
                }
            ]
        }
    }
    errors = [
        {
            "type": "ERROR",
            "section": "Study",
            "title": "Study title is required",
            "jsonPath": "$.investigation.studies[0].title",
        }
    ]

    enriched_errors = enrich_validation_errors_with_isa_json(errors, isa_json)

    assert enriched_errors[0]["value"] == ""


def test_validation_result_extracts_v2_policy_root_causes():
    report = {
        "content": {
            "task": {
                "task_id": "validation-task-1",
                "task_status": "SUCCESS",
                "ready": True,
                "is_successful": True,
            },
            "task_result": {
                "resourceId": "MTBLS123",
                "messages": {
                    "summary": [],
                    "violations": [
                        {
                            "type": "ERROR",
                            "identifier": "rule_a_100_001",
                            "title": "Referenced raw data file is missing",
                            "violation": "Raw data file 'missing.raw' is referenced but was not found.",
                            "section": "Assay",
                            "sourceFile": "a_MTBLS123_lc-ms.txt",
                            "sourceColumnHeader": "Raw Spectral Data File",
                            "sourceColumnIndex": 12,
                            "values": ["missing.raw"],
                        }
                    ],
                },
            },
        }
    }

    errors = get_validation_errors(report)
    validation_result = get_validation_result("mtbls123", report, include_root_causes=True)

    assert format_validation_error(errors[0]) == (
        "Assay: Raw data file 'missing.raw' is referenced but was not found. | "
        "location=a_MTBLS123_lc-ms.txt | field=Raw Spectral Data File | "
        "rule=rule_a_100_001 | value=missing.raw"
    )
    assert validation_result["accession"] == "MTBLS123"
    assert validation_result["rootCauses"] == [
        {
            "section": "Assay",
            "message": "Raw data file 'missing.raw' is referenced but was not found.",
            "title": "Referenced raw data file is missing",
            "location": "a_MTBLS123_lc-ms.txt",
            "field": "Raw Spectral Data File",
            "rule": "rule_a_100_001",
            "columnIndex": 12,
            "value": ["missing.raw"],
        }
    ]


@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_jwt_token")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_validate_study_fetches_isa_json_and_posts_it_to_validation_api(
    mock_get_base_url,
    mock_get_jwt_token,
    mock_post,
    mock_get,
    tmp_path,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_jwt_token.return_value = "jwt-token"
    isa_json = {
        "investigation": {
            "studies": [
                {
                    "title": "Metadata Test Study",
                    "studyDesignDescriptors": [{"annotationValue": "metabolite profiling"}],
                }
            ]
        }
    }
    study_response = MagicMock()
    study_response.json.return_value = {"content": {"study": isa_json}}
    mock_get.return_value = study_response

    validation_response = MagicMock()
    validation_response.status_code = 200
    validation_response.json.return_value = {
        "status": "success",
        "content": {
            "task": {
                "taskId": "validation-task-1",
                "taskStatus": "SUCCESS",
                "ready": True,
                "isSuccessful": True,
            },
            "taskResult": {"messages": {"summary": [], "violations": []}},
        },
    }
    mock_post.return_value = validation_response

    result = SubmissionClient(api_token="valid-key").validate_study(
        "MTBLS123",
        validation_file_path=tmp_path / "validation-report.json",
        use_isa_json=True,
    )

    assert result.errors == []
    mock_get.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws/studies/MTBLS123",
        headers={"user-token": "valid-key"},
        timeout=30,
    )
    mock_post.assert_called_once()
    assert mock_post.call_args.args[0] == "https://wwwdev.ebi.ac.uk/metabolights/ws3/submissions/v2/validations/MTBLS123"
    assert mock_post.call_args.kwargs["json"] == isa_json


@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_jwt_token")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_find_validation_root_causes_saves_isa_json_and_enriched_report(
    mock_get_base_url,
    mock_get_jwt_token,
    mock_post,
    mock_get,
    tmp_path,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_jwt_token.return_value = "jwt-token"
    isa_json = {
        "investigation": {
            "studies": [
                {
                    "title": "",
                }
            ]
        }
    }
    study_response = MagicMock()
    study_response.json.return_value = {"content": {"study": isa_json}}
    mock_get.return_value = study_response

    validation_response = MagicMock()
    validation_response.status_code = 200
    validation_response.json.return_value = {
        "status": "success",
        "content": {
            "task": {
                "taskId": "validation-task-1",
                "taskStatus": "SUCCESS",
                "ready": True,
                "isSuccessful": True,
            },
            "taskResult": {
                "messages": {
                    "summary": [],
                    "violations": [
                        {
                            "type": "ERROR",
                            "section": "Study",
                            "title": "Study title is required",
                            "jsonPath": "$.investigation.studies[0].title",
                            "identifier": "rule_i_100_001",
                        }
                    ],
                }
            },
        },
    }
    mock_post.return_value = validation_response
    isa_json_path = tmp_path / "MTBLS123.json"
    report_path = tmp_path / "validation-debug.json"

    result = SubmissionClient(api_token="valid-key").find_validation_root_causes(
        "mtbls123",
        isa_json_file_path=isa_json_path,
        validation_file_path=report_path,
    )

    saved_isa_json = json.loads(isa_json_path.read_text(encoding="utf-8"))
    saved_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result.isa_json_path == isa_json_path.resolve()
    assert result.validation_result.report_path == report_path.resolve()
    assert saved_isa_json == isa_json
    assert saved_report["accession"] == "MTBLS123"
    assert saved_report["rootCauses"] == [
        {
            "section": "Study",
            "message": "Study title is required",
            "field": "$.investigation.studies[0].title",
            "rule": "rule_i_100_001",
            "value": "",
        }
    ]


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_jwt_token")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_validate_study_saves_accession_without_root_causes_by_default(
    mock_get_base_url,
    mock_get_jwt_token,
    mock_post,
    tmp_path,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_jwt_token.return_value = "jwt-token"
    validation_start_response = MagicMock()
    validation_start_response.json.return_value = {
        "status": "success",
        "content": {
            "task": {
                "taskId": "validation-task-1",
                "taskStatus": "SUCCESS",
                "ready": True,
                "isSuccessful": True,
            },
            "taskResult": {
                "messages": {
                    "summary": [],
                    "violations": [
                        {
                            "type": "ERROR",
                            "section": "Study",
                            "title": "Missing required metadata",
                            "sourceFile": "i_Investigation.txt",
                            "line": 4,
                            "rule": "INVESTIGATION_TITLE_REQUIRED",
                        }
                    ],
                }
            },
        },
    }
    mock_post.return_value = validation_start_response
    report_path = tmp_path / "validation-report.json"

    result = SubmissionClient(api_token="valid-key").validate_study(
        "mtbls123",
        validation_file_path=report_path,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result.errors[0]["title"] == "Missing required metadata"
    assert report["accession"] == "MTBLS123"
    assert "rootCauses" not in report


@patch("mtblspy.commands.submissions.client.time.sleep")
@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_jwt_token")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_validate_study_timeout_shows_last_task_state(
    mock_get_base_url,
    mock_get_jwt_token,
    mock_post,
    mock_get,
    mock_sleep,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_jwt_token.return_value = "jwt-token"
    validation_start_response = MagicMock()
    validation_start_response.json.return_value = {
        "status": "success",
        "content": {
            "task": {
                "taskId": "validation-task-1",
                "taskStatus": "STARTED",
                "ready": False,
                "isSuccessful": None,
            },
            "taskResult": None,
        },
    }
    validation_status_response = MagicMock()
    validation_status_response.json.return_value = {
        "status": "success",
        "content": {
            "task": {
                "taskId": "validation-task-1",
                "taskStatus": "STARTED",
                "ready": False,
                "isSuccessful": None,
                "message": "Validation is still running",
            },
            "taskResult": None,
        },
    }
    mock_post.return_value = validation_start_response
    mock_get.return_value = validation_status_response

    with pytest.raises(SubmissionAPIError) as exc_info:
        SubmissionClient(api_token="valid-key").validate_study(
            "MTBLS123",
            max_polls=1,
            poll_interval=0,
        )

    assert "Validation task for MTBLS123 did not complete in time" in str(exc_info.value)
    assert "status=STARTED" in str(exc_info.value)
    assert "message=Validation is still running" in str(exc_info.value)
    assert mock_sleep.call_count == 2


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_upload_metadata_defaults_to_local_submission_data_folder(
    mock_get_base_url,
    mock_get_api_key,
    mock_post,
    tmp_path,
    monkeypatch,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"

    from mtblspy.commands.submissions import client
    monkeypatch.setattr(client, "DEFAULT_LOCAL_SUBMISSION_DATA_PATH", tmp_path)

    study_id = "MTBLS999"
    study_data_dir = tmp_path / study_id
    study_data_dir.mkdir()
    (study_data_dir / "i_Investigation.txt").write_text("investigation", encoding="utf-8")

    response = MagicMock()
    response.status_code = 201
    response.content = b'{"success": true}'
    response.json.return_value = {"success": True}
    mock_post.return_value = response

    result = SubmissionClient().upload_metadata(study_id)

    assert [path.name for path in result.uploaded_files] == ["i_Investigation.txt"]
    mock_post.assert_called_once()


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_upload_metadata_uploads_selected_files_and_reports_skipped_files(
    mock_get_base_url,
    mock_get_api_key,
    mock_post,
    tmp_path,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    (tmp_path / "i_Investigation.txt").write_text("investigation", encoding="utf-8")
    (tmp_path / "s_MTBLS123.txt").write_text("samples", encoding="utf-8")
    (tmp_path / "a_MTBLS123_assay.txt").write_text("assay", encoding="utf-8")

    response = MagicMock()
    response.status_code = 201
    response.content = b'{"success": true}'
    response.json.return_value = {"success": True}
    mock_post.return_value = response

    result = SubmissionClient().upload_metadata(
        "MTBLS123",
        metadata_path=tmp_path,
        selected_files="i_Investigation.txt,a_MTBLS123_assay.txt",
    )

    assert [path.name for path in result.uploaded_files] == ["i_Investigation.txt", "a_MTBLS123_assay.txt"]
    assert [path.name for path in result.skipped_files] == ["s_MTBLS123.txt"]
    assert [call.kwargs["files"]["file"][0] for call in mock_post.call_args_list] == [
        "i_Investigation.txt",
        "a_MTBLS123_assay.txt",
    ]


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_upload_metadata_rejects_file_names_for_other_study_before_api_call(
    mock_get_base_url,
    mock_get_api_key,
    mock_post,
    tmp_path,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    (tmp_path / "i_Investigation.txt").write_text("investigation", encoding="utf-8")
    (tmp_path / "s_MTBLS999.txt").write_text("samples", encoding="utf-8")
    (tmp_path / "a_MTBLS999_lc-ms.txt").write_text("assay", encoding="utf-8")
    (tmp_path / "m_MTBLS999.tsv").write_text("maf", encoding="utf-8")

    with pytest.raises(SubmissionAPIError) as exc_info:
        SubmissionClient().upload_metadata("MTBLS123", metadata_path=tmp_path)

    assert str(exc_info.value) == "Metadata file name validation failed for MTBLS123."
    assert exc_info.value.errors == [
        "a_MTBLS999_lc-ms.txt: assay file name must be a_MTBLS123.txt, a_MTBLS123_*.txt, or a_MTBLS123-*.txt.",
        "m_MTBLS999.tsv: metabolite assignment file name must be m_MTBLS123.tsv, m_MTBLS123_*.tsv, or m_MTBLS123-*.tsv.",
        "s_MTBLS999.txt: sample file name must be s_MTBLS123.txt.",
    ]
    mock_get_api_key.assert_not_called()
    mock_post.assert_not_called()


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_upload_metadata_formats_api_errors_readably(
    mock_get_base_url,
    mock_get_api_key,
    mock_post,
    tmp_path,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    (tmp_path / "i_Investigation.txt").write_text("investigation", encoding="utf-8")
    (tmp_path / "s_MTBLS123.txt").write_text("samples", encoding="utf-8")

    response = MagicMock()
    response.status_code = 400
    response.content = b'{"content":null,"err":"MetabolightsException: There is no study., http_code: 400","message":"There is no study."}'
    response.json.return_value = {
        "content": None,
        "err": "MetabolightsException: There is no study., http_code: 400",
        "message": "There is no study.",
    }
    mock_post.return_value = response

    with pytest.raises(SubmissionAPIError) as exc_info:
        SubmissionClient().upload_metadata("MTBLS123", metadata_path=tmp_path)

    assert str(exc_info.value) == "Metadata upload failed for 2 file(s)."
    assert exc_info.value.errors == [
        "i_Investigation.txt: HTTP 400 - There is no study.",
        "s_MTBLS123.txt: HTTP 400 - There is no study.",
    ]


@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_download_metadata_files_discovers_all_metadata_files(
    mock_get_base_url,
    mock_get_api_key,
    mock_get,
    tmp_path,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    study_response = MagicMock()
    study_response.status_code = 200
    study_response.json.return_value = {
        "content": {
            "study": {
                "sampleFile": "s_MTBLS123.txt",
                "assays": {"a_MTBLS123_lc-ms.txt": {}},
                "referencedAssignmentFiles": ["m_MTBLS123.tsv"],
            }
        }
    }
    download_responses = []
    for content in (b"investigation", b"samples", b"assay", b"maf"):
        response = MagicMock()
        response.status_code = 200
        response.content = content
        download_responses.append(response)
    mock_get.side_effect = [study_response, *download_responses]

    result = SubmissionClient().download_metadata_files("MTBLS123", target_path=tmp_path)

    assert [path.name for path in result.downloaded_files] == [
        "i_Investigation.txt",
        "s_MTBLS123.txt",
        "a_MTBLS123_lc-ms.txt",
        "m_MTBLS123.tsv",
    ]
    assert result.missing_files == []
    assert (tmp_path / "i_Investigation.txt").read_bytes() == b"investigation"
    assert mock_get.call_args_list[1].args[0] == (
        "https://wwwdev.ebi.ac.uk/metabolights/ws/studies/MTBLS123/download?file=i_Investigation.txt"
    )


@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_download_metadata_file_continues_after_bad_candidate_url(
    mock_get_base_url,
    mock_get_api_key,
    mock_get,
    tmp_path,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    bad_response = MagicMock()
    bad_response.status_code = 400
    bad_response.reason = "BAD REQUEST"
    bad_response.text = "Bad metadata download route"
    bad_response.json.side_effect = ValueError("not json")
    good_response = MagicMock()
    good_response.status_code = 200
    good_response.content = b"metadata"
    mock_get.side_effect = [bad_response, good_response]
    output_path = tmp_path / "i_Investigation.txt"

    result = SubmissionClient().download_metadata_file("MTBLS123", "i_Investigation.txt", output_path)

    assert result == output_path
    assert output_path.read_bytes() == b"metadata"
    assert mock_get.call_args_list[0].args[0] == (
        "https://wwwdev.ebi.ac.uk/metabolights/ws/studies/MTBLS123/download?file=i_Investigation.txt"
    )
    assert mock_get.call_args_list[1].args[0] == (
        "https://wwwdev.ebi.ac.uk/metabolights/ws/studies/MTBLS123/files/i_Investigation.txt"
    )


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_delete_metadata_files_deletes_selected_files(
    mock_get_base_url,
    mock_get_api_key,
    mock_post,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    response = MagicMock()
    response.status_code = 204
    response.content = b""
    mock_post.return_value = response

    result = SubmissionClient().delete_metadata_files(
        "MTBLS123",
        selected_files="i_Investigation.txt,s_MTBLS123.txt",
    )

    assert result.deleted_files == ["i_Investigation.txt", "s_MTBLS123.txt"]
    assert result.missing_files == []
    assert result.errors == []
    mock_post.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws/studies/MTBLS123/files",
        headers={
            "user-token": "valid-key",
            "accept": "application/json",
            "Content-Type": "application/json",
        },
        params={"location": "study", "force": "false"},
        json={
            "files": [
                {"name": "i_Investigation.txt"},
                {"name": "s_MTBLS123.txt"},
            ]
        },
        timeout=60,
    )


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_delete_metadata_files_reports_active_sample_file_message(
    mock_get_base_url,
    mock_get_api_key,
    mock_post,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    response = MagicMock()
    response.status_code = 200
    response.content = b"{}"
    response.json.return_value = {
        "message": "It is not allowed to delete active sample file s_REQ20250911213069.txt"
    }
    mock_post.return_value = response

    result = SubmissionClient().delete_metadata_files(
        "REQ20250911213069",
        selected_files="s_REQ20250911213069.txt",
    )

    assert result.deleted_files == []
    assert result.missing_files == []
    assert result.errors == [
        "It is not allowed to delete active sample file s_REQ20250911213069.txt"
    ]


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_delete_metadata_files_treats_deleted_file_message_as_success(
    mock_get_base_url,
    mock_get_api_key,
    mock_post,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    file_name = "a_REQ20260528220084_LC-MS_negative_reverse-phase.txt"
    response = MagicMock()
    response.status_code = 200
    response.content = b"{}"
    response.json.return_value = {"deleted_files": f"File {file_name} is deleted"}
    mock_post.return_value = response

    result = SubmissionClient().delete_metadata_files(
        "REQ20260528220084",
        selected_files=file_name,
    )

    assert result.deleted_files == [file_name]
    assert result.missing_files == []
    assert result.errors == []


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_delete_metadata_files_reports_api_errors(
    mock_get_base_url,
    mock_get_api_key,
    mock_post,
):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    response = MagicMock()
    response.status_code = 400
    response.reason = "BAD REQUEST"
    response.url = "https://wwwdev.ebi.ac.uk/metabolights/ws/studies/MTBLS123/files?location=study&force=false"
    response.json.return_value = {"message": "Unable to delete selected files."}
    mock_post.return_value = response

    with pytest.raises(SubmissionAPIError) as exc_info:
        SubmissionClient().delete_metadata_files("MTBLS123", selected_files="i_Investigation.txt")

    assert str(exc_info.value) == "Metadata delete failed for MTBLS123."
    assert exc_info.value.errors == [
        "HTTP 400 BAD REQUEST - Unable to delete selected files. for url: "
        "https://wwwdev.ebi.ac.uk/metabolights/ws/studies/MTBLS123/files?location=study&force=false"
    ]


@patch("mtblspy.commands.submissions.client.get_base_url")
def test_delete_metadata_files_requires_files(mock_get_base_url):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"

    with pytest.raises(SubmissionAPIError) as exc_info:
        SubmissionClient().delete_metadata_files("MTBLS123", selected_files="")

    assert "Metadata delete requires --files" in str(exc_info.value)


class FakeFTP:
    instances = []

    def __init__(self, host, timeout=60):
        self.host = host
        self.timeout = timeout
        self.current_directory = "/"
        self.uploaded_paths = []
        self.created_directories = []
        self.renamed_paths = []
        self.deleted_paths = []
        FakeFTP.instances.append(self)

    def login(self, user, password):
        self.user = user
        self.password = password

    def cwd(self, path):
        if path == "/":
            self.current_directory = "/"
        elif path.startswith("/"):
            self.current_directory = path.rstrip("/") or "/"
        else:
            self.current_directory = f"{self.current_directory.rstrip('/')}/{path}".rstrip("/")

    def pwd(self):
        return self.current_directory

    def mkd(self, path):
        self.created_directories.append(path)

    def mlsd(self, path):
        entries = {
            "/incoming/MTBLS123": [
                ("folder1", {"type": "dir"}),
            ],
            "/incoming/MTBLS123/folder1": [
                ("file2.raw", {"type": "file", "size": "4"}),
            ],
        }
        return entries.get(path.rstrip("/"), [])

    def storbinary(self, command, file_handle):
        filename = command.removeprefix("STOR ")
        self.uploaded_paths.append(f"{self.current_directory.rstrip('/')}/{filename}")
        file_handle.read()

    def retrbinary(self, command, callback):
        filename = command.removeprefix("RETR ")
        callback(f"downloaded:{filename}".encode())

    def rename(self, fromname, toname):
        from_path = self.absolute_path(fromname)
        to_path = self.absolute_path(toname)
        self.renamed_paths.append((from_path, to_path))
        self.uploaded_paths = [to_path if path == from_path else path for path in self.uploaded_paths]

    def delete(self, path):
        absolute_path = self.absolute_path(path)
        self.deleted_paths.append(absolute_path)
        self.uploaded_paths = [uploaded_path for uploaded_path in self.uploaded_paths if uploaded_path != absolute_path]

    def absolute_path(self, path):
        if path.startswith("/"):
            return path
        return f"{self.current_directory.rstrip('/')}/{path}"

    def quit(self):
        self.closed = True


@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_upload_data_files_skips_remote_existing_files_and_deduplicates_selected_folders(
    mock_get_base_url,
    mock_get_api_key,
    mock_get,
    tmp_path,
):
    FakeFTP.instances = []
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    response = MagicMock()
    response.json.return_value = {
        "study_id": "MTBLS123",
        "ftp_folder": "/incoming/MTBLS123",
        "ftp_host": "ftp-private.ebi.ac.uk",
        "ftp_user": "ftp-user",
        "ftp_password": "ftp-password",
    }
    mock_get.return_value = response

    folder = tmp_path / "folder1"
    subfolder = folder / "folder2"
    subfolder.mkdir(parents=True)
    (subfolder / "file1.raw").write_text("new-data", encoding="utf-8")
    (folder / "file2.raw").write_text("same", encoding="utf-8")

    result = SubmissionClient().upload_data_files(
        "MTBLS123",
        data_files_root_path=tmp_path,
        selected_files="folder1/folder2,folder1",
        ftp_factory=FakeFTP,
    )

    assert result.uploaded_files == ["folder1/folder2/file1.raw"]
    assert result.skipped_files == ["folder1/file2.raw"]
    assert result.missing_on_local == []
    assert FakeFTP.instances[0].uploaded_paths == ["/incoming/MTBLS123/folder1/folder2/file1.raw"]
    assert FakeFTP.instances[0].renamed_paths == [
        (
            "/incoming/MTBLS123/folder1/folder2/.ftp_file1.raw",
            "/incoming/MTBLS123/folder1/folder2/file1.raw",
        )
    ]


class DownloadFTP(FakeFTP):
    def mlsd(self, path):
        entries = {
            "/incoming/MTBLS123": [
                ("raw", {"type": "dir"}),
                ("i_Investigation.txt", {"type": "file", "size": "4"}),
                ("s_MTBLS123.txt", {"type": "file", "size": "4"}),
                ("a_MTBLS123_lc-ms.txt", {"type": "file", "size": "4"}),
                ("m_MTBLS123_lc-ms.tsv", {"type": "file", "size": "4"}),
                (".ftp_interrupted.raw", {"type": "file", "size": "1"}),
            ],
            "/incoming/MTBLS123/raw": [
                ("file1.raw", {"type": "file", "size": "4"}),
                ("file2.raw", {"type": "file", "size": "4"}),
            ],
        }
        return entries.get(path.rstrip("/"), [])


@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_download_data_files_downloads_selected_ftp_folder(
    mock_get_base_url,
    mock_get_api_key,
    mock_get,
    tmp_path,
):
    FakeFTP.instances = []
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    response = MagicMock()
    response.json.return_value = {
        "study_id": "MTBLS123",
        "ftp_folder": "/incoming/MTBLS123",
        "ftp_host": "ftp-private.ebi.ac.uk",
        "ftp_user": "ftp-user",
        "ftp_password": "ftp-password",
    }
    mock_get.return_value = response

    result = SubmissionClient().download_data_files(
        "MTBLS123",
        target_path=tmp_path,
        selected_files="raw",
        ftp_factory=DownloadFTP,
    )

    assert [path.relative_to(tmp_path).as_posix() for path in result.downloaded_files] == [
        "raw/file1.raw",
        "raw/file2.raw",
    ]
    assert result.missing_files == []
    assert (tmp_path / "raw" / "file1.raw").read_bytes() == b"downloaded:raw/file1.raw"
    assert not (tmp_path / ".ftp_interrupted.raw").exists()
    assert not (tmp_path / "i_Investigation.txt").exists()
    assert not (tmp_path / "s_MTBLS123.txt").exists()
    assert not (tmp_path / "a_MTBLS123_lc-ms.txt").exists()
    assert not (tmp_path / "m_MTBLS123_lc-ms.tsv").exists()


@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_download_data_files_excludes_metadata_files_by_default(
    mock_get_base_url,
    mock_get_api_key,
    mock_get,
    tmp_path,
):
    FakeFTP.instances = []
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    response = MagicMock()
    response.json.return_value = {
        "study_id": "MTBLS123",
        "ftp_folder": "/incoming/MTBLS123",
        "ftp_host": "ftp-private.ebi.ac.uk",
        "ftp_user": "ftp-user",
        "ftp_password": "ftp-password",
    }
    mock_get.return_value = response

    result = SubmissionClient().download_data_files(
        "MTBLS123",
        target_path=tmp_path,
        download_all=True,
        ftp_factory=DownloadFTP,
    )

    assert [path.relative_to(tmp_path).as_posix() for path in result.downloaded_files] == [
        "raw/file1.raw",
        "raw/file2.raw",
    ]
    assert result.missing_files == []
    assert not (tmp_path / ".ftp_interrupted.raw").exists()
    assert not (tmp_path / "i_Investigation.txt").exists()
    assert not (tmp_path / "s_MTBLS123.txt").exists()
    assert not (tmp_path / "a_MTBLS123_lc-ms.txt").exists()
    assert not (tmp_path / "m_MTBLS123_lc-ms.tsv").exists()


@patch("mtblspy.commands.submissions.client.get_base_url")
def test_download_data_files_requires_selection_or_all(mock_get_base_url):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"

    with pytest.raises(SubmissionAPIError) as exc_info:
        SubmissionClient().download_data_files("MTBLS123")

    assert "Data download requires --files" in str(exc_info.value)


@patch("mtblspy.commands.submissions.client.get_base_url")
def test_download_data_files_rejects_selection_with_all(mock_get_base_url):
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"

    with pytest.raises(SubmissionAPIError) as exc_info:
        SubmissionClient().download_data_files("MTBLS123", selected_files="raw", download_all=True)

    assert "Use either --files or --all" in str(exc_info.value)


@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_download_data_files_emits_progress_events(
    mock_get_base_url,
    mock_get_api_key,
    mock_get,
    tmp_path,
):
    FakeFTP.instances = []
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    response = MagicMock()
    response.json.return_value = {
        "study_id": "MTBLS123",
        "ftp_folder": "/incoming/MTBLS123",
        "ftp_host": "ftp-private.ebi.ac.uk",
        "ftp_user": "ftp-user",
        "ftp_password": "ftp-password",
    }
    mock_get.return_value = response
    progress_events = []

    result = SubmissionClient().download_data_files(
        "MTBLS123",
        target_path=tmp_path,
        selected_files="raw",
        ftp_factory=DownloadFTP,
        progress_callback=progress_events.append,
    )

    assert [path.relative_to(tmp_path).as_posix() for path in result.downloaded_files] == [
        "raw/file1.raw",
        "raw/file2.raw",
    ]
    assert progress_events == [
        {"event": "start", "total": 2},
        {"event": "item", "path": "raw/file1.raw", "status": "downloaded"},
        {"event": "item", "path": "raw/file2.raw", "status": "downloaded"},
    ]


@patch("mtblspy.commands.submissions.client.get_base_url")
def test_upload_data_files_reports_missing_selected_files_without_ftp(
    mock_get_base_url,
    tmp_path,
):
    FakeFTP.instances = []
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"

    result = SubmissionClient().upload_data_files(
        "MTBLS123",
        data_files_root_path=tmp_path,
        selected_files="missing.raw",
        ftp_factory=FakeFTP,
    )

    assert result.uploaded_files == []
    assert result.missing_on_local == ["missing.raw"]
    assert FakeFTP.instances == []


@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_upload_data_files_emits_progress_events(
    mock_get_base_url,
    mock_get_api_key,
    mock_get,
    tmp_path,
):
    FakeFTP.instances = []
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    response = MagicMock()
    response.json.return_value = {
        "study_id": "MTBLS123",
        "ftp_folder": "/incoming/MTBLS123",
        "ftp_host": "ftp-private.ebi.ac.uk",
        "ftp_user": "ftp-user",
        "ftp_password": "ftp-password",
    }
    mock_get.return_value = response
    data_file = tmp_path / "file1.raw"
    data_file.write_text("raw-data", encoding="utf-8")
    progress_events = []

    result = SubmissionClient().upload_data_files(
        "MTBLS123",
        data_files_root_path=tmp_path,
        ftp_factory=FakeFTP,
        progress_callback=progress_events.append,
    )

    assert result.uploaded_files == ["file1.raw"]
    assert progress_events == [
        {"event": "start", "total": 1},
        {"event": "item", "path": "file1.raw", "status": "uploaded"},
    ]


class LoginRootFTP(FakeFTP):
    def __init__(self, host, timeout=60):
        super().__init__(host, timeout=timeout)
        self.current_directory = "/"

    def cwd(self, path):
        if path in ("/incoming/MTBLS123", "incoming/MTBLS123", "MTBLS123"):
            raise error_perm("550 Failed to change directory.")
        super().cwd(path)

    def mlsd(self, path):
        return []


class NoSubdirectoryCwdFTP(LoginRootFTP):
    def cwd(self, path):
        if path in ("folder1", "folder2", "empty-folder"):
            raise error_perm("550 Failed to change directory.")
        super().cwd(path)

    def storbinary(self, command, file_handle):
        target = command.removeprefix("STOR ")
        self.uploaded_paths.append(f"{self.current_directory.rstrip('/')}/{target}")
        file_handle.read()


class PathMkdOnlyFTP(NoSubdirectoryCwdFTP):
    def __init__(self, host, timeout=60):
        super().__init__(host, timeout=timeout)
        self.allowed_store_paths = set()

    def mkd(self, path):
        super().mkd(path)
        self.allowed_store_paths.add(path)

    def storbinary(self, command, file_handle):
        target = command.removeprefix("STOR ")
        directory = posixpath.dirname(target)
        if directory and directory not in self.allowed_store_paths:
            raise error_perm("553 Could not create file.")
        self.uploaded_paths.append(f"{self.current_directory.rstrip('/')}/{target}")
        file_handle.read()


class SizeMismatchFTP(FakeFTP):
    def __init__(self, host, timeout=60):
        super().__init__(host, timeout=timeout)
        self.uploaded_sizes = {}

    def storbinary(self, command, file_handle):
        filename = command.removeprefix("STOR ")
        upload_path = f"{self.current_directory.rstrip('/')}/{filename}"
        self.uploaded_paths.append(upload_path)
        self.uploaded_sizes[upload_path] = len(file_handle.read())

    def size(self, path):
        upload_path = self.absolute_path(path)
        uploaded_size = self.uploaded_sizes.get(upload_path)
        if uploaded_size is None:
            return None
        return uploaded_size - 1


class TemporaryFilesFTP(FakeFTP):
    def mlsd(self, path):
        entries = {
            "/incoming/MTBLS123": [
                (".ftp_root.raw", {"type": "file", "size": "1"}),
                ("final.raw", {"type": "file", "size": "1"}),
                ("folder1", {"type": "dir"}),
            ],
            "/incoming/MTBLS123/folder1": [
                (".ftp_nested.raw", {"type": "file", "size": "2"}),
                ("nested.raw", {"type": "file", "size": "2"}),
            ],
        }
        return entries.get(path.rstrip("/"), [])


class NlstOnlyTemporaryFilesFTP(TemporaryFilesFTP):
    directories = {"/", "/incoming/MTBLS123", "/incoming/MTBLS123/folder1"}

    def mlsd(self, path):
        raise error_perm("500 Unknown command.")

    def nlst(self, path):
        entries = {
            "/incoming/MTBLS123": [
                "/incoming/MTBLS123/.ftp_root.raw",
                "/incoming/MTBLS123/final.raw",
                "/incoming/MTBLS123/folder1",
            ],
            "/incoming/MTBLS123/folder1": [
                "/incoming/MTBLS123/folder1/.ftp_nested.raw",
                "/incoming/MTBLS123/folder1/nested.raw",
            ],
        }
        return entries.get(path.rstrip("/"), [])

    def cwd(self, path):
        if path == "/":
            self.current_directory = "/"
            return
        absolute_path = path if path.startswith("/") else f"{self.current_directory.rstrip('/')}/{path}"
        absolute_path = absolute_path.rstrip("/") or "/"
        if absolute_path not in self.directories:
            raise error_perm("550 Failed to change directory.")
        self.current_directory = absolute_path


@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_upload_data_files_uses_login_directory_when_ftp_folder_is_not_accessible(
    mock_get_base_url,
    mock_get_api_key,
    mock_get,
    tmp_path,
):
    FakeFTP.instances = []
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    response = MagicMock()
    response.json.return_value = {
        "study_id": "MTBLS123",
        "ftp_folder": "/incoming/MTBLS123",
        "ftp_host": "ftp-private.ebi.ac.uk",
        "ftp_user": "ftp-user",
        "ftp_password": "ftp-password",
    }
    mock_get.return_value = response
    data_file = tmp_path / "folder1" / "file1.raw"
    data_file.parent.mkdir()
    data_file.write_text("raw-data", encoding="utf-8")

    result = SubmissionClient().upload_data_files(
        "MTBLS123",
        data_files_root_path=tmp_path,
        ftp_factory=LoginRootFTP,
    )

    assert result.errors == []
    assert result.uploaded_files == ["folder1/file1.raw"]
    assert FakeFTP.instances[0].uploaded_paths == ["/folder1/file1.raw"]


@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_upload_data_files_falls_back_to_path_based_store_when_cwd_to_subfolder_fails(
    mock_get_base_url,
    mock_get_api_key,
    mock_get,
    tmp_path,
):
    FakeFTP.instances = []
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    response = MagicMock()
    response.json.return_value = {
        "study_id": "MTBLS123",
        "ftp_folder": "/incoming/MTBLS123",
        "ftp_host": "ftp-private.ebi.ac.uk",
        "ftp_user": "ftp-user",
        "ftp_password": "ftp-password",
    }
    mock_get.return_value = response
    (tmp_path / "empty-folder").mkdir()
    folder = tmp_path / "folder1"
    folder.mkdir()
    (folder / "file1.raw").write_text("raw-data", encoding="utf-8")

    result = SubmissionClient().upload_data_files(
        "MTBLS123",
        data_files_root_path=tmp_path,
        ftp_factory=NoSubdirectoryCwdFTP,
    )

    assert result.errors == []
    assert result.uploaded_files == ["folder1/file1.raw"]
    assert result.skipped_files == ["empty-folder/"]
    assert FakeFTP.instances[0].uploaded_paths == ["/folder1/file1.raw"]


@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_upload_data_files_creates_cumulative_directories_before_path_based_store(
    mock_get_base_url,
    mock_get_api_key,
    mock_get,
    tmp_path,
):
    FakeFTP.instances = []
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    response = MagicMock()
    response.json.return_value = {
        "study_id": "MTBLS123",
        "ftp_folder": "/incoming/MTBLS123",
        "ftp_host": "ftp-private.ebi.ac.uk",
        "ftp_user": "ftp-user",
        "ftp_password": "ftp-password",
    }
    mock_get.return_value = response
    data_file = tmp_path / "folder1" / "folder2" / "file1.raw"
    data_file.parent.mkdir(parents=True)
    data_file.write_text("raw-data", encoding="utf-8")

    result = SubmissionClient().upload_data_files(
        "MTBLS123",
        data_files_root_path=tmp_path,
        ftp_factory=PathMkdOnlyFTP,
    )

    assert result.errors == []
    assert result.uploaded_files == ["folder1/folder2/file1.raw"]
    assert "folder1" in FakeFTP.instances[0].created_directories
    assert "folder1/folder2" in FakeFTP.instances[0].created_directories
    assert FakeFTP.instances[0].uploaded_paths == ["/folder1/folder2/file1.raw"]
    assert FakeFTP.instances[0].renamed_paths == [
        ("/folder1/folder2/.ftp_file1.raw", "/folder1/folder2/file1.raw")
    ]


@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_upload_data_files_reports_temporary_file_size_mismatch(
    mock_get_base_url,
    mock_get_api_key,
    mock_get,
    tmp_path,
):
    FakeFTP.instances = []
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    response = MagicMock()
    response.json.return_value = {
        "study_id": "MTBLS123",
        "ftp_folder": "/incoming/MTBLS123",
        "ftp_host": "ftp-private.ebi.ac.uk",
        "ftp_user": "ftp-user",
        "ftp_password": "ftp-password",
    }
    mock_get.return_value = response
    data_file = tmp_path / "file1.raw"
    data_file.write_text("raw-data", encoding="utf-8")

    result = SubmissionClient().upload_data_files(
        "MTBLS123",
        data_files_root_path=tmp_path,
        ftp_factory=SizeMismatchFTP,
    )

    assert result.uploaded_files == []
    assert result.errors == [
        "file1.raw: Uploaded temporary file size mismatch for file1.raw: expected 8 bytes, got 7 bytes."
    ]
    assert FakeFTP.instances[0].deleted_paths == ["/incoming/MTBLS123/.ftp_file1.raw"]


@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_clear_ftp_temporary_files_deletes_dot_ftp_files(
    mock_get_base_url,
    mock_get_api_key,
    mock_get,
):
    FakeFTP.instances = []
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    response = MagicMock()
    response.json.return_value = {
        "study_id": "MTBLS123",
        "ftp_folder": "/incoming/MTBLS123",
        "ftp_host": "ftp-private.ebi.ac.uk",
        "ftp_user": "ftp-user",
        "ftp_password": "ftp-password",
    }
    mock_get.return_value = response

    result = SubmissionClient().clear_ftp_temporary_files(
        "MTBLS123",
        ftp_factory=TemporaryFilesFTP,
    )

    assert result.deleted_files == [".ftp_root.raw", "folder1/.ftp_nested.raw"]
    assert result.errors == []
    assert FakeFTP.instances[0].deleted_paths == [
        "/incoming/MTBLS123/.ftp_root.raw",
        "/incoming/MTBLS123/folder1/.ftp_nested.raw",
    ]


@patch("mtblspy.commands.submissions.client.requests.get")
@patch("mtblspy.commands.submissions.client.get_api_key")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_clear_ftp_temporary_files_falls_back_to_nlst_when_mlsd_is_not_supported(
    mock_get_base_url,
    mock_get_api_key,
    mock_get,
):
    FakeFTP.instances = []
    mock_get_base_url.return_value = "https://wwwdev.ebi.ac.uk/metabolights/ws"
    mock_get_api_key.return_value = "valid-key"
    response = MagicMock()
    response.json.return_value = {
        "study_id": "MTBLS123",
        "ftp_folder": "/incoming/MTBLS123",
        "ftp_host": "ftp-private.ebi.ac.uk",
        "ftp_user": "ftp-user",
        "ftp_password": "ftp-password",
    }
    mock_get.return_value = response

    result = SubmissionClient().clear_ftp_temporary_files(
        "MTBLS123",
        ftp_factory=NlstOnlyTemporaryFilesFTP,
    )

    assert result.deleted_files == [".ftp_root.raw", "folder1/.ftp_nested.raw"]
    assert result.errors == []
    assert FakeFTP.instances[0].deleted_paths == [
        "/incoming/MTBLS123/.ftp_root.raw",
        "/incoming/MTBLS123/folder1/.ftp_nested.raw",
    ]
