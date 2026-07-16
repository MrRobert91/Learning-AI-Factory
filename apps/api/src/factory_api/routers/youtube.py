import json
import secrets
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.auth import CurrentUser
from factory_api.config import get_settings
from factory_api.db import get_db
from factory_api.models import Artifact, Job, OAuthToken, Project
from factory_api.routers.runs import _job_read
from factory_api.runner import PREFIXES, runner
from factory_api.schemas import JobRead, YouTubePublishRequest, YouTubeStatus
from factory_api.youtube import YOUTUBE_SCOPES

router = APIRouter(prefix="/api/youtube", tags=["youtube"])

DB = Annotated[Session, Depends(get_db)]

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# Single-user app: one in-flight OAuth state is enough.
_pending_states: set[str] = set()


def _get_token(db: Session) -> OAuthToken | None:
    return db.scalars(
        select(OAuthToken).where(OAuthToken.provider == "google").limit(1)
    ).first()


@router.get("/status", response_model=YouTubeStatus)
def youtube_status(user: CurrentUser, db: DB):
    settings = get_settings()
    return YouTubeStatus(
        configured=bool(settings.google_client_id and settings.google_client_secret),
        connected=_get_token(db) is not None,
    )


@router.get("/auth-url")
def auth_url(user: CurrentUser):
    settings = get_settings()
    if not (settings.google_client_id and settings.google_client_secret):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configura GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET (ver docs/YOUTUBE.md)",
        )
    state = secrets.token_urlsafe(24)
    _pending_states.add(state)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(YOUTUBE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return {"url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}"}


@router.get("/callback")
def oauth_callback(code: str, state: str, user: CurrentUser, db: DB):
    import httpx

    settings = get_settings()
    if state not in _pending_states:
        raise HTTPException(status_code=400, detail="Estado OAuth inválido o caducado")
    _pending_states.discard(state)
    resp = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Google rechazó el código: {resp.text}")
    data = resp.json()
    token = _get_token(db)
    payload = json.dumps(
        {"token": data.get("access_token"), "refresh_token": data.get("refresh_token")}
    )
    if token is None:
        db.add(OAuthToken(user_id=user.id, provider="google", token_json=payload))
    else:
        # Keep the old refresh_token if Google didn't return a new one.
        old = json.loads(token.token_json)
        merged = {
            "token": data.get("access_token"),
            "refresh_token": data.get("refresh_token") or old.get("refresh_token"),
        }
        token.token_json = json.dumps(merged)
    db.commit()
    return RedirectResponse(url="/?youtube=connected")


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(user: CurrentUser, db: DB):
    token = _get_token(db)
    if token is not None:
        db.delete(token)
        db.commit()


@router.post("/publish", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def publish_video(body: YouTubePublishRequest, user: CurrentUser, db: DB):
    """Explicit human action — the only path that uploads to YouTube."""
    settings = get_settings()
    if not (settings.google_client_id and settings.google_client_secret):
        raise HTTPException(status_code=503, detail="YouTube no está configurado")
    if _get_token(db) is None:
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
            status_code=409, detail=f"No hay vídeo para «{base}»: genera el vídeo primero"
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
        kind="youtube_upload", project_id=package.project_id, payload_json=json.dumps(payload)
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    runner.enqueue(job.id)
    return _job_read(job)
