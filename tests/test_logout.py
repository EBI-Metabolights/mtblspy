import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from keyring.errors import PasswordDeleteError

from mtblspy.commands.cli import cli
from mtblspy.credential_files import (
    CredentialStorageError,
    read_private_json,
    write_private_json,
)
from mtblspy.credentials import DEFAULT_BASE_URL, CredentialStore

PRODUCTION = "https://www.ebi.ac.uk/metabolights/ws"
CUSTOM = "https://custom.example/metabolights/ws"


def test_logout_all_clears_current_legacy_and_custom_servers(isolated_credentials):
    CredentialStore().replace_session({"access_token": "development-secret"})
    CredentialStore.for_base_url(PRODUCTION).replace_session(
        {"access_token": "production-secret"}
    )
    CredentialStore.for_base_url(CUSTOM).replace_session(
        {"access_token": "custom-secret"}
    )
    # Legacy clients could save production tokens under the default service.
    isolated_credentials[("mtblspy", "jwt-token:" + PRODUCTION + "3")] = "legacy-secret"
    isolated_credentials[("mtblspy", "user-name")] = "legacy-user"
    isolated_credentials[("other-application", "password")] = "keep"
    CredentialStore().set_base_url(PRODUCTION)

    result = CliRunner().invoke(cli, ["auth", "logout", "--all"])

    assert result.exit_code == 0, result.output
    assert isolated_credentials == {("other-application", "password"): "keep"}
    assert "all known" in result.output
    assert "production-secret" not in result.output


def test_logout_one_server_preserves_other_servers(isolated_credentials):
    CredentialStore.for_base_url(PRODUCTION).replace_session(
        {"access_token": "production"}
    )
    CredentialStore.for_base_url(CUSTOM).replace_session({"access_token": "custom"})
    result = CliRunner().invoke(cli, ["auth", "logout", "--base-url", PRODUCTION])
    assert result.exit_code == 0, result.output
    assert (
        CredentialStore.for_base_url(PRODUCTION).get_oauth_session(PRODUCTION + "3")
        is None
    )
    assert CredentialStore.for_base_url(CUSTOM).get_jwt_token(CUSTOM) == "custom"


def test_all_logout_keeps_trying_after_one_entry_is_denied(isolated_credentials):
    store = CredentialStore.for_base_url(PRODUCTION)
    store.replace_session({"access_token": "current-secret"})
    isolated_credentials[(store.service_name, "api-token")] = "blocked-secret"
    isolated_credentials[(store.service_name, "user-name")] = "remove-user"
    CredentialStore.for_base_url(CUSTOM).replace_session(
        {"access_token": "custom-secret"}
    )

    def delete(service, account):
        if account == "api-token" and service == store.service_name:
            raise PasswordDeleteError("blocked-secret")
        isolated_credentials.pop((service, account), None)

    with patch("keyring.delete_password", side_effect=delete):
        result = CliRunner().invoke(cli, ["auth", "logout", "--all"])

    assert result.exit_code == 1
    assert "Logged out" not in result.output
    assert "Unable to sign out of all sessions" in result.output
    assert "blocked-secret" not in result.output
    assert isolated_credentials == {(store.service_name, "api-token"): "blocked-secret"}


def test_logout_detects_backend_that_silently_keeps_an_entry(isolated_credentials):
    store = CredentialStore()
    store.replace_session({"access_token": "secret"})
    with (
        patch("keyring.delete_password", return_value=None),
        pytest.raises(CredentialStorageError, match="Unable to sign out"),
    ):
        store.clear_session()
    assert ("mtblspy", "session") in isolated_credentials


def test_file_logout_all_discovers_servers_without_registry(
    monkeypatch, tmp_path, isolated_credentials
):
    monkeypatch.setenv("MTBLS_CREDENTIAL_STORAGE", "file")
    path = tmp_path / "credentials.json"
    write_private_json(
        path,
        {
            "mtblspy-" + CUSTOM: {
                "session": json.dumps({"access_token": "custom-secret"})
            },
            "mtblspy": {"api-token": "legacy-secret"},
            "other-application": {"value": "keep"},
        },
    )
    isolated_credentials[("mtblspy", "session")] = "keyring-session"
    result = CliRunner().invoke(cli, ["auth", "logout", "--all"])
    assert result.exit_code == 0, result.output
    assert read_private_json(path) == {"other-application": {"value": "keep"}}
    assert isolated_credentials == {("mtblspy", "session"): "keyring-session"}


def test_keyring_logout_does_not_delete_file_sessions(tmp_path):
    path = tmp_path / "credentials.json"
    saved = {"mtblspy": {"session": "file-session"}}
    write_private_json(path, saved)
    result = CliRunner().invoke(cli, ["auth", "logout", "--all"])
    assert result.exit_code == 0
    assert read_private_json(path) == saved


def test_server_registry_survives_changing_selected_server(tmp_path):
    CredentialStore.for_base_url(CUSTOM).replace_session({"access_token": "custom"})
    CredentialStore().set_base_url(PRODUCTION)
    settings = read_private_json(tmp_path / "config.json")
    assert CUSTOM in settings["credential_servers"]
    assert settings["base_url"] == PRODUCTION


def test_logout_all_includes_old_saved_server_without_registry(
    isolated_credentials, tmp_path
):
    service = "mtblspy-" + CUSTOM
    isolated_credentials[(service, "api-token")] = "legacy-custom-secret"
    write_private_json(tmp_path / "config.json", {"base_url": CUSTOM})
    CredentialStore.clear_all_sessions()
    assert not isolated_credentials


def test_logout_all_rejects_server_option():
    result = CliRunner().invoke(
        cli, ["auth", "logout", "--all", "--base-url", DEFAULT_BASE_URL]
    )
    assert result.exit_code == 2
    assert "Use either --all or --base-url" in result.output


def test_logout_all_warns_about_environment_credentials(monkeypatch):
    monkeypatch.setenv("MTBLS_JWT_TOKEN", "private-value")
    monkeypatch.setenv("MTBLS_TOKEN_FILE", "/private/shared-mcp-cache.json")
    result = CliRunner().invoke(cli, ["auth", "logout", "--all"])
    assert result.exit_code == 0, result.output
    assert "MTBLS_JWT_TOKEN" in result.output
    assert "MTBLS_TOKEN_FILE" in result.output
    assert "private-value" not in result.output
