import json
import os
import stat
from unittest.mock import patch

import pytest
from keyring.errors import KeyringError, PasswordDeleteError

from mtblspy.credential_files import (
    CredentialStorageError,
    credential_file_path,
    read_private_json,
    write_private_json,
)
from mtblspy.credentials import DEFAULT_BASE_URL, CredentialStore


def seed_legacy(monkeypatch, tmp_path, entries, backend="keyring"):
    store = CredentialStore.for_base_url("https://one.example/ws")
    values = {
        "user-name": "user@example.org",
        "api-token": "api-value",
        "jwt-token:https://one.example/ws3": "stale-access",
        "refresh-token:https://one.example/ws3": "stale-refresh",
        "oauth-session:https://one.example/ws3": json.dumps(
            {
                "access_token": "current-access",
                "refresh_token": "current-refresh",
                "issuer": "https://one.example/iam/realms/metabolights",
                "client_id": "original-client",
                "token_type": "Bearer",
            }
        ),
    }
    if backend == "file":
        monkeypatch.setenv("MTBLS_CREDENTIAL_STORAGE", "file")
        write_private_json(tmp_path / "credentials.json", {store.service_name: values})
    else:
        entries.update(
            {(store.service_name, name): value for name, value in values.items()}
        )
    return store, values


@pytest.mark.parametrize("backend", ["keyring", "file"])
def test_migration_keeps_current_session_and_removes_duplicate_entries(
    monkeypatch, tmp_path, isolated_credentials, backend
):
    store, _ = seed_legacy(monkeypatch, tmp_path, isolated_credentials, backend)
    assert store.get_api_token() == "api-value"
    assert store.get_user_name() == "user@example.org"
    assert store.get_jwt_token("https://one.example/ws3") == "current-access"
    assert store.get_refresh_token("https://one.example/ws3") == "current-refresh"
    if backend == "file":
        values = read_private_json(tmp_path / "credentials.json")[store.service_name]
    else:
        values = {
            account: value
            for (service, account), value in isolated_credentials.items()
            if service == store.service_name
        }
    assert set(values) == {"session"}
    record = json.loads(values["session"])
    assert record["user_name"] == "user@example.org"
    assert record["client_id"] == "original-client"
    assert "stale-access" not in values["session"]
    assert "stale-refresh" not in values["session"]


def test_failed_migration_write_preserves_every_legacy_entry(
    monkeypatch, tmp_path, isolated_credentials
):
    store, old = seed_legacy(monkeypatch, tmp_path, isolated_credentials)
    with (
        patch("keyring.set_password", side_effect=KeyringError),
        pytest.raises(CredentialStorageError),
    ):
        store.get_api_token()
    for name, value in old.items():
        assert isolated_credentials[(store.service_name, name)] == value
    assert (store.service_name, "session") not in isolated_credentials


def test_failed_migration_verification_never_deletes_old_entries(
    monkeypatch, tmp_path, isolated_credentials
):
    store, old = seed_legacy(monkeypatch, tmp_path, isolated_credentials)
    original_get = __import__("keyring").get_password
    with (
        patch(
            "keyring.get_password",
            side_effect=lambda service, account: (
                None if account == "session" else original_get(service, account)
            ),
        ),
        pytest.raises(CredentialStorageError, match="confirm"),
    ):
        store.get_api_token()
    for name, value in old.items():
        assert isolated_credentials[(store.service_name, name)] == value


def test_failed_legacy_deletion_keeps_verified_session_and_retries_at_login(
    monkeypatch, tmp_path, isolated_credentials, caplog
):
    store, old = seed_legacy(monkeypatch, tmp_path, isolated_credentials)
    with patch("keyring.delete_password", side_effect=KeyringError):
        assert store.get_api_token() == "api-value"
    assert (
        json.loads(isolated_credentials[(store.service_name, "session")])[
            "refresh_token"
        ]
        == "current-refresh"
    )
    assert "earlier session could not be cleared" in caplog.text
    assert "current-refresh" not in caplog.text
    for name in old:
        assert (store.service_name, name) in isolated_credentials
    store.replace_session(
        {"access_token": "replacement", "refresh_token": "replacement-refresh"},
        user_name="replacement-user",
    )
    assert set(isolated_credentials) == {(store.service_name, "session")}


def test_legacy_base_url_moves_to_nonsecret_settings(isolated_credentials, tmp_path):
    isolated_credentials[("mtblspy", "base-url")] = "https://one.example/ws"
    assert CredentialStore().get_base_url() == "https://one.example/ws"
    assert not isolated_credentials
    assert read_private_json(tmp_path / "config.json") == {
        "base_url": "https://one.example/ws"
    }


def test_legacy_tokens_without_combined_json_still_migrate(isolated_credentials):
    isolated_credentials[("mtblspy", "jwt-token:" + DEFAULT_BASE_URL + "3")] = "access"
    isolated_credentials[("mtblspy", "refresh-token:" + DEFAULT_BASE_URL + "3")] = (
        "refresh"
    )
    session = CredentialStore().get_oauth_session(DEFAULT_BASE_URL + "3")
    assert session["access_token"] == "access"
    assert session["refresh_token"] == "refresh"
    assert session["client_id"] == "swagger-ui-test"
    assert set(isolated_credentials) == {("mtblspy", "session")}


def test_malformed_legacy_json_is_never_removed(isolated_credentials):
    name = ("mtblspy", "oauth-session:" + DEFAULT_BASE_URL + "3")
    isolated_credentials[name] = "malformed-private-token-data"
    with pytest.raises(CredentialStorageError) as error:
        CredentialStore().get_api_token()
    assert "malformed-private-token-data" not in str(error.value)
    assert isolated_credentials == {name: "malformed-private-token-data"}


def test_refresh_preserves_account_details_in_one_entry(isolated_credentials):
    store = CredentialStore()
    store.replace_session(
        {"access_token": "first", "refresh_token": "first-refresh"},
        api_token="api",
        user_name="user",
    )
    store.set_oauth_session(
        DEFAULT_BASE_URL + "3",
        {"access_token": "second", "refresh_token": "second-refresh"},
    )
    assert store.get_api_token() == "api"
    assert store.get_user_name() == "user"
    assert store.get_jwt_token(DEFAULT_BASE_URL + "3") == "second"
    assert store.get_refresh_token(DEFAULT_BASE_URL + "3") == "second-refresh"
    assert len(isolated_credentials) == 1


def test_new_login_performs_one_credential_write(isolated_credentials):
    import keyring

    with patch("keyring.set_password", wraps=keyring.set_password) as save:
        CredentialStore().replace_session(
            {"access_token": "access", "refresh_token": "refresh"},
            api_token="api",
            user_name="user",
        )
    assert save.call_count == 1
    assert len(isolated_credentials) == 1


def test_keyring_deletion_error_does_not_report_false_cleanup(
    monkeypatch, tmp_path, isolated_credentials, caplog
):
    store, old = seed_legacy(monkeypatch, tmp_path, isolated_credentials)
    with patch("keyring.delete_password", side_effect=PasswordDeleteError):
        assert store.get_api_token() == "api-value"
    assert "earlier session could not be cleared" in caplog.text
    for name in old:
        assert (store.service_name, name) in isolated_credentials


def test_failed_new_login_save_preserves_previous_working_record(isolated_credentials):
    store = CredentialStore()
    store.replace_session(
        {"access_token": "working", "refresh_token": "working-refresh"},
        user_name="original-user",
    )
    saved = dict(isolated_credentials)
    with (
        patch("keyring.set_password", side_effect=KeyringError),
        pytest.raises(CredentialStorageError),
    ):
        store.replace_session(
            {"access_token": "replacement"}, user_name="replacement-user"
        )
    assert isolated_credentials == saved


def test_saving_selected_server_removes_old_keychain_setting(
    isolated_credentials, tmp_path
):
    isolated_credentials[("mtblspy", "base-url")] = "https://old.example/ws"
    CredentialStore().set_base_url("https://new.example/ws")
    assert not isolated_credentials
    assert read_private_json(tmp_path / "config.json") == {
        "base_url": "https://new.example/ws"
    }


def test_keyring_failure_never_silently_writes_a_file(tmp_path):
    with (
        patch("keyring.set_password", side_effect=KeyringError("secret-token-value")),
        pytest.raises(CredentialStorageError) as error,
    ):
        CredentialStore().set_api_token("secret-token-value")
    assert "secret-token-value" not in str(error.value)
    assert "Unable to save your sign-in session" in str(error.value)
    assert not (tmp_path / "credentials.json").exists()


def test_explicit_file_storage_survives_new_store_and_isolates_servers(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MTBLS_CREDENTIAL_STORAGE", "file")
    with patch(
        "keyring.set_password", side_effect=AssertionError("must not use keyring")
    ):
        CredentialStore.for_base_url("https://one.example/ws").set_api_token("one")
        CredentialStore.for_base_url("https://two.example/ws").set_api_token("two")
    assert (
        CredentialStore.for_base_url("https://one.example/ws").get_api_token() == "one"
    )
    assert (
        CredentialStore.for_base_url("https://two.example/ws").get_api_token() == "two"
    )
    if os.name == "posix":
        assert stat.S_IMODE((tmp_path / "credentials.json").stat().st_mode) == 0o600


def test_atomic_rotation_and_logout_preserve_other_server(monkeypatch):
    monkeypatch.setenv("MTBLS_CREDENTIAL_STORAGE", "file")
    one = CredentialStore.for_base_url("https://one.example/ws")
    two = CredentialStore.for_base_url("https://two.example/ws")
    one.set_oauth_session(
        "https://one.example/ws3",
        {"access_token": "old", "refresh_token": "old-refresh"},
    )
    two.set_api_token("keep")
    one.set_oauth_session(
        "https://one.example/ws3",
        {"access_token": "new", "refresh_token": "new-refresh"},
    )
    assert (
        one.get_oauth_session("https://one.example/ws3")["refresh_token"]
        == "new-refresh"
    )
    one.clear_session("https://one.example/ws", "https://one.example/ws3")
    assert one.get_oauth_session("https://one.example/ws3") is None
    assert two.get_api_token() == "keep"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "hardlink"])
def test_refuses_unsafe_credential_paths(tmp_path, kind):
    path = tmp_path / "credentials.json"
    write_private_json(path, {"secret": "value"})
    if kind == "file":
        path.chmod(0o644)
    elif kind == "directory":
        tmp_path.chmod(0o755)
    elif kind == "hardlink":
        (tmp_path / "copy").hardlink_to(path)
    else:
        target = tmp_path / "target.json"
        path.rename(target)
        path.symlink_to(target)
    try:
        with pytest.raises(CredentialStorageError):
            read_private_json(path)
        with pytest.raises(CredentialStorageError):
            write_private_json(path, {"replacement": "value"})
    finally:
        tmp_path.chmod(0o700)


def test_atomic_write_preserves_previous_file_on_failure(tmp_path):
    path = tmp_path / "credentials.json"
    write_private_json(path, {"old": "session"})
    with (
        patch("mtblspy.credential_files.Path.replace", side_effect=OSError),
        pytest.raises(CredentialStorageError),
    ):
        write_private_json(path, {"new": "session"})
    assert json.loads(path.read_text()) == {"old": "session"}
    assert not list(tmp_path.glob(".mtblspy-*.tmp"))


def test_invalid_file_does_not_disclose_its_content(tmp_path):
    path = tmp_path / "credentials.json"
    path.write_text("private-refresh-token")
    path.chmod(0o600)
    with pytest.raises(CredentialStorageError) as error:
        read_private_json(path)
    assert "private-refresh-token" not in str(error.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_legacy_default_settings_permissions_are_repaired(monkeypatch, tmp_path):
    from pathlib import Path

    monkeypatch.delenv("MTBLS_CREDENTIAL_FILE")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    folder = tmp_path / ".mtblspy"
    folder.mkdir(mode=0o755)
    folder.chmod(0o755)
    settings = folder / "config.json"
    settings.write_text('{"base_url": "https://example.org/ws"}')
    settings.chmod(0o644)
    before = settings.read_bytes()

    assert credential_file_path() == folder / "credentials.json"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE(settings.stat().st_mode) == 0o600
    assert settings.read_bytes() == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_custom_directory_is_not_automatically_chmodded(monkeypatch, tmp_path):
    folder = tmp_path / "custom"
    folder.mkdir(mode=0o755)
    folder.chmod(0o755)
    monkeypatch.setenv("MTBLS_CREDENTIAL_FILE", str(folder / "credentials.json"))
    assert credential_file_path() == folder / "credentials.json"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o755


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_legacy_settings_links_are_rejected_without_changing_target(
    monkeypatch, tmp_path, kind
):
    from pathlib import Path

    monkeypatch.delenv("MTBLS_CREDENTIAL_FILE")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    folder = tmp_path / ".mtblspy"
    folder.mkdir(mode=0o700)
    target = tmp_path / "other.json"
    target.write_text("unchanged")
    target.chmod(0o644)
    settings = folder / "config.json"
    if kind == "symlink":
        settings.symlink_to(target)
    else:
        settings.hardlink_to(target)
    with pytest.raises(CredentialStorageError, match="access your sign-in session"):
        credential_file_path()
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert target.read_text() == "unchanged"
