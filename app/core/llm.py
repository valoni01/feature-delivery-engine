from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from openai import AsyncOpenAI

from app.core.config import get_settings

_llm_client: AsyncOpenAI | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    global _llm_client
    settings = get_settings()
    _llm_client = AsyncOpenAI(api_key=settings.openai_api_key)
    app.state.llm = _llm_client
    yield
    await _llm_client.close()
    _llm_client = None


def get_llm_client() -> AsyncOpenAI:
    """Get the LLM client. Works from both routes and agent nodes."""
    if _llm_client is None:
        raise RuntimeError("LLM client not initialized. Is the app running?")
    return _llm_client
