from typing import Literal

from pydantic import BaseModel, Field

from app.agents.base import track_agent_run
from app.agents.state import PipelineState
from app.core.llm import get_llm_client

SYSTEM_PROMPT = """You are a senior software architect. Your job is to analyze a Feature Requirement Document (FRD) and produce a structured requirement summary.

Be thorough. Extract every requirement, even implicit ones. Flag anything ambiguous as an open question."""


class FunctionalRequirement(BaseModel):
    id: str = Field(description="Unique ID like FR-1, FR-2")
    description: str
    priority: Literal["must-have", "should-have", "nice-to-have"]


class NonFunctionalRequirement(BaseModel):
    id: str = Field(description="Unique ID like NFR-1, NFR-2")
    description: str
    category: Literal["performance", "security", "scalability", "reliability", "usability"]


class RequirementSummary(BaseModel):
    title: str = Field(description="Short title for the feature")
    summary: str = Field(description="2-3 sentence overview of what the feature does")
    goals: list[str]
    functional_requirements: list[FunctionalRequirement]
    non_functional_requirements: list[NonFunctionalRequirement]
    acceptance_criteria: list[str]
    assumptions: list[str]
    open_questions: list[str]


async def parse_frd(state: PipelineState) -> dict:
    """LangGraph node: parses a Feature Requirement Document into structured requirements."""
    llm = get_llm_client()
    model = state["model"]
    workflow_id = state["workflow_id"]

    async with track_agent_run(workflow_id, "frd_parser", model, input_data={"source_field": "feature_doc_text"}) as run:
        response = await llm.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": state["feature_doc_text"]},
            ],
            response_format=RequirementSummary,
            temperature=0.2,
        )

        parsed = response.choices[0].message.parsed
        tokens = response.usage.total_tokens if response.usage else 0

        result = parsed.model_dump()
        run.output_data = result
        run.tokens_used = tokens

    return {"requirement_summary": result, "current_step": "parsing"}
