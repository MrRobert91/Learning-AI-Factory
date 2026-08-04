import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.auth import (
    CurrentUser,
    LoginRateLimiter,
    create_auth_session,
    resolve_client_ip,
    revoke_all_sessions,
    revoke_session,
)
from factory_api.config import get_settings
from factory_api.db import get_db
from factory_api.models import AuthSession, User
from factory_api.schemas import LoginRequest, UserRead

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.effective_session_cookie_name,
        value=token,
        max_age=settings.session_max_age_seconds,
        secure=settings.app_env == "production",
        httponly=True,
        samesite="lax",
        path="/",
    )


def _delete_session_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie("__Host-factory_session", path="/", secure=True)


@router.post("/login", response_model=UserRead)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
):
    settings = get_settings()
    client_ip = resolve_client_ip(request, settings)
    limiter = LoginRateLimiter(settings)
    retry_after = limiter.retry_after(db, client_ip)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos de acceso. Inténtalo más tarde.",
            headers={"Retry-After": str(retry_after)},
        )

    user = db.scalars(select(User).limit(1)).first()
    password_ok = secrets.compare_digest(body.password, settings.app_password)
    if not password_ok or user is None:
        limiter.record_failure(db, client_ip)
        time.sleep(settings.login_failure_delay_seconds)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
        )
    auth_session, token = create_auth_session(db, user.id)
    _set_session_cookie(response, token)
    request.state.auth_session = auth_session
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    auth_session: AuthSession = request.state.auth_session
    revoke_session(db, auth_session, "logout")
    _delete_session_cookies(response)


@router.post("/sessions/revoke-all")
def revoke_all(
    request: Request,
    response: Response,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    revoked = revoke_all_sessions(db, user.id)
    _delete_session_cookies(response)
    request.state.auth_session = None
    return {"revoked": revoked}


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser):
    return user
