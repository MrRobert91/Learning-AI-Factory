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
