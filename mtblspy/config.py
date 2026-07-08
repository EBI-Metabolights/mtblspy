import os

from mtblspy.credentials import CredentialStore

DEFAULT_BASE_URL = "https://www.ebi.ac.uk/metabolights/ws"
_CREDENTIAL_STORE = CredentialStore()


def get_config():
    return {"base_url": get_base_url()}


def save_config(api_key=None, base_url=None, user_name=None, credential_base_url=None):
    if api_key:
        save_api_key(api_key, credential_base_url=credential_base_url)
    if base_url:
        save_base_url(base_url)
    if user_name:
        save_user_name(user_name, credential_base_url=credential_base_url)


def save_api_key(api_key, credential_base_url=None):
    get_credential_store(credential_base_url).set_api_token(api_key)


def get_api_key(credential_base_url=None):
    return os.getenv("MTBLS_API_KEY") or get_credential_store(credential_base_url).get_api_token()


def save_user_name(user_name, credential_base_url=None):
    get_credential_store(credential_base_url).set_user_name(user_name)


def get_user_name(credential_base_url=None):
    return (
        os.getenv("MTBLS_USER")
        or os.getenv("MTBLS_USERNAME")
        or get_credential_store(credential_base_url).get_user_name()
    )


def save_base_url(base_url):
    base_url = base_url.strip().rstrip("/")
    if not base_url:
        raise ValueError("Base URL cannot be empty.")
    _CREDENTIAL_STORE.set_base_url(base_url)


def get_saved_base_url():
    return _CREDENTIAL_STORE.get_base_url()


def save_jwt_token(rest_api_base_url, jwt_token, credential_base_url=None):
    get_credential_store(credential_base_url).set_jwt_token(rest_api_base_url, jwt_token)


def get_jwt_token(rest_api_base_url, credential_base_url=None):
    return get_credential_store(credential_base_url).get_jwt_token(rest_api_base_url)


def save_refresh_token(rest_api_base_url, refresh_token, credential_base_url=None):
    get_credential_store(credential_base_url).set_refresh_token(rest_api_base_url, refresh_token)


def get_refresh_token(rest_api_base_url, credential_base_url=None):
    return get_credential_store(credential_base_url).get_refresh_token(rest_api_base_url)


def clear_session(rest_api_base_url=None, submission_api_base_url=None, credential_base_url=None):
    get_credential_store(credential_base_url).clear_session(rest_api_base_url, submission_api_base_url)


def get_base_url():
    return os.getenv("MTBLS_BASE_URL") or get_saved_base_url() or DEFAULT_BASE_URL


def get_credential_store(credential_base_url=None):
    base_url = normalize_base_url(credential_base_url) if credential_base_url else None
    if not base_url or base_url == DEFAULT_BASE_URL:
        return _CREDENTIAL_STORE
    return CredentialStore.for_base_url(base_url)


def get_credential_base_url(base_url):
    base_url = normalize_base_url(base_url)
    if base_url == DEFAULT_BASE_URL:
        return None
    return base_url


def normalize_base_url(base_url):
    return str(base_url).strip().rstrip("/")
