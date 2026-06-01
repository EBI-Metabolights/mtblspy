import json
from unittest.mock import MagicMock, patch

import pytest

from mtblspy.commands.submissions.client import (
    SubmissionClient,
    format_validation_error,
    get_validation_errors,
    get_keycloak_token_url,
    get_studies_from_user_response,
    save_sample_study_input,
)
from mtblspy.commands.submissions.exceptions import AuthenticationError, StudyValidationError, SubmissionAPIError
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
    )
    mock_save_jwt_token.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws3",
        "jwt-token",
    )
    mock_save_refresh_token.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws3",
        "refresh-token",
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
    )
    mock_save_jwt_token.assert_called_once_with(
        "https://www.ebi.ac.uk/metabolights/ws3",
        "jwt-token",
    )
    mock_save_refresh_token.assert_called_once_with(
        "https://www.ebi.ac.uk/metabolights/ws3",
        "refresh-token",
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
    )
    mock_save_refresh_token.assert_called_once_with(
        "https://wwwdev.ebi.ac.uk/metabolights/ws3",
        "new-refresh-token",
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


@patch("mtblspy.commands.submissions.client.requests.put")
@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_jwt_token")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_submit_study_blocks_status_update_when_validation_errors(
    mock_get_base_url,
    mock_get_jwt_token,
    mock_post,
    mock_put,
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
                    "violations": [{"type": "ERROR", "title": "Missing required metadata", "section": "Study"}],
                }
            },
        },
    }
    mock_post.return_value = validation_start_response

    with pytest.raises(StudyValidationError):
        SubmissionClient(api_token="valid-key").submit_study(
            "MTBLS123",
            status="Private",
            validation_file_path=tmp_path / "validation-report.json",
        )

    mock_put.assert_not_called()


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


@patch("mtblspy.commands.submissions.client.requests.post")
@patch("mtblspy.commands.submissions.client.get_jwt_token")
@patch("mtblspy.commands.submissions.client.get_base_url")
def test_validate_study_saves_accession_and_root_causes(
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
    assert report["rootCauses"] == [
        {
            "section": "Study",
            "message": "Missing required metadata",
            "location": "i_Investigation.txt:4",
            "rule": "INVESTIGATION_TITLE_REQUIRED",
        }
    ]


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
