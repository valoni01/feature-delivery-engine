from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class IntegrationType(StrEnum):
    TICKETING = "ticketing"
    SOURCE_CONTROL = "source_control"


class TicketingProvider(StrEnum):
    JIRA = "jira"
    LINEAR = "linear"
    GITHUB_ISSUES = "github_issues"


class SourceControlProvider(StrEnum):
    GITHUB = "github"
    GITLAB = "gitlab"


class IntegrationCreate(BaseModel):
    service_id: int
    integration_type: IntegrationType
    provider: str = Field(..., min_length=1, max_length=50)
    external_identifier: str | None = Field(default=None, max_length=255)
    base_url: str | None = None
    config: dict[str, Any] | None = None


class IntegrationUpdate(BaseModel):
    external_identifier: str | None = Field(default=None, max_length=255)
    base_url: str | None = None
    config: dict[str, Any] | None = None
    is_active: bool | None = None


class IntegrationResponse(BaseModel):
    id: int
    service_id: int
    integration_type: str
    provider: str
    external_identifier: str | None
    base_url: str | None
    config: dict[str, Any] | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
