from typing import Literal

from pydantic import BaseModel, Field, model_validator

DurationPreset = Literal[
    "microvideo",
    "minicourse",
    "short",
    "standard",
    "complete",
    "custom",
]

DURATION_PRESETS: dict[str, tuple[int, int, int]] = {
    "microvideo": (1, 1, 1),
    "minicourse": (1, 3, 5),
    "short": (2, 3, 8),
    "standard": (3, 4, 10),
    "complete": (5, 4, 15),
}


class DurationSpec(BaseModel):
    """Exact project structure plus the tolerated target duration."""

    preset: DurationPreset
    module_count: int = Field(ge=1, le=5)
    videos_per_module: int = Field(ge=1, le=5)
    target_minutes_per_video: int = Field(ge=1, le=60)
    total_videos: int = 0
    total_minutes: int = 0
    tolerance_ratio: float = Field(default=0.2, ge=0.2, le=0.2)

    @model_validator(mode="before")
    @classmethod
    def apply_preset(cls, value):
        if isinstance(value, dict) and value.get("preset") in DURATION_PRESETS:
            modules, videos, minutes = DURATION_PRESETS[value["preset"]]
            value = {
                **value,
                "module_count": modules,
                "videos_per_module": videos,
                "target_minutes_per_video": minutes,
            }
        return value

    @model_validator(mode="after")
    def materialize_derived_values(self) -> "DurationSpec":
        self.total_videos = self.module_count * self.videos_per_module
        self.total_minutes = self.total_videos * self.target_minutes_per_video
        self.tolerance_ratio = 0.2
        return self
