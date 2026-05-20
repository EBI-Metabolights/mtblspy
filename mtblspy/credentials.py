import keyring
from keyring.errors import KeyringError


class CredentialStorageError(RuntimeError):
    """Raised when credentials cannot be read from or written to keyring."""


class CredentialStore:
    service_name = "mtblspy"
    api_token_username = "api-token"
    user_name_username = "user-name"

    def get_api_token(self):
        return self._get_password(self.api_token_username)

    def set_api_token(self, api_token):
        self._set_password(self.api_token_username, api_token)

    def get_user_name(self):
        return self._get_password(self.user_name_username)

    def set_user_name(self, user_name):
        self._set_password(self.user_name_username, user_name)

    def get_jwt_token(self, rest_api_base_url):
        return self._get_password(self._jwt_username(rest_api_base_url))

    def set_jwt_token(self, rest_api_base_url, jwt_token):
        self._set_password(self._jwt_username(rest_api_base_url), jwt_token)

    def get_refresh_token(self, rest_api_base_url):
        return self._get_password(self._refresh_username(rest_api_base_url))

    def set_refresh_token(self, rest_api_base_url, refresh_token):
        self._set_password(self._refresh_username(rest_api_base_url), refresh_token)

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

    @staticmethod
    def _jwt_username(rest_api_base_url):
        return f"jwt-token:{rest_api_base_url.rstrip('/')}"

    @staticmethod
    def _refresh_username(rest_api_base_url):
        return f"refresh-token:{rest_api_base_url.rstrip('/')}"
