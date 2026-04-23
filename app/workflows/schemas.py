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
    repo_url: str = Field(..., min_length=1, description="GitHub repository URL, e.g. https://github.com/owner/repo")
    branch: str | None = Field(default=None, description="Branch to clone. Defaults to the repo's default branch.")


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
    repo_url: str
    branch: str | None
    pending_questions: list[dict[str, Any]] | None
    requirement_summary: dict[str, Any] | None
    technical_design: dict[str, Any] | None
    tasks: list[dict[str, Any]] | None
    pr_url: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClarificationQuestion(BaseModel):
    id: str
    question: str
    why: str


class ClarificationResponse(BaseModel):
    workflow_id: int
    status: str
    clarifying_questions: list[ClarificationQuestion]


class ClarificationAnswers(BaseModel):
    answers: dict[str, str] = Field(
        ...,
        description="Map of question ID to answer, e.g. {'Q-1': 'Yes, we need both email and SMS'}",
    )
