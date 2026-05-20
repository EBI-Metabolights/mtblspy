import os

from mtblspy.credentials import CredentialStore

DEFAULT_BASE_URL = "https://wwwdev.ebi.ac.uk/metabolights/ws"
_CREDENTIAL_STORE = CredentialStore()


def get_config():
    return {"base_url": get_base_url()}


def save_config(api_key=None, base_url=None, user_name=None):
    if api_key:
        save_api_key(api_key)
    if user_name:
        save_user_name(user_name)


def save_api_key(api_key):
    _CREDENTIAL_STORE.set_api_token(api_key)


def get_api_key():
    return os.getenv("MTBLS_API_KEY") or _CREDENTIAL_STORE.get_api_token()


def save_user_name(user_name):
    _CREDENTIAL_STORE.set_user_name(user_name)


def get_user_name():
    return os.getenv("MTBLS_USER") or os.getenv("MTBLS_USERNAME") or _CREDENTIAL_STORE.get_user_name()


def save_jwt_token(rest_api_base_url, jwt_token):
    _CREDENTIAL_STORE.set_jwt_token(rest_api_base_url, jwt_token)


def get_jwt_token(rest_api_base_url):
    return _CREDENTIAL_STORE.get_jwt_token(rest_api_base_url)


def save_refresh_token(rest_api_base_url, refresh_token):
    _CREDENTIAL_STORE.set_refresh_token(rest_api_base_url, refresh_token)


def get_refresh_token(rest_api_base_url):
    return _CREDENTIAL_STORE.get_refresh_token(rest_api_base_url)


def get_base_url():
    return os.getenv("MTBLS_BASE_URL") or DEFAULT_BASE_URL
