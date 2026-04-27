import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import AgentRun
from app.core.db import get_async_session

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("fde.agents")


@asynccontextmanager
async def track_agent_run(
    workflow_id: int,
    agent_name: str,
    model: str,
    input_data: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
) -> AsyncGenerator[AgentRun]:
    """Context manager that tracks an agent execution in the database and OTel.

    Usage inside a LangGraph node:

        async with track_agent_run(workflow_id, "frd_parser", model) as run:
            result = await llm_call(...)
            run.output_data = result
            run.tokens_used = usage.total_tokens
    """
    owns_session = db is None
    session = db or get_async_session()()

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

    with tracer.start_as_current_span(
        f"agent.{agent_name}",
        attributes={
            "agent.name": agent_name,
            "agent.model": model,
            "workflow.id": workflow_id,
            "agent.run_id": run.id,
        },
    ) as span:
        try:
            yield run
            run.status = run.status if run.status != "running" else "success"
            run.duration_ms = int((time.monotonic() - start) * 1000)

            span.set_attribute("agent.status", run.status)
            span.set_attribute("agent.duration_ms", run.duration_ms)
            if run.tokens_used:
                span.set_attribute("agent.tokens_used", run.tokens_used)

            logger.info(
                "agent_run_complete",
                extra={
                    "workflow_id": workflow_id,
                    "agent": agent_name,
                    "model": model,
                    "tokens": run.tokens_used,
                    "duration_ms": run.duration_ms,
                    "status": run.status,
                },
            )
            await session.commit()

        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.duration_ms = int((time.monotonic() - start) * 1000)

            span.set_attribute("agent.status", "failed")
            span.set_attribute("agent.duration_ms", run.duration_ms)
            span.record_exception(exc)
            span.set_status(trace.StatusCode.ERROR, str(exc))

            logger.error(
                "agent_run_failed",
                extra={
                    "workflow_id": workflow_id,
                    "agent": agent_name,
                    "error": str(exc),
                    "duration_ms": run.duration_ms,
                },
            )
            await session.commit()
            raise

        finally:
            if owns_session:
                await session.close()
