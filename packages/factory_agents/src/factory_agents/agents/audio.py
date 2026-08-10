"""Configurable automatic narration synthesis stage."""

from factory_agents.runtime import AgentSpec, register

AUDIO_SPEC = register(
    AgentSpec(
        name="audio",
        display_name="Generación de audio",
        description=(
            "Sintetiza y versiona la narración segmentada y sus subtítulos, "
            "para poder reutilizarla en montajes de vídeo posteriores."
        ),
        base_prompt="",
        tool_names=("TTS", "ffprobe"),
        consumes=("voice_script",),
        produces=("audio", "subtitles"),
        kind="automatic",
    )
)
