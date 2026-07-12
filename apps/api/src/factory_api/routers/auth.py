import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.auth import CurrentUser, create_session_token
from factory_api.config import get_settings
from factory_api.db import get_db
from factory_api.models import User
from factory_api.schemas import LoginRequest, UserRead

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserRead)
def login(
    body: LoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
):
    settings = get_settings()
    if not secrets.compare_digest(body.password, settings.app_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Contraseña incorrecta"
        )
    user = db.scalars(select(User).limit(1)).first()
    if user is None:
        raise HTTPException(status_code=500, detail="Usuario por defecto no inicializado")
    response.set_cookie(
        key=settings.session_cookie_name,
        value=create_session_token(user.id),
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie(get_settings().session_cookie_name, path="/")


@router.get("/me", response_model=UserRead)
def me(user: CurrentUser):
    return user
