from mtblspy.config import (
    DEFAULT_BASE_URL,
    clear_session,
    get_api_key,
    get_base_url,
    get_config,
    get_jwt_token,
    get_refresh_token,
    get_user_name,
    save_config,
    save_jwt_token,
    save_refresh_token,
)


class FakeCredentialStore:
    def __init__(self):
        self.api_token = None
        self.user_name = None
        self.jwt_tokens = {}
        self.refresh_tokens = {}
        self.cleared_session = None

    def get_api_token(self):
        return self.api_token

    def set_api_token(self, api_token):
        self.api_token = api_token

    def get_user_name(self):
        return self.user_name

    def set_user_name(self, user_name):
        self.user_name = user_name

    def get_jwt_token(self, rest_api_base_url):
        return self.jwt_tokens.get(rest_api_base_url)

    def set_jwt_token(self, rest_api_base_url, jwt_token):
        self.jwt_tokens[rest_api_base_url] = jwt_token

    def get_refresh_token(self, rest_api_base_url):
        return self.refresh_tokens.get(rest_api_base_url)

    def set_refresh_token(self, rest_api_base_url, refresh_token):
        self.refresh_tokens[rest_api_base_url] = refresh_token

    def clear_session(self, rest_api_base_url=None, submission_api_base_url=None):
        self.cleared_session = (rest_api_base_url, submission_api_base_url)


def configure_fake_credentials(monkeypatch):
    fake_store = FakeCredentialStore()
    monkeypatch.setattr("mtblspy.config._CREDENTIAL_STORE", fake_store)
    return fake_store


def test_get_config_uses_default_base_url(monkeypatch):
    configure_fake_credentials(monkeypatch)

    config = get_config()

    assert config == {"base_url": "https://www.ebi.ac.uk/metabolights/ws"}
    assert DEFAULT_BASE_URL == "https://www.ebi.ac.uk/metabolights/ws"


def test_save_config_stores_auth_values_in_keyring_only(monkeypatch):
    fake_store = configure_fake_credentials(monkeypatch)

    save_config(api_key="test-key", base_url="https://test.com", user_name="user@example.org")

    config = get_config()
    assert config == {"base_url": DEFAULT_BASE_URL}
    assert fake_store.api_token == "test-key"
    assert fake_store.user_name == "user@example.org"
    assert get_api_key() == "test-key"
    assert get_user_name() == "user@example.org"
    assert get_base_url() == DEFAULT_BASE_URL


def test_env_vars_override(monkeypatch):
    configure_fake_credentials(monkeypatch)
    save_config(api_key="file-key", base_url="https://file.com")

    monkeypatch.setenv("MTBLS_API_KEY", "env-key")
    monkeypatch.setenv("MTBLS_BASE_URL", "https://env.com")

    assert get_api_key() == "env-key"
    assert get_base_url() == "https://env.com"


def test_jwt_token_uses_keyring(monkeypatch):
    fake_store = configure_fake_credentials(monkeypatch)

    save_jwt_token("https://test.com/metabolights/ws", "jwt-token")

    assert fake_store.jwt_tokens == {"https://test.com/metabolights/ws": "jwt-token"}
    assert get_jwt_token("https://test.com/metabolights/ws") == "jwt-token"


def test_refresh_token_uses_keyring(monkeypatch):
    fake_store = configure_fake_credentials(monkeypatch)

    save_refresh_token("https://test.com/metabolights/ws3", "refresh-token")

    assert fake_store.refresh_tokens == {"https://test.com/metabolights/ws3": "refresh-token"}
    assert get_refresh_token("https://test.com/metabolights/ws3") == "refresh-token"


def test_clear_session_uses_keyring(monkeypatch):
    fake_store = configure_fake_credentials(monkeypatch)

    clear_session("https://test.com/metabolights/ws", "https://test.com/metabolights/ws3")

    assert fake_store.cleared_session == (
        "https://test.com/metabolights/ws",
        "https://test.com/metabolights/ws3",
    )
