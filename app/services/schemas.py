from datetime import datetime

from pydantic import BaseModel, Field


class ServiceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    department: str | None = Field(default=None, max_length=100)
    is_active: bool = True


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    department: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class ServiceResponse(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None
    department: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
