from pydantic import BaseModel, Field


class VoiceSegment(BaseModel):
    slide: int = Field(ge=1, description="Número de slide al que acompaña este segmento")
    text: str = Field(min_length=1, description="Texto a narrar, ya adaptado a oralidad")


class VoiceScript(BaseModel):
    """Narration script segmented per slide, ready for TTS."""

    lesson_title: str
    language: str = "es"
    segments: list[VoiceSegment] = Field(min_length=1)
