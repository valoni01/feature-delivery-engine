import json

from pydantic import BaseModel, Field

from app.agents.base import track_agent_run
from app.agents.state import PipelineState
from app.core.llm import get_llm_client


class ImplementationTask(BaseModel):
    id: str = Field(description="Task ID like T-1, T-2")
    title: str = Field(description="Short descriptive title")
    description: str = Field(description="Detailed description of what to implement")
    files: list[str] = Field(description="File paths this task touches")
    depends_on: list[str] = Field(default_factory=list, description="Task IDs that must complete first")
    estimated_complexity: str = Field(description="low, medium, or high")


class TaskPlan(BaseModel):
    tasks: list[ImplementationTask]
    implementation_order: list[str] = Field(description="Task IDs in the order they should be implemented")


SYSTEM_PROMPT = """You are a tech lead breaking down a technical design into ordered implementation tasks.

Each task should be a self-contained unit of work that an engineer (or AI agent) can pick up and implement independently. Tasks should be small enough to be completed in a single focused session.

RULES:
1. Each task should touch a small number of files (1-3 ideally)
2. Define clear dependencies — which tasks must finish before others can start
3. Order tasks so foundational work (models, schemas) comes before dependent work (routes, logic)
4. Include a testing task for each functional area
5. Keep tasks atomic — don't combine unrelated changes

TYPICAL ORDERING:
1. Data models and migrations
2. Schemas/types
3. Core business logic / service layer
4. API routes
5. Integration wiring
6. Tests

Be specific in descriptions. An engineer reading the task should know exactly what to create/modify without re-reading the full design."""


async def plan_tasks(state: PipelineState) -> dict:
    """LangGraph node: breaks the technical design into ordered implementation tasks."""
    llm = get_llm_client()
    model = state["model"]
    workflow_id = state["workflow_id"]

    req_summary = json.dumps(state["requirement_summary"], indent=2)
    tech_design = json.dumps(state["technical_design"], indent=2)

    async with track_agent_run(
        workflow_id, "task_planner", model,
        input_data={"source_field": "technical_design"},
    ) as run:
        response = await llm.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"## Requirement Summary\n```json\n{req_summary}\n```\n\n"
                    f"## Technical Design\n```json\n{tech_design}\n```\n\n"
                    "Break this into ordered implementation tasks."
                )},
            ],
            response_format=TaskPlan,
            temperature=0.2,
        )

        plan = response.choices[0].message.parsed
        tokens = response.usage.total_tokens if response.usage else 0
        result = [t.model_dump() for t in plan.tasks]

        run.output_data = {"tasks": result, "order": plan.implementation_order}
        run.tokens_used = tokens

    return {"tasks": result, "current_step": "ticketing"}
