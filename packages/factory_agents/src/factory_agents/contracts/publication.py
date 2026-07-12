from pydantic import BaseModel, Field


class PublicationPackage(BaseModel):
    """Everything needed to publish a lesson video on YouTube."""

    video_title: str = Field(max_length=100, description="Título optimizado (máx. 100 chars)")
    description: str = Field(
        description="Descripción completa: resumen, capítulos con timestamps, enlaces"
    )
    tags: list[str] = Field(default_factory=list, max_length=25)
    chapters: list[str] = Field(
        default_factory=list,
        description="Capítulos en formato 'MM:SS Título' (el primero debe ser 00:00)",
    )
    thumbnail_title: str = Field(
        default="", max_length=60, description="Texto corto y potente para la miniatura"
    )
    thumbnail_subtitle: str = Field(
        default="", max_length=80, description="Subtítulo opcional de la miniatura"
    )
    playlist: str = Field(default="", description="Nombre de la playlist del curso")
    language: str = "es"
