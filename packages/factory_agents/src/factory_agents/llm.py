"""LLM access via OpenRouter (OpenAI-compatible API)."""

from openai import OpenAI

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"


def get_llm_client(api_key: str) -> OpenAI:
    if not api_key:
        raise MissingApiKeyError("OPENROUTER_API_KEY no está configurada")
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=api_key,
        default_headers={
            # OpenRouter attribution headers (optional but recommended)
            "HTTP-Referer": "https://github.com/MrRobert91/Learning-AI-Factory",
            "X-Title": "AI Learning Factory",
        },
    )


class MissingApiKeyError(RuntimeError):
    pass
