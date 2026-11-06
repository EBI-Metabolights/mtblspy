"""Authentication output describes user actions without exposing implementation."""

import re
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from keyring.errors import KeyringError

from mtblspy.commands.cli import cli
from mtblspy.commands.submissions.client import SubmissionClient
from mtblspy.credentials import CredentialStore

BASE = "https://www.ebi.ac.uk/metabolights/ws"
INTERNAL_DETAILS = re.compile(
    r"keyring|keychain|backend|storage|credential[-_ ](?:file|store)|"
    r"MTBLS_CREDENTIAL_|\.mtblspy|credentials\.json|config\.json|mode\s+(600|700)",
    re.IGNORECASE,
)


def assert_public_message(output):
    match = INTERNAL_DETAILS.search(output)
    assert match is None, match.group(0) if match else ""
    assert "private-token-value" not in output


@pytest.mark.parametrize(
    "arguments",
    [
        ["--help"],
        ["auth", "--help"],
        ["auth", "login", "--help"],
        ["auth", "logout", "--help"],
    ],
)
def test_auth_help_omits_backend_details(arguments):
    result = CliRunner().invoke(cli, arguments)
    assert result.exit_code == 0
    assert_public_message(result.output)


@pytest.mark.parametrize("backend", ["keyring", "file"])
@pytest.mark.parametrize("all_sessions", [False, True])
def test_logout_success_is_independent_of_backend(monkeypatch, backend, all_sessions):
    monkeypatch.setenv("MTBLS_CREDENTIAL_STORAGE", backend)
    store = CredentialStore.for_base_url(BASE)
    store.replace_session({"access_token": "private-token-value"})
    arguments = (
        ["auth", "logout", "--all"]
        if all_sessions
        else ["auth", "logout", "--base-url", BASE]
    )
    result = CliRunner().invoke(cli, arguments)
    assert result.exit_code == 0, result.output
    assert "Logged out" in result.output
    assert_public_message(result.output)


@pytest.mark.parametrize("operation", ["get_password", "delete_password"])
def test_logout_errors_omit_dependency_details(operation):
    store = CredentialStore.for_base_url(BASE)
    store.replace_session({"access_token": "private-token-value"})
    with patch(
        "keyring." + operation,
        side_effect=KeyringError("keyring backend private-token-value"),
    ):
        result = CliRunner().invoke(cli, ["auth", "logout", "--all"])
    assert result.exit_code == 1
    assert "Unable to sign out" in result.output
    assert_public_message(result.output)


def test_login_save_failure_omits_dependency_details():
    with (
        patch(
            "keyring.set_password",
            side_effect=KeyringError("keychain backend private-token-value"),
        ),
        patch.object(
            SubmissionClient, "try_fetch_api_token_from_jwt", return_value=None
        ),
    ):
        result = CliRunner().invoke(
            cli,
            ["auth", "login", "--base-url", BASE, "--non-interactive"],
            env={"MTBLS_JWT_TOKEN": "private-token-value"},
        )
    assert result.exit_code == 1
    assert "Unable to save your sign-in session" in result.output
    assert_public_message(result.output)


def test_invalid_internal_configuration_is_not_exposed():
    result = CliRunner().invoke(
        cli,
        ["auth", "logout", "--all"],
        env={"MTBLS_CREDENTIAL_STORAGE": "invalid-backend"},
    )
    assert result.exit_code == 1
    assert "Please contact support" in result.output
    assert_public_message(result.output)


def test_filesystem_failure_does_not_expose_paths():
    with patch(
        "mtblspy.credential_files.Path.mkdir",
        side_effect=PermissionError("keyring /private/.mtblspy/config.json"),
    ):
        result = CliRunner().invoke(cli, ["auth", "logout", "--all"])
    assert result.exit_code == 1
    assert "Unable to access your sign-in session" in result.output
    assert_public_message(result.output)


def test_user_guide_omits_backend_configuration():
    from pathlib import Path

    guide = (
        Path(__file__).resolve().parents[1] / "docs" / "submission_workflow_guide.md"
    )
    text = guide.read_text()
    assert_public_message(
        text[text.index("### Top-Level CLI") : text.index("### 2. Configuration")]
    )
