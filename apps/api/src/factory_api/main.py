from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from factory_api.config import get_settings
from factory_api.db import SessionLocal
from factory_api.models import User
from factory_api.routers import (
    agents,
    artifacts,
    auth,
    ideation,
    projects,
    runs,
    workflows,
)
from factory_api.routers.agents import seed_default_profiles
from factory_api.routers.workflows import seed_template_workflows
from factory_api.runner import runner


def ensure_default_user() -> None:
    """Single-user mode: make sure the owner user row exists."""
    settings = get_settings()
    with SessionLocal() as db:
        user = db.scalars(select(User).limit(1)).first()
        if user is None:
            db.add(
                User(
                    email=settings.default_user_email,
                    display_name=settings.default_user_name,
                )
            )
            db.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_settings().data_dir.mkdir(parents=True, exist_ok=True)
    ensure_default_user()
    with SessionLocal() as db:
        seed_default_profiles(db)
        seed_template_workflows(db)
    await runner.start()
    yield
    await runner.stop()


app = FastAPI(title="AI Learning Factory API", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(ideation.router)
app.include_router(agents.router)
app.include_router(runs.router)
app.include_router(artifacts.router)
app.include_router(workflows.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
