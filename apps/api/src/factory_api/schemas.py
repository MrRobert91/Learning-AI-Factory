from datetime import datetime
from typing import Literal

from factory_agents.contracts import DurationSpec
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
    duration_spec: DurationSpec | None = None
    research_mode: Literal["provided_only", "provided_plus_web", "web_only"] = "web_only"


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    topic: str | None = None
    audience: str | None = None
    level: str | None = None
    language: str | None = None
    style: str | None = None
    output_format: str | None = None
    duration_spec: DurationSpec | None = None
    research_mode: Literal["provided_only", "provided_plus_web", "web_only"] | None = None
    status: str | None = None


class IdeationCreate(BaseModel):
    idea: str = Field(min_length=1, description="Idea inicial, aunque sea vaga")
    research_mode: Literal["provided_only", "provided_plus_web", "web_only"] = "web_only"


class IdeationDraftCreate(IdeationCreate):
    pass


class IdeationResearchModeUpdate(BaseModel):
    research_mode: Literal["provided_only", "provided_plus_web", "web_only"]


class IdeationUrlCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


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
    research_mode: Literal["provided_only", "provided_plus_web", "web_only"]
    source_count: int = 0
    has_brief: bool = False
    created_at: datetime
    updated_at: datetime


class IdeationSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    session_id: str | None
    project_id: str | None
    kind: str
    media_type: str
    name: str
    original_url: str | None
    final_url: str | None
    sha256: str
    size_bytes: int
    status: Literal["pending", "ready", "failed"]
    error: str
    metadata: dict = Field(default_factory=dict, validation_alias="source_metadata")
    captured_at: datetime


class IdeationSessionRead(IdeationSessionSummary):
    brief: dict | None = None
    messages: list[IdeationMessageRead] = []
    sources: list[IdeationSourceRead] = []


class AgentSpecRead(BaseModel):
    name: str
    display_name: str
    description: str
    kind: str
    tool_names: list[str]
    consumes: list[str]
    produces: list[str]


class LogoCandidateRead(BaseModel):
    id: str
    source: Literal["uploaded", "generated"]
    name: str
    path: str
    thumbnail_path: str
    media_type: str
    width: int
    height: int
    sha256: str
    prompt: str | None = None
    model: str | None = None
    seed: int | None = None
    cost_usd: float | None = None
    created_at: datetime
    status: Literal["available", "error"] = "available"
    error: str | None = None


class LogoVisibility(BaseModel):
    cover: bool = True
    content: bool = True
    summary: bool = True


class LogoGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    model: str | None = None
    name: str = Field(default="", max_length=120)


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    soul_md: str = ""
    agents_md: str = ""
    model: str | None = None
    orientation: Literal["horizontal", "vertical"] | None = None
    images_enabled: bool | None = None
    image_model: str | None = None
    image_style: str | None = None
    image_style_prompt: str | None = None
    automatic_review_enabled: bool | None = None
    max_automatic_regenerations: int | None = Field(default=None, ge=0, le=5)
    human_review_enabled: bool | None = None
    slide_palette: dict[str, str] | None = None
    logo_mode: Literal["none", "uploaded", "generated"] | None = None
    active_logo_id: str | None = None
    logo_placement: Literal[
        "top-left", "top-right", "bottom-left", "bottom-right"
    ] | None = None
    logo_size: Literal["small", "medium", "large"] | None = None
    logo_margin_px: int | None = Field(default=None, ge=0, le=128)
    logo_opacity: float | None = Field(default=None, ge=0, le=1)
    logo_visibility: LogoVisibility | None = None


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    soul_md: str | None = None
    agents_md: str | None = None
    model: str | None = None
    orientation: Literal["horizontal", "vertical"] | None = None
    images_enabled: bool | None = None
    image_model: str | None = None
    image_style: str | None = None
    image_style_prompt: str | None = None
    automatic_review_enabled: bool | None = None
    max_automatic_regenerations: int | None = Field(default=None, ge=0, le=5)
    human_review_enabled: bool | None = None
    slide_palette: dict[str, str] | None = None
    logo_mode: Literal["none", "uploaded", "generated"] | None = None
    active_logo_id: str | None = None
    logo_placement: Literal[
        "top-left", "top-right", "bottom-left", "bottom-right"
    ] | None = None
    logo_size: Literal["small", "medium", "large"] | None = None
    logo_margin_px: int | None = Field(default=None, ge=0, le=128)
    logo_opacity: float | None = Field(default=None, ge=0, le=1)
    logo_visibility: LogoVisibility | None = None
    is_default: bool | None = None
    note: str = ""


class ProfileRead(BaseModel):
    id: str
    agent_type: str
    name: str
    soul_md: str
    agents_md: str
    model: str | None = None
    orientation: Literal["horizontal", "vertical"] | None = None
    images_enabled: bool | None = None
    image_model: str | None = None
    image_style: str | None = None
    image_style_prompt: str | None = None
    automatic_review_enabled: bool
    max_automatic_regenerations: int
    human_review_enabled: bool
    slide_palette: dict[str, str] | None = None
    logo_mode: Literal["none", "uploaded", "generated"] | None = None
    active_logo_id: str | None = None
    logo_placement: Literal[
        "top-left", "top-right", "bottom-left", "bottom-right"
    ] | None = None
    logo_size: Literal["small", "medium", "large"] | None = None
    logo_margin_px: int | None = None
    logo_opacity: float | None = None
    logo_visibility: LogoVisibility | None = None
    logo_candidates: list[LogoCandidateRead] | None = None
    version: int
    is_default: bool
    created_at: datetime
    updated_at: datetime


class ProfileVersionRead(BaseModel):
    version: int
    soul_md: str
    agents_md: str
    model: str | None = None
    orientation: Literal["horizontal", "vertical"] | None = None
    images_enabled: bool | None = None
    image_model: str | None = None
    image_style: str | None = None
    image_style_prompt: str | None = None
    automatic_review_enabled: bool
    max_automatic_regenerations: int
    human_review_enabled: bool
    slide_palette: dict[str, str] | None = None
    logo_mode: Literal["none", "uploaded", "generated"] | None = None
    active_logo_id: str | None = None
    logo_placement: Literal[
        "top-left", "top-right", "bottom-left", "bottom-right"
    ] | None = None
    logo_size: Literal["small", "medium", "large"] | None = None
    logo_margin_px: int | None = None
    logo_opacity: float | None = None
    logo_visibility: LogoVisibility | None = None
    logo_candidates: list[LogoCandidateRead] | None = None
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


class ImprovementProposalRead(BaseModel):
    id: str
    project_id: str | None
    kind: str
    agent_type: str
    slug: str
    title: str
    proposed_content: str
    evidence: str
    status: str
    applied_profile_id: str | None
    created_at: datetime


class WorkflowStep(BaseModel):
    agent: str
    profile_id: str | None = None


class AutomaticReviewPolicyRead(BaseModel):
    enabled: bool = False
    max_regenerations: int = 0
    profile_id: str | None = None
    profile_version: int | None = None
    evaluator_model: str | None = None
    human_review_enabled: bool = False


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
    usage_summary: dict = Field(default_factory=dict)
    review_policies: dict[str, AutomaticReviewPolicyRead] = {}
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    events: list[JobEventRead] = []


class ArtifactVersionRead(BaseModel):
    id: str
    version: int
    is_selected: bool
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class ArtifactRead(BaseModel):
    id: str
    project_id: str
    type: str
    format: str
    title: str
    logical_key: str
    version: int
    is_selected: bool
    metadata: dict = Field(default_factory=dict)
    created_by_job_id: str | None
    created_at: datetime
    content: str | None = None
    renders: list[str] = []
    versions: list[ArtifactVersionRead] = []


class ArtifactEdit(BaseModel):
    content: str = Field(min_length=1)


class SlideImageRegenerate(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)


class SlidePaletteApply(BaseModel):
    palette: dict[str, str]
    scope: Literal["deck", "project"] = "deck"


class SlidePalettePreview(BaseModel):
    palette: dict[str, str]


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
    duration_spec: DurationSpec | None
    research_mode: Literal["provided_only", "provided_plus_web", "web_only"]
    sources: list[IdeationSourceRead] = []
    status: str
    created_at: datetime
    updated_at: datetime
