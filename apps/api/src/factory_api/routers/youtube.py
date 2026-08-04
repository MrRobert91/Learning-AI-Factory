import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from factory_api.auth import CurrentUser
from factory_api.config import get_settings
from factory_api.credentials import (
    CredentialCipher,
    CredentialDecryptionError,
    CredentialStore,
)
from factory_api.db import get_db
from factory_api.models import (
    Artifact,
    AuthSession,
    Job,
    OAuthAuthorizationState,
    Project,
)
from factory_api.routers.runs import _job_read
from factory_api.runner import PREFIXES, runner
from factory_api.schemas import JobRead, YouTubePublishRequest, YouTubeStatus
from factory_api.youtube import YOUTUBE_SCOPES

router = APIRouter(prefix="/api/youtube", tags=["youtube"])
DB = Annotated[Session, Depends(get_db)]

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def _state_aad(user_id: str, auth_session_id: str) -> str:
    return f"oauth-state\0google\0{user_id}\0{auth_session_id}"


def _token_data(db: Session, user_id: str) -> dict | None:
    try:
        return CredentialStore().get(db, provider="google", user_id=user_id)
    except CredentialDecryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Las credenciales de YouTube no se pueden descifrar; revisa la clave activa.",
        ) from exc


@router.get("/status", response_model=YouTubeStatus)
def youtube_status(user: CurrentUser, db: DB):
    settings = get_settings()
    return YouTubeStatus(
        configured=bool(settings.google_client_id and settings.google_client_secret),
        connected=_token_data(db, user.id) is not None,
    )


@router.get("/auth-url")
def auth_url(request: Request, user: CurrentUser, db: DB):
    settings = get_settings()
    if not (settings.google_client_id and settings.google_client_secret):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configura GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET (ver docs/YOUTUBE.md)",
        )
    auth_session: AuthSession = request.state.auth_session
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    now = datetime.now(UTC)
    cipher = CredentialCipher()
    db.execute(
        delete(OAuthAuthorizationState).where(
            OAuthAuthorizationState.expires_at < now - timedelta(days=1)
        )
    )
    db.add(
        OAuthAuthorizationState(
            state_hash=hashlib.sha256(state.encode()).hexdigest(),
            user_id=user.id,
            auth_session_id=auth_session.id,
            provider="google",
            code_verifier_encrypted=cipher.encrypt_json(
                {"verifier": verifier},
                associated_data=_state_aad(user.id, auth_session.id),
            ),
            redirect_uri=settings.google_redirect_uri,
            created_at=now,
            expires_at=now + timedelta(minutes=10),
        )
    )
    db.commit()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(YOUTUBE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return {"url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}"}


@router.get("/callback")
def oauth_callback(code: str, state: str, request: Request, user: CurrentUser, db: DB):
    import httpx

    settings = get_settings()
    auth_session: AuthSession = request.state.auth_session
    now = datetime.now(UTC)
    state_row = db.scalars(
        select(OAuthAuthorizationState)
        .where(
            OAuthAuthorizationState.state_hash == hashlib.sha256(state.encode()).hexdigest(),
            OAuthAuthorizationState.provider == "google",
            OAuthAuthorizationState.user_id == user.id,
            OAuthAuthorizationState.auth_session_id == auth_session.id,
        )
        .limit(1)
    ).first()
    if state_row is None:
        raise HTTPException(status_code=400, detail="Estado OAuth inválido o caducado")
    consumed = db.execute(
        update(OAuthAuthorizationState)
        .where(
            OAuthAuthorizationState.id == state_row.id,
            OAuthAuthorizationState.consumed_at.is_(None),
            OAuthAuthorizationState.expires_at > now,
        )
        .values(consumed_at=now)
        .execution_options(synchronize_session=False)
    )
    if consumed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="Estado OAuth inválido o caducado")
    db.commit()
    verifier_payload, _ = CredentialCipher().decrypt_json(
        state_row.code_verifier_encrypted,
        associated_data=_state_aad(user.id, auth_session.id),
    )
    try:
        resp = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": state_row.redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier_payload["verifier"],
            },
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="No se pudo completar la autorización con Google.",
        ) from exc
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail="Google rechazó el código de autorización. Vuelve a conectar YouTube.",
        )
    try:
        data = resp.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Google devolvió una respuesta de autorización inválida.",
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("access_token"), str):
        raise HTTPException(
            status_code=502,
            detail="Google no devolvió una credencial de acceso válida.",
        )
    old = _token_data(db, user.id) or {}
    CredentialStore().put(
        db,
        provider="google",
        user_id=user.id,
        value={
            "token": data.get("access_token"),
            "refresh_token": data.get("refresh_token") or old.get("refresh_token"),
        },
    )
    return RedirectResponse(url="/?youtube=connected")


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(user: CurrentUser, db: DB):
    CredentialStore().delete(db, provider="google", user_id=user.id)


@router.post("/publish", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def publish_video(body: YouTubePublishRequest, user: CurrentUser, db: DB):
    """Explicit human action — the only path that uploads to YouTube."""
    settings = get_settings()
    if not (settings.google_client_id and settings.google_client_secret):
        raise HTTPException(status_code=503, detail="YouTube no está configurado")
    if _token_data(db, user.id) is None:
        raise HTTPException(status_code=409, detail="YouTube no está conectado: autoriza primero")

    package = db.get(Artifact, body.package_artifact_id)
    if package is None or package.type != "publication_package":
        raise HTTPException(status_code=404, detail="Paquete de publicación no encontrado")
    project = db.get(Project, package.project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Paquete de publicación no encontrado")

    base = package.title.removeprefix(PREFIXES["publication_package"])
    video = db.scalars(
        select(Artifact)
        .where(
            Artifact.project_id == package.project_id,
            Artifact.type == "video",
            Artifact.title == f"{PREFIXES['video']}{base}",
            Artifact.is_selected.is_(True),
        )
        .order_by(Artifact.created_at.desc())
        .limit(1)
    ).first()
    if video is None:
        raise HTTPException(
            status_code=409,
            detail=f"No hay vídeo para «{base}»: genera el vídeo primero",
        )
    if body.privacy not in ("private", "unlisted", "public"):
        raise HTTPException(status_code=422, detail="Privacidad inválida")

    payload = {
        "project_id": package.project_id,
        "video_artifact_id": video.id,
        "package_artifact_id": package.id,
        "privacy": body.privacy,
    }
    job = Job(
        kind="youtube_upload",
        project_id=package.project_id,
        payload_json=json.dumps(payload),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    runner.enqueue(job.id)
    return _job_read(job)
