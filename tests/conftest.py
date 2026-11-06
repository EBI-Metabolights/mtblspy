"""Keep authentication tests isolated from the developer's real credentials."""

import sys

import pytest
from keyring.errors import PasswordDeleteError


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch, tmp_path):
    for name in (
        "MTBLS_API_KEY",
        "MTBLS_BASE_URL",
        "MTBLS_USER",
        "MTBLS_USERNAME",
        "MTBLS_PASSWORD",
        "MTBLS_JWT_TOKEN",
        "MTBLS_REFRESH_TOKEN",
        "MTBLS_TOKEN_FILE",
        "MTBLS_OIDC_ISSUER",
        "MTBLS_OIDC_CLIENT_ID",
        "MTBLS_CREDENTIAL_STORAGE",
        "MTBLS_NON_INTERACTIVE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MTBLS_CREDENTIAL_FILE", str(tmp_path / "credentials.json"))
    entries = {}

    def delete(service, account):
        try:
            entries.pop((service, account))
        except KeyError:
            raise PasswordDeleteError from None

    monkeypatch.setattr(
        "keyring.get_password", lambda service, account: entries.get((service, account))
    )
    monkeypatch.setattr(
        "keyring.set_password",
        lambda service, account, value: entries.__setitem__((service, account), value),
    )
    monkeypatch.setattr("keyring.delete_password", delete)
    folder_check = sys.modules.get(
        "mtblspy.commands.submissions.submission_check_folders"
    )
    if folder_check is not None:
        monkeypatch.setattr(
            folder_check, "DEFAULT_LOCAL_SUBMISSION_CACHE_PATH", tmp_path / "reports"
        )
    return entries
