"""LLM helpers — LangChain + OpenRouter."""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from settings import settings


def get_llm(model: str = "openai/gpt-4o-mini") -> ChatOpenAI:
    """Return a ChatOpenAI instance configured for OpenRouter."""
    return ChatOpenAI(
        model=model,
        api_key=settings.openrouter_api_key,  # type: ignore[arg-type]
        base_url="https://openrouter.ai/api/v1",
    )
