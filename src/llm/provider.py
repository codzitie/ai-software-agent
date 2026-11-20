"""The only place that creates an LLM client.

Agents call get_llm() and never import a provider package themselves.
To change provider or model, edit .env or settings; no agent code changes.
"""
from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel

from config import settings
from src.utils.errors import AgentError
from src.utils.trace import LLMTrace 


@lru_cache(maxsize=8)
def get_llm(temperature: float | None = None, max_tokens: int | None = None) -> BaseChatModel:
    temp = settings.LLM_TEMPERATURE if temperature is None else temperature
    tokens = max_tokens or settings.LLM_MAX_TOKENS
    provider = settings.LLM_PROVIDER.lower()

    # Imports are lazy so only the provider you use needs to be installed.
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.LLM_MODEL,
            temperature=temp,
            max_tokens=tokens,
            timeout=settings.LLM_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
            callbacks=[LLMTrace()],
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.LLM_MODEL,
            temperature=temp,
            max_tokens=tokens,
            timeout=settings.LLM_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
            callbacks=[LLMTrace()],
        )

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=settings.LLM_MODEL,
            temperature=temp,
            max_output_tokens=tokens,
            timeout=settings.LLM_TIMEOUT,
            max_retries=settings.LLM_MAX_RETRIES,
            callbacks=[LLMTrace()],
        )

    raise AgentError(
        f"Unknown LLM_PROVIDER '{settings.LLM_PROVIDER}'. Use anthropic, openai or google."
    )