from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    topic: str = ""
    audience: str = ""
    level: str = ""
    language: str = "es"
    style: str = ""
    output_format: str = ""


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    topic: str | None = None
    audience: str | None = None
    level: str | None = None
    language: str | None = None
    style: str | None = None
    output_format: str | None = None
    status: str | None = None


class IdeationCreate(BaseModel):
    idea: str = Field(min_length=1, description="Idea inicial, aunque sea vaga")


class IdeationMessageCreate(BaseModel):
    content: str = Field(min_length=1)


class IdeationMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    seq: int
    role: str
    kind: str
    content: str
    payload: dict | None = None
    created_at: datetime


class IdeationSessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    initial_idea: str
    project_id: str | None
    has_brief: bool = False
    created_at: datetime
    updated_at: datetime


class IdeationSessionRead(IdeationSessionSummary):
    brief: dict | None = None
    messages: list[IdeationMessageRead] = []


class AgentSpecRead(BaseModel):
    name: str
    display_name: str
    description: str
    kind: str
    tool_names: list[str]
    consumes: list[str]
    produces: list[str]


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    soul_md: str = ""
    agents_md: str = ""
    model: str | None = None


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    soul_md: str | None = None
    agents_md: str | None = None
    model: str | None = None
    is_default: bool | None = None
    note: str = ""


class ProfileRead(BaseModel):
    id: str
    agent_type: str
    name: str
    soul_md: str
    agents_md: str
    model: str | None = None
    version: int
    is_default: bool
    created_at: datetime
    updated_at: datetime


class ProfileVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    soul_md: str
    agents_md: str
    note: str
    created_at: datetime


class WikiPageWrite(BaseModel):
    title: str = ""
    content_md: str = ""


class WikiPageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    title: str
    content_md: str
    updated_at: datetime


class YouTubeStatus(BaseModel):
    configured: bool
    connected: bool


class YouTubePublishRequest(BaseModel):
    package_artifact_id: str
    privacy: str = "private"


class WorkflowStep(BaseModel):
    agent: str
    profile_id: str | None = None
    approval_after: bool | None = None


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    steps: list[WorkflowStep] = Field(min_length=1)


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    steps: list[WorkflowStep] | None = None


class WorkflowRead(BaseModel):
    id: str
    name: str
    description: str
    steps: list[dict]
    is_template: bool
    created_at: datetime
    updated_at: datetime


class WorkflowRunCreate(BaseModel):
    workflow_id: str


class ApprovalRequest(BaseModel):
    approved: bool
    feedback: str = ""


class AgentRunCreate(BaseModel):
    agent: str = Field(description="curator | planner | lessons | slides | pipeline")
    profile_id: str | None = None


class JobEventRead(BaseModel):
    seq: int
    type: str
    summary: str
    data: dict | None = None
    created_at: datetime


class JobRead(BaseModel):
    id: str
    kind: str
    status: str
    error: str
    project_id: str | None
    result: dict | None = None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    events: list[JobEventRead] = []


class ArtifactRead(BaseModel):
    id: str
    project_id: str
    type: str
    format: str
    title: str
    created_by_job_id: str | None
    created_at: datetime
    content: str | None = None
    renders: list[str] = []


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    topic: str
    audience: str
    level: str
    language: str
    style: str
    output_format: str
    status: str
    created_at: datetime
    updated_at: datetime
