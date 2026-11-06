"""Refreshable OAuth sessions, including a shared MCP login token cache."""

import base64
import hashlib
import json
import math
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from mtblspy import config
from mtblspy.credential_files import (
    credential_file_path,
    credential_lock,
    read_private_json,
    write_private_json,
)
from mtblspy.exceptions import AuthenticationError

DEFAULT_CLIENT_ID = "swagger-ui-test"


def session_source_id(session):
    return hashlib.sha256(json.dumps(session, sort_keys=True).encode()).hexdigest()


def decode_claims(token):
    try:
        payload = token.split(".")[1]
        result = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        return result if isinstance(result, dict) else {}
    except (IndexError, ValueError, TypeError, UnicodeError):
        return {}


def validate_issuer(issuer):
    parts = urlsplit(issuer)
    if (
        not parts.hostname
        or parts.scheme != "https"
        and not (
            parts.scheme == "http"
            and parts.hostname in {"localhost", "127.0.0.1", "::1"}
        )
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise AuthenticationError(
            "The OAuth issuer must be an HTTPS URL without credentials or query parameters."
        )
    return issuer.rstrip("/")


def default_issuer(base_url):
    parts = urlsplit(base_url)
    context = parts.path.removesuffix("/ws3").removesuffix("/ws") or "/metabolights"
    iam = (
        "/test/iam"
        if parts.hostname and parts.hostname.startswith("wwwdev.")
        else "/iam"
    )
    return f"{parts.scheme}://{parts.netloc}{context}{iam}/realms/metabolights"


def make_session(
    access_token, refresh_token=None, *, issuer=None, client_id=None, base_url
):
    access_token = (access_token or "").strip()
    if access_token.lower().startswith("bearer "):
        access_token = access_token[7:].strip()
    claims = decode_claims(access_token)
    issuer = validate_issuer(issuer or default_issuer(base_url))
    if claims.get("iss") and (
        not isinstance(claims["iss"], str) or claims["iss"].rstrip("/") != issuer
    ):
        raise AuthenticationError(
            "Token issuer does not match this server. Supply the correct --base-url and --issuer."
        )
    client_id = client_id or claims.get("azp") or DEFAULT_CLIENT_ID
    if not isinstance(client_id, str) or not client_id.strip():
        raise AuthenticationError("A nonempty OAuth client ID is required.")
    if claims.get("azp") and claims["azp"] != client_id:
        raise AuthenticationError(
            "The client ID does not match the token's authorized party."
        )
    session = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "issuer": issuer,
        "client_id": client_id,
        "token_type": "Bearer",
    }
    if "exp" in claims:
        session["expires_at"] = claims["exp"]
    return session


def _expiry(value):
    if isinstance(value, bool):
        raise AuthenticationError(
            "Your sign-in session could not be loaded. Please sign in again."
        )
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise AuthenticationError(
            "Your sign-in session could not be loaded. Please sign in again."
        ) from None
    if not math.isfinite(result) or result < 0:
        raise AuthenticationError(
            "Your sign-in session could not be loaded. Please sign in again."
        )
    return result


def validate_session(session, *, issuer=None, client_id=None):
    if not isinstance(session, dict):
        raise AuthenticationError("No usable login session. Run 'mtbls auth login'.")
    for name in ("issuer", "client_id", "access_token"):
        if not isinstance(session.get(name), str) or not session[name].strip():
            raise AuthenticationError(
                "Your sign-in session is incomplete. Please sign in again."
            )
    validate_issuer(session["issuer"])
    if issuer and session["issuer"].rstrip("/") != issuer.rstrip("/"):
        raise AuthenticationError("Your MCP sign-in uses a different OAuth issuer.")
    if client_id and session["client_id"] != client_id:
        raise AuthenticationError("Your MCP sign-in uses a different OAuth client.")
    if str(session.get("token_type", "Bearer")).lower() != "bearer":
        raise AuthenticationError("Only bearer token sessions are supported.")
    refresh = session.get("refresh_token")
    if refresh is not None and (not isinstance(refresh, str) or not refresh.strip()):
        raise AuthenticationError(
            "Your sign-in session could not be renewed. Please sign in again."
        )
    for name in ("expires_at", "refresh_expires_at"):
        if session.get(name) is not None:
            _expiry(session[name])
    claims = decode_claims(session["access_token"])
    if claims.get("iss") and (
        not isinstance(claims["iss"], str)
        or claims["iss"].rstrip("/") != session["issuer"].rstrip("/")
    ):
        raise AuthenticationError("The access token does not match the session issuer.")
    if claims.get("azp") and claims["azp"] != session["client_id"]:
        raise AuthenticationError("The access token does not match the session client.")


def token_is_valid(session):
    if not session.get("access_token"):
        return False
    expiries = [
        value
        for value in (
            session.get("expires_at"),
            decode_claims(session["access_token"]).get("exp"),
        )
        if value is not None
    ]
    return all(_expiry(value) > time.time() + 60 for value in expiries)


def refresh_session(session):
    """Return a replacement session without exposing token responses in errors."""
    validate_session(session)
    refresh = session.get("refresh_token")
    if not refresh or (
        session.get("refresh_expires_at") is not None
        and _expiry(session["refresh_expires_at"]) <= time.time()
    ):
        raise AuthenticationError(
            "The login session has expired. Run 'mtbls auth login' again."
        )
    endpoint = session["issuer"].rstrip("/") + "/protocol/openid-connect/token"
    try:
        response = requests.post(
            endpoint,
            data={
                "grant_type": "refresh_token",
                "client_id": session["client_id"],
                "refresh_token": refresh,
            },
            headers={"Accept": "application/json"},
            timeout=30,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise AuthenticationError(
            "Unable to refresh the login session. Check the network and try again."
        ) from None
    if response.status_code in {400, 401, 403}:
        raise AuthenticationError(
            "The server rejected session refresh. Run 'mtbls auth login' again."
        )
    if not 200 <= response.status_code < 300:
        raise AuthenticationError(
            "Session refresh failed. Try again shortly; the stored session was preserved."
        )
    try:
        data = response.json()
    except ValueError:
        raise AuthenticationError("Session refresh returned invalid JSON.") from None
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("access_token"), str)
        or not data["access_token"]
    ):
        raise AuthenticationError("Session refresh did not return an access token.")
    updated = {**session, "access_token": data["access_token"]}
    if "refresh_token" in data:
        updated["refresh_token"] = data["refresh_token"]
    updated["token_type"] = data.get("token_type", "Bearer")
    expiry = data.get("expires_in")
    if expiry is not None:
        updated["expires_at"] = time.time() + _expiry(expiry)
    else:
        updated.pop("expires_at", None)
        if decode_claims(updated["access_token"]).get("exp") is None:
            raise AuthenticationError(
                "Session refresh did not return token expiry information."
            )
    if "refresh_expires_in" in data:
        lifetime = _expiry(data["refresh_expires_in"])
        updated["refresh_expires_at"] = time.time() + lifetime if lifetime else None
    if "scope" in data:
        updated["scope"] = data["scope"]
    validate_session(updated)
    if not token_is_valid(updated):
        raise AuthenticationError(
            "Session refresh returned an expired or unusable access token."
        )
    return updated


class OAuthSession:
    def __init__(self, base_url, credential_base_url=None):
        self.base_url = base_url
        self.credential_base_url = credential_base_url

    def save(self, session):
        config.save_oauth_session(
            self.base_url, session, credential_base_url=self.credential_base_url
        )

    def _configured_session(self):
        token_file = os.getenv("MTBLS_TOKEN_FILE")
        if token_file:
            return {
                "token_file": str(Path(token_file).expanduser().absolute()),
                "issuer": os.getenv("MTBLS_OIDC_ISSUER")
                or default_issuer(self.base_url),
                "client_id": os.getenv("MTBLS_OIDC_CLIENT_ID"),
            }
        access = os.getenv("MTBLS_JWT_TOKEN")
        if access:
            refresh = os.getenv("MTBLS_REFRESH_TOKEN")
            session = make_session(
                access,
                refresh,
                issuer=os.getenv("MTBLS_OIDC_ISSUER"),
                client_id=os.getenv("MTBLS_OIDC_CLIENT_ID"),
                base_url=self.base_url,
            )
            session["source_id"] = session_source_id(session)
            if token_is_valid(session) and not refresh:
                return session
            cached = config.get_oauth_session(
                self.base_url, credential_base_url=self.credential_base_url
            )
            return (
                cached
                if cached and cached.get("source_id") == session["source_id"]
                else session
            )
        return config.get_oauth_session(
            self.base_url, credential_base_url=self.credential_base_url
        )

    def get_access_token(self, force_refresh=False):
        session = self._configured_session()
        if session is None:
            return None
        if session.get("token_file"):
            return self.from_token_file(session, force_refresh=force_refresh)
        validate_session(session)
        if not force_refresh and token_is_valid(session):
            return session["access_token"]
        # All CLI processes for this server must re-read after acquiring the lock.
        identity = hashlib.sha256(self.base_url.encode()).hexdigest()
        lock_dir = credential_file_path().parent / "locks"
        with credential_lock(lock_dir / (identity + ".lock")):
            current = self._configured_session()
            validate_session(current)
            if token_is_valid(current) and (
                not force_refresh or current["access_token"] != session["access_token"]
            ):
                return current["access_token"]
            updated = refresh_session(current)
            self.save(updated)
            return updated["access_token"]

    @staticmethod
    def from_token_file(link, *, force_refresh=False):
        path = Path(link["token_file"])
        # Same lock name and flock protocol as the mtbls-ai-skills MCP bridge.
        with credential_lock(path.with_suffix(".lock")):
            saved = read_private_json(path)
            validate_session(
                saved, issuer=link.get("issuer"), client_id=link.get("client_id")
            )
            if not force_refresh and token_is_valid(saved):
                return saved["access_token"]
            updated = refresh_session(saved)
            write_private_json(path, updated)
            return updated["access_token"]

    def attach_token_file(self, path, *, issuer=None, client_id=None):
        link = {
            "token_file": str(Path(path).expanduser().absolute()),
            "issuer": validate_issuer(issuer or default_issuer(self.base_url)),
            "client_id": client_id,
        }
        self.from_token_file(link)
        self.save(link)
