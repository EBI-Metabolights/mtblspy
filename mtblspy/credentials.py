import keyring
from keyring.errors import KeyringError, PasswordDeleteError


class CredentialStorageError(RuntimeError):
    """Raised when credentials cannot be read from or written to keyring."""


class CredentialStore:
    service_name = "mtblspy"
    api_token_username = "api-token"
    user_name_username = "user-name"
    base_url_username = "base-url"

    def get_api_token(self):
        return self._get_password(self.api_token_username)

    def set_api_token(self, api_token):
        self._set_password(self.api_token_username, api_token)

    def delete_api_token(self):
        self._delete_password(self.api_token_username)

    def get_user_name(self):
        return self._get_password(self.user_name_username)

    def set_user_name(self, user_name):
        self._set_password(self.user_name_username, user_name)

    def delete_user_name(self):
        self._delete_password(self.user_name_username)

    def get_base_url(self):
        return self._get_password(self.base_url_username)

    def set_base_url(self, base_url):
        self._set_password(self.base_url_username, base_url)

    def get_jwt_token(self, rest_api_base_url):
        return self._get_password(self._jwt_username(rest_api_base_url))

    def set_jwt_token(self, rest_api_base_url, jwt_token):
        self._set_password(self._jwt_username(rest_api_base_url), jwt_token)

    def delete_jwt_token(self, rest_api_base_url):
        self._delete_password(self._jwt_username(rest_api_base_url))

    def get_refresh_token(self, rest_api_base_url):
        return self._get_password(self._refresh_username(rest_api_base_url))

    def set_refresh_token(self, rest_api_base_url, refresh_token):
        self._set_password(self._refresh_username(rest_api_base_url), refresh_token)

    def delete_refresh_token(self, rest_api_base_url):
        self._delete_password(self._refresh_username(rest_api_base_url))

    def clear_session(self, rest_api_base_url=None, submission_api_base_url=None):
        self.delete_api_token()
        self.delete_user_name()
        for base_url in (rest_api_base_url, submission_api_base_url):
            if base_url:
                self.delete_jwt_token(base_url)
                self.delete_refresh_token(base_url)

    def _get_password(self, username):
        try:
            return keyring.get_password(self.service_name, username)
        except KeyringError as exc:
            raise CredentialStorageError(f"Unable to read credentials from keyring: {exc}") from exc

    def _set_password(self, username, password):
        try:
            keyring.set_password(self.service_name, username, password)
        except KeyringError as exc:
            raise CredentialStorageError(f"Unable to save credentials to keyring: {exc}") from exc

    def _delete_password(self, username):
        try:
            keyring.delete_password(self.service_name, username)
        except PasswordDeleteError:
            pass
        except KeyringError as exc:
            raise CredentialStorageError(f"Unable to delete credentials from keyring: {exc}") from exc

    @staticmethod
    def _jwt_username(rest_api_base_url):
        return f"jwt-token:{rest_api_base_url.rstrip('/')}"

    @staticmethod
    def _refresh_username(rest_api_base_url):
        return f"refresh-token:{rest_api_base_url.rstrip('/')}"
