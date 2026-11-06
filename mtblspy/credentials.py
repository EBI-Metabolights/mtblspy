"""One credential record per server, with verified migration of older entries."""

import hashlib
import json
import logging
import os

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from mtblspy.credential_files import (
    CredentialStorageError,
    credential_file_path,
    credential_lock,
    read_private_json,
    write_private_json,
)

DEFAULT_BASE_URL = "https://wwwdev.ebi.ac.uk/metabolights/ws"
OAUTH_FIELDS = {
    "access_token",
    "refresh_token",
    "issuer",
    "client_id",
    "token_type",
    "expires_at",
    "refresh_expires_at",
    "scope",
    "requested_scope",
    "source_id",
    "token_file",
}
logger = logging.getLogger(__name__)


def rest_base_url(url):
    url = url.strip().rstrip("/")
    return url[:-1] if url.endswith("/ws3") else url


class CredentialStore:
    service_name = "mtblspy"
    session_username = "session"
    api_token_username = "api-token"
    user_name_username = "user-name"
    base_url_username = "base-url"

    def __init__(self, service_name=None):
        if service_name:
            self.service_name = service_name
        prefix = "mtblspy-"
        self.base_url = (
            rest_base_url(self.service_name[len(prefix) :])
            if self.service_name.startswith(prefix)
            else DEFAULT_BASE_URL
        )

    @classmethod
    def for_base_url(cls, base_url):
        return cls(f"mtblspy-{rest_base_url(base_url)}")

    def get_api_token(self):
        return self._get_field("api_token")

    def set_api_token(self, api_token):
        self._update_fields({"api_token": api_token})

    def delete_api_token(self):
        self._update_fields({}, remove={"api_token"})

    def get_user_name(self):
        return self._get_field("user_name")

    def set_user_name(self, user_name):
        self._update_fields({"user_name": user_name})

    def delete_user_name(self):
        self._update_fields({}, remove={"user_name"})

    def get_base_url(self):
        path = credential_file_path().parent / "config.json"
        with credential_lock(path.with_suffix(".lock")):
            settings = read_private_json(path) or {}
            if settings.get("base_url"):
                return settings["base_url"]
            legacy = self._get_password(self.base_url_username)
            if legacy:
                settings["base_url"] = legacy
                write_private_json(path, settings)
                if read_private_json(path) != settings:
                    raise CredentialStorageError(
                        "Unable to update your account settings. Please try again."
                    )
                self._cleanup_legacy((self.base_url_username,))
            return legacy

    def set_base_url(self, base_url):
        path = credential_file_path().parent / "config.json"
        with credential_lock(path.with_suffix(".lock")):
            settings = read_private_json(path) or {}
            settings["base_url"] = base_url
            write_private_json(path, settings)
            if read_private_json(path) != settings:
                raise CredentialStorageError(
                    "Unable to update your account settings. Please try again."
                )
            if self._get_password(self.base_url_username) is not None:
                self._cleanup_legacy((self.base_url_username,))

    def get_jwt_token(self, rest_api_base_url):
        return self._get_field("access_token")

    def set_jwt_token(self, rest_api_base_url, jwt_token):
        from mtblspy.oauth import make_session

        with self._record_lock():
            record = self._load_record()
            record.pop("expires_at", None)
            record.update(
                make_session(
                    jwt_token, record.get("refresh_token"), base_url=self.base_url
                )
            )
            self._save_record(record)

    def delete_jwt_token(self, rest_api_base_url):
        self._update_fields({}, remove={"access_token", "expires_at"})

    def get_refresh_token(self, rest_api_base_url):
        return self._get_field("refresh_token")

    def set_refresh_token(self, rest_api_base_url, refresh_token):
        self._update_fields({"refresh_token": refresh_token})

    def delete_refresh_token(self, rest_api_base_url):
        self._update_fields({}, remove={"refresh_token", "refresh_expires_at"})

    def get_oauth_session(self, base_url):
        with self._record_lock():
            record = self._load_record()
        if not (record.get("access_token") or record.get("token_file")):
            return None
        return {key: value for key, value in record.items() if key in OAUTH_FIELDS}

    def set_oauth_session(self, base_url, session):
        self._update_fields(
            {key: value for key, value in session.items() if key in OAUTH_FIELDS},
            remove=OAUTH_FIELDS,
        )

    def replace_session(self, session, *, api_token=None, user_name=None):
        """Commit a new login without first deleting the old working session."""
        with self._record_lock():
            pending = [
                name
                for name in self._legacy_names()
                if self._get_password(name) is not None
            ]
            record = {
                "version": 1,
                "base_url": self.base_url,
                **{key: value for key, value in session.items() if key in OAUTH_FIELDS},
            }
            if api_token is not None:
                record["api_token"] = api_token
            if user_name is not None:
                record["user_name"] = user_name
            self._save_record(record, legacy_names=pending)

    def clear_session(
        self,
        rest_api_base_url=None,
        submission_api_base_url=None,
        *,
        additional_base_urls=(),
    ):
        with self._record_lock():
            remaining = []
            urls = [
                url
                for url in (
                    rest_api_base_url,
                    submission_api_base_url,
                    *additional_base_urls,
                )
                if url
            ]
            for name in [self.session_username, *self._legacy_names(*urls)]:
                try:
                    self._delete_password(name)
                except CredentialStorageError:
                    remaining.append(name)
            if remaining:
                raise CredentialStorageError(
                    f"Unable to sign out of {self.base_url}. Please try again or contact support."
                )

    @classmethod
    def clear_all_sessions(cls):
        """Clear known mtblspy servers in the explicitly selected backend."""
        path = credential_file_path().parent / "config.json"
        with credential_lock(path.with_suffix(".lock")):
            settings = read_private_json(path) or {}
        servers = settings.get("credential_servers", [])
        if not isinstance(servers, list) or any(
            not isinstance(url, str) for url in servers
        ):
            raise CredentialStorageError(
                "Unable to find all your sessions. Use logout --base-url to sign out of individual servers."
            )
        servers = {DEFAULT_BASE_URL, "https://www.ebi.ac.uk/metabolights/ws", *servers}
        servers.update(
            url
            for url in (settings.get("base_url"), os.getenv("MTBLS_BASE_URL"))
            if url
        )
        default = cls()
        stores = {default.service_name: default}
        for url in sorted(servers):
            store = cls.for_base_url(url)
            stores[store.service_name] = store
        if cls.storage_backend() == "file":
            with credential_lock(credential_file_path().with_suffix(".lock")):
                data = read_private_json(credential_file_path()) or {}
            for name in data:
                if name == "mtblspy" or name.startswith("mtblspy-"):
                    stores[name] = cls(name)
        failures = []
        for store in stores.values():
            try:
                store.clear_session(
                    additional_base_urls=servers
                    if store.service_name == "mtblspy"
                    else ()
                )
            except CredentialStorageError:
                failures.append(store.service_name)
        if failures:
            raise CredentialStorageError(
                "Unable to sign out of all sessions. Please try again or contact support."
            )

    def _record_lock(self):
        identity = hashlib.sha256(self.service_name.encode()).hexdigest()
        return credential_lock(
            credential_file_path().parent / "records" / (identity + ".lock")
        )

    def _get_field(self, name):
        with self._record_lock():
            return self._load_record().get(name)

    def _update_fields(self, fields, *, remove=()):
        with self._record_lock():
            record = self._load_record()
            for name in remove:
                record.pop(name, None)
            record.update(fields)
            self._save_record(record)

    def _decode_record(self, value):
        try:
            record = json.loads(value)
            if (
                not isinstance(record, dict)
                or record.get("version") != 1
                or record.get("base_url") != self.base_url
            ):
                raise ValueError
            return record
        except (ValueError, TypeError):
            raise CredentialStorageError(
                "Your sign-in session could not be loaded. Please sign in again."
            ) from None

    def _legacy_names(self, *base_urls):
        endpoints = []
        for url in (self.base_url, *base_urls):
            base = rest_base_url(url)
            for endpoint in (
                base,
                base + "3" if base.endswith("/ws") else base + "/ws3",
            ):
                if endpoint not in endpoints:
                    endpoints.append(endpoint)
        return [
            self.api_token_username,
            self.user_name_username,
            self.base_url_username,
            *[
                f"{kind}:{url}"
                for kind in ("jwt-token", "refresh-token", "oauth-session")
                for url in endpoints
            ],
        ]

    def _load_record(self):
        value = self._get_password(self.session_username)
        if value is not None:
            return self._decode_record(value)
        legacy = {
            name: value
            for name in self._legacy_names()
            if (value := self._get_password(name)) is not None
        }
        record = {"version": 1, "base_url": self.base_url}
        if not legacy:
            return record
        for old, new in (
            (self.api_token_username, "api_token"),
            (self.user_name_username, "user_name"),
        ):
            if old in legacy:
                record[new] = legacy[old]
        for name, value in legacy.items():
            if name.startswith("oauth-session:"):
                try:
                    session = json.loads(value)
                    if not isinstance(session, dict):
                        raise ValueError
                except (ValueError, TypeError):
                    raise CredentialStorageError(
                        "Your sign-in session could not be loaded. Please sign in again."
                    ) from None
                record.update(
                    {
                        key: value
                        for key, value in session.items()
                        if key in OAUTH_FIELDS
                    }
                )
        if not (record.get("access_token") or record.get("token_file")):
            from mtblspy.oauth import make_session

            access = next(
                (
                    legacy[name]
                    for name in reversed(self._legacy_names())
                    if name.startswith("jwt-token:") and name in legacy
                ),
                None,
            )
            refresh = next(
                (
                    legacy[name]
                    for name in reversed(self._legacy_names())
                    if name.startswith("refresh-token:") and name in legacy
                ),
                None,
            )
            if access:
                record.update(make_session(access, refresh, base_url=self.base_url))
            elif refresh:
                record["refresh_token"] = refresh
        if record.get("access_token"):
            from mtblspy.oauth import validate_session

            validate_session(record)
        if self.base_url_username in legacy:
            path = credential_file_path().parent / "config.json"
            with credential_lock(path.with_suffix(".lock")):
                settings = read_private_json(path) or {}
                if not settings.get("base_url"):
                    settings["base_url"] = legacy[self.base_url_username]
                    write_private_json(path, settings)
                if read_private_json(path) != settings:
                    raise CredentialStorageError(
                        "Unable to update your account settings. Please try again."
                    )
        self._save_record(record, legacy_names=legacy)
        return record

    def _save_record(self, record, *, legacy_names=()):
        encoded = json.dumps(record)
        self._set_password(self.session_username, encoded)
        if self._get_password(self.session_username) != encoded:
            raise CredentialStorageError(
                "Unable to confirm your sign-in session. Please try signing in again."
            )
        self._register_server()
        self._cleanup_legacy(legacy_names)

    def _register_server(self):
        path = credential_file_path().parent / "config.json"
        with credential_lock(path.with_suffix(".lock")):
            settings = read_private_json(path) or {}
            servers = settings.setdefault("credential_servers", [])
            if not isinstance(servers, list) or any(
                not isinstance(url, str) for url in servers
            ):
                raise CredentialStorageError(
                    "Unable to load your account settings. Please try again."
                )
            if self.base_url not in servers:
                servers.append(self.base_url)
                write_private_json(path, settings)

    def _cleanup_legacy(self, names):
        for name in names:
            try:
                self._delete_password(name)
            except CredentialStorageError:
                logger.warning(
                    "Your current session is available, but an earlier session could not be cleared. Please try signing out again."
                )
                return

    @staticmethod
    def storage_backend():
        backend = os.getenv("MTBLS_CREDENTIAL_STORAGE", "keyring")
        if backend not in {"keyring", "file"}:
            raise CredentialStorageError(
                "Unable to initialize sign-in. Please contact support."
            )
        return backend

    def _file_operation(self, username, value=None, *, operation="get"):
        path = credential_file_path()
        with credential_lock(path.with_suffix(".lock")):
            data = read_private_json(path) or {}
            accounts = data.get(self.service_name, {})
            if not isinstance(accounts, dict):
                raise CredentialStorageError(
                    "Your sign-in session could not be loaded. Please sign in again."
                )
            if operation == "get":
                result = accounts.get(username)
                if result is not None and not isinstance(result, str):
                    raise CredentialStorageError(
                        "Your sign-in session could not be loaded. Please sign in again."
                    )
                return result
            if operation == "set":
                accounts[username] = value
            else:
                if username not in accounts:
                    return
                accounts.pop(username, None)
            if accounts:
                data[self.service_name] = accounts
            else:
                data.pop(self.service_name, None)
            write_private_json(path, data)

    @staticmethod
    def _keyring_error(action):
        if action == "delete":
            return CredentialStorageError(
                "Unable to complete logout. Please try again or contact support."
            )
        if action == "save":
            return CredentialStorageError(
                "Unable to save your sign-in session. Please try again or contact support."
            )
        return CredentialStorageError(
            "Unable to load your sign-in session. Please try again or contact support."
        )

    def _get_password(self, username):
        if self.storage_backend() == "file":
            return self._file_operation(username)
        try:
            return keyring.get_password(self.service_name, username)
        except KeyringError:
            raise self._keyring_error("read") from None

    def _set_password(self, username, password):
        if self.storage_backend() == "file":
            return self._file_operation(username, password, operation="set")
        try:
            keyring.set_password(self.service_name, username, password)
        except KeyringError:
            raise self._keyring_error("save") from None

    def _delete_password(self, username):
        if self.storage_backend() == "file":
            return self._file_operation(username, operation="delete")
        if self._get_password(username) is None:
            return
        try:
            keyring.delete_password(self.service_name, username)
        except PasswordDeleteError:
            if self._get_password(username) is not None:
                raise self._keyring_error("delete") from None
        except KeyringError:
            raise self._keyring_error("delete") from None
        if self._get_password(username) is not None:
            raise self._keyring_error("delete") from None

    @staticmethod
    def _jwt_username(rest_api_base_url):
        return f"jwt-token:{rest_api_base_url.rstrip('/')}"

    @staticmethod
    def _refresh_username(rest_api_base_url):
        return f"refresh-token:{rest_api_base_url.rstrip('/')}"
