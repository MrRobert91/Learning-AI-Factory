from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from factory_api.config import get_settings
from factory_api.db import get_db
from factory_api.models import User


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="session")


def create_session_token(user_id: str) -> str:
    return _serializer().dumps(user_id)


def verify_session_token(token: str) -> str | None:
    try:
        return _serializer().loads(token, max_age=get_settings().session_max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> User:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    user_id = verify_session_token(token) if token else None
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
