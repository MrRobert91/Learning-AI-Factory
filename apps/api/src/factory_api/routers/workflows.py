import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from factory_api.auth import CurrentUser
from factory_api.db import get_db
from factory_api.models import Artifact, Job, Project, Workflow
from factory_api.routers.agents import get_default_profile
from factory_api.routers.runs import _base_payload, _job_read, _profile_fields
from factory_api.runner import append_event, runner
from factory_api.schemas import (
    ApprovalRequest,
    JobRead,
    WorkflowCreate,
    WorkflowRead,
    WorkflowRunCreate,
    WorkflowUpdate,
)
from factory_api.workflow_engine import missing_workflow_inputs, validate_definition

router = APIRouter(prefix="/api", tags=["workflows"])

DB = Annotated[Session, Depends(get_db)]

TEMPLATES = [
    {
        "name": "Curso completo (hasta slides)",
        "description": (
            "Investiga, diseña el plan, escribe las lecciones y genera las slides. "
            "Cada perfil decide si su fase requiere aprobación humana."
        ),
        "steps": [
            {"agent": "curator"},
            {"agent": "planner"},
            {"agent": "lessons"},
            {"agent": "slides"},
        ],
    },
    {
        "name": "Investigación y plan",
        "description": "Solo el research brief y la estructura del curso.",
        "steps": [{"agent": "curator"}, {"agent": "planner"}],
    },
    {
        "name": "Lecciones y slides (desde plan existente)",
        "description": (
            "Parte de un course_plan ya generado o subido y produce lecciones y slides."
        ),
        "steps": [
            {"agent": "lessons"},
            {"agent": "slides"},
        ],
    },
    {
        "name": "Solo slides (desde lecciones existentes)",
        "description": "Convierte lecciones existentes (generadas o subidas) en slides.",
        "steps": [{"agent": "slides"}],
    },
    {
        "name": "Curso completo con vídeo",
        "description": (
            "El flujo entero: investigación, plan, lecciones, slides, guion docente, "
            "narración TTS y montaje del vídeo. Los perfiles controlan las aprobaciones."
        ),
        "steps": [
            {"agent": "curator"},
            {"agent": "planner"},
            {"agent": "lessons"},
            {"agent": "slides"},
            {"agent": "script"},
            {"agent": "voice"},
            {"agent": "video"},
        ],
    },
    {
        "name": "Guion docente desde slides existentes",
        "description": (
            "Sube tus propias slides (Marp .md o .pptx) y genera solo el guion del profesor."
        ),
        "steps": [{"agent": "script"}],
    },
    {
        "name": "Narración y vídeo (desde guion)",
        "description": "Adapta el guion a voz, sintetiza la narración y monta el vídeo.",
        "steps": [{"agent": "voice"}, {"agent": "video"}],
    },
]


def seed_template_workflows(db: Session) -> None:
    for template in TEMPLATES:
        exists = db.scalars(
            select(Workflow)
            .where(Workflow.is_template.is_(True), Workflow.name == template["name"])
            .limit(1)
        ).first()
        if exists is None:
            db.add(
                Workflow(
                    name=template["name"],
                    description=template["description"],
                    definition_json=json.dumps({"steps": template["steps"]}),
                    is_template=True,
                )
            )
        else:
            # Factory templates are canonical. This also strips historical
            # workflow-owned approval_after flags from existing databases.
            exists.description = template["description"]
            exists.definition_json = json.dumps({"steps": template["steps"]})
    db.commit()


def _workflow_read(w: Workflow) -> WorkflowRead:
    definition = json.loads(w.definition_json)
    steps = [
        {
            key: value
            for key, value in step.items()
            if key not in {"evaluate", "approval_after"}
        }
        for step in definition.get("steps", [])
    ]
    return WorkflowRead(
        id=w.id,
        name=w.name,
        description=w.description,
        steps=steps,
        is_template=w.is_template,
        created_at=w.created_at,
        updated_at=w.updated_at,
    )


@router.get("/workflows", response_model=list[WorkflowRead])
def list_workflows(user: CurrentUser, db: DB):
    workflows = db.scalars(
        select(Workflow)
        .where((Workflow.is_template.is_(True)) | (Workflow.owner_id == user.id))
        .order_by(Workflow.is_template.desc(), Workflow.created_at)
    ).all()
    return [_workflow_read(w) for w in workflows]


@router.post("/workflows", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
def create_workflow(body: WorkflowCreate, user: CurrentUser, db: DB):
    definition = {"steps": [s.model_dump(exclude_none=True) for s in body.steps]}
    problems = validate_definition(definition)
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))
    workflow = Workflow(
        owner_id=user.id,
        name=body.name,
        description=body.description,
        definition_json=json.dumps(definition),
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return _workflow_read(workflow)


@router.get("/workflows/{workflow_id}", response_model=WorkflowRead)
def get_workflow(workflow_id: str, user: CurrentUser, db: DB):
    workflow = db.get(Workflow, workflow_id)
    if workflow is None or (not workflow.is_template and workflow.owner_id != user.id):
        raise HTTPException(status_code=404, detail="Workflow no encontrado")
    return _workflow_read(workflow)


@router.patch("/workflows/{workflow_id}", response_model=WorkflowRead)
def update_workflow(workflow_id: str, body: WorkflowUpdate, user: CurrentUser, db: DB):
    workflow = db.get(Workflow, workflow_id)
    if workflow is None or (not workflow.is_template and workflow.owner_id != user.id):
        raise HTTPException(status_code=404, detail="Workflow no encontrado")
    if workflow.is_template:
        raise HTTPException(
            status_code=409, detail="Las plantillas no se editan: duplícala primero"
        )
    if body.name is not None:
        workflow.name = body.name
    if body.description is not None:
        workflow.description = body.description
    if body.steps is not None:
        definition = {"steps": [s.model_dump(exclude_none=True) for s in body.steps]}
        problems = validate_definition(definition)
        if problems:
            raise HTTPException(status_code=422, detail="; ".join(problems))
        workflow.definition_json = json.dumps(definition)
    db.commit()
    db.refresh(workflow)
    return _workflow_read(workflow)


@router.delete("/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(workflow_id: str, user: CurrentUser, db: DB):
    workflow = db.get(Workflow, workflow_id)
    if workflow is None or (not workflow.is_template and workflow.owner_id != user.id):
        raise HTTPException(status_code=404, detail="Workflow no encontrado")
    if workflow.is_template:
        raise HTTPException(status_code=409, detail="Las plantillas no se borran")
    db.delete(workflow)
    db.commit()


@router.post(
    "/projects/{project_id}/workflow-runs",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_run(
    project_id: str, body: WorkflowRunCreate, user: CurrentUser, db: DB
):
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    workflow = db.get(Workflow, body.workflow_id)
    if workflow is None or (not workflow.is_template and workflow.owner_id != user.id):
        raise HTTPException(status_code=404, detail="Workflow no encontrado")

    definition = json.loads(workflow.definition_json)
    if project.duration_spec is None and any(
        step.get("agent") != "curator" for step in definition.get("steps", [])
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Configura la duración y estructura del proyecto antes de ejecutar "
                "un workflow que incluya planner o fases posteriores."
            ),
        )
    available = set(
        db.scalars(
            select(Artifact.type).where(
                Artifact.project_id == project_id,
                Artifact.is_selected.is_(True),
            )
        ).all()
    )
    missing = missing_workflow_inputs(definition, available)
    if missing:
        raise HTTPException(
            status_code=409,
            detail="El workflow requiere artefactos previos: " + ", ".join(missing),
        )
    # Freeze per-step profile content into the definition so the run is
    # reproducible even if profiles change later.
    from factory_api.models import AgentProfile

    for step in definition["steps"]:
        profile = None
        if step.get("profile_id"):
            profile = db.get(AgentProfile, step["profile_id"])
            if profile is not None and profile.agent_type != step["agent"]:
                profile = None
        if profile is None:
            profile = get_default_profile(db, step["agent"])
        step["overrides"] = _profile_fields(profile)

    payload = _base_payload(db, project)
    payload["definition"] = definition
    payload["workflow_name"] = workflow.name

    job = Job(kind="workflow_run", project_id=project.id, payload_json=json.dumps(payload))
    db.add(job)
    db.commit()
    db.refresh(job)
    runner.enqueue(job.id)
    return _job_read(job)


@router.post("/runs/{job_id}/approve", response_model=JobRead)
def approve_run(job_id: str, body: ApprovalRequest, user: CurrentUser, db: DB):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ejecución no encontrada")
    if job.status != "waiting_approval":
        raise HTTPException(status_code=409, detail="La ejecución no espera aprobación")
    if not body.approved and not body.feedback.strip():
        raise HTTPException(status_code=422, detail="Escribe feedback para regenerar la fase")
    payload = json.loads(job.payload_json)
    payload["_resume"] = {
        "approved": body.approved,
        "feedback": body.feedback.strip(),
    }
    job.payload_json = json.dumps(payload)
    job.status = "queued"
    db.commit()
    db.refresh(job)
    append_event(
        job_id,
        "approval",
        ("Aprobado" if body.approved else "Feedback enviado para regenerar")
        + (f": {body.feedback}" if body.feedback else ""),
    )
    runner.enqueue(job.id)
    return _job_read(job)


@router.post("/runs/{job_id}/cancel", response_model=JobRead)
def cancel_run(job_id: str, user: CurrentUser, db: DB):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ejecución no encontrada")
    if job.status not in ("queued", "waiting_approval"):
        raise HTTPException(
            status_code=409,
            detail="Solo se pueden cancelar ejecuciones en cola o esperando aprobación",
        )
    job.status = "failed"
    job.error = "Cancelado por el usuario"
    db.commit()
    db.refresh(job)
    return _job_read(job)
