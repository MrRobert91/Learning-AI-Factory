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
    improvements,
    projects,
    runs,
    wiki,
    workflows,
    youtube,
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


async def _analytics_scheduler() -> None:
    """Optional periodic continuous-improvement analysis (off by default)."""
    import asyncio
    import json
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from factory_api.models import Job
    from factory_api.routers.agents import get_default_profile
    from factory_api.routers.runs import _profile_fields

    settings = get_settings()
    interval = timedelta(days=settings.analytics_interval_days)
    while True:
        await asyncio.sleep(3600)
        try:
            with SessionLocal() as db:
                uploads = db.scalars(
                    select(Job).where(Job.kind == "youtube_upload", Job.status == "done")
                ).all()
                project_ids = {j.project_id for j in uploads if j.project_id}
                for project_id in project_ids:
                    last = db.scalars(
                        select(Job)
                        .where(Job.project_id == project_id, Job.kind == "analyst_run")
                        .order_by(Job.created_at.desc())
                        .limit(1)
                    ).first()
                    if last is not None and datetime.now(UTC) - last.created_at.replace(
                        tzinfo=UTC
                    ) < interval:
                        continue
                    from factory_api.models import Project

                    project = db.get(Project, project_id)
                    if project is None:
                        continue
                    profile = get_default_profile(db, "analyst")
                    payload = {
                        "project_id": project_id,
                        "project_title": project.title,
                        **_profile_fields(profile),
                    }
                    job = Job(
                        kind="analyst_run",
                        project_id=project_id,
                        payload_json=json.dumps(payload),
                    )
                    db.add(job)
                    db.commit()
                    runner.enqueue(job.id)
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Analytics scheduler tick failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    import asyncio

    get_settings().data_dir.mkdir(parents=True, exist_ok=True)
    ensure_default_user()
    with SessionLocal() as db:
        seed_default_profiles(db)
        seed_template_workflows(db)
    await runner.start()
    scheduler_task = None
    if get_settings().analytics_interval_days > 0:
        scheduler_task = asyncio.create_task(_analytics_scheduler())
    yield
    if scheduler_task is not None:
        scheduler_task.cancel()
    await runner.stop()


app = FastAPI(title="AI Learning Factory API", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(ideation.router)
app.include_router(agents.router)
app.include_router(runs.router)
app.include_router(artifacts.router)
app.include_router(workflows.router)
app.include_router(wiki.router)
app.include_router(youtube.router)
app.include_router(improvements.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
