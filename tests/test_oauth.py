import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest
import requests
from click.testing import CliRunner

from mtblspy import config
from mtblspy.commands.cli import cli
from mtblspy.commands.submissions.client import SubmissionClient
from mtblspy.commands.submissions.exceptions import AuthenticationError
from mtblspy.credential_files import read_private_json, write_private_json
from mtblspy.oauth import OAuthSession, make_session

BASE = "https://www.ebi.ac.uk/metabolights/ws"
SUBMISSION = BASE + "3"
ISSUER = "https://www.ebi.ac.uk/metabolights/iam/realms/metabolights"
CLIENT = "mtbls-ai-skills-client"


def jwt(expiry, *, client=CLIENT, issuer=ISSUER):
    from base64 import urlsafe_b64encode

    payload = {"exp": expiry, "iss": issuer, "azp": client, "email": "user@example.org"}
    encoded = urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"e30.{encoded}.signature"


def expired_session():
    return make_session(jwt(time.time() - 120), "refresh-original", base_url=BASE)


def response(**overrides):
    payload = {
        "access_token": jwt(time.time() + 3600),
        "refresh_token": "refresh-rotated",
        "expires_in": 3600,
        "refresh_expires_in": 7200,
        "token_type": "Bearer",
        **overrides,
    }
    return Mock(status_code=200, json=lambda: payload)


def manager():
    return OAuthSession(SUBMISSION, BASE)


def test_jwt_login_saves_client_and_refresh_and_removes_previous_identity():
    config.save_api_key("previous-account-key", credential_base_url=BASE)
    config.save_refresh_token(
        SUBMISSION, "previous-account-refresh", credential_base_url=BASE
    )
    token = jwt(time.time() + 3600)
    SubmissionClient(base_url=BASE).login_with_jwt(
        token, refresh_token="refresh-original"
    )
    saved = config.get_oauth_session(SUBMISSION, credential_base_url=BASE)
    assert saved["client_id"] == CLIENT
    assert saved["refresh_token"] == "refresh-original"
    assert saved["issuer"] == ISSUER
    assert config.get_api_key(credential_base_url=BASE) is None


def test_saved_api_key_remains_usable_for_legacy_rest_endpoints():
    manager().save(expired_session())
    config.save_api_key("valid-api-key", credential_base_url=BASE)
    assert SubmissionClient(base_url=BASE).get_auth_headers() == {
        "user-token": "valid-api-key"
    }


def test_automatic_refresh_uses_original_client_and_atomically_saves_rotation():
    manager().save(expired_session())
    with patch("mtblspy.oauth.requests.post", return_value=response()) as post:
        headers = SubmissionClient(base_url=BASE).get_auth_headers()
    assert headers["Authorization"].startswith("Bearer ")
    assert post.call_args.args[0] == ISSUER + "/protocol/openid-connect/token"
    assert post.call_args.kwargs["data"] == {
        "grant_type": "refresh_token",
        "client_id": CLIENT,
        "refresh_token": "refresh-original",
    }
    assert post.call_args.kwargs["allow_redirects"] is False
    assert (
        config.get_oauth_session(SUBMISSION, credential_base_url=BASE)["refresh_token"]
        == "refresh-rotated"
    )
    with patch(
        "mtblspy.oauth.requests.post", side_effect=AssertionError("should reuse token")
    ):
        assert SubmissionClient(base_url=BASE).get_auth_headers() == headers


def test_refresh_preserves_refresh_token_when_server_does_not_rotate_it():
    manager().save(expired_session())
    result = response()
    data = result.json()
    data.pop("refresh_token")
    result.json = lambda: data
    with patch("mtblspy.oauth.requests.post", return_value=result):
        manager().get_access_token()
    assert (
        config.get_oauth_session(SUBMISSION, credential_base_url=BASE)["refresh_token"]
        == "refresh-original"
    )


@pytest.mark.parametrize("status", [400, 401, 403, 500, 302])
def test_failed_refresh_preserves_session_and_redacts_errors(status):
    saved = expired_session()
    manager().save(saved)
    result = Mock(
        status_code=status, json=lambda: {"error_description": "refresh-original"}
    )
    with (
        patch("mtblspy.oauth.requests.post", return_value=result),
        pytest.raises(AuthenticationError) as error,
    ):
        manager().get_access_token()
    assert "refresh-original" not in str(error.value)
    assert config.get_oauth_session(SUBMISSION, credential_base_url=BASE) == saved


def test_network_failure_does_not_disclose_token():
    manager().save(expired_session())
    with (
        patch(
            "mtblspy.oauth.requests.post",
            side_effect=requests.Timeout("refresh-original"),
        ),
        pytest.raises(AuthenticationError, match="Check the network") as error,
    ):
        manager().get_access_token()
    assert "refresh-original" not in str(error.value)


def test_expired_refresh_session_never_calls_the_server():
    saved = {**expired_session(), "refresh_expires_at": time.time() - 1}
    manager().save(saved)
    with (
        patch("mtblspy.oauth.requests.post") as post,
        pytest.raises(AuthenticationError, match="expired"),
    ):
        manager().get_access_token()
    post.assert_not_called()


def test_shared_mcp_file_rotates_in_place_and_retains_helper_metadata(tmp_path):
    path = tmp_path / "mcp.json"
    saved = {
        **expired_session(),
        "requested_scope": "openid",
        "scope": "openid",
        "expires_at": time.time() - 120,
    }
    write_private_json(path, saved)
    manager().save({"token_file": str(path), "issuer": ISSUER, "client_id": CLIENT})
    with patch("mtblspy.oauth.requests.post", return_value=response()) as post:
        manager().get_access_token()
        manager().get_access_token()
    assert post.call_count == 1
    updated = read_private_json(path)
    assert updated["requested_scope"] == "openid"
    assert updated["refresh_token"] == "refresh-rotated"
    stored = config.get_oauth_session(SUBMISSION, credential_base_url=BASE)
    assert "refresh_token" not in stored
    assert "access_token" not in stored
    config.clear_session(BASE, SUBMISSION, credential_base_url=BASE)
    assert read_private_json(path) == updated


def test_shared_file_rejects_other_issuer_before_sending_credentials(tmp_path):
    path = tmp_path / "mcp.json"
    write_private_json(
        path, {**expired_session(), "issuer": "https://other.example/realm"}
    )
    with (
        patch("mtblspy.oauth.requests.post") as post,
        pytest.raises(AuthenticationError, match="different OAuth issuer"),
    ):
        manager().attach_token_file(path)
    post.assert_not_called()


def test_simultaneous_commands_refresh_only_once(monkeypatch, tmp_path):
    monkeypatch.setenv("MTBLS_CREDENTIAL_STORAGE", "file")
    manager().save(expired_session())

    def refresh(*args, **kwargs):
        time.sleep(0.1)
        return response()

    with (
        patch("mtblspy.oauth.requests.post", side_effect=refresh) as post,
        ThreadPoolExecutor(max_workers=4) as pool,
    ):
        tokens = list(pool.map(lambda _: manager().get_access_token(), range(4)))
    assert len(set(tokens)) == 1
    assert post.call_count == 1


def test_parallel_processes_share_rotated_refresh_token(monkeypatch, tmp_path):
    monkeypatch.setenv("MTBLS_CREDENTIAL_STORAGE", "file")
    manager().save(expired_session())
    calls = tmp_path / "refresh-calls"
    program = """
import time
from pathlib import Path
from unittest.mock import Mock
import mtblspy.oauth as oauth
def refresh(*args, **kwargs):
    with Path(CALLS).open('a') as log:
        log.write('refresh\\n')
    time.sleep(0.15)
    return Mock(status_code=200, json=lambda: {
        'access_token': 'fresh-access', 'refresh_token': 'rotated-refresh',
        'expires_in': 3600, 'token_type': 'Bearer',
    })
oauth.requests.post = refresh
assert oauth.OAuthSession(SUBMISSION, BASE).get_access_token() == 'fresh-access'
"""
    program = (
        f"CALLS={str(calls)!r}\nBASE={BASE!r}\nSUBMISSION={SUBMISSION!r}\n" + program
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        children = list(
            pool.map(
                lambda _: subprocess.run(
                    [sys.executable, "-c", program],
                    env=dict(os.environ),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                ),
                range(4),
            )
        )
    for child in children:
        assert child.returncode == 0, child.stderr
    assert calls.read_text().splitlines() == ["refresh"]


@pytest.mark.skipif(os.name != "posix", reason="MCP helper's Unix flock protocol")
def test_shared_file_respects_mcp_helpers_lock(tmp_path):
    import fcntl

    path = tmp_path / "mcp.json"
    write_private_json(path, expired_session())
    manager().save({"token_file": str(path), "issuer": ISSUER, "client_id": CLIENT})
    lock_path = path.with_suffix(".lock")
    lock_path.touch(mode=0o600)
    with (
        lock_path.open("r+") as lock,
        patch("mtblspy.oauth.requests.post", return_value=response()) as post,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        fcntl.flock(lock, fcntl.LOCK_EX)
        pending = pool.submit(manager().get_access_token)
        time.sleep(0.1)
        assert not pending.done()
        post.assert_not_called()
        fcntl.flock(lock, fcntl.LOCK_UN)
        assert pending.result(timeout=5)
    post.assert_called_once()


def test_pipeline_credentials_reuse_rotation_across_cli_processes(monkeypatch):
    monkeypatch.setenv("MTBLS_CREDENTIAL_STORAGE", "file")
    monkeypatch.setenv("MTBLS_JWT_TOKEN", jwt(time.time() - 120))
    monkeypatch.setenv("MTBLS_REFRESH_TOKEN", "refresh-original")
    monkeypatch.setenv("MTBLS_BASE_URL", BASE)
    with patch("mtblspy.oauth.requests.post", return_value=response()) as post:
        first = manager().get_access_token()
        assert manager().get_access_token() == first
    assert post.call_count == 1
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "from mtblspy.commands.submissions.client import SubmissionClient; assert SubmissionClient().get_auth_headers()['Authorization'].startswith('Bearer ')",
        ],
        env=dict(os.environ),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert child.returncode == 0, child.stderr
    assert not child.stdout


def test_login_with_expired_environment_jwt_reuses_rotated_session(monkeypatch):
    monkeypatch.setenv("MTBLS_CREDENTIAL_STORAGE", "file")
    token = jwt(time.time() - 120)
    monkeypatch.setenv("MTBLS_JWT_TOKEN", token)
    monkeypatch.setenv("MTBLS_REFRESH_TOKEN", "refresh-original")
    with patch("mtblspy.oauth.requests.post", return_value=response()) as post:
        client = SubmissionClient(base_url=BASE)
        client.login_with_jwt(token, refresh_token="refresh-original")
        assert client.get_auth_headers()["Authorization"].startswith("Bearer ")
    assert post.call_count == 1


def test_environment_access_only_session_does_not_touch_keyring(monkeypatch):
    monkeypatch.setenv("MTBLS_JWT_TOKEN", jwt(time.time() + 3600))
    with patch(
        "keyring.get_password", side_effect=AssertionError("keyring unavailable")
    ):
        assert (
            SubmissionClient(base_url=BASE)
            .get_auth_headers()["Authorization"]
            .startswith("Bearer ")
        )


def test_token_file_env_works_without_any_keyring_access(monkeypatch, tmp_path):
    path = tmp_path / "mcp.json"
    write_private_json(
        path, make_session(jwt(time.time() + 3600), "refresh", base_url=BASE)
    )
    monkeypatch.setenv("MTBLS_TOKEN_FILE", str(path))
    with patch(
        "keyring.get_password", side_effect=AssertionError("keyring unavailable")
    ):
        assert (
            SubmissionClient(base_url=BASE)
            .get_auth_headers()["Authorization"]
            .startswith("Bearer ")
        )


def test_401_retries_once_with_fresh_token():
    client = SubmissionClient(base_url=BASE)
    with (
        patch.object(
            client, "get_auth_headers", return_value={"Authorization": "Bearer old"}
        ),
        patch(
            "mtblspy.commands.submissions.client.requests.get",
            side_effect=[Mock(status_code=401), Mock(status_code=200, json=list)],
        ) as get,
        patch.object(
            client,
            "get_submission_headers",
            return_value={"Authorization": "Bearer new"},
        ) as refresh,
    ):
        assert client.list_studies() == []
    refresh.assert_called_once_with()
    assert get.call_count == 2
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer new"


def test_noninteractive_login_never_prompts():
    result = CliRunner().invoke(cli, ["auth", "login", "--non-interactive"])
    assert result.exit_code == 2
    assert "Missing login credentials" in result.output
    assert "Please enter" not in result.output


def test_cli_login_imports_refresh_credentials_without_printing_secrets():
    token = jwt(time.time() + 3600)
    with patch(
        "mtblspy.commands.submissions.client.requests.get",
        return_value=Mock(status_code=501, headers={}, json=dict),
    ):
        result = CliRunner().invoke(
            cli,
            [
                "auth",
                "login",
                "--base-url",
                BASE,
                "--non-interactive",
            ],
            env={
                "MTBLS_CREDENTIAL_STORAGE": "file",
                "MTBLS_JWT_TOKEN": token,
                "MTBLS_REFRESH_TOKEN": "refresh-original",
            },
        )
    # Optional API-token discovery is unrelated to OAuth session storage.
    assert result.exit_code == 0, result.output
    assert "refresh-original" not in result.output
    assert token not in result.output


@pytest.mark.parametrize(
    "issuer",
    [
        "http://example.org/realm",
        "https://user:pass@example.org/realm",
        "https://example.org/realm?token=secret",
    ],
)
def test_rejects_unsafe_issuer(issuer):
    with pytest.raises(AuthenticationError, match="HTTPS"):
        make_session("opaque-token", "refresh", issuer=issuer, base_url=BASE)
