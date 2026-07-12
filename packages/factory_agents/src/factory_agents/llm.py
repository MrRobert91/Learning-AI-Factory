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


def get_chat_model(model: str, api_key: str, temperature: float = 0.7):
    """LangChain chat model against OpenRouter (used by deep agents)."""
    from langchain_openai import ChatOpenAI

    if not api_key:
        raise MissingApiKeyError("OPENROUTER_API_KEY no está configurada")
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
        temperature=temperature,
    )
