import hashlib
import ipaddress
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from factory_api.config import Settings, get_settings
from factory_api.db import get_db
from factory_api.models import AuthSession, LoginAttempt, User


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="session-v2")


def _secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def create_session_token(session_id: str, secret: str) -> str:
    return _serializer().dumps({"sid": session_id, "secret": secret})


def verify_session_token(token: str) -> tuple[str, str] | None:
    try:
        payload = _serializer().loads(token, max_age=get_settings().session_max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(payload, dict):
        return None
    session_id = payload.get("sid")
    secret = payload.get("secret")
    if not isinstance(session_id, str) or not isinstance(secret, str):
        return None
    return session_id, secret


def create_auth_session(db: Session, user_id: str) -> tuple[AuthSession, str]:
    settings = get_settings()
    now = _utcnow()
    secret = secrets.token_urlsafe(32)
    auth_session = AuthSession(
        user_id=user_id,
        secret_hash=_secret_hash(secret),
        created_at=now,
        expires_at=now + timedelta(seconds=settings.session_max_age_seconds),
        last_seen_at=now,
    )
    db.add(auth_session)
    db.flush()
    _cleanup_sessions(db, now)
    db.commit()
    db.refresh(auth_session)
    return auth_session, create_session_token(auth_session.id, secret)


def _cleanup_sessions(db: Session, now: datetime, limit: int = 100) -> None:
    stale_ids = db.scalars(
        select(AuthSession.id)
        .where(AuthSession.expires_at < now - timedelta(days=7))
        .order_by(AuthSession.expires_at)
        .limit(limit)
    ).all()
    if stale_ids:
        db.execute(delete(AuthSession).where(AuthSession.id.in_(stale_ids)))


def get_current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    settings = get_settings()
    token = request.cookies.get(settings.effective_session_cookie_name)
    parsed = verify_session_token(token) if token else None
    auth_session = db.get(AuthSession, parsed[0]) if parsed else None
    now = _utcnow()
    if (
        parsed is None
        or auth_session is None
        or auth_session.revoked_at is not None
        or _as_utc(auth_session.expires_at) <= now
        or not secrets.compare_digest(auth_session.secret_hash, _secret_hash(parsed[1]))
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    user = db.get(User, auth_session.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    if now - _as_utc(auth_session.last_seen_at) >= timedelta(
        seconds=settings.session_touch_interval_seconds
    ):
        auth_session.last_seen_at = now
        db.commit()
    request.state.auth_session = auth_session
    return user


def revoke_session(db: Session, auth_session: AuthSession, reason: str) -> None:
    if auth_session.revoked_at is None:
        auth_session.revoked_at = _utcnow()
        auth_session.revoked_reason = reason[:80]
        db.commit()


def revoke_all_sessions(db: Session, user_id: str, reason: str = "revoke_all") -> int:
    result = db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=_utcnow(), revoked_reason=reason[:80])
    )
    db.commit()
    return result.rowcount or 0


def resolve_client_ip(request: Request, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    direct = request.client.host if request.client else "unknown"
    trusted = False
    try:
        direct_ip = ipaddress.ip_address(direct)
        trusted = any(
            direct_ip in ipaddress.ip_network(value, strict=False)
            for value in settings.trusted_proxy_networks
        )
    except ValueError:
        trusted = False
    if trusted:
        forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
        real_ip = request.headers.get("x-real-ip", "").strip()
        candidate = forwarded or real_ip
        try:
            return str(ipaddress.ip_address(candidate)) if candidate else direct
        except ValueError:
            return direct
    return direct


class LoginRateLimiter:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def retry_after(self, db: Session, client_ip: str) -> int | None:
        now = _utcnow()
        cutoff = now - timedelta(seconds=self.settings.login_window_seconds)
        ip_count = (
            db.scalar(
                select(func.count(LoginAttempt.id)).where(
                    LoginAttempt.created_at >= cutoff, LoginAttempt.client_ip == client_ip
                )
            )
            or 0
        )
        global_count = (
            db.scalar(select(func.count(LoginAttempt.id)).where(LoginAttempt.created_at >= cutoff))
            or 0
        )
        if (
            ip_count < self.settings.login_max_attempts_per_ip
            and global_count < self.settings.login_max_attempts_global
        ):
            return None
        oldest = db.scalar(
            select(func.min(LoginAttempt.created_at)).where(LoginAttempt.created_at >= cutoff)
        )
        if oldest is None:
            return 1
        return max(
            1,
            int(self.settings.login_window_seconds - (now - _as_utc(oldest)).total_seconds()) + 1,
        )

    def record_failure(self, db: Session, client_ip: str) -> None:
        now = _utcnow()
        db.add(LoginAttempt(client_ip=client_ip, created_at=now))
        old_ids = db.scalars(
            select(LoginAttempt.id)
            .where(
                LoginAttempt.created_at
                < now - timedelta(seconds=self.settings.login_window_seconds * 2)
            )
            .order_by(LoginAttempt.created_at)
            .limit(200)
        ).all()
        if old_ids:
            db.execute(delete(LoginAttempt).where(LoginAttempt.id.in_(old_ids)))
        db.commit()


def request_origin(request: Request) -> str | None:
    raw = request.headers.get("origin") or request.headers.get("referer")
    if not raw:
        return None
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def csrf_origin_allowed(request: Request, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if settings.app_env != "production":
        return True
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return True
    if not request.cookies.get(settings.effective_session_cookie_name):
        return True
    return request_origin(request) in settings.allowed_origins


CurrentUser = Annotated[User, Depends(get_current_user)]
