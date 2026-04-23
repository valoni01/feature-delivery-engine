import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import AgentRun
from app.core.db import async_session


@asynccontextmanager
async def track_agent_run(
    workflow_id: int,
    agent_name: str,
    model: str,
    input_data: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
) -> AsyncGenerator[AgentRun]:
    """Context manager that tracks an agent execution in the database.

    Usage inside a LangGraph node:

        async with track_agent_run(workflow_id, "frd_parser", model) as run:
            result = await llm_call(...)
            run.output_data = result
            run.tokens_used = usage.total_tokens
    """
    owns_session = db is None
    session = db or async_session()

    run = AgentRun(
        workflow_id=workflow_id,
        agent_name=agent_name,
        status="running",
        input_data=input_data,
        model_used=model,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    start = time.monotonic()

    try:
        yield run
        run.status = run.status if run.status != "running" else "success"
        run.duration_ms = int((time.monotonic() - start) * 1000)
        await session.commit()

    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)
        run.duration_ms = int((time.monotonic() - start) * 1000)
        await session.commit()
        raise

    finally:
        if owns_session:
            await session.close()
