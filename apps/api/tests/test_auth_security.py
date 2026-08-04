import base64
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from factory_api.auth import LoginRateLimiter, csrf_origin_allowed
from factory_api.config import Settings
from factory_api.credentials import (
    CredentialCipher,
    CredentialDecryptionError,
    CredentialStore,
)
from factory_api.db import SessionLocal
from factory_api.models import LoginAttempt, OAuthAuthorizationState, OAuthToken, User
from factory_api.routers.auth import _set_session_cookie
from fastapi import Request, Response
from pydantic import ValidationError
from sqlalchemy import delete, select


def _key(key_id: str) -> str:
    return f"{key_id}:{base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}"


def _production_settings(**updates) -> Settings:
    values = {
        "app_env": "production",
        "app_origins": "https://factory.example",
        "app_password": "correct-horse-battery-staple",
        "secret_key": "0123456789abcdef" * 3,
        "credential_encryption_keys": _key("active"),
        "google_redirect_uri": "https://factory.example/api/youtube/callback",
    }
    values.update(updates)
    return Settings(_env_file=None, **values)


def _request(method: str, *, origin: str | None = None, cookie: str | None = None):
    headers = []
    if origin:
        headers.append((b"origin", origin.encode()))
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/projects",
            "headers": headers,
            "client": ("127.0.0.1", 1234),
            "scheme": "https",
            "server": ("factory.example", 443),
        }
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("app_password", "changeme"),
        ("secret_key", "short"),
        ("app_origins", "http://factory.example"),
        ("credential_encryption_keys", "local:invalid"),
    ],
)
def test_production_rejects_unsafe_configuration(field, value):
    with pytest.raises(ValidationError):
        _production_settings(**{field: value})


def test_production_cookie_and_csrf_policy(monkeypatch):
    settings = _production_settings()
    monkeypatch.setattr("factory_api.routers.auth.get_settings", lambda: settings)
    response = Response()
    _set_session_cookie(response, "opaque-token")
    cookie = response.headers["set-cookie"]
    assert "__Host-factory_session=" in cookie
    assert "Secure" in cookie and "HttpOnly" in cookie and "Path=/" in cookie

    raw_cookie = "__Host-factory_session=opaque-token"
    assert csrf_origin_allowed(
        _request("POST", origin="https://factory.example", cookie=raw_cookie), settings
    )
    assert not csrf_origin_allowed(
        _request("DELETE", origin="https://evil.example", cookie=raw_cookie), settings
    )
    assert not csrf_origin_allowed(_request("PATCH", cookie=raw_cookie), settings)
    assert csrf_origin_allowed(_request("POST", origin="https://evil.example"), settings)


def test_login_rate_limit_is_per_ip_and_global():
    settings = Settings(
        _env_file=None,
        login_max_attempts_per_ip=2,
        login_max_attempts_global=3,
        login_window_seconds=600,
    )
    limiter = LoginRateLimiter(settings)
    with SessionLocal() as db:
        db.execute(delete(LoginAttempt))
        db.commit()
        assert limiter.retry_after(db, "198.51.100.10") is None
        limiter.record_failure(db, "198.51.100.10")
        limiter.record_failure(db, "198.51.100.10")
        assert limiter.retry_after(db, "198.51.100.10")
        assert limiter.retry_after(db, "198.51.100.11") is None
        limiter.record_failure(db, "198.51.100.11")
        assert limiter.retry_after(db, "198.51.100.12")
        db.execute(delete(LoginAttempt))
        db.commit()


def test_login_endpoint_returns_retry_after(client, monkeypatch):
    settings = Settings(
        _env_file=None,
        login_max_attempts_per_ip=2,
        login_max_attempts_global=10,
        login_window_seconds=600,
        login_failure_delay_seconds=0,
    )
    monkeypatch.setattr("factory_api.routers.auth.get_settings", lambda: settings)
    with SessionLocal() as db:
        db.execute(delete(LoginAttempt))
        db.commit()
    try:
        assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        blocked = client.post("/api/auth/login", json={"password": "wrong"})
        assert blocked.status_code == 429
        assert int(blocked.headers["retry-after"]) > 0
        assert "password" not in blocked.text.lower()
    finally:
        with SessionLocal() as db:
            db.execute(delete(LoginAttempt))
            db.commit()


def test_logout_revokes_stolen_cookie(client):
    assert client.post("/api/auth/login", json={"password": "test-password"}).status_code == 200
    token = client.cookies.get("factory_session")
    assert token
    assert client.post("/api/auth/logout").status_code == 204
    client.cookies.set("factory_session", token)
    assert client.get("/api/auth/me").status_code == 401


def test_tampered_session_cookie_is_rejected(client):
    assert client.post("/api/auth/login", json={"password": "test-password"}).status_code == 200
    token = client.cookies.get("factory_session")
    assert token
    replacement = "A" if token[-1] != "A" else "B"
    client.cookies.set("factory_session", token[:-1] + replacement)
    assert client.get("/api/auth/me").status_code == 401


def test_revoke_all_invalidates_other_session(client):
    from factory_api.main import app
    from fastapi.testclient import TestClient

    assert client.post("/api/auth/login", json={"password": "test-password"}).status_code == 200
    with TestClient(app) as other:
        assert other.post("/api/auth/login", json={"password": "test-password"}).status_code == 200
        response = client.post("/api/auth/sessions/revoke-all")
        assert response.status_code == 200 and response.json()["revoked"] >= 2
        assert other.get("/api/auth/me").status_code == 401


def test_credential_store_encrypts_legacy_and_rotates_keys():
    old_settings = Settings(_env_file=None, credential_encryption_keys=_key("old"))
    new_settings = Settings(
        _env_file=None,
        credential_encryption_keys=f"{_key('new')},{old_settings.credential_encryption_keys}",
    )
    with SessionLocal() as db:
        user = db.scalars(select(User).limit(1)).first()
        assert user is not None
        db.execute(delete(OAuthToken).where(OAuthToken.provider == "rotation-test"))
        db.commit()
        store = CredentialStore(old_settings)
        token = store.put(
            db,
            provider="rotation-test",
            user_id=user.id,
            value={"token": "access-secret", "refresh_token": "refresh-secret"},
        )
        assert "access-secret" not in token.token_json
        assert json.loads(token.token_json)["kid"] == "old"

        value = CredentialStore(new_settings).get(db, provider="rotation-test", user_id=user.id)
        assert value == {"token": "access-secret", "refresh_token": "refresh-secret"}
        db.refresh(token)
        assert json.loads(token.token_json)["kid"] == "new"
        db.delete(token)
        db.commit()


def test_credential_cipher_authenticates_provider_and_user():
    cipher = CredentialCipher(Settings(_env_file=None, credential_encryption_keys=_key("k")))
    encrypted = cipher.encrypt_json({"token": "secret"}, associated_data="google\0user-a")
    with pytest.raises(CredentialDecryptionError):
        cipher.decrypt_json(encrypted, associated_data="google\0user-b")


def test_oauth_state_is_persistent_single_use_pkce_and_tokens_are_encrypted(
    auth_client, monkeypatch
):
    settings = Settings(
        _env_file=None,
        google_client_id="client-id",
        google_client_secret="client-secret",
        google_redirect_uri="http://localhost:3000/api/youtube/callback",
    )
    monkeypatch.setattr("factory_api.routers.youtube.get_settings", lambda: settings)

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"access_token": "access-secret", "refresh_token": "refresh-secret"}

    captured = {}

    def fake_post(url, data, timeout):
        captured.update(data)
        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)
    auth_url = auth_client.get("/api/youtube/auth-url")
    assert auth_url.status_code == 200
    query = parse_qs(urlparse(auth_url.json()["url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    state = query["state"][0]
    assert query["code_challenge"][0]

    with SessionLocal() as db:
        row = db.scalars(
            select(OAuthAuthorizationState).where(
                OAuthAuthorizationState.state_hash == hashlib.sha256(state.encode()).hexdigest()
            )
        ).one()
        assert state not in row.code_verifier_encrypted

    callback = auth_client.get(
        "/api/youtube/callback",
        params={"code": "code", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code == 307
    assert captured["code_verifier"]
    with SessionLocal() as db:
        token = db.scalars(select(OAuthToken).where(OAuthToken.provider == "google")).one()
        assert "access-secret" not in token.token_json
        assert "refresh-secret" not in token.token_json
        assert CredentialStore().get(db, provider="google", user_id=token.user_id) == {
            "token": "access-secret",
            "refresh_token": "refresh-secret",
        }

    replay = auth_client.get("/api/youtube/callback", params={"code": "again", "state": state})
    assert replay.status_code == 400
    with SessionLocal() as db:
        db.execute(delete(OAuthToken).where(OAuthToken.provider == "google"))
        db.execute(delete(OAuthAuthorizationState))
        db.commit()
