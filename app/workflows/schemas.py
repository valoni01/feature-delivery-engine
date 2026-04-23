from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class WorkflowStatus(StrEnum):
    DRAFT = "draft"
    PARSING = "parsing"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    DESIGNING = "designing"
    REVIEWING = "reviewing"
    TICKETING = "ticketing"
    IMPLEMENTING = "implementing"
    PR_CREATED = "pr_created"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowCreate(BaseModel):
    service_id: int
    title: str = Field(..., min_length=1, max_length=255)
    feature_doc_text: str = Field(..., min_length=1)
    repo_path: str = Field(..., min_length=1, description="Absolute path to the repository to analyze")


class WorkflowUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    feature_doc_text: str | None = Field(default=None, min_length=1)
    requirement_summary: dict[str, Any] | None = None
    technical_design: dict[str, Any] | None = None
    tasks: list[dict[str, Any]] | None = None


class WorkflowResponse(BaseModel):
    id: int
    service_id: int
    title: str
    status: str
    feature_doc_text: str
    requirement_summary: dict[str, Any] | None
    technical_design: dict[str, Any] | None
    tasks: list[dict[str, Any]] | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClarificationQuestion(BaseModel):
    id: str
    question: str
    context: str


class ClarificationResponse(BaseModel):
    workflow_id: int
    status: str
    clarifying_questions: list[ClarificationQuestion]


class ClarificationAnswers(BaseModel):
    answers: dict[str, str] = Field(
        ...,
        description="Map of question ID to answer, e.g. {'Q-1': 'Yes, we need both email and SMS'}",
    )
