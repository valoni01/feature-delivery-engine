from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request
from openai import AsyncOpenAI

from app.core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    settings = get_settings()
    app.state.llm = AsyncOpenAI(api_key=settings.openai_api_key)
    yield
    await app.state.llm.close()


async def get_llm_client(request: Request) -> AsyncOpenAI:
    return request.app.state.llm
